"""ZimaCompare v3.9 — Lecture SMART avec parsing corrigé.

Corrections v3.9 :
  - Détection correcte du type de disque (HDD/SSD/NVMe) via plusieurs champs.
  - Filtrage des devices fantômes (slots SD vides, USB déconnectés).
  - Calcul d'un score de santé synthétique pour les HDD.
  - Mise en avant des attributs critiques unifiée ATA + NVMe.
"""
import json
import os
import re
import subprocess
import threading
import time
from pathlib import Path
from typing import Dict, List, Optional

from config import setup_logging

logger = setup_logging()

_CACHE: Dict[str, dict] = {}
_CACHE_LOCK = threading.Lock()
_CACHE_TTL = 60


def _run_smartctl(*args: str, timeout: int = 15) -> Optional[dict]:
    """Lance smartctl avec --json=c et retourne le JSON parsé."""
    try:
        cmd = ["smartctl", "--json=c", *args]
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
        if result.stdout:
            try:
                return json.loads(result.stdout)
            except json.JSONDecodeError:
                logger.warning(f"[SMART] JSON invalide pour {args}: {result.stdout[:200]}")
    except subprocess.TimeoutExpired:
        logger.warning(f"[SMART] Timeout sur {args}")
    except FileNotFoundError:
        logger.warning("[SMART] smartctl introuvable")
    except Exception as e:
        logger.warning(f"[SMART] Erreur exécution {args}: {e}")
    return None


def list_devices() -> List[str]:
    data = _run_smartctl("--scan", "--json=c", timeout=10)
    devices = []
    if data and "devices" in data:
        for dev in data["devices"]:
            name = dev.get("name")
            if name:
                devices.append(name)
    return sorted(devices)


def _is_phantom_device(raw: dict) -> bool:
    """Détecte les devices que smartctl liste mais ne peut pas lire (slots SD
    vides, USB déconnectés, etc.) — caractérisés par l'absence totale d'infos."""
    if not raw:
        return True
    # Si aucun des champs basiques n'est présent → fantôme
    has_model    = bool(raw.get("model_name") or raw.get("model_family"))
    has_status   = raw.get("smart_status") is not None
    has_capacity = (raw.get("user_capacity") or {}).get("bytes") is not None
    # Pas de modèle ET pas de status ET pas de capacité → c'est un fantôme
    return not (has_model or has_status or has_capacity)


def _detect_disk_type(raw: dict) -> str:
    """Détermine HDD/SSD/NVMe à partir de plusieurs champs smartctl."""
    # 1. NVMe : device.protocol = "NVMe"
    proto = (raw.get("device") or {}).get("protocol", "").lower()
    if "nvme" in proto:
        return "NVMe"

    # 2. rotation_rate explicite (peut être à la racine OU sous ata_smart_data)
    rotation = raw.get("rotation_rate")
    if rotation is None:
        rotation = (raw.get("ata_smart_data") or {}).get("rotation_rate")

    if rotation is not None:
        if rotation == 0:
            return "SSD"
        if rotation > 0:
            return f"HDD {rotation} RPM"

    # 3. form factor + interface ATA : si c'est un disque SATA sans rotation
    #    indiquée, on regarde le nom du modèle
    model = (raw.get("model_name") or raw.get("model_family") or "").upper()
    if any(k in model for k in ("SSD", "SOLID STATE", "NAND")):
        return "SSD"
    # Indicateurs HDD courants (WD Red, WD Black, Seagate, IronWolf, etc.)
    if any(k in model for k in ("WD20EFRX", "WD30EFRX", "WD40EFRX", "WD60EFRX", "WD80EFRX",
                                 "ST", "IRONWOLF", "BARRACUDA", "WD20EZAZ", "WD40EZAZ",
                                 "WD20EZRZ", "HGST", "HUS", "HUH")):
        return "HDD"

    return "Inconnu"


def _interface_label(raw: dict) -> str:
    proto = (raw.get("device") or {}).get("protocol", "")
    if proto: return proto
    # smartctl Linux indique parfois aussi /dev/sda type=sat
    typ = (raw.get("device") or {}).get("type", "")
    if typ: return typ.upper()
    return "?"


