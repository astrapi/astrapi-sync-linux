# astrapi_sync_cli/cli.py
import argparse
import asyncio
import sys
from pathlib import Path

import httpx

from astrapi_sync_cli import config as cfgmod
from astrapi_sync_cli.api_client import ApiClient
from astrapi_sync_cli.engine import MAX_AUTO_DELETE, sync_folder_once


def _server_detail(response: httpx.Response) -> str:
    """Extrahiert FastAPIs "detail"-Feld aus einer Fehlerantwort, falls
    vorhanden, statt des rohen Response-Texts (T-229-SYNC)."""
    try:
        body = response.json()
    except ValueError:
        return response.text or f"{response.status_code} {response.reason_phrase}"
    if isinstance(body, dict) and "detail" in body:
        return str(body["detail"])
    return response.text or f"{response.status_code} {response.reason_phrase}"


def _format_error(exc: Exception) -> str:
    """Menschenlesbare Fehlermeldung statt rohem Traceback (T-229-SYNC)."""
    if isinstance(exc, httpx.HTTPStatusError):
        return _server_detail(exc.response)
    if isinstance(exc, httpx.RequestError):
        return f"Server nicht erreichbar ({exc})"
    return str(exc)


def cmd_pair(args) -> int:
    import socket

    label = args.description or socket.gethostname()
    result = ApiClient.pair(args.server_url, args.pairing_code, label, args.platform)
    cfg = cfgmod.load()
    cfg["server_url"] = args.server_url.rstrip("/")
    cfg["device_token"] = result["device_token"]
    cfg["device_id"] = result["device_id"]
    cfg["device_label"] = label
    cfgmod.save(cfg)
    print(f"Gekoppelt als Gerät {result['device_id']}. Zugriff auf Ordner: {result['folder_ids']}")
    print(f"Konfiguration gespeichert unter {cfgmod.config_path()}")
    return 0


def cmd_list_folders(args) -> int:
    cfg = cfgmod.load()
    if not cfg["device_token"]:
        print("Noch nicht gekoppelt -- siehe 'astrapi-sync-cli pair'.", file=sys.stderr)
        return 1
    client = ApiClient(cfg["server_url"], cfg["device_token"])
    folders = client.list_folders()
    mapped = cfg.get("folders", {})
    for f in folders:
        local = mapped.get(f["id"])
        status = f"-> {local}" if local else "(nicht verbunden)"
        print(f"{f['id']:>4}  {f['description']:<30} {status}")
    return 0


def cmd_add_folder(args) -> int:
    cfg = cfgmod.load()
    cfg.setdefault("folders", {})[args.folder_id] = str(Path(args.local_path).expanduser().resolve())
    cfgmod.save(cfg)
    print(f"Ordner {args.folder_id} <-> {cfg['folders'][args.folder_id]}")
    return 0


def cmd_sync(args) -> int:
    cfg = cfgmod.load()
    if not cfg["device_token"]:
        print("Noch nicht gekoppelt -- siehe 'astrapi-sync-cli pair'.", file=sys.stderr)
        return 1
    client = ApiClient(cfg["server_url"], cfg["device_token"])
    folders = cfg.get("folders", {})
    if args.folder:
        folders = {k: v for k, v in folders.items() if k == args.folder}
    if not folders:
        print("Keine Ordner konfiguriert -- siehe 'astrapi-sync-cli add-folder'.", file=sys.stderr)
        return 1
    device_label = cfg.get("device_label") or "geraet"
    had_abort = False
    had_error = False
    for fid, local_path in folders.items():
        try:
            result = sync_folder_once(
                client, fid, Path(local_path), device_label=device_label, confirm_deletes=args.yes_delete
            )
        except Exception as exc:
            # Ein Fehler bei EINEM Ordner (z.B. HTTP 403 nach veralteter
            # folder_id-Zuordnung) darf nicht die ganze Schleife abbrechen
            # -- deutlich ausgeben und mit dem naechsten Ordner
            # weitermachen (T-216-SYNC, real so aufgetreten).
            had_error = True
            print(f"[{fid}] FEHLER: {_format_error(exc)}", file=sys.stderr)
            continue
        if result.get("aborted"):
            had_abort = True
            print(f"[{fid}] ABGEBROCHEN: {result['reason']}")
            if result["would_delete_local"]:
                print(f"  Würde lokal gelöscht: {result['would_delete_local']}")
            if result["would_delete_remote"]:
                print(f"  Würde auf dem Server gelöscht: {result['would_delete_remote']}")
            print("  Wenn das gewollt ist: 'astrapi-sync-cli sync --yes-delete' erneut ausführen.")
        else:
            print(f"[{fid}] {result}")
    return 1 if (had_abort or had_error) else 0


