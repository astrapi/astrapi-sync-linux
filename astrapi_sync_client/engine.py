# astrapi_sync_client/engine.py
"""Kern der Sync-Engine: vergleicht lokalen Ordner, Server-Index und den
zuletzt bekannten Server-Stand (state.py), leitet daraus Uploads,
Downloads, Löschungen und Konflikte ab.

Kein rsync-Rolling-Hash, keine Byte-Verschiebungs-Erkennung -- fester
Blockvergleich per Position (siehe block_hash.py / Architektur im Plan).
"""
import shutil
from datetime import datetime
from pathlib import Path

from astrapi_sync_client.api_client import ApiClient, ConflictError
from astrapi_sync_client.block_hash import whole_file_hash
from astrapi_sync_client.state import load_state, save_state

# Sicherheitsschwelle gegen Massen-Löschungen: mehr als so viele Dateien
# in einem einzigen Lauf werden NICHT automatisch gelöscht (weder lokal
# noch remote), sondern der Lauf bricht vorher ab und meldet, was er
# gelöscht HÄTTE. Grund: der Client kann nicht unterscheiden zwischen
# "jemand hat bewusst Dateien gelöscht" und "der Server/lokale Ordner hat
# plötzlich unerwartet nichts mehr" (z.B. weil außerhalb der App etwas am
# Datenverzeichnis manipuliert wurde) -- ein einzelner Sync-Lauf sollte
# nie mehr als eine Handvoll Dateien auf einmal stillschweigend vernichten
# können. Siehe T-203-SYNC.
MAX_AUTO_DELETE = 3


def _local_files(root: Path) -> dict[str, Path]:
    return {
        p.relative_to(root).as_posix(): p
        for p in sorted(root.rglob("*"))
        if p.is_file() and ".syncconflict-" not in p.name
    }


def _local_empty_dirs(root: Path) -> list[str]:
    """Relative Pfade aller (rekursiv) leeren lokalen Verzeichnisse.

    Muss NACH dem Datei-Sync-Loop aufgerufen werden -- ein Verzeichnis,
    das gerade erst eine Datei bekommen (Up-/Download) oder verloren
    (Löschung) hat, darf nicht mit einem veralteten Leer-Zustand
    bewertet werden.
    """
    return [
        p.relative_to(root).as_posix()
        for p in sorted(root.rglob("*"))
        if p.is_dir() and not any(f.is_file() for f in p.rglob("*"))
    ]


def _conflict_copy(local_path: Path, device_label: str) -> Path:
    ts = datetime.now().strftime("%Y%m%d-%H%M%S")
    conflict_path = local_path.with_name(f"{local_path.stem}.syncconflict-{ts}-{device_label}{local_path.suffix}")
    shutil.copy2(local_path, conflict_path)
    return conflict_path


def _plan_deletions(
    remote_index: dict, local_index: dict, known: dict
) -> tuple[list[str], list[str]]:
    """Ermittelt, welche lokalen bzw. Remote-Löschungen dieser Lauf
    auslösen WÜRDE, ohne irgendetwas auszuführen -- Grundlage für die
    Massen-Löschungs-Sicherheitsabfrage in sync_folder_once()."""
    local_deletes: list[str] = []
    remote_deletes: list[str] = []
    for rel_path in set(remote_index) | set(local_index) | set(known):
        remote = remote_index.get(rel_path)
        local_path = local_index.get(rel_path)
        last_known = known.get(rel_path)
        if last_known is None:
            continue
        if remote is None and local_path is not None:
            if whole_file_hash(local_path) == last_known.get("sha256"):
                local_deletes.append(rel_path)
        elif remote is not None and local_path is None:
            if last_known.get("sha256") == remote["sha256"]:
                remote_deletes.append(rel_path)
    return local_deletes, remote_deletes


