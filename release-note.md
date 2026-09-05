## 6.6.7

### Fixed

* Fixed Linux DDMod downloads hanging for minutes on a flaky CDN, writing game files without execute permission, and showing games at 0B in Steam after a failed install.
* Fixed the download flow never actually closing Steam on Linux (it looked for the Windows process name), which left depot key writes locked.
* Fixed the "Local file" download source importing manifests without downloading the game.
* Proton-only games (no Linux depot, e.g. The Binding of Isaac) now download the Windows depots with the Windows file filter, so they launch through Proton instead of installing an empty folder.
* Fixed the DRM badge showing on nearly every Store game after a games.json refresh stripped the DRM data.
* Fixed the Downloads tab: the row now appears the moment a download starts, progress shows downloaded/total MB with speed and the depot name instead of freezing at 35%, the bar climbs steadily across all depots instead of snapping back between them, completed downloads leave the Active section, and "Clear finished" actually clears the history.
* Fixed Lure Fix and Update showing duplicate toasts, the tray menu having two quit entries, and the Remove Game dialog descriptions overflowing their buttons.
* Fixed launch options and Online Fix edits being silently overwritten by Steam on Linux.
* Fixed cloud save detection scanning the wrong folders on Linux.
* Fixed games whose Lua lists depots before the base app (e.g. Katana ZERO) being registered under a depot ID and showing as "App ..." instead of the real name.
* Fixed newly shipped DLCs missing from the DLC check list (e.g. Elden Ring Tarnished Pack) because cached app info never refreshed.
* Fixed Hubcap outages and connection problems being reported as "API key rejected"; the error now says whether the key was actually rejected or Hubcap was just unreachable.

### Improved

* Linux builds are about 104 MB smaller; Windows-only tools are no longer bundled.
* Steam closes faster at the start of a download. Note: Steam stays closed when the download finishes, so restart it (the "Restart Steam" button injects SLSsteam) to see the new game as owned.
* The release workflow no longer requires Google Drive credentials.
