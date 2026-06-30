"""ZimaCompare v3.6 - Génération du package d'installation (.zip).

v3.6 : utilise la variable d'environnement FRONTEND_PATH pour localiser le
dossier frontend (qui doit être monté en lecture seule dans le container
backend via le docker-compose).
"""
import io
import json
import os
import shutil
import zipfile
from datetime import datetime
from pathlib import Path
from typing import Optional

from config import APP_DATA_ROOT, PATHS_HISTORY_FILE, setup_logging

logger = setup_logging()

APP_ROOT = Path("/app")

# NEW v3.6 : chemin du frontend, configurable via env var
# Le compose monte /DATA/AppData/zimacompare-v3/frontend → /app_frontend (readonly)
FRONTEND_ROOT = Path(os.environ.get("FRONTEND_PATH", "/app_frontend"))

# Fichiers backend NON-Python à empaqueter explicitement.
BACKEND_EXTRA_FILES = ["Dockerfile", "requirements.txt"]


def _collect_backend_files() -> list:
    """Liste des fichiers backend à inclure dans le ZIP installer.

    Les modules Python sont détectés AUTOMATIQUEMENT (glob de /app/*.py) :
    plus besoin de tenir une liste à jour à la main, et un nouveau module
    ne peut plus être oublié dans le paquet.

    Bug historique corrigé : mountcheck.py était absent des installers
    générés jusqu'au 2026-05-23 car il manquait dans l'ancienne liste codée
    en dur — toute nouvelle installation plantait au boot (import manquant).

    On ajoute ensuite les fichiers non-.py indispensables (Dockerfile,
    requirements.txt).
    """
    py_files = sorted(p.name for p in APP_ROOT.glob("*.py"))
    extras   = [f for f in BACKEND_EXTRA_FILES if (APP_ROOT / f).exists()]
    return py_files + extras

FRONTEND_INCLUDES = [
    "package.json", "vite.config.js", "index.html",
    "Dockerfile",
]
FRONTEND_DIRS_NESTED = ["src", "nginx"]
FRONTEND_EXCLUDES = {"node_modules", "dist", ".vite", "package-lock.json"}


