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


def atomic_write(path: Path, content: str, mode: int | None = None) -> None:
    """Schreibt content atomar (Temp-Datei im selben Verzeichnis + os.replace()).

    Bricht der Prozess mitten im Schreiben ab (Absturz, SIGKILL,
    Stromausfall), bleibt dank atomarem Rename immer entweder die alte
    oder die neue vollständige Datei stehen, nie ein kaputter
    Zwischenzustand (T-217-SYNC). Mit gesetztem `mode` bekommt die
    Temp-Datei ihre Rechte im selben Syscall wie das Anlegen, dann
    ersetzt `os.replace()` atomar die Zieldatei -- kein Zeitfenster mit
    zu weiten Rechten, unabhängig davon, ob die Zieldatei vorher schon
    (mit anderen Rechten) existierte (T-218-SYNC).
    """
    tmp = path.with_name(f".{path.name}.tmp-{os.getpid()}")
    data = content.encode()
    if mode is not None:
        fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, mode)
        try:
            os.write(fd, data)
        finally:
            os.close(fd)
    else:
        tmp.write_bytes(data)
    os.replace(tmp, path)


def save(cfg: dict) -> None:
    atomic_write(config_path(), json.dumps(cfg, indent=2, ensure_ascii=False), mode=0o600)
