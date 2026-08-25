# astrapi_sync_cli/api_client.py
import json
from pathlib import Path
from urllib.parse import quote

import httpx

from astrapi_sync_cli.block_hash import DEFAULT_BLOCK_SIZE, hash_blocks, read_block


def _quote_path(rel_path: str) -> str:
    """URL-kodiert einen relativen Pfad für den Einsatz im URL-Pfad-Segment.

    Ohne das wird z.B. "#" von httpx als Fragment-Trenner interpretiert und
    der Rest des Pfads still abgeschnitten, bevor die Anfrage überhaupt
    losgeschickt wird (siehe T-214-SYNC) -- "/" bleibt bewusst unkodiert,
    da es der echte Pfad-Trenner ist.
    """
    return quote(rel_path, safe="/")


class ConflictError(Exception):
    def __init__(self, rel_path: str):
        self.rel_path = rel_path
        super().__init__(f"Konflikt bei {rel_path}: Server-Stand hat sich geändert")


class ApiClient:
    def __init__(self, server_url: str, device_token: str):
        self.server_url = server_url.rstrip("/")
        self.device_token = device_token
        self._client = httpx.Client(
            base_url=self.server_url,
            headers={"Authorization": f"Bearer {device_token}"} if device_token else {},
            timeout=30,
        )

    @staticmethod
    def pair(server_url: str, pairing_token: str, description: str = "", platform: str = "cli") -> dict:
        resp = httpx.post(
            f"{server_url.rstrip('/')}/api/sync/pair",
            json={"token": pairing_token, "description": description, "platform": platform},
            timeout=15,
        )
        resp.raise_for_status()
        return resp.json()

    def list_folders(self) -> list[dict]:
        r = self._client.get("/api/sync/folders")
        r.raise_for_status()
        return r.json()["folders"]

    def get_index(self, folder_id: str) -> dict[str, dict]:
        r = self._client.get(f"/api/sync/folders/{folder_id}/index")
        r.raise_for_status()
        return {e["path"]: e for e in r.json()["files"]}

    def get_index_full(self, folder_id: str) -> tuple[dict[str, dict], list[str]]:
        """Wie get_index(), liefert zusätzlich die (leeren) Verzeichnisse --
        ein Request statt zwei."""
        r = self._client.get(f"/api/sync/folders/{folder_id}/index")
        r.raise_for_status()
        body = r.json()
        return {e["path"]: e for e in body["files"]}, body.get("dirs", [])

    def download(self, folder_id: str, rel_path: str, dest: Path) -> None:
        dest.parent.mkdir(parents=True, exist_ok=True)
        tmp = dest.with_name(dest.name + ".astrapi-sync-tmp")
        with self._client.stream(
            "GET", f"/api/sync/folders/{folder_id}/files/{_quote_path(rel_path)}"
        ) as r:
            r.raise_for_status()
            with open(tmp, "wb") as f:
                for chunk in r.iter_bytes():
                    f.write(chunk)
        tmp.replace(dest)  # atomarer Rename statt in-place-Schreiben

    def upload(
        self,
        folder_id: str,
        rel_path: str,
        local_path: Path,
        remote_blocks: list[str] | None,
        expected_server_sha256: str | None,
    ) -> dict:
        local_hashes = hash_blocks(local_path)
        size = local_path.stat().st_size
        mtime = local_path.stat().st_mtime
        remote_blocks = remote_blocks or []

        changed = [
            i
            for i, h in enumerate(local_hashes)
            if i >= len(remote_blocks) or remote_blocks[i] != h
        ]
        data = b"".join(read_block(local_path, i, DEFAULT_BLOCK_SIZE) for i in changed)

        meta = {
            "size": size,
            "mtime": mtime,
            "block_size": DEFAULT_BLOCK_SIZE,
            "blocks": local_hashes,
            "changed": changed,
            "expected_server_sha256": expected_server_sha256,
        }
        r = self._client.post(
            f"/api/sync/folders/{folder_id}/files/{_quote_path(rel_path)}",
            data={"meta": json.dumps(meta)},
            files={"data": ("data.bin", data, "application/octet-stream")},
        )
        if r.status_code == 409:
            raise ConflictError(rel_path)
        r.raise_for_status()
        return r.json()

    def delete(self, folder_id: str, rel_path: str) -> None:
        r = self._client.delete(f"/api/sync/folders/{folder_id}/files/{_quote_path(rel_path)}")
        if r.status_code not in (200, 204, 404):
            r.raise_for_status()

    def create_dir(self, folder_id: str, rel_path: str) -> None:
        r = self._client.post(f"/api/sync/folders/{folder_id}/dirs/{_quote_path(rel_path)}")
        r.raise_for_status()

    def delete_dir(self, folder_id: str, rel_path: str) -> bool:
        """Gibt zurück, ob das Verzeichnis tatsächlich entfernt wurde --
        False z.B. wenn es zwischenzeitlich (noch im selben Lauf) doch
        nicht mehr leer war."""
        r = self._client.delete(f"/api/sync/folders/{folder_id}/dirs/{_quote_path(rel_path)}")
        if r.status_code == 404:
            return False
        r.raise_for_status()
        return bool(r.json().get("deleted", True))

    def log_sync(self, folder_id: str, summary: dict) -> None:
        """Meldet dem Server eine Zusammenfassung des gerade beendeten
        Sync-Laufs fürs Activity Log (ein Eintrag pro Lauf, nicht pro
        Datei -- der Server selbst sieht nur Einzel-Requests)."""
        self._client.post(f"/api/sync/folders/{folder_id}/sync-log", json=summary)
