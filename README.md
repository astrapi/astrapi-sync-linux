# astrapi-sync-client

CLI-Client + geteilte Sync-Engine für [astrapi-sync](../astrapi-sync/)
(Ordner-Synchronisation über mehrere eigene Geräte). Eigenständiges
Python-Paket, unabhängig von `astrapi-core` — läuft auf jedem Client-Gerät,
nicht auf dem Server.

Grundlage für die spätere GTK4-Desktop-App (Phase 4): `engine.py`/
`api_client.py`/`daemon.py` sind UI-unabhängig und dafür gedacht,
wiederverwendet zu werden.

## Installation

```bash
python -m venv .venv
source .venv/bin/activate
pip install -e .
```

## Verwendung

```bash
# 1. Im Server-UI (Geräte -> "Gerät koppeln") einen Pairing-Code erzeugen
astrapi-sync-cli pair http://sync.simpsons.lan:5004 <pairing-code>

# 2. Verfügbare Ordner anzeigen
astrapi-sync-cli list-folders

# 3. Einen Server-Ordner mit einem lokalen Ordner verbinden
astrapi-sync-cli add-folder 1 ~/Dokumente

# 4a. Einmalig syncen
astrapi-sync-cli sync

# 4b. Dauerhaft im Hintergrund syncen (Dateibeobachtung + Server-Push)
astrapi-sync-cli daemon
```

## Sync-Algorithmus (Kurzfassung)

Block-Hashing nach fester Blockgröße (1 MiB, Syncthing-Stil, kein
rsync-Rolling-Hash). Pro Ordner wird lokal der zuletzt bekannte
Server-Stand je Datei gespeichert (`~/.config/astrapi-sync/state/`) —
weicht beim nächsten Sync sowohl der lokale als auch der Server-Hash
davon ab, ist das ein echter Konflikt: die lokale Version wird als
`*.syncconflict-<zeit>-<gerät>` gesichert, die Server-Version übernommen.
