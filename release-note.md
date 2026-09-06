## 6.6.7a

### New

* The Store tab now defaults to a Popular sort, built from Steam's top-selling chart (cached for 24 hours, falls back to recently-updated when offline).
* The Download Older Version box now searches by manifest GID (selects the matching archived row) or by build ID (downloads that build directly). Archived rows show the first digits of their GID.
* Older-version downloads ask which library to install to when you have more than one.
* Settings can inject SLSsteam into Gaming Mode on SteamOS / Steam Deck (`/usr/bin/steam-jupiter`), not just Desktop Mode.
* Downloads can be cancelled while running, with an option to delete the partial files.

### Fixed

* Older-version downloads now show the real game name instead of "App 1234567", never ask you to type a name, show live depot progress like normal installs (including through the DDMod backup engine), and register with SLSSteam so Steam shows Play instead of Purchase.
* Build-ID downgrade works on Linux: it no longer claims to be Windows-only, fetches a missing Lua automatically, and closes Steam around the config writes.
* Native downloads are fast again. The CDN server list was silently ignored and chunks were spread across every server, so slow hosts dominated (53 KB/s while DDMod hit 12 MB/s on the same list). Servers are now latency-probed and only the top 4 are used.
* Cover images for new releases (Steam moved them to hashed paths, so the old URLs 404'd). The Store tab now resolves the real cover URLs in batches.
* Downgrading a game no longer restarts Steam when the download finishes.
* Goldberg config tools no longer crash when launched from the app (the frozen build leaked PYTHONHOME into the child process).