# Attributs SMART vraiment importants (ATA SMART IDs + champs NVMe)
CRITICAL_ATA_IDS = {
    5:   "Reallocated_Sector_Ct",   # Secteurs remappés → KO majeur
    187: "Reported_Uncorrect",       # Erreurs non corrigées
    188: "Command_Timeout",
    197: "Current_Pending_Sector",   # Secteurs en attente de remap
    198: "Offline_Uncorrectable",    # Erreurs détectées hors-ligne
    199: "UDMA_CRC_Error_Count",     # Problème câble SATA
    9:   "Power_On_Hours",
    194: "Temperature_Celsius",
}

CRITICAL_NVME_KEYS = {
    "critical_warning":  "Critical Warning",
    "media_errors":      "Media Errors",
    "percentage_used":   "Percentage Used",
    "available_spare":   "Available Spare",
    "unsafe_shutdowns":  "Unsafe Shutdowns",
    "num_err_log_entries": "Num Err Log Entries",
}


def _compute_age(raw: dict, disk_type: str) -> dict:
    """Indicateur d'age derive de power_on_hours (heures de fonctionnement).

    Independant du niveau SMART. Seuils : watch >= 3 ans (26304 h),
    old >= 5 ans (43800 h). Presentation (libelle/couleur) cote frontend.
    """
    WATCH_H = 26304  # 3 ans
    OLD_H = 43800    # 5 ans
    hours = (raw.get("power_on_time") or {}).get("hours")
    if not isinstance(hours, (int, float)) or hours < 0:
        return {"hours": None, "years": None, "level": "unknown"}
    years = round(hours / 8760.0, 1)
    if hours >= OLD_H:
        level = "old"
    elif hours >= WATCH_H:
        level = "watch"
    else:
        level = "ok"
    return {"hours": int(hours), "years": years, "level": level}


def _build_health_summary(raw: dict, disk_type: str) -> dict:
    """Construit un résumé de santé synthétique avec niveau de criticité."""
    issues = []
    warnings = []

    smart_passed = (raw.get("smart_status") or {}).get("passed")
    if smart_passed is False:
        issues.append("Status SMART FAILED")

    if "HDD" in disk_type:
        ata_table = (raw.get("ata_smart_attributes") or {}).get("table", [])
        for attr in ata_table:
            aid = attr.get("id")
            name = attr.get("name", "")
            raw_str = (attr.get("raw") or {}).get("string", "0")
            try:
                # On extrait le premier nombre du raw (parfois "0" parfois "39 (Min/Max 25/45)")
                m = re.match(r"^-?\d+", raw_str)
                raw_val = int(m.group()) if m else 0
            except Exception:
                raw_val = 0
            when_failed = attr.get("when_failed", "-")
            if when_failed and when_failed not in ("", "-"):
                issues.append(f"{name}: when_failed={when_failed}")

            # Compteurs critiques
            if aid == 5 and raw_val > 0:
                warnings.append(f"Secteurs réalloués: {raw_val}")
            if aid == 197 and raw_val > 0:
                issues.append(f"Secteurs pending: {raw_val}")
            if aid == 198 and raw_val > 0:
                warnings.append(f"Offline uncorrectable: {raw_val}")
            if aid == 199 and raw_val > 0:
                warnings.append(f"UDMA CRC errors: {raw_val} (vérifier câble SATA)")
            if aid == 187 and raw_val > 0:
                warnings.append(f"Reported uncorrect: {raw_val}")

    elif disk_type == "NVMe":
        nvme = raw.get("nvme_smart_health_information_log") or {}
        cw = nvme.get("critical_warning", 0)
        if cw and cw != 0:
            issues.append(f"NVMe critical_warning: 0x{cw:x}")
        media_err = nvme.get("media_errors", 0)
        if media_err and media_err > 0:
            issues.append(f"NVMe media errors: {media_err}")
        pct_used = nvme.get("percentage_used", 0)
        if pct_used and pct_used >= 90:
            warnings.append(f"Endurance: {pct_used}% consommée")
        elif pct_used and pct_used >= 75:
            warnings.append(f"Endurance: {pct_used}% consommée")
        spare = nvme.get("available_spare", 100)
        spare_thresh = nvme.get("available_spare_threshold", 10)
        if spare and spare_thresh and spare < spare_thresh:
            issues.append(f"Spare ({spare}%) sous seuil ({spare_thresh}%)")

    # Niveau global
    if issues:
        level = "danger"
    elif warnings:
        level = "warning"
    elif smart_passed:
        level = "ok"
    else:
        level = "unknown"

    age = _compute_age(raw, disk_type)

    return {"level": level, "issues": issues, "warnings": warnings, "age": age}


