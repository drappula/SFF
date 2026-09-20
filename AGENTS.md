# AGENTS.md

Source of truth for agent behavior is `.claude/CLAUDE.md` — honor its setup, build, architecture, and convention sections. This file is the OpenCode-runnable summary.

## Setup / run

- Install in order (do not merge steps):
  ```bash
  pip install -r requirements.txt          # Linux: requirements-linux.txt
  pip install steam==1.4.4 --no-deps
  ```
  `steam==1.4.4` declares stale `urllib3<2`; second step bypasses it. Steam works on `urllib3 2.x`. Do not "fix" the pin.
- `seleniumbase` is intentionally unpinned. Only if SteamDB Cloudflare bypass is needed: `pip install seleniumbase --no-deps` (also `curl_cffi`, `zendriver` already in requirements).
- Run with project venv only: `.venv/bin/python Main_gui.py` (GUI) / `.venv/bin/python Main.py` (CLI). Never system Python. On GUI launch `qt.qpa.services: Failed to register with host portal` is harmless — ignore, do not screenshot or probe the window at startup.
- No test suite, no linter config beyond `black` as a dep. Verification is `py_compile` / manual run.

## Builds

- Windows CLI: `pyinstaller build_sff.spec` (`build_simple.bat`); GUI: `pyinstaller build_sff_gui.spec` (`build_simple_gui.bat`); installer: `installer.nsi` (NSIS). `build_sff.spec` has `_validate_rich_packaging()` that aborts if `rich` hiddenimports/data are incomplete — keep it green.
- Linux AppImage: `./build_linux_appimage.sh` (uses `build_sff_linux.spec` + `appimagetool`). Requires `zstandard` for VSZTD chunks and `pyinstaller`.
- `store_metadata/` (games.json seed) is gitignored but bundled by specs when present. Regenerate: `python tools/fetch_store_metadata.py`. CI runs this before both builds.
- CI: `.github/workflows/release.yml` triggers on `v*` tags (plus manual dispatch), builds Linux + Windows.

## Architecture

- Two entry points share `sff/`: `Main.py` (CLI, argparse) and `Main_gui.py` (PyQt6). GUI is PyQt6 shell + `sff/webui/` (QWebChannel). JS calls `sff/gui/web_bridge.py` → `sff/gui/bridges/{store,download,game,cloudsaves,misc}.py`. Bridge methods dispatch to `QThread` workers via `pyqtSignal`; only trivial getters are sync.
- Core "add game" flow: `sff/lua/` (fetch Lua) → `sff/manifest/` (decrypt manifests via `https://manifest.luastools.xyz/m/<depot>/<manifest>` first, then GitHub mirrors / ManifestHub / Tor fallback, depot selector fix in `sff/webui/js/app.js:1598`) → `sff/steam_tools_compat.install_lua_to_steam` → `sff/lua/writer.py` (no-op on Windows) → depot keys for injection.
- Platform split: **Windows** — `sff/app_injector/lumacore.py` (DLL hijack via `dwmapi.dll`/`LumaCore.dll`); Steam downloads natively (Home "Download Game" is preferred). **Linux** — no LumaCore; `sff/app_injector/sls.py` + `sff/linux/` (SLSsteam/SLScheevo) + `sff/downloads/native_downloader.py` (pure-Python CDN, needs `zstandard`) or DepotDownloaderMod via .NET 9 (`sff/downloads/depot_downloader.py`, `sff/store/ddmod_launcher.py`). `sff/linux/acf_writer.py` writes ACF; `LOOP_NO_PROMPT` in `download_bridge.py` handles native→DDMod fallback.
- Storage: `sff/core/storage/` (VDF/ACF/INI/YAML, `settings.bin`), `sff/steam_path.py` (registry on Windows, multi-location + Flatpak on Linux). Other: `sff/game/` (fixes/cracks/DLC unlockers, `download_queue.json`/`acf_pending_queue.json` in repo root), `sff/network/` (`steam` lib + store scrape), `sff/i18n.py` + `sff/locales/`.

## Conventions

- Prose that ships (comments, `CHANGELOG.md`, `release-note.md`, dialogs/toasts) must run the `unslop` skill. Comments sparse, only for genuinely confusing code — preserve war-story comments (e.g. PyQt6 guard in `Main_gui.py`).
- Every new source file starts with the GPL header block.
- Git remotes: SSH only (`git@github.com:...`), never HTTPS.
- Silent decisions (fallbacks, retries, provider verdicts, swallowed exceptions) must leave `logger.debug`/`logger.warning` breadcrumbs (bridges/core) or `print`+`colorama` in CLI flows — debug level unless user-visible. Long flows also log step entry so hangs are traceable.
- `CHANGELOG.md`: if HEAD is latest release, add under `## Unreleased` (create if missing); else append to existing Unreleased. One–two sentences per entry, no session narrative, no examples from current work. If fixing unreleased-only code, fold into that feature's entry — no separate "Fixed:".
- Release (only on explicit `<version>` like `6.6.8`): 1) `CHANGELOG.md` `## Unreleased` → `## <version>`, 2) `sff/core/strings.py` `VERSION = "<version>"`, 3) replace `release-note.md` with version-only notes, 4) commit via `caveman-commit` (`chore(release): v<version>`), 5) `git push origin main`, 6) `git tag -a v<version> -m "v<version>" && git push origin v<version>`, 7) watch `gh run list --workflow=release.yml`.
