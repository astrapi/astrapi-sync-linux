# astrapi-sync-client – Projektkontext für GitHub Copilot

Wird im Repo versioniert und von VS Code Copilot automatisch geladen.

---

## Was ist astrapi-sync-client?

CLI-Client + geteilte Sync-Engine für [astrapi-sync](https://github.com/astrapi/astrapi-sync)
(Ordner-Synchronisation über mehrere eigene Geräte, Server + Clients). Eigenständiges
Python-Paket, **unabhängig von astrapi-core** — läuft auf jedem Client-Gerät, nicht auf
dem Server. PyPI-Paketname: keiner (kein PyPI-Release geplant, reines GitHub-Backup).

Grundlage für die spätere GTK4-Desktop-App ([astrapi-sync-gtk](https://github.com/astrapi/astrapi-sync-gtk)):
`engine.py`/`api_client.py`/`daemon.py` sind UI-unabhängig und dafür gedacht,
wiederverwendet zu werden.

---

## Stack

| Komponente | Details |
|---|---|
| HTTP-Client | `httpx` |
| WebSocket | `websockets` (Push-Benachrichtigungen vom Server) |
| Dateibeobachtung | `watchdog` (Daemon-Modus) |
| Persistenz | JSON-Dateien unter `~/.config/astrapi-sync/` (Config, Sync-State) |
| Python | ≥ 3.11 |

---

## Verzeichnisstruktur

```
astrapi_sync_client/
├── cli.py           # Console-Script: astrapi-sync-cli (pair, add-folder, sync, daemon, status)
├── config.py         # Lokale Konfiguration (Server-URL, Geräte-Token, Ordner-Zuordnungen)
├── api_client.py      # HTTP-Client für die Sync-API (Index, Up-/Download, Dirs, Delete)
├── block_hash.py       # Block-Hashing (Client-Seite, identisch zum Server-Protokoll)
├── engine.py             # Kern: Drei-Wege-Abgleich (lokal / Server / letzter bekannter Stand)
├── state.py               # Zuletzt bekannter Server-Stand je Ordner (files + dirs)
└── daemon.py                # Hintergrundprozess: Dateibeobachtung + WebSocket-Reaktion
```

---

## Sync-Algorithmus (Kurzfassung)

Block-Hashing nach fester Blockgröße (1 MiB, Syncthing-Stil, kein rsync-Rolling-Hash).
Drei-Wege-Vergleich (lokal / Server / letzter bekannter Stand aus `state.py`) erkennt
echte Konflikte (`*.syncconflict-<zeit>-<gerät>`-Kopie) vs. einseitige Änderungen.

Leere Verzeichnisse werden über einen eigenen, einfacheren Abgleich neben dem
Datei-Protokoll synchronisiert (kein Massenlöschungs-Schutz nötig — ein leeres
Verzeichnis kann keine Daten verlieren).

**Sicherheitsschwelle gegen Massen-Löschungen** (`MAX_AUTO_DELETE` in `engine.py`):
löst ein Lauf mehr Datei-Löschungen aus als die Schwelle, bricht er komplett ab und
meldet nur, was er gelöscht *hätte* — Ausführung erst mit `--yes-delete`.

---

## Versionierung

Statische Version in `pyproject.toml` (`0.1.0`), **kein** setuptools-scm, **kein**
PyPI-Release — reines GitHub-Backup, Installation bleibt `pip install -e .` bzw.
Deployment per manuellem Übertragen auf die Client-Geräte.
