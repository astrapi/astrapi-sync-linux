# astrapi_sync_cli/block_hash.py
"""Block-Hashing -- muss exakt zum Server (astrapi_sync/api/block_hash.py)
passen (gleiche Blockgröße, gleiche Hash-Funktion), sonst stimmen die
Positions-Vergleiche nicht. Bewusst dupliziert statt geteilt: Server und
Client sind unabhängig deploybare Pakete (siehe Plan, Repo-Aufteilung)."""
import hashlib
from pathlib import Path

DEFAULT_BLOCK_SIZE = 1 << 20  # 1 MiB


def hash_blocks(path: Path, block_size: int = DEFAULT_BLOCK_SIZE) -> list[str]:
    hashes = []
    with open(path, "rb") as f:
        while True:
            chunk = f.read(block_size)
            if not chunk:
                break
            hashes.append(hashlib.sha256(chunk).hexdigest())
    return hashes


def whole_file_hash(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def read_block(path: Path, index: int, block_size: int = DEFAULT_BLOCK_SIZE) -> bytes:
    with open(path, "rb") as f:
        f.seek(index * block_size)
        return f.read(block_size)