INSTALL_MD = r"""# ZimaCompare — Installation propre

Ce paquet contient tout le nécessaire pour installer ZimaCompare sur une
ZimaBoard (ou tout système avec Docker + CasaOS).

## Prérequis

- Docker installé (CasaOS l'inclut par défaut)
- Accès SSH à la machine
- Volumes des disques à comparer accessibles sur l'hôte (par défaut sous `/media/...`)

## Structure du ZIP

```
zimacompare-installer/
├── INSTALL.md                  ← ce fichier
├── docker-compose.yaml         ← à coller dans CasaOS
├── install.sh                  ← script d'installation guidée
├── migrate-paths-history.sh    ← import d'un historique existant
├── healthcheck.sh              ← test post-installation
├── backend/                    ← code Python (FastAPI + uvicorn)
└── frontend/                   ← code React (Vite)
```

## Installation pas à pas

### 1. Copier le contenu sur la ZimaBoard

Depuis ton poste, via SCP (remplace `192.168.1.10` par l'IP de ta ZimaBoard) :

```bash
scp -r zimacompare-installer/ user@192.168.1.10:/tmp/
```

Ou bien décompresse directement sur la ZimaBoard :

```bash
ssh user@192.168.1.10
sudo mkdir -p /DATA/AppData/zimacompare-v3
sudo unzip /tmp/zimacompare-installer-*.zip -d /DATA/AppData/zimacompare-v3
sudo mv /DATA/AppData/zimacompare-v3/zimacompare-installer/* /DATA/AppData/zimacompare-v3/
sudo rmdir /DATA/AppData/zimacompare-v3/zimacompare-installer
```

### 2. Lancer le script d'installation

Le script automatise les étapes critiques (build du frontend, création du
dossier data, vérifications).

```bash
cd /DATA/AppData/zimacompare-v3
sudo bash install.sh
```

Le script :
- vérifie la présence de Docker
- crée le dossier `data/`
- exécute `npm install && npm run build` via un container Node (sans
  installer Node sur l'hôte)
- vérifie qu'il n'y a pas de conflit avec une ancienne installation

### 3. Adapter le docker-compose à ton environnement

Édite `docker-compose.yaml` et adapte la section `volumes` du service
`backend` selon **tes propres disques** :

```yaml
- type: bind
  source: /media/HDD-Storage1     ← chemin RÉEL sur l'hôte
  target: /disks/HDD-Storage1     ← chemin VU par l'app (préfixe /disks/ obligatoire)
```

⚠️ Règle : tous les chemins cible doivent commencer par `/disks/` ou
`/network/`. Tout autre préfixe est rejeté par l'application.

⚠️ NE TOUCHE PAS aux 3 volumes système :
- `data → /app_data`           — données de l'app
- `backend → /app`             — code backend
- `frontend → /app_frontend`   — code frontend (readonly, nécessaire pour
                                   l'export du paquet d'installation)

### 4. Installer dans CasaOS

1. Ouvre l'UI CasaOS
2. App Store → bouton `+` → **Installer une application personnalisée**
3. Onglet **Importer**, colle le contenu de `docker-compose.yaml`
4. Valide

Le premier démarrage prend 1-2 minutes (apt-get + pip install au boot).

### 5. (Optionnel) Importer un historique existant

```bash
sudo bash migrate-paths-history.sh /tmp/paths_history.json
```

### 6. Vérifier que tout fonctionne

```bash
sudo bash healthcheck.sh
```

## Accès à l'interface

```
http://<IP-zimaboard>:8501
```

## Maintenance

### Rebuilder le frontend après modification

```bash
docker run --rm -v /DATA/AppData/zimacompare-v3/frontend:/app -w /app \
  node:20-alpine sh -c "npm run build"
docker restart zimacompare-frontend
```

### Redémarrer après modification du backend

```bash
docker restart zimacompare-backend
```

### Sauvegarde

```bash
sudo tar czf zimacompare-backup-$(date +%F).tar.gz /DATA/AppData/zimacompare-v3/data/
```

### Désinstaller proprement

```bash
# Depuis CasaOS : désinstalle l'app zimacompare
sudo rm -rf /DATA/AppData/zimacompare-v3
```

## Dépannage rapide

| Symptôme | Cause probable | Fix |
|---|---|---|
| `404` sur `/api/...` | Config nginx pas montée | Vérifier le bind sur `default.conf` |
| `backend: name resolution failed` | `network_mode: bridge` | Vérifier le réseau `zimanet` |
| Cache hash à 0 entrées | Volume `/app_data` mal monté | `ls` du dossier data |
| ZIP installer 31 KB seulement | Frontend non monté dans le backend | Vérifier `/app_frontend` dans le compose |
"""


