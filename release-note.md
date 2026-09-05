## 6.6.7

### Fixed

* Fixed Linux DDMod downloads hanging for minutes on a flaky CDN, writing game files without execute permission, and showing games at 0B in Steam after a failed install.
* Fixed the download flow never actually closing Steam on Linux (it looked for the Windows process name), which left depot key writes locked.
* Fixed the "Local file" download source importing manifests without downloading the game.
* Proton-only games (no Linux depot, e.g. The Binding of Isaac) now download the Windows depots with the Windows file filter, so they launch through Proton instead of installing an empty folder.
* Fixed the DRM badge showing on nearly every Store game after a games.json refresh stripped the DRM data.
* Fixed the Downloads tab: the row now appears the moment a download starts, progress shows downloaded/total MB with speed and the depot name instead of freezing at 35%, completed downloads leave the Active section, and "Clear finished" actually clears the history.
* Fixed Lure Fix and Update showing duplicate toasts, the tray menu having two quit entries, and the Remove Game dialog descriptions overflowing their buttons.
* Fixed launch options and Online Fix edits being silently overwritten by Steam on Linux.
* Fixed cloud save detection scanning the wrong folders on Linux.

### Improved

* Linux builds are about 104 MB smaller; Windows-only tools are no longer bundled.
* Steam closes faster at the start of a download. Note: Steam stays closed when the download finishes, so restart it (the "Restart Steam" button injects SLSsteam) to see the new game as owned.
* The release workflow no longer requires Google Drive credentials.

## 6.6.6

### New

* **Download Queue** — Queue multiple games from the Store with up to 3 parallel downloads, configurable in Settings. The Downloads tab now shows queued, active, completed, and failed downloads with live progress, Pause/Resume, Retry, Remove, and persistent auto-resume after restart.
* **Offline Store catalog** — A full store catalog now ships with SteaMidra, so the Store and search work instantly even without an internet connection.
* **Faster app-info lookups** — SteamCMD's JSON mirror is now the primary source, with Steam CM as a fallback. Download modals no longer block on Steam login.
* **Better older-version support** — Downgraded Build IDs and manifest IDs are now written into Steam's ACF and persistently retried if Steam is still using the file.

### Fixed

* Fixed game list updates failing when Valve rejects the bundled Steam Web API key by falling back to GitHub mirrors.
* Fixed Goldberg fixes failing when game files are locked or the game is still running.
* Fixed Linux archive extraction creating flat files with Windows-style backslashes instead of proper folders.
* Fixed DDMod downloads failing when the selected folder name contains colons.
* Fixed Windows Steam **"Disk write error"** and some invalid-content errors caused by SteaMidra making ACF files read-only.
* Fixed the Linux native downloader writing game files as flat filenames instead of their correct subfolders. A background repair also fixes previously affected installs.
* Fixed downloaded manifests not being moved into Steam's depotcache.
* Fixed several Steam CM freezes, cross-thread `gevent LoopExit` errors, DLC stalls, and MidraEveryDay downloads taking minutes.
* Fixed crack matching false positives between similarly named games.
* Fixed the DepotBox rate-limit dropdown rendering as a white native popup on Windows 11.
* Removed unused `MountedDepots` blocks from ACF patching.

### Improved

* **Memory management** — Added hourly cleanup for browser cache and Python memory to reduce memory growth during long sessions.
* **SteamTools/OST Lua support** — SteaMidra can detect depot-key Lua files in `config/lua` and offer to migrate new files into LumaCore's `stplug-in` folder.
* **Faster background branch lookups** — Background requests now use bounded fetches and can no longer hold the Steam connection for minutes.
* **Discord links updated** — The new community invite is now available throughout the README, documentation, Home, and Settings pages.
* **UI polish** — Improved custom dropdowns, modal scrollbars, and removed the misleading achievement-setup step from download progress.
