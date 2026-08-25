# astrapi-sync-cli

CLI-Client + geteilte Sync-Engine für [astrapi-sync](https://github.com/astrapi/astrapi-sync)
(Ordner-Synchronisation über mehrere eigene Geräte). Eigenständiges
Python-Paket, unabhängig von `astrapi-core` — läuft auf jedem Client-Gerät,
nicht auf dem Server.

Grundlage für [astrapi-sync-gui](../astrapi-sync-gui/): `engine.py`/
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

### Automatischer Start (systemd --user)

Bei Installation über das Arch-Paket (`packages_archlinux/astrapi-sync-cli`)
liegt eine `astrapi-sync-cli.service`-User-Unit bei:

```bash
systemctl --user enable --now astrapi-sync-cli.service

# läuft auch ohne aktive Login-Session (z.B. nach Reboot vor dem Login):
loginctl enable-linger "$USER"
```

## Sync-Algorithmus (Kurzfassung)

Block-Hashing nach fester Blockgröße (1 MiB, Syncthing-Stil, kein
rsync-Rolling-Hash). Pro Ordner wird lokal der zuletzt bekannte
Server-Stand je Datei gespeichert (`~/.config/astrapi-sync/state/`) —
weicht beim nächsten Sync sowohl der lokale als auch der Server-Hash
davon ab, ist das ein echter Konflikt: die lokale Version wird als
`*.syncconflict-<zeit>-<gerät>` gesichert, die Server-Version übernommen.

Leere Verzeichnisse werden ebenfalls synchronisiert (eigener, einfacherer
Abgleich neben dem Datei-Protokoll, kein Massenlöschungs-Schutz nötig, da
ein leeres Verzeichnis keine Daten verlieren kann).

Sicherheitsschwelle gegen Massen-Löschungen: löst ein Sync-Lauf mehr als
eine Handvoll Datei-Löschungen aus (Standard: 3), bricht er vorher ab und
meldet nur, was er gelöscht *hätte* — erst `--yes-delete` führt sie
tatsächlich aus. Grund: der Client kann nicht unterscheiden zwischen
"bewusst gelöscht" und "Server/Ordner hat plötzlich unerwartet nichts
mehr" (z. B. externe Manipulation).
