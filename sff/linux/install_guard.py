# SteaMidra - Steam game setup and manifest tool (SFF)
# Copyright (c) 2025-2026 Midrag (https://github.com/Midrags)
#
# This file is part of SteaMidra.
#
# SteaMidra is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# SteaMidra is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with SteaMidra.  If not, see <https://www.gnu.org/licenses/>.

"""Guards against Steam wiping SLSsteam-installed games.

Steam treats an ACF whose buildid or InstalledDepots do not match the
live branch as an interrupted update. Pressing Update then deletes the
game folder and re-stages it, which fails for injected titles. These
helpers keep partial or stale states from reaching Steam: the ACF only
ever lists depots whose manifests are on disk, the downloaded GIDs are
pinned in SLSsteam ManifestIds, and Steam launches warn about installs
that would not survive an Update click.
"""

import logging
from pathlib import Path

logger = logging.getLogger(__name__)


def _candidate_manifest_paths(steam_path: Path, depot_id: str, manifest_gid: str) -> list:
    return [
        steam_path / "depotcache" / f"{depot_id}_{manifest_gid}.manifest",
        steam_path / "config" / "depotcache" / f"{depot_id}_{manifest_gid}.manifest",
    ]


def manifest_is_downloaded(steam_path, depot_id, manifest_gid) -> bool:
    """True when the manifest file for a depot is present in depotcache."""
    try:
        root = Path(steam_path)
        gid = str(manifest_gid or "").strip()
        if not gid or not str(depot_id).strip().isdigit():
            return False
        return any(p.exists() for p in _candidate_manifest_paths(root, str(depot_id), gid))
    except Exception as exc:
        logger.debug("manifest_is_downloaded failed for depot %s: %s", depot_id, exc)
        return False


def filter_manifest_map_to_downloaded(manifest_map: dict, steam_path) -> dict:
    """Keep only depots whose manifest files are actually on disk.

    Writing an ACF entry for a depot without its manifest makes Steam
    treat the install as corrupt and wipe the game folder on Update.
    """
    kept: dict = {}
    for depot_id, manifest_gid in (manifest_map or {}).items():
        if manifest_is_downloaded(steam_path, depot_id, manifest_gid):
            kept[str(depot_id)] = str(manifest_gid)
        else:
            logger.debug("install_guard: dropping depot %s, manifest %s not on disk", depot_id, manifest_gid)
    return kept


def pin_manifest_ids(sls_config_path, manifest_map: dict) -> int:
    """Pin downloaded manifest GIDs into SLSsteam ManifestIds. Returns count."""
    if not manifest_map or sls_config_path is None:
        return 0
    pinned = 0
    try:
        from sff.linux.yaml_config import add_manifest_id
    except ImportError as exc:
        logger.debug("install_guard: yaml_config unavailable, ManifestIds not pinned: %s", exc)
        return 0
    for depot_id, manifest_gid in manifest_map.items():
        try:
            if add_manifest_id(Path(sls_config_path), str(depot_id), str(manifest_gid)):
                pinned += 1
        except Exception as exc:
            logger.debug("install_guard: ManifestId pin failed for depot %s: %s", depot_id, exc)
    if pinned:
        logger.debug("install_guard: pinned %d manifest(s) into %s", pinned, sls_config_path)
    return pinned


def warn_if_outdated(installed_buildid, live_buildid, print_fn=print) -> bool:
    """Warn when the downloaded build is older than the live branch.

    Returns True when outdated. Steam will offer an Update for such an
    install, and accepting it wipes the game folder.
    """
    try:
        installed = int(str(installed_buildid or "0").strip() or "0")
        live = int(str(live_buildid or "0").strip() or "0")
    except (ValueError, TypeError):
        return False
    if installed and live and installed < live:
        logger.debug("install_guard: build %s is older than live %s", installed, live)
        print_fn(
            "Downloaded build is older than the current Steam build "
            f"({installed} < {live}). Steam will offer an Update — "
            "decline it and re-download through SteaMidra instead, "
            "or Steam will delete the game files."
        )
        return True
    return False


def scan_broken_installs(steam_path) -> list:
    """Find installs Steam would wipe on Update. Local checks only.

    Flags ACFs with empty InstalledDepots despite game files on disk,
    and ACF depots whose manifest files are missing from depotcache.
    Returns a list of {"appid": ..., "problems": [...]}.
    """
    broken: list = []
    if steam_path is None:
        return broken
    try:
        root = Path(steam_path)
        try:
            from sff.core.storage.vdf import get_steam_libs, vdf_load
            libs = get_steam_libs(root) if root else []
        except Exception as exc:
            logger.debug("install_guard: library lookup failed: %s", exc)
            libs, vdf_load = [root], None
        if vdf_load is None:
            from sff.core.storage.vdf import vdf_load as _vdf_load
            vdf_load = _vdf_load
        for lib in libs or [root]:
            steamapps = Path(lib) / "steamapps"
            if not steamapps.is_dir():
                continue
            for acf_path in sorted(steamapps.glob("appmanifest_*.acf")):
                try:
                    appid = acf_path.stem.split("_", 1)[1]
                    data = vdf_load(acf_path)
                    state = data.get("AppState", {}) or {}
                    installed = state.get("InstalledDepots", {}) or {}
                    problems: list = []
                    if not installed:
                        installdir = str(state.get("installdir", "") or "")
                        game_dir = steamapps / "common" / installdir if installdir else None
                        has_files = bool(
                            game_dir is not None
                            and game_dir.is_dir()
                            and any(game_dir.iterdir())
                        )
                        size = str(state.get("SizeOnDisk", "0") or "0")
                        if has_files or (size.isdigit() and int(size) > 0):
                            problems.append("ACF lists no depots but game files exist")
                    else:
                        for depot_id, entry in installed.items():
                            gid = entry.get("manifest", "") if isinstance(entry, dict) else ""
                            if not manifest_is_downloaded(root, depot_id, gid):
                                problems.append(f"depot {depot_id} manifest {gid or '?'} missing")
                    if problems:
                        broken.append({"appid": appid, "problems": problems})
                except Exception as exc:
                    logger.debug("install_guard: skipping %s: %s", acf_path.name, exc)
    except Exception as exc:
        logger.debug("install_guard: scan failed: %s", exc)
    return broken
