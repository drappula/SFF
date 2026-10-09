## 6.9.1

### Fixed

* Steam can no longer wipe Linux installs with its Update button — the ACF lists only depots with manifests on disk, downloaded builds get pinned in SLSsteam ManifestIds, and installs that would not survive an update are flagged at Steam start.

### Changed

* LumaCore no longer uses `dwmapi.dll` — installs cover `xinput1_4.dll`, `LumaCore.dll` and `LumaCorePayload.dll` only, and leftover copies are removed automatically.
