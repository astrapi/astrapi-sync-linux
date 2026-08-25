# astrapi_sync_client/daemon.py
"""Dauerbetrieb (Phase 3): lokale Dateiänderungen (watchdog) UND
Server-Push (WebSocket) lösen jeweils einen Sync-Lauf aus, dazu ein
periodischer Fallback-Sync als Sicherheitsnetz (falls ein Event verpasst
wurde -- Netzwerkausfall, watchdog-Limitierung o.ä.)."""
import asyncio
import queue
from pathlib import Path

import websockets
from watchdog.events import FileSystemEventHandler
from watchdog.observers import Observer

from astrapi_sync_client.api_client import ApiClient
from astrapi_sync_client.engine import sync_folder_once


class _ChangeHandler(FileSystemEventHandler):
    def __init__(self, q: "queue.Queue"):
        self._q = q

    def on_any_event(self, event):
        if event.is_directory:
            return
        if ".astrapi-sync-tmp" in event.src_path or ".syncconflict-" in event.src_path:
            return
        self._q.put(True)


async def _debounced_local_watch(local_root: Path, sync_fn, debounce_seconds: float = 1.5) -> None:
    q: "queue.Queue" = queue.Queue()
    observer = Observer()
    observer.schedule(_ChangeHandler(q), str(local_root), recursive=True)
    observer.start()
    try:
        while True:
            await asyncio.to_thread(q.get)
            # Kurz warten und puffern -- eine grosse Kopieraktion feuert
            # sonst pro Datei einen eigenen (teuren) vollen Sync-Lauf aus.
            await asyncio.sleep(debounce_seconds)
            while not q.empty():
                q.get_nowait()
            await sync_fn()
    finally:
        observer.stop()
        observer.join()


async def _ws_listener(server_url: str, device_token: str, folder_id: str, sync_fn) -> None:
    ws_url = server_url.replace("https://", "wss://").replace("http://", "ws://").rstrip("/")
    ws_url = f"{ws_url}/api/sync/folders/{folder_id}/events?token={device_token}"
    while True:
        try:
            async with websockets.connect(ws_url, ping_interval=20) as ws:
                async for _msg in ws:
                    await sync_fn()
        except Exception:
            await asyncio.sleep(5)  # Server kurz nicht erreichbar -- erneut versuchen


async def _periodic_fallback(sync_fn, interval_seconds: int = 300) -> None:
    while True:
        await asyncio.sleep(interval_seconds)
        await sync_fn()


async def run_daemon(cfg: dict, folder_ids: list[str] | None = None) -> None:
    client = ApiClient(cfg["server_url"], cfg["device_token"])
    folders = cfg.get("folders", {})
    if folder_ids:
        folders = {k: v for k, v in folders.items() if k in folder_ids}
    if not folders:
        print("Keine Ordner konfiguriert -- siehe 'astrapi-sync-cli add-folder'.")
        return

    device_label = cfg.get("device_label") or "geraet"
    locks = {fid: asyncio.Lock() for fid in folders}
    tasks: list[asyncio.Task] = []

    def make_sync_fn(fid: str, root: Path):
        async def _sync():
            async with locks[fid]:
                result = await asyncio.to_thread(
                    sync_folder_once, client, fid, root, device_label
                )
                changed = sum(len(v) for v in result.values())
                if changed:
                    print(f"[{fid}] {result}")

        return _sync

    for fid, local_path in folders.items():
        root = Path(local_path)
        sync_fn = make_sync_fn(fid, root)
        # Initialer Sync beim Start, bevor auf Events gewartet wird.
        await sync_fn()
        tasks.append(asyncio.create_task(_debounced_local_watch(root, sync_fn)))
        tasks.append(asyncio.create_task(_ws_listener(cfg["server_url"], cfg["device_token"], fid, sync_fn)))
        tasks.append(asyncio.create_task(_periodic_fallback(sync_fn)))

    print(f"astrapi-sync-cli daemon läuft für {len(folders)} Ordner …")
    await asyncio.gather(*tasks)
