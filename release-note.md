## 6.9.0

### Fixed

* SteaMidra no longer hangs on startup when it needs to install or update SLSsteam. The install runs in the background instead of freezing the window.
* The Patch Gaming Mode button now shows on all Linux systems, not just SteamOS, so CachyOS, ROG Ally and similar handhelds can use it.
* Unnamed depots in the picker show `Depot <id>` instead of repeating the game name on every row.
* Old depots that store chunks as ZIP (Assassin's Creed and others) now download correctly on the built-in downloader.
* The depot file list tries LuasTools and the GitHub mirrors before Hubcap, so it works without a Hubcap key.
* Overall download progress never jumps backwards when switching depots.
* The app shows as `SteaMidra` in the system monitor instead of `python`, with correct dock grouping.
* New Linux installs no longer show `Content still encrypted` (e.g. Celeste) — install manifests are written back into the ACF.

### Changed

* LumaCore installs and updates now come from drappula/LumaCore (V37+) instead of the inactive upstream repo.
* Manifest downloads try LuasTools first, then the GitHub mirrors, then ManifestHub.
* The invalid-key popup has a red Remove Key button that clears the saved key so the provider falls back to Free Providers.

### Improved

* Lower idle RAM: store metadata and the depot-key database load on first use instead of at startup (around 650 MB idle instead of 1 GB).
