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


def _local_files(root: Path) -> dict[str, Path]:
    return {
        p.relative_to(root).as_posix(): p
        for p in sorted(root.rglob("*"))
        if p.is_file() and ".syncconflict-" not in p.name
    }


def _conflict_copy(local_path: Path, device_label: str) -> Path:
    ts = datetime.now().strftime("%Y%m%d-%H%M%S")
    conflict_path = local_path.with_name(f"{local_path.stem}.syncconflict-{ts}-{device_label}{local_path.suffix}")
    shutil.copy2(local_path, conflict_path)
    return conflict_path


def sync_folder_once(
    client: ApiClient, folder_id: str, local_root: Path, device_label: str = "geraet"
) -> dict:
    local_root.mkdir(parents=True, exist_ok=True)
    remote_index = client.get_index(folder_id)
    local_index = _local_files(local_root)
    state = load_state(folder_id)
    known = state.get("files", {})

    result = {
        "uploaded": [],
        "downloaded": [],
        "deleted_local": [],
        "deleted_remote": [],
        "conflicts": [],
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

    save_state(folder_id, {"files": known})
    return result
