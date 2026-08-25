# astrapi-sync-linux – Projektkontext für GitHub Copilot

Wird im Repo versioniert und von VS Code Copilot automatisch geladen.

---

## Was ist astrapi-sync-linux?

Monorepo mit den Linux-seitigen Clients für [astrapi-sync](https://github.com/astrapi/astrapi-sync)
(Ordner-Synchronisation über mehrere eigene Geräte, Server + Clients). Zwei
eigenständige Python-Pakete, beide **unabhängig von astrapi-core**:

- **`astrapi-sync-cli/`** — fertig. Kommandozeilen-Client + geteilte Sync-Engine.
- **`astrapi-sync-gui/`** — geplant, noch kein Code. GTK4-Desktop-Oberfläche, hängt
  als normale Python-Dependency von `astrapi-sync-cli` ab (kein eigenes Protokoll).

Kein PyPI-Release für keins der beiden Pakete geplant — reines GitHub-Backup.
Android-Client (Kotlin/Gradle) liegt in einem eigenen Repo, `astrapi-sync-android`.

---

## Stack (astrapi-sync-cli)

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
astrapi-sync-cli/
├── pyproject.toml
└── astrapi_sync_cli/
    ├── cli.py           # Console-Script: astrapi-sync-cli (pair, add-folder, sync, daemon, status)
    ├── config.py         # Lokale Konfiguration (Server-URL, Geräte-Token, Ordner-Zuordnungen)
    ├── api_client.py      # HTTP-Client für die Sync-API (Index, Up-/Download, Dirs, Delete)
    ├── block_hash.py       # Block-Hashing (Client-Seite, identisch zum Server-Protokoll)
    ├── engine.py             # Kern: Drei-Wege-Abgleich (lokal / Server / letzter bekannter Stand)
    ├── state.py               # Zuletzt bekannter Server-Stand je Ordner (files + dirs)
    └── daemon.py                # Hintergrundprozess: Dateibeobachtung + WebSocket-Reaktion

astrapi-sync-gui/          # noch kein Code, siehe README dort
```

---

## Sync-Algorithmus (Kurzfassung, astrapi-sync-cli)

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
PyPI-Release — reines GitHub-Backup, Installation bleibt `pip install -e .` im
jeweiligen Unterordner bzw. Deployment per manuellem Übertragen auf die
Client-Geräte.
