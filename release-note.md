## 6.8.0

### New

* SteaMidra checks your Hubcap, Ryuu and DepotBox keys shortly after launch and whenever a download uses them. A dead key shows a dialog with the provider's site, and that provider stops auto-selecting until you save a working key.
* Games no longer auto-update by default on Windows: the manifest-pin helper is installed at startup, so added games stay on their pinned version. Remove it any time in Auto Update Games.
* The Store opens instantly. Its first page is fetched in the background at startup, and your results are kept when you switch tabs.
* After a Steam update, once SteaMidra fills the LumaCore pattern cache it offers to restart Steam right away so the patterns load.

### Changed

* The first download after opening SteaMidra is far faster. Free Providers used to spend up to a minute re-parsing the depot-key database and probing manifest mirrors one at a time; the database is now warmed in the background at startup, mirrors are tried in parallel, and a Lua with only lost manifest files gets just those files re-seeded.
* Store search is several times faster; typing no longer re-cleans all 200k game names per query.
* Manifest fetches try the GitHub mirrors before ManifestHub, so the API-key prompt no longer interrupts a download a free source can finish. The dead public GMRC mirrors are gone.
* Windows installer builds take about seven minutes less. The installer is 150 MB larger as the trade.
* Ryuu links open the key generator directly, and the key dialogs say to log in first: the key shows up as "auth_key" only after signing in.
* Settings has a "Download Speed Limit" box that caps the built-in downloader's rate (0 = no limit). It does not apply to Steam/LumaCore or DepotDownloaderMod downloads.
* On Linux, SLSsteam installs run the Headcrab script, which keeps the Steam client at a version the injection supports. The background update check won't install while Steam is running.
* The Steam Updates tile on the Home tab works on Linux too. Turning client auto-updates back on is one click, not a steam.cfg edit.
* Linux Setup and the hash fix ask before closing a running Steam client, so they never kill a game mid-session.
* Finishing a download no longer asks whether to enable auto-updates for that game. Set them per game in Auto Update Games, or for all new games in Settings.
* The Free Providers name replaces the old MidraEveryDay handle everywhere in the UI and docs.

### Fixed

* Photo themes (Dawn, Dusk, Flow, Lake, Midnight City, Snow) no longer flash at startup and vanish.
* Deleting a game with "delete files" also drops its manifests from depotcache and the staging folder, so a reinstall can't resurrect the old pin.
* When the chosen source doesn't have a game, SteaMidra says so and offers to fall back to Free Providers, instead of looping "enter a new API key" or failing quietly. If no provider has it, a dialog points to the providers' Discords to request the game.
* Ryuu premium-key and DepotBox Lua files no longer arrive without their manifest files, so Steam starts pulling files instead of idling at zero.
* A download interrupted by rate limits left a partial Lua behind, and every retry reused it: the game appeared added and nothing downloaded. Cached Free Providers Lua files are now verified and refetched when keys or manifests are missing.
* Windows downloads use LumaCore again instead of the built-in downloader. If registration fails because Steam holds the files locked, the download says so instead of claiming the game is in your library.
* Downloads no longer stall on "Parsing Lua..."; the already-registered check reads one file instead of re-scanning everything.
* The pattern cache prewarm no longer misses patterns that exist; the "No cached LumaCore support data" banner clears once the current build is covered.
* Ryuu downloads work for games without a public branch; the old route 404'd on most games.
* Recently Updated shows real dates again, sorted by Steam's last-modified stamp.
* The startup tray message no longer claims the app is running in the tray while its window is open.
* Pressing Enter in the log viewer no longer clears it.
* The "✓ Saved" marker on stored API keys sits over the input field instead of covering the Save/Test buttons.
* The Store's loading placeholder matches the real card grid instead of a strip of thin bars.
