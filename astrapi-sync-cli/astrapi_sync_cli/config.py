# astrapi_sync_cli/config.py
"""Lokale Konfiguration: Server-URL, Geräte-Token, Ordner-Zuordnungen.

Geräte-Token liegt im Klartext in config.json (Datei-Rechte 0600) --
bewusste MVP-Vereinfachung statt OS-Keyring-Integration; ausbaufähig,
sobald die GTK4-App kommt (Phase 4).
"""
import json
import os
from pathlib import Path

DEFAULTS = {"server_url": "", "device_token": "", "device_id": "", "device_label": "", "folders": {}}
# folders: {folder_id: local_path}


def config_dir() -> Path:
    base = Path(os.environ.get("XDG_CONFIG_HOME") or "~/.config").expanduser()
    d = base / "astrapi-sync"
    d.mkdir(parents=True, exist_ok=True)
    return d


def config_path() -> Path:
    return config_dir() / "config.json"


def state_dir() -> Path:
    d = config_dir() / "state"
    d.mkdir(parents=True, exist_ok=True)
    return d


def load() -> dict:
    p = config_path()
    if not p.exists():
        return dict(DEFAULTS)
    data = json.loads(p.read_text())
    return {**DEFAULTS, **data}


def save(cfg: dict) -> None:
    p = config_path()
    p.write_text(json.dumps(cfg, indent=2, ensure_ascii=False))
    p.chmod(0o600)
