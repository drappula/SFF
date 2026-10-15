## 6.10.0-pre

### Added

* First-run interactive tutorial — new users get a 1-minute guided tour covering setup, the Store tab, download sources with key instructions, and the Downloads tab, using a fake demo game. Replay it from Settings.

### Fixed

* DDMod downloads that fetched nothing no longer report success — empty install dirs fail with a real error instead of a false "Download complete".
* Windows frozen auto-update works again — the missing `safe_extract_zip` import is fixed.
* Fix Game picks the right Linux mode from the folder contents instead of depending on the caller.
* Native downloader rejects wrong-depot manifests up front with a clear error instead of dying in AES decrypt.
* Store search is ~3x faster — normalized names and search tokens are precomputed once at load.
