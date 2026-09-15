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

# Best-effort post-save enrichment for HubCap and Ryuu .lua files. Some
# DLCs ship as their own appid with no depots and just piggyback on the
# parent game's manifest, so they need an addappid(<dlc_appid>) line in
# the .lua to actually unlock. The free-provider Lua builders already do this inline; the
# helper here lets HubCap and Ryuu match that coverage without copying
# the appinfo walk into their own modules.

import logging
import re
from pathlib import Path
from typing import Optional

from sff.network.steam_client import (
    SteamInfoProvider,
    ParsedDLC,
    create_provider_for_current_thread,
)
from sff.core.structs import DLCTypes

logger = logging.getLogger(__name__)

# Match `addappid(123)` and `addappid(123, 1, "<sha256>")` with optional
# whitespace and an optional trailing `-- comment`. Case-insensitive on
# the function name because the wild .lua files run the gamut. The keyed
# form counts as Already_Present because LumaCore treats it as an
# ownership claim on the same appid.
_ADDAPPID_RE = re.compile(
    r'^\s*addappid\s*\(\s*(\d+)\s*'
    r'(?:,\s*[01]\s*,\s*["\'][0-9a-fA-F]+["\']\s*)?\)\s*'
    r'(?:--.*)?\s*$',
    re.IGNORECASE | re.MULTILINE,
)


def _existing_addappid_ids(text: str) -> set:
    out = set()
    for m in _ADDAPPID_RE.finditer(text):
        try:
            out.add(int(m.group(1)))
        except (TypeError, ValueError):
            pass
    return out


def _compute_depotless_set(provider: SteamInfoProvider, parent_appid: int) -> set:
    # Returns set() on every failure path. The wrapping helper treats an
    # empty set as "nothing to append" so an appinfo blip leaves the .lua
    # exactly as the provider wrote it.
    try:
        parent_info = provider.get_single_app_info(int(parent_appid))
        if not parent_info or not isinstance(parent_info, dict):
            return set()
        extended = parent_info.get("extended", {}) or {}
        if not isinstance(extended, dict):
            return set()
        listofdlc = extended.get("listofdlc", "") or ""
        if not isinstance(listofdlc, str) or not listofdlc.strip():
            return set()
        try:
            dlc_ids = [int(x.strip()) for x in listofdlc.split(",") if x.strip().isdigit()]
        except (TypeError, ValueError):
            return set()
        if not dlc_ids:
            return set()
        dlc_infos = provider.get_app_info(dlc_ids)
        if not dlc_infos or not isinstance(dlc_infos, dict):
            return set()
        depotless = set()
        for dlc_id in dlc_ids:
            data = dlc_infos.get(dlc_id) or dlc_infos.get(str(dlc_id))
            if not data:
                continue
            try:
                dlc = ParsedDLC(int(dlc_id), data, parent_info, local_ids=[])
                if dlc.type == DLCTypes.NOT_DEPOT:
                    depotless.add(int(dlc_id))
            except Exception as e:
                logger.debug("dlc_appid_enricher: ParsedDLC raised for %s: %s", dlc_id, e)
                continue
        return depotless
    except Exception as e:
        logger.debug("dlc_appid_enricher: provider walk failed for %s: %s", parent_appid, e)
        return set()


def _append_lines(lua_path: Path, missing_ids: list) -> int:
    if not missing_ids:
        return 0
    try:
        # Pre-read so the appended block starts on its own line if the
        # prior file did not end in one. Avoids the `addappid(123)`
        # gluing onto a previous comment.
        size = lua_path.stat().st_size if lua_path.exists() else 0
        needs_leading_newline = False
        if size > 0:
            with lua_path.open("rb") as f:
                f.seek(-1, 2)
                last = f.read(1)
                if last not in (b"\n", b"\r"):
                    needs_leading_newline = True

        with lua_path.open("a", encoding="utf-8") as f:
            if needs_leading_newline:
                f.write("\n")
            for appid in missing_ids:
                f.write(f"addappid({int(appid)})\n")
        return len(missing_ids)
    except (OSError, PermissionError) as e:
        logger.debug("dlc_appid_enricher: append to %s failed: %s", lua_path, e)
        return 0


def append_depotless_dlcs(
    lua_path: Path,
    parent_appid,
    *,
    provider: Optional[SteamInfoProvider] = None,
) -> int:
    """Best-effort post-save enrichment for a saved <parent>.lua file.

    Walks the parent's appinfo via SteamInfoProvider, computes the
    NOT_DEPOT DLC subset, and appends `addappid(<dlc_appid>)` lines for
    every DLC in that subset that is not already declared in the file.

    Returns the number of lines appended (0 on any failure path).
    Never raises. Callers treat the return as advisory only and never
    use it to gate the wrapping download success.
    """
    try:
        parent_id = int(parent_appid)
    except (TypeError, ValueError):
        logger.debug("dlc_appid_enricher: bad parent_appid %r", parent_appid)
        return 0

    if not isinstance(lua_path, Path):
        try:
            lua_path = Path(lua_path)
        except Exception:
            return 0

    if not lua_path.exists():
        return 0

    try:
        if provider is None:
            provider = create_provider_for_current_thread()
    except Exception as e:
        logger.debug("dlc_appid_enricher: provider construction failed: %s", e)
        return 0

    depotless = _compute_depotless_set(provider, parent_id)
    if not depotless:
        return 0

    try:
        text = lua_path.read_text(encoding="utf-8", errors="replace")
    except Exception as e:
        logger.debug("dlc_appid_enricher: read %s failed: %s", lua_path, e)
        return 0

    existing = _existing_addappid_ids(text)
    missing = sorted(d for d in depotless if d not in existing and d != parent_id)
    if not missing:
        return 0

    return _append_lines(lua_path, missing)
