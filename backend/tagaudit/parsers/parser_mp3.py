"""
parsers/parser_mp3.py - ZimaTAG MP3 Parser
Support ID3v2.2/2.3/2.4, Bitrate réel, Encodeur LAME
"""
import struct
from pathlib import Path
from typing import Dict, Optional, Tuple

class MP3Parser:
    """Parser natif MP3 avec support complet ID3v2"""

    ENCODINGS = {0: 'latin1', 1: 'utf-16', 2: 'utf-16be', 3: 'utf-8'}

    FRAME_V22_TO_V23 = {
        'TT2': 'TIT2', 'TP1': 'TPE1', 'TP2': 'TPE2', 'TAL': 'TALB',
        'TYE': 'TYER', 'TCO': 'TCON', 'TRK': 'TRCK', 'TPA': 'TPOS', 'TCM': 'TCOM'
    }

    BITRATE_TABLE = [0, 32, 40, 48, 56, 64, 80, 96, 112, 128, 160, 192, 224, 256, 320]
    SAMPLERATE_TABLE = [44100, 48000, 32000]

    def __init__(self, filepath: Path):
        self.filepath = filepath
        self.tags: Dict[str, str] = {}
        self.audio_info: Dict[str, any] = {}
        self.cover_data: Optional[bytes] = None

    def parse(self) -> Dict:
        """Parse complet du fichier MP3"""
        try:
            with open(self.filepath, 'rb') as f:
                header = f.read(10)
                if header[:3] == b'ID3':
                    self._parse_id3v2(f, header)
                self._parse_audio_frame(f)
                if not self.tags.get('TSSE'):
                    self._detect_lame(f)
            return self._build_result()
        except Exception:
            return self._build_result()

    def _parse_id3v2(self, f, header: bytes):
        """Parse tags ID3v2"""
        version = header[3]
        size = self._synchsafe(header[6:10])
        self.audio_info['id3_version'] = f"ID3v2.{version}"

        if version == 2:
            self._parse_v22(f, size)
        elif version in (3, 4):
            self._parse_v23_v24(f, size, version)
        self._normalize_year()

    def _synchsafe(self, data: bytes) -> int:
        return sum((b & 0x7F) << (7 * (3-i)) for i, b in enumerate(data))

    def _parse_v22(self, f, size: int):
        """Parse frames ID3v2.2"""
        start = f.tell()
        while f.tell() - start < size:
            hdr = f.read(6)
            if len(hdr) < 6 or hdr[0] == 0:
                break
            fid = hdr[:3].decode('latin1', errors='ignore')
            fsize = struct.unpack('>I', b'\x00' + hdr[3:6])[0]
            if fsize == 0 or fsize > size:
                break
            data = f.read(fsize)
            fid_v23 = self.FRAME_V22_TO_V23.get(fid, fid)
            self._process_frame(fid_v23, data)

    def _parse_v23_v24(self, f, size: int, version: int):
        """Parse frames ID3v2.3/2.4"""
        start = f.tell()
        while f.tell() - start < size:
            hdr = f.read(10)
            if len(hdr) < 10 or hdr[0] == 0:
                break
            fid = hdr[:4].decode('latin1', errors='ignore')
            fsize = self._synchsafe(hdr[4:8]) if version == 4 else struct.unpack('>I', hdr[4:8])[0]
            if fsize == 0 or fsize > size:
                break
            data = f.read(fsize)
            self._process_frame(fid, data)

    def _process_frame(self, fid: str, data: bytes):
        """Traite un frame ID3"""
        if not data:
            return
        if fid.startswith('T') and fid != 'TXXX':
            text = self._decode_text(data)
            if text:
                if fid == 'TRCK':
                    parts = text.split('/')
                    self.tags['TRCK'] = parts[0].strip()
                    if len(parts) > 1:
                        self.tags['TRCK_TOTAL'] = parts[1].strip()
                elif fid == 'TPOS':
                    parts = text.split('/')
                    self.tags['TPOS'] = parts[0].strip()
                    if len(parts) > 1:
                        self.tags['TPOS_TOTAL'] = parts[1].strip()
                else:
                    self.tags[fid] = text
        elif fid == 'APIC':
            self.cover_data = self._extract_apic(data)

    def _decode_text(self, data: bytes) -> Optional[str]:
        """Décode frame texte"""
        if len(data) < 2:
            return None
        enc = self.ENCODINGS.get(data[0], 'latin1')
        try:
            return data[1:].decode(enc, errors='ignore').rstrip('\x00').strip()
        except:
            return None

    def _extract_apic(self, data: bytes) -> Optional[bytes]:
        """Extrait image APIC"""
        if len(data) < 2:
            return None
        pos = 1
        mime_end = data.find(b'\x00', pos)
        if mime_end == -1:
            return None
        pos = mime_end + 2
        desc_end = data.find(b'\x00', pos)
        if desc_end == -1:
            return None
        return data[desc_end + 1:]

    def _normalize_year(self):
        """Normalise le tag année"""
        for key in ('TDRC', 'TYER'):
            if key in self.tags:
                year = str(self.tags[key])[:4]
                if year.isdigit():
                    self.tags['YEAR'] = year
                    break

    def _parse_audio_frame(self, f):
        """Durée/bitrate/samplerate via mutagen (saute proprement l'ID3v2,
        gère VBR/Xing). Corrige la fausse synchro MPEG dans les grosses
        pochettes. Repli sur l'ancien scan naïf si mutagen échoue."""
        try:
            from mutagen.mp3 import MP3
            info = MP3(self.filepath).info
            length = float(getattr(info, 'length', 0) or 0)
            if length > 0:
                self.audio_info['duration_seconds'] = length
            br = getattr(info, 'bitrate', 0) or 0
            if br > 0:
                self.audio_info['bitrate'] = int(round(br / 1000))
            sr = getattr(info, 'sample_rate', 0) or 0
            if sr > 0:
                self.audio_info['samplerate'] = int(sr)
            ch = getattr(info, 'channels', 0) or 0
            if ch > 0:
                self.audio_info['channels'] = int(ch)
            if self.audio_info.get('duration_seconds'):
                return
        except Exception:
            pass
        # --- repli : ancien scan naïf (peut être faussé par une grosse pochette) ---
        self._parse_audio_frame_naive(f)

    def _parse_audio_frame_naive(self, f):
        """Ancien parse de frame audio MPEG (repli uniquement)."""
        try:
            f.seek(0)
            data = f.read(65536)
            for i in range(len(data) - 4):
                if data[i] == 0xFF and (data[i + 1] & 0xE0) == 0xE0:
                    hdr = struct.unpack('>I', data[i:i+4])[0]
                    br_idx = (hdr >> 12) & 15
                    sr_idx = (hdr >> 10) & 3
                    ch_mode = (hdr >> 6) & 3
                    if 0 < br_idx < 15 and sr_idx < 3:
                        self.audio_info['bitrate'] = self.BITRATE_TABLE[br_idx]
                        self.audio_info['samplerate'] = self.SAMPLERATE_TABLE[sr_idx]
                        self.audio_info['channels'] = 1 if ch_mode == 3 else 2
                        if self.audio_info['bitrate'] > 0:
                            fsize = self.filepath.stat().st_size
                            self.audio_info['duration_seconds'] = (fsize * 8) / (self.audio_info['bitrate'] * 1000)
                        break
        except:
            pass

    def _detect_lame(self, f):
        """Détecte encodeur LAME"""
        try:
            f.seek(0)
            data = f.read(32768)
            idx = data.find(b'LAME')
            if idx != -1:
                enc = data[idx:idx+20].decode('ascii', errors='ignore').split('\x00')[0]
                enc = ''.join(c for c in enc if c.isprintable())
                if enc:
                    self.tags['TSSE'] = enc
        except:
            pass

    def _build_result(self) -> Dict:
        return {'tags': self.tags, 'audio_info': self.audio_info, 'cover_data': self.cover_data}