INSTALL_SH = r"""#!/bin/bash
# install.sh — installation guidée de ZimaCompare
set -e

INSTALL_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DATA_DIR="$INSTALL_DIR/data"

echo "═══════════════════════════════════════════════════════"
echo "  ZimaCompare — installation"
echo "  Dossier cible : $INSTALL_DIR"
echo "═══════════════════════════════════════════════════════"
echo ""

if ! command -v docker &> /dev/null; then
    echo "❌ Docker non installé. Installe-le d'abord."
    exit 1
fi
echo "✓ Docker $(docker --version | cut -d' ' -f3 | tr -d ',')"

for d in backend frontend; do
    if [ ! -d "$INSTALL_DIR/$d" ]; then
        echo "❌ Dossier manquant : $INSTALL_DIR/$d"
        exit 1
    fi
done
echo "✓ Structure du paquet OK"

mkdir -p "$DATA_DIR"
echo "✓ Dossier data/ prêt : $DATA_DIR"

# Si paths_history.json est présent dans le paquet, le copier dans data/
if [ -f "$INSTALL_DIR/paths_history.json" ] && [ ! -f "$DATA_DIR/paths_history.json" ]; then
    cp "$INSTALL_DIR/paths_history.json" "$DATA_DIR/"
    echo "✓ paths_history.json restauré dans data/"
fi

echo ""
echo "→ Build du frontend (npm install + vite build)…"
docker run --rm \
    -v "$INSTALL_DIR/frontend:/app" \
    -w /app \
    node:20-alpine \
    sh -c "npm install --no-audit --no-fund && npm run build"

if [ ! -f "$INSTALL_DIR/frontend/dist/index.html" ]; then
    echo "❌ Le build a échoué (dist/index.html absent)"
    exit 1
fi
echo "✓ Frontend buildé"

if docker ps -a --format '{{.Names}}' | grep -q '^zimacompare-'; then
    echo ""
    echo "⚠ Containers ZimaCompare déjà présents — désinstalle l'app dans CasaOS"
    echo "  si tu veux une installation neuve."
fi

echo ""
echo "═══════════════════════════════════════════════════════"
echo "  ✓ Installation locale terminée"
echo "═══════════════════════════════════════════════════════"
echo ""
echo "Prochaines étapes :"
echo "  1. Édite docker-compose.yaml et adapte les volumes /disks/"
echo "  2. Dans CasaOS → App Store → + → Import → colle docker-compose.yaml"
echo "  3. Teste avec : sudo bash $INSTALL_DIR/healthcheck.sh"
"""


HEALTHCHECK_SH = r"""#!/bin/bash
# healthcheck.sh
PORT=${ZIMA_PORT:-8501}
PASS=0; FAIL=0
check() {
    local label="$1"; local cmd="$2"
    if eval "$cmd" &>/dev/null; then echo "✓ $label"; PASS=$((PASS+1))
    else echo "✗ $label"; FAIL=$((FAIL+1)); fi
}
echo "═══ ZimaCompare healthcheck ═══"
echo ""
check "Container backend  UP"       "docker ps --format '{{.Names}}' | grep -q '^zimacompare-backend$'"
check "Container frontend UP"       "docker ps --format '{{.Names}}' | grep -q '^zimacompare-frontend$'"
check "API /api/status (200)"       "curl -fs http://localhost:$PORT/api/status > /dev/null"
check "API renvoie du JSON"         "curl -fs http://localhost:$PORT/api/status | grep -q app_state"
check "Résolution DNS interne"      "docker exec zimacompare-frontend wget -qO- http://backend:8000/api/status > /dev/null"
check "Dossier data écrit"          "[ -f /DATA/AppData/zimacompare-v3/data/app_state.json ]"
check "Frontend index.html"         "[ -f /DATA/AppData/zimacompare-v3/frontend/dist/index.html ]"
check "Config nginx montée"         "docker exec zimacompare-frontend test -f /etc/nginx/conf.d/default.conf"
check "Frontend monté dans backend" "docker exec zimacompare-backend test -d /app_frontend/src"
echo ""
echo "═══ Résultat : $PASS OK · $FAIL KO ═══"
if [ $FAIL -eq 0 ]; then
    echo ""
    echo "✓ Tout fonctionne. UI : http://$(hostname -I | awk '{print $1}'):$PORT"
    exit 0
else
    exit 1
fi
"""


MIGRATE_HISTORY_SH = r"""#!/bin/bash
set -e
SRC="$1"
DST="/DATA/AppData/zimacompare-v3/data/paths_history.json"
if [ -z "$SRC" ]; then
    echo "Usage : sudo bash migrate-paths-history.sh /chemin/vers/paths_history.json"
    exit 1
fi
if [ ! -f "$SRC" ]; then echo "❌ Fichier introuvable : $SRC"; exit 1; fi
if ! python3 -c "import json; json.load(open('$SRC'))" 2>/dev/null; then
    echo "❌ JSON invalide"; exit 1
fi
if [ -f "$DST" ]; then
    cp "$DST" "${DST}.backup-$(date +%Y%m%d-%H%M%S)"
    echo "✓ Backup de l'ancien créé"
fi
mkdir -p "$(dirname "$DST")"
cp "$SRC" "$DST"
if docker ps --format '{{.Names}}' | grep -q '^zimacompare-backend$'; then
    docker restart zimacompare-backend > /dev/null
    echo "✓ Backend redémarré"
fi
echo "✓ paths_history.json importé dans $DST"
"""


