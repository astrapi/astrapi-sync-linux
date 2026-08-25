# astrapi_sync_cli/cli.py
import argparse
import asyncio
import sys
from pathlib import Path

from astrapi_sync_cli import config as cfgmod
from astrapi_sync_cli.api_client import ApiClient
from astrapi_sync_cli.engine import MAX_AUTO_DELETE, sync_folder_once


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
    for fid, local_path in folders.items():
        result = sync_folder_once(
            client, fid, Path(local_path), device_label=device_label, confirm_deletes=args.yes_delete
        )
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
    return 1 if had_abort else 0


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
    cfg = cfgmod.load()
    print(f"Server:      {cfg['server_url'] or '(nicht gekoppelt)'}")
    print(f"Geräte-ID:   {cfg['device_id'] or '-'}")
    print("Ordner:")
    for fid, local_path in cfg.get("folders", {}).items():
        print(f"  {fid} -> {local_path}")
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
    sys.exit(args.func(args))


if __name__ == "__main__":
    main()