def sync_folder_once(
    client: ApiClient,
    folder_id: str,
    local_root: Path,
    device_label: str = "geraet",
    confirm_deletes: bool = False,
    max_auto_delete: int = MAX_AUTO_DELETE,
) -> dict:
    local_root.mkdir(parents=True, exist_ok=True)
    remote_index, remote_dirs = client.get_index_full(folder_id)
    local_index = _local_files(local_root)
    state = load_state(folder_id, local_root)
    known = state.get("files", {})
    known_dirs = set(state.get("dirs", []))

    local_deletes, remote_deletes = _plan_deletions(remote_index, local_index, known)
    total_deletes = len(local_deletes) + len(remote_deletes)
    if total_deletes > max_auto_delete and not confirm_deletes:
        return {
            "aborted": True,
            "reason": (
                f"{total_deletes} Löschungen in einem Lauf "
                f"(Grenze: {max_auto_delete}) -- ohne Bestätigung nicht ausgeführt"
            ),
            "would_delete_local": local_deletes,
            "would_delete_remote": remote_deletes,
        }

    result = {
        "uploaded": [],
        "downloaded": [],
        "deleted_local": [],
        "deleted_remote": [],
        "conflicts": [],
        "dirs_created_local": [],
        "dirs_created_remote": [],
        "dirs_deleted_local": [],
        "dirs_deleted_remote": [],
    }

    for rel_path in sorted(set(remote_index) | set(local_index) | set(known)):
        remote = remote_index.get(rel_path)
        local_path = local_index.get(rel_path)
        last_known = known.get(rel_path)
        local_hash = whole_file_hash(local_path) if local_path else None

        # ── nur im Verlaufsspeicher, sonst nirgends -> vergessen ────────
        if remote is None and local_path is None:
            known.pop(rel_path, None)
            continue

        # ── nur lokal vorhanden ──────────────────────────────────────────
        if remote is None and local_path is not None:
            if last_known is not None and local_hash == last_known.get("sha256"):
                # kannten wir schon (mit demselben Inhalt), Server hat sie
                # nicht mehr -> Server hat sie geloescht, hier nachziehen
                local_path.unlink()
                known.pop(rel_path, None)
                result["deleted_local"].append(rel_path)
            else:
                # neu, oder lokal seit der Server-Loeschung veraendert
                # -> hochladen ("wiederherstellen")
                info = client.upload(folder_id, rel_path, local_path, None, None)
                known[rel_path] = {"sha256": info["sha256"], "size": local_path.stat().st_size}
                result["uploaded"].append(rel_path)
            continue

        # ── nur remote vorhanden ─────────────────────────────────────────
        if remote is not None and local_path is None:
            if last_known is not None and last_known.get("sha256") == remote["sha256"]:
                # kannten wir schon (unveraendert auf dem Server), ist
                # jetzt lokal weg -> wir haben sie geloescht, dem Server
                # mitteilen statt sie einfach wieder runterzuladen
                client.delete(folder_id, rel_path)
                known.pop(rel_path, None)
                result["deleted_remote"].append(rel_path)
            else:
                dest = local_root / rel_path
                client.download(folder_id, rel_path, dest)
                known[rel_path] = {"sha256": remote["sha256"], "size": remote["size"]}
                result["downloaded"].append(rel_path)
            continue

        # ── auf beiden Seiten vorhanden ──────────────────────────────────
        if local_hash == remote["sha256"]:
            known[rel_path] = {"sha256": local_hash, "size": local_path.stat().st_size}
            continue

        local_changed = last_known is None or last_known.get("sha256") != local_hash
        remote_changed = last_known is None or last_known.get("sha256") != remote["sha256"]

        if local_changed and remote_changed and last_known is not None:
            _conflict_copy(local_path, device_label)
            client.download(folder_id, rel_path, local_path)
            known[rel_path] = {"sha256": remote["sha256"], "size": remote["size"]}
            result["conflicts"].append(rel_path)
            continue

        if remote_changed and not local_changed:
            client.download(folder_id, rel_path, local_path)
            known[rel_path] = {"sha256": remote["sha256"], "size": remote["size"]}
            result["downloaded"].append(rel_path)
            continue

        # lokal geaendert (oder Erst-Sync ohne bekannten Stand) -> hochladen
        try:
            info = client.upload(folder_id, rel_path, local_path, remote.get("blocks"), remote.get("sha256"))
        except ConflictError:
            # Wettlauf zwischen Index-Abruf und Upload: Server hat sich
            # zwischenzeitlich veraendert -> wie ein echter Konflikt behandeln
            _conflict_copy(local_path, device_label)
            fresh = client.get_index(folder_id).get(rel_path)
            if fresh:
                client.download(folder_id, rel_path, local_path)
                known[rel_path] = {"sha256": fresh["sha256"], "size": fresh["size"]}
            result["conflicts"].append(rel_path)
            continue
        known[rel_path] = {"sha256": info["sha256"], "size": local_path.stat().st_size}
        result["uploaded"].append(rel_path)

    # ── Leere Verzeichnisse ────────────────────────────────────────────────
    # Kein Massenlöschungs-Schutz nötig wie oben bei Dateien: ein leeres
    # Verzeichnis enthält per Definition keine Daten, die verloren gehen
    # könnten -- Erstellen/Löschen läuft daher immer automatisch.
    # local_dirs erst JETZT (nach dem Datei-Loop) ermitteln: ein
    # Verzeichnis, das durch einen gerade erfolgten Up-/Download seinen
    # Leer-Zustand verloren hat, darf hier nicht mehr als leer gelten.
    local_dirs = set(_local_empty_dirs(local_root))
    remote_dirs_set = set(remote_dirs)

    for rel_path in sorted(local_dirs | remote_dirs_set | known_dirs):
        in_local = rel_path in local_dirs
        in_remote = rel_path in remote_dirs_set
        was_known = rel_path in known_dirs

        if in_local and in_remote:
            known_dirs.add(rel_path)
            continue

        if in_local and not in_remote:
            if was_known:
                # bekannt gewesen, Server hat ihn geloescht -> lokal nachziehen.
                # rmdir() kann fehlschlagen, wenn "leer" hier veraltet ist
                # (z.B. weiter oben im selben Lauf gerade erst eine Datei
                # hineinsynchronisiert wurde) -- dann bleibt er bekannt,
                # kein Fantom-Löschen im Ergebnis-Report.
                try:
                    (local_root / rel_path).rmdir()
                    known_dirs.discard(rel_path)
                    result["dirs_deleted_local"].append(rel_path)
                except OSError:
                    known_dirs.add(rel_path)
            else:
                client.create_dir(folder_id, rel_path)
                known_dirs.add(rel_path)
                result["dirs_created_remote"].append(rel_path)
            continue

        if in_remote and not in_local:
            if was_known:
                # bekannt gewesen, lokal geloescht -> dem Server mitteilen
                if client.delete_dir(folder_id, rel_path):
                    known_dirs.discard(rel_path)
                    result["dirs_deleted_remote"].append(rel_path)
                else:
                    known_dirs.add(rel_path)
            else:
                (local_root / rel_path).mkdir(parents=True, exist_ok=True)
                known_dirs.add(rel_path)
                result["dirs_created_local"].append(rel_path)
            continue

        # weder lokal noch remote, nur noch im Verlaufsspeicher -> vergessen
        known_dirs.discard(rel_path)

    save_state(folder_id, local_root, {"files": known, "dirs": sorted(known_dirs)})
    return result
