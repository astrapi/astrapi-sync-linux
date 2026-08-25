# astrapi_sync_cli/state.py
"""Pro Ordner: der zuletzt bekannte Server-Stand je Datei (Hash + Größe)
sowie die Liste zuletzt bekannter leerer Verzeichnisse ("dirs").

Grundlage für die Drei-Wege-Erkennung in engine.py: weicht der aktuelle
lokale ODER der aktuelle Server-Hash vom hier gespeicherten "letzten
bekannten" Hash ab, hat sich seit dem letzten Sync etwas geändert --
weichen BEIDE ab, ist es ein echter Konflikt. Für leere Verzeichnisse gilt
dieselbe Drei-Wege-Logik, nur ohne Hash (nur "war bekannt: ja/nein"), da
es dort nichts als den bloßen Pfad gibt, das sich "ändern" könnte.

An den lokalen Pfad gebunden (local_root wird mitgespeichert): zeigt ein
folder_id inzwischen auf einen ANDEREN lokalen Ordner (add-folder wurde
geändert), ist ein alter gespeicherter Stand für den jetzigen Ordner
irrelevant und wird verworfen -- sonst könnten zufällig gleich benannte
Dateien mit zufällig gleichem Inhalt im neuen Ordner fälschlich als
"server-seitig gelöscht, hier auch löschen" erkannt werden.
"""
import json

from astrapi_sync_cli.config import atomic_write, state_dir


def load_state(folder_id: str, local_root) -> dict:
    p = state_dir() / f"{folder_id}.json"
    if not p.exists():
        return {"files": {}, "dirs": []}
    try:
        data = json.loads(p.read_text())
    except json.JSONDecodeError as exc:
        # Vor T-217-SYNC konnte ein Absturz mitten im (nicht-atomaren)
        # Schreiben genau das erzeugen -- jetzt nur noch durch manuelle
        # Manipulation der Datei erreichbar, aber die Fehlermeldung soll
        # trotzdem sagen, was zu tun ist, statt einen nackten Traceback zu
        # werfen.
        raise RuntimeError(
            f"State-Datei für Ordner {folder_id} ist beschädigt ({p}): {exc}. "
            "Datei löschen, um den Stand neu aufzubauen -- bei bereits "
            "divergenten Pfaden greift dabei die Konflikterkennung aus "
            "T-215-SYNC."
        ) from exc
    if data.get("local_root") != str(local_root):
        return {"files": {}, "dirs": []}
    return data


def save_state(folder_id: str, local_root, state: dict) -> None:
    state = dict(state)
    state["local_root"] = str(local_root)
    p = state_dir() / f"{folder_id}.json"
    atomic_write(p, json.dumps(state, indent=2))
