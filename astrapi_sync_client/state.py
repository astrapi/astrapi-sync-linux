# astrapi_sync_client/state.py
"""Pro Ordner: der zuletzt bekannte Server-Stand je Datei (Hash + Größe).

Grundlage für die Drei-Wege-Erkennung in engine.py: weicht der aktuelle
lokale ODER der aktuelle Server-Hash vom hier gespeicherten "letzten
bekannten" Hash ab, hat sich seit dem letzten Sync etwas geändert --
weichen BEIDE ab, ist es ein echter Konflikt.
"""
import json

from astrapi_sync_client.config import state_dir


def load_state(folder_id: str) -> dict:
    p = state_dir() / f"{folder_id}.json"
    if not p.exists():
        return {"files": {}}
    return json.loads(p.read_text())


def save_state(folder_id: str, state: dict) -> None:
    p = state_dir() / f"{folder_id}.json"
    p.write_text(json.dumps(state, indent=2))
