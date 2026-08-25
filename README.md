# astrapi-sync-linux

Linux-seitige Clients für [astrapi-sync](https://github.com/astrapi/astrapi-sync)
(Ordner-Synchronisation über mehrere eigene Geräte). Monorepo mit zwei
eigenständigen Python-Paketen:

| Paket | Status | Beschreibung |
|---|---|---|
| [`astrapi-sync-cli`](astrapi-sync-cli/) | fertig | Kommandozeilen-Client + geteilte Sync-Engine (Pairing, Block-Delta-Sync, Konflikt-Erkennung, Massenlöschungs-Schutz) |
| [`astrapi-sync-gui`](astrapi-sync-gui/) | geplant | GTK4-Desktop-Oberfläche, baut auf `astrapi-sync-cli` auf (kein eigenes Protokoll) |

Kein PyPI-/Flatpak-Release geplant — reines GitHub-Backup, passend zum
persönlichen, nicht öffentlich vertriebenen Charakter der ganzen
sync-Familie. Installation bleibt lokal: `pip install -e .` im
jeweiligen Unterordner.

Der Android-Client hat ein eigenes Repo:
[astrapi-sync-android](https://github.com/astrapi/astrapi-sync-android)
(Kotlin/Gradle, kein gemeinsamer Code mit den Python-Paketen hier).