def cmd_daemon(args) -> int:
    from astrapi_sync_cli.daemon import run_daemon

    cfg = cfgmod.load()
    if not cfg["device_token"]:
        print("Noch nicht gekoppelt -- siehe 'astrapi-sync-cli pair'.", file=sys.stderr)
        return 1
    folder_ids = [args.folder] if args.folder else None
    asyncio.run(run_daemon(cfg, folder_ids))
    return 0


def cmd_status(args) -> int:
    """Zeigt neben der Config auch den echten lokalen Sync-Zustand je
    Ordner -- Anzahl bekannter Dateien/Verzeichnisse und Zeitpunkt des
    letzten Laufs aus der lokalen state.json, ganz ohne Server-Roundtrip
    (T-228-SYNC)."""
    import json
    from datetime import datetime

    from astrapi_sync_cli.config import state_dir

    cfg = cfgmod.load()
    print(f"Server:      {cfg['server_url'] or '(nicht gekoppelt)'}")
    print(f"Geräte-ID:   {cfg['device_id'] or '-'}")
    print("Ordner:")
    for fid, local_path in cfg.get("folders", {}).items():
        line = f"  {fid} -> {local_path}"
        state_path = state_dir() / f"{fid}.json"
        if not state_path.exists():
            print(f"{line}  (noch nie synchronisiert)")
            continue
        try:
            raw = json.loads(state_path.read_text())
        except json.JSONDecodeError:
            print(f"{line}  (State-Datei beschädigt, siehe {state_path})")
            continue
        if raw.get("local_root") != local_path:
            # Ordner wurde inzwischen mit einem anderen lokalen Pfad
            # verbunden -- der gespeicherte Stand gehört zum alten Pfad
            # und wird beim nächsten Sync verworfen (siehe state.py).
            print(f"{line}  (Pfad seit letztem Sync geändert -- Stand wird beim nächsten Lauf neu aufgebaut)")
            continue
        n_files = len(raw.get("files", {}))
        n_dirs = len(raw.get("dirs", []))
        last_sync = datetime.fromtimestamp(state_path.stat().st_mtime).strftime("%Y-%m-%d %H:%M:%S")
        print(f"{line}  ({n_files} Dateien, {n_dirs} Verzeichnisse, zuletzt synchronisiert {last_sync})")
    return 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="astrapi-sync-cli")
    sub = p.add_subparsers(dest="command", required=True)

    pp = sub.add_parser("pair", help="Gerät mit einem Server koppeln")
    pp.add_argument("server_url", help="z.B. http://sync.simpsons.lan:5004")
    pp.add_argument("pairing_code", help="Im Server-UI unter Geräte -> 'Gerät koppeln' erzeugt")
    pp.add_argument("--description", default="")
    pp.add_argument("--platform", default="cli")
    pp.set_defaults(func=cmd_pair)

    lf = sub.add_parser("list-folders", help="Für dieses Gerät freigegebene Ordner anzeigen")
    lf.set_defaults(func=cmd_list_folders)

    af = sub.add_parser("add-folder", help="Server-Ordner mit einem lokalen Ordner verbinden")
    af.add_argument("folder_id")
    af.add_argument("local_path")
    af.set_defaults(func=cmd_add_folder)

    sy = sub.add_parser("sync", help="Einmaligen Sync-Lauf ausführen")
    sy.add_argument("--folder", default=None, help="Nur diesen Ordner syncen (Standard: alle)")
    sy.add_argument(
        "--yes-delete",
        action="store_true",
        help=f"Löschungen auch dann ausführen, wenn ein Lauf mehr als {MAX_AUTO_DELETE} "
        "Dateien auf einmal löschen würde (sonst wird zur Sicherheit abgebrochen)",
    )
    sy.set_defaults(func=cmd_sync)

    da = sub.add_parser("daemon", help="Dauerhaft im Hintergrund syncen (Dateibeobachtung + WebSocket-Push)")
    da.add_argument("--folder", default=None, help="Nur diesen Ordner (Standard: alle)")
    da.set_defaults(func=cmd_daemon)

    st = sub.add_parser("status", help="Aktuelle Konfiguration anzeigen")
    st.set_defaults(func=cmd_status)

    return p


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()
    try:
        sys.exit(args.func(args))
    except (httpx.HTTPStatusError, httpx.RequestError) as exc:
        # Zentraler Fang fuer alle Befehle, die cmd_sync's eigene
        # Pro-Ordner-Behandlung nicht durchlaufen (pair, list-folders,
        # status-Vorstufe, daemon-Start) -- klare Meldung statt rohem
        # Traceback (T-229-SYNC).
        print(f"FEHLER: {_format_error(exc)}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