def _add_file(zf: zipfile.ZipFile, src_path: Path, arcname: str):
    if src_path.exists() and src_path.is_file():
        zf.write(src_path, arcname)


def _add_dir(zf: zipfile.ZipFile, src_dir: Path, arcname_prefix: str, excludes=None):
    excludes = excludes or set()
    if not src_dir.exists() or not src_dir.is_dir(): return
    for root, dirs, files in os.walk(src_dir):
        dirs[:]  = [d for d in dirs  if d not in excludes]
        files    = [f for f in files if f not in excludes]
        rel_root = os.path.relpath(root, src_dir)
        for fname in files:
            src = Path(root) / fname
            rel = fname if rel_root == "." else os.path.join(rel_root, fname)
            arc = f"{arcname_prefix}/{rel}".replace("\\", "/")
            try: zf.write(src, arc)
            except Exception as e:
                logger.warning(f"[INSTALLER] skip {src}: {e}")


def build_installer_zip(include_paths_history: bool = True,
                        docker_compose_path: Optional[Path] = None) -> Path:
    """Génère le ZIP d'installation et retourne son chemin."""
    timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    out_name  = f"zimacompare-installer-{timestamp}.zip"
    out_path  = APP_DATA_ROOT / out_name
    root_dir  = "zimacompare-installer"

    # NEW v3.6 : on regarde plusieurs emplacements pour le frontend
    front_candidates = [
        FRONTEND_ROOT,                                   # /app_frontend (volume readonly)
        Path("/DATA/AppData/zimacompare-v3/frontend"),   # accès direct si exécuté hors container
        APP_ROOT.parent / "frontend",
    ]
    front_dir = next(
        (c for c in front_candidates
         if c.exists() and (c / "package.json").exists()),
        None
    )

    logger.info(f"[INSTALLER] Génération de {out_name}…")
    if front_dir:
        logger.info(f"[INSTALLER] Frontend trouvé dans : {front_dir}")
    else:
        logger.warning(f"[INSTALLER] Frontend introuvable. "
                       f"Vérifiez que {FRONTEND_ROOT} est monté en lecture seule.")

    with zipfile.ZipFile(out_path, "w", zipfile.ZIP_DEFLATED, compresslevel=6) as zf:
        # Documentation et scripts
        zf.writestr(f"{root_dir}/INSTALL.md",               INSTALL_MD)
        zf.writestr(f"{root_dir}/install.sh",               INSTALL_SH)
        zf.writestr(f"{root_dir}/healthcheck.sh",           HEALTHCHECK_SH)
        zf.writestr(f"{root_dir}/migrate-paths-history.sh", MIGRATE_HISTORY_SH)

        # docker-compose.yaml
        if docker_compose_path and docker_compose_path.exists():
            zf.write(docker_compose_path, f"{root_dir}/docker-compose.yaml")
        else:
            zf.writestr(f"{root_dir}/docker-compose.yaml", _default_compose())

        # Backend — modules .py détectés automatiquement + fichiers extra
        n_backend = 0
        backend_names = []
        for fname in _collect_backend_files():
            src = APP_ROOT / fname
            if src.exists():
                zf.write(src, f"{root_dir}/backend/{fname}")
                backend_names.append(fname)
                n_backend += 1
        logger.info(f"[INSTALLER] Backend : {n_backend} fichiers — "
                    f"{', '.join(backend_names)}")

        # Frontend
        n_frontend = 0
        if front_dir:
            for rel in FRONTEND_INCLUDES:
                src = front_dir / rel
                if src.exists():
                    _add_file(zf, src, f"{root_dir}/frontend/{rel}")
                    n_frontend += 1
            for d in FRONTEND_DIRS_NESTED:
                src_dir = front_dir / d
                if src_dir.exists():
                    _add_dir(zf, src_dir, f"{root_dir}/frontend/{d}", excludes=FRONTEND_EXCLUDES)
                    # On compte ce qu'on vient d'ajouter (approximation)
                    n_frontend += sum(1 for _ in src_dir.rglob("*")
                                      if _.is_file() and _.name not in FRONTEND_EXCLUDES)

        # Paths history
        if include_paths_history and PATHS_HISTORY_FILE.exists():
            zf.write(PATHS_HISTORY_FILE, f"{root_dir}/paths_history.json")

        # Manifest
        meta = {
            "generated_at":          datetime.now().isoformat(),
            "includes_paths_history": include_paths_history and PATHS_HISTORY_FILE.exists(),
            "backend_files_count":   n_backend,
            "backend_files":         backend_names,
            "frontend_found":        bool(front_dir),
            "frontend_path_used":    str(front_dir) if front_dir else None,
        }
        zf.writestr(f"{root_dir}/MANIFEST.json", json.dumps(meta, indent=2, ensure_ascii=False))

    size_kb = out_path.stat().st_size / 1024
    logger.info(f"[INSTALLER] ZIP créé : {out_path} ({size_kb:.1f} KB) — "
                f"backend: {n_backend} fichiers, frontend: "
                f"{'OK' if front_dir else 'MANQUANT'}")
    return out_path


