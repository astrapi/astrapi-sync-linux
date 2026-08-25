# astrapi_sync_cli/daemon.py
"""Dauerbetrieb (Phase 3): lokale Dateiänderungen (watchdog) UND
Server-Push (WebSocket) lösen jeweils einen Sync-Lauf aus, dazu ein
periodischer Fallback-Sync als Sicherheitsnetz (falls ein Event verpasst
wurde -- Netzwerkausfall, watchdog-Limitierung o.ä.)."""
import asyncio
import queue
import sys
import time
from pathlib import Path

import websockets
from watchdog.events import FileSystemEventHandler
from watchdog.observers import Observer

from astrapi_sync_cli.api_client import ApiClient
from astrapi_sync_cli.engine import sync_folder_once

# Schliessen-Codes, mit denen der Server signalisiert, dass die
# WebSocket-Verbindung nicht nur voruebergehend, sondern DAUERHAFT
# ungueltig ist (Geraet geloescht/deaktiviert, Token ungueltig, kein
# Zugriff mehr auf den Ordner) -- siehe astrapi_sync/api/sync.py::folder_events().
_WS_PERMANENT_CLOSE_CODES = {4401: "Token ungültig", 4403: "kein Zugriff auf diesen Ordner"}


class _ChangeHandler(FileSystemEventHandler):
    def __init__(self, q: "queue.Queue"):
        self._q = q

    def on_any_event(self, event):
        if event.is_directory:
            return
        if ".astrapi-sync-tmp" in event.src_path or ".syncconflict-" in event.src_path:
            return
        self._q.put(True)


class _LocalWriteGuard:
    """Unterdrückt watchdog-Events für ein kurzes Zeitfenster nach einem
    Sync-Lauf, der selbst lokal geschrieben hat (Download, lokales Löschen,
    Verzeichnis-Änderung) -- sonst löst jeder serverseitig ausgelöste
    Download sofort einen weiteren, unnötigen Sync-Lauf aus, der nichts zu
    tun findet (T-221-SYNC)."""

    _LOCAL_WRITE_KEYS = ("downloaded", "deleted_local", "dirs_created_local", "dirs_deleted_local")

    def __init__(self, suppress_seconds: float = 2.0):
        self._suppress_seconds = suppress_seconds
        self._suppress_until = 0.0

    def note_result(self, result: dict) -> None:
        if any(result.get(k) for k in self._LOCAL_WRITE_KEYS):
            self._suppress_until = time.monotonic() + self._suppress_seconds

    def should_suppress(self) -> bool:
        return time.monotonic() < self._suppress_until


async def _debounced_local_watch(
    local_root: Path, sync_fn, guard: "_LocalWriteGuard | None" = None, debounce_seconds: float = 1.5
) -> None:
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
            if guard is not None and guard.should_suppress():
                # Events stammen hoechstwahrscheinlich vom eigenen letzten
                # Sync-Lauf selbst (z.B. gerade heruntergeladene Dateien) --
                # kein erneuter Lauf noetig (T-221-SYNC).
                continue
            await sync_fn()
    finally:
        observer.stop()
        observer.join()


async def _ws_listener(server_url: str, device_token: str, folder_id: str, sync_fn) -> None:
    ws_url = server_url.replace("https://", "wss://").replace("http://", "ws://").rstrip("/")
    ws_url = f"{ws_url}/api/sync/folders/{folder_id}/events?token={device_token}"
    while True:
        close_code = None
        try:
            async with websockets.connect(ws_url, ping_interval=20) as ws:
                async for _msg in ws:
                    await sync_fn()
                close_code = ws.close_code
        except Exception:
            pass
        if close_code in _WS_PERMANENT_CLOSE_CODES:
            # Dauerhafter Fehler (Geraet geloescht/deaktiviert, Token
            # ungueltig, kein Zugriff mehr) -- endloses Alle-5-Sekunden-
            # Retry waere fuer immer sinnlos und bliebe fuer den Nutzer
            # unsichtbar. Task fuer diesen Ordner sauber beenden, deutlich
            # ins Journal loggen; der periodische Fallback-Sync bleibt
            # unberuehrt (T-223-SYNC).
            print(
                f"[{folder_id}] WebSocket-Push dauerhaft beendet "
                f"(Code {close_code}: {_WS_PERMANENT_CLOSE_CODES[close_code]}) -- "
                "Gerät im Server-UI prüfen. Kein weiterer Verbindungsversuch für "
                "diesen Ordner.",
                file=sys.stderr,
            )
            return
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

    def make_sync_fn(fid: str, root: Path, guard: "_LocalWriteGuard"):
        async def _sync():
            async with locks[fid]:
                result = await asyncio.to_thread(
                    sync_folder_once, client, fid, root, device_label
                )
                guard.note_result(result)
                if result.get("aborted"):
                    # Im Dauerbetrieb NIE automatisch bestaetigen -- nur
                    # laut loggen, der naechste Trigger (Dateiaenderung,
                    # WebSocket-Event, periodischer Fallback) versucht es
                    # einfach erneut. Manuelles Eingreifen (sync --yes-delete)
                    # noetig, wenn die Loeschung wirklich gewollt ist.
                    print(f"[{fid}] ABGEBROCHEN: {result['reason']}")
                    if result["would_delete_local"]:
                        print(f"  Würde lokal gelöscht: {result['would_delete_local']}")
                    if result["would_delete_remote"]:
                        print(f"  Würde auf dem Server gelöscht: {result['would_delete_remote']}")
                    return
                changed = sum(len(v) for v in result.values())
                if changed:
                    print(f"[{fid}] {result}")

        return _sync

    for fid, local_path in folders.items():
        root = Path(local_path)
        guard = _LocalWriteGuard()
        sync_fn = make_sync_fn(fid, root, guard)
        # Initialer Sync beim Start, bevor auf Events gewartet wird.
        await sync_fn()
        tasks.append(asyncio.create_task(_debounced_local_watch(root, sync_fn, guard)))
        tasks.append(asyncio.create_task(_ws_listener(cfg["server_url"], cfg["device_token"], fid, sync_fn)))
        tasks.append(asyncio.create_task(_periodic_fallback(sync_fn)))

    print(f"astrapi-sync-cli daemon läuft für {len(folders)} Ordner …")
    await asyncio.gather(*tasks)