def _parse_smart_data(raw: dict, device: str) -> dict:
    if not raw:
        return {"device": device, "ok": False, "error": "Aucune donnée"}

    if _is_phantom_device(raw):
        return {"device": device, "ok": False, "phantom": True,
                "error": "Slot vide ou périphérique non lisible"}

    model        = raw.get("model_name") or raw.get("model_family") or "?"
    serial       = raw.get("serial_number", "?")
    firmware     = raw.get("firmware_version", "?")
    capacity     = (raw.get("user_capacity") or {}).get("bytes")
    smart_status = (raw.get("smart_status") or {}).get("passed")
    disk_type    = _detect_disk_type(raw)
    interface    = _interface_label(raw)

    # Température : peut être à plusieurs endroits
    temp_curr = None
    temp = raw.get("temperature") or {}
    if temp:
        temp_curr = temp.get("current")

    # Power on / cycles
    power_on_hours = None
    poh = raw.get("power_on_time") or {}
    if poh:
        power_on_hours = poh.get("hours")
    power_cycle_count = raw.get("power_cycle_count")

    # Attributs SMART (ATA)
    attributes = []
    ata_smart = raw.get("ata_smart_attributes") or {}
    for attr in ata_smart.get("table", []):
        attributes.append({
            "id":          attr.get("id"),
            "name":        attr.get("name"),
            "value":       attr.get("value"),
            "worst":       attr.get("worst"),
            "thresh":      attr.get("thresh"),
            "when_failed": attr.get("when_failed", "-"),
            "raw":         (attr.get("raw") or {}).get("string", ""),
            "is_critical": attr.get("id") in CRITICAL_ATA_IDS,
        })

    # NVMe
    nvme_health = raw.get("nvme_smart_health_information_log") or {}
    if nvme_health:
        for k, v in nvme_health.items():
            attributes.append({
                "id":          k,
                "name":        k.replace("_", " ").title(),
                "value":       v if isinstance(v, (int, float, str)) else "?",
                "worst":       None, "thresh": None,
                "when_failed": "-",
                "raw":         str(v),
                "is_critical": k in CRITICAL_NVME_KEYS,
            })

    health = _build_health_summary(raw, disk_type)

    return {
        "device":            device,
        "ok":                True,
        "model":             model,
        "serial":            serial,
        "firmware":          firmware,
        "capacity_bytes":    capacity,
        "disk_type":         disk_type,
        "interface":         interface,
        "smart_status":      smart_status,
        "temperature":       temp_curr,
        "power_on_hours":    power_on_hours,
        "power_cycle_count": power_cycle_count,
        "attributes":        attributes,
        "health":            health,
    }


def get_device_smart(device: str, use_cache: bool = True) -> dict:
    if use_cache:
        with _CACHE_LOCK:
            cached = _CACHE.get(device)
        if cached and (time.monotonic() - cached["_ts"] < _CACHE_TTL):
            return cached["data"]
    raw  = _run_smartctl("-a", device)
    data = _parse_smart_data(raw or {}, device)
    with _CACHE_LOCK:
        _CACHE[device] = {"_ts": time.monotonic(), "data": data}
    return data


def get_all_smart(use_cache: bool = True, include_phantoms: bool = False) -> List[dict]:
    """Liste tous les devices. Par défaut, ne retourne PAS les fantômes (slots vides)."""
    devices = list_devices()
    out = []
    for d in devices:
        info = get_device_smart(d, use_cache=use_cache)
        if info.get("phantom") and not include_phantoms:
            logger.debug(f"[SMART] {d} ignoré (fantôme)")
            continue
        out.append(info)
    return out


def clear_cache():
    with _CACHE_LOCK:
        _CACHE.clear()