def _default_compose() -> str:
    """Compose de secours — version COMPLÈTE et à jour (3 services :
    backend, rclone, frontend ; propagation shared/rslave ; volume
    /app_rclone du mode rapide). Utilisé si le compose réel est
    introuvable sur le système au moment de générer le ZIP."""
    return 'name: zimacompare\nservices:\n  backend:\n    cpu_shares: 90\n    command:\n      - bash\n      - -c\n      - >\n        apt-get update && apt-get install -y --no-install-recommends\n        smartmontools curl && \\\n\n        pip install --no-cache-dir -r /app/requirements.txt && \\\n\n        cd /app && uvicorn main:app --host 0.0.0.0 --port 8000\n    container_name: zimacompare-backend\n    depends_on:\n      rclone:\n        condition: service_started\n        required: true\n    deploy:\n      resources:\n        limits:\n          memory: 16508243968\n        reservations:\n          devices: []\n    environment:\n      - PGID=1000\n      - PUID=1000\n      - TZ=Europe/Paris\n      - RCLONE_RC_URL=http://zimacompare-rclone:5572\n      - RCLONE_RC_USER=zima\n      - RCLONE_RC_PASS=CHANGE-ME-rclone-2026\n    image: python:3.12-slim\n    labels:\n      icon: https://filedn.eu/lXD7ErB2q6Sp19LoIrttSsj/zimacompare/ChatGPT%20Image%2021%20mai%202026%2C%2015_10_31%20v2.PNG\n    privileged: true\n    restart: unless-stopped\n    volumes:\n      - type: bind\n        source: /DATA/AppData/zimacompare-v3/data\n        target: /app_data\n      - type: bind\n        source: /DATA/AppData/zimacompare-v3/backend\n        target: /app\n      - type: bind\n        source: /DATA/AppData/zimacompare-v3/frontend\n        target: /app_frontend\n        read_only: true\n      - type: bind\n        source: /media/HDD-Storage1\n        target: /disks/HDD-Storage1\n      - type: bind\n        source: /media/HDD-Storage2\n        target: /disks/HDD-Storage2\n      - type: bind\n        source: /media/SSD_NAS\n        target: /disks/SSD_NAS\n      - type: bind\n        source: /media/Sauvegarde\n        target: /disks/Sauvegarde\n      - type: bind\n        source: /media/Nouveau nom\n        target: /disks/Nouveau_nom\n      - type: bind\n        source: /media/192.168.1.254/Disque 1\n        target: /network/NAS_Disque1\n      - type: bind\n        source: /media/192.168.1.254/Music\n        target: /network/NAS_Music\n      - type: bind\n        source: /media/192.168.1.254/sondage\n        target: /network/NAS_Sondage\n      - type: bind\n        source: /media/192.168.1.254/cam\n        target: /network/NAS_Cam\n      - type: bind\n        source: /DATA/AppData/zimacompare-v3/rclone\n        target: /app_rclone\n      - /DATA/AppData/zimacompare-v3/pcloud-mount:/network/pCloud:rslave\n    ports: []\n    devices: []\n    cap_add: []\n    networks:\n      - zimanet\n  rclone:\n    cpu_shares: 90\n    command:\n      - mount\n      - "pcloud:"\n      - /mnt/pcloud\n      - --allow-other\n      - --allow-non-empty\n      - --vfs-cache-mode\n      - writes\n      - --vfs-cache-max-size\n      - "2G"\n      - --vfs-cache-max-age\n      - "1h"\n      - --cache-dir\n      - /config/rclone/cache\n      - --dir-cache-time\n      - "30s"\n      - --umask\n      - "002"\n      - --config\n      - /config/rclone/rclone.conf\n      - --rc\n      - --rc-addr\n      - ":5572"\n    container_name: zimacompare-rclone\n    devices:\n      - /dev/fuse\n    privileged: true\n    environment:\n      - TZ=Europe/Paris\n      - RCLONE_RC_USER=zima\n      - RCLONE_RC_PASS=CHANGE-ME-rclone-2026\n    image: rclone/rclone:latest\n    labels:\n      icon: https://filedn.eu/lXD7ErB2q6Sp19LoIrttSsj/zimacompare/ChatGPT%20Image%2021%20mai%202026%2C%2015_10_31%20v2.PNG\n    restart: unless-stopped\n    volumes:\n      - type: bind\n        source: /DATA/AppData/zimacompare-v3/rclone\n        target: /config/rclone\n      - type: bind\n        source: /media/HDD-Storage1\n        target: /disks/HDD-Storage1\n        read_only: true\n      - /DATA/AppData/zimacompare-v3/pcloud-mount:/mnt/pcloud:shared\n    ports: []\n    networks:\n      - zimanet\n  frontend:\n    cpu_shares: 90\n    command: []\n    container_name: zimacompare-frontend\n    depends_on:\n      backend:\n        condition: service_started\n        required: true\n    deploy:\n      resources:\n        limits:\n          memory: 16508243968\n        reservations:\n          devices: []\n    image: nginx:alpine\n    labels:\n      icon: https://filedn.eu/lXD7ErB2q6Sp19LoIrttSsj/zimacompare/ChatGPT%20Image%2021%20mai%202026%2C%2015_10_31%20v2.PNG\n    ports:\n      - target: 80\n        published: "8501"\n        protocol: tcp\n    restart: unless-stopped\n    volumes:\n      - type: bind\n        source: /DATA/AppData/zimacompare-v3/frontend/dist\n        target: /usr/share/nginx/html\n      - type: bind\n        source: /DATA/AppData/zimacompare-v3/frontend/nginx/default.conf\n        target: /etc/nginx/conf.d/default.conf\n    devices: []\n    cap_add: []\n    environment: []\n    networks:\n      - zimanet\n    privileged: false\nnetworks:\n  zimanet:\n    name: zimacompare_zimanet\n    driver: bridge\nx-casaos:\n  author: self\n  category: self\n  hostname: ""\n  icon: https://filedn.eu/lXD7ErB2q6Sp19LoIrttSsj/zimacompare/ChatGPT%20Image%2021%20mai%202026%2C%2015_10_31%20v2.PNG\n  index: /\n  is_uncontrolled: false\n  main: frontend\n  port_map: "8501"\n  scheme: http\n  store_app_id: zimacompare\n  title:\n    custom: ""\n    en_us: ZimaCompare\n'


def list_installers() -> list:
    result = []
    for f in sorted(APP_DATA_ROOT.glob("zimacompare-installer-*.zip"), reverse=True):
        try:
            stat = f.stat()
            result.append({
                "name": f.name,
                "size": stat.st_size,
                "date": datetime.fromtimestamp(stat.st_mtime).isoformat(timespec="seconds"),
            })
        except Exception: pass
    return result
