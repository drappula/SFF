## 6.10.1

### Added

* Download button for injected, not-downloaded games — games SteaMidra manages via stplug-in/saved_lua but has not downloaded yet now show in the Library with a Download action that opens Steam's install dialog, instead of a dead Play button.

### Fixed

* Typed app ids find unlisted components — the Store searched only its merged app list, so an app Steam hides from search (Call of Duty: WWII - Multiplayer, 476620) showed "No games found" unless the live app-list fetch had contributed it. A query that is a plain app id now resolves through `GetItems` when no catalog row matches, and the store-type filter admits mods, demos and software.
* Zero-hit store queries fall back to Steam's store search — the name search scores app lists that only contain games, so a mod or demo typed in the Store came up empty. A query that scores nothing now asks Steam's own store search once before reporting "no games found".
* Updating while SteaMidra runs no longer fails — the installer now kills the running app before overwriting `SteaMidra_GUI.exe`.
* Uninstaller can't wipe unrelated folders anymore — the uninstaller now pins itself to the folder it actually lives in and refuses to run unless that folder is named `SteaMidra` and contains `SteaMidra_GUI.exe`. The installer enforces a dedicated folder: choosing any other location asks "Install into \<chosen>\SteaMidra instead?" (No takes you back to the picker).