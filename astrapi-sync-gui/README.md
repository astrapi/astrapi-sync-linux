# astrapi-sync-gui

**Status: geplant, noch nicht begonnen.**

Linux-Desktop-Oberfläche (GTK4) für [astrapi-sync](https://github.com/astrapi/astrapi-sync)
(Ordner-Synchronisation über mehrere eigene Geräte). Systray-Icon,
Einrichtungsdialog, Sync-Status-Anzeige.

Hängt als normale Python-Dependency von [astrapi-sync-cli](../astrapi-sync-cli/)
ab (geteilte Sync-Engine + API-Client liegen dort bereits fertig) — hier
kommt nur die GTK4-Oberfläche dazu, kein eigenes Sync-Protokoll.

Details zur Gesamtarchitektur: `architecture/abhaengigkeiten.md` und
`projects/sync/` im astrapi-hub-Vault.
