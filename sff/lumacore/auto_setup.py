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
import logging
import re
from pathlib import Path
from typing import Optional

import httpx

_LUMACORE_GITHUB_REPO = "drappula/LumaCore"
_LUMACORE_RELEASE_API = f"https://api.github.com/repos/{_LUMACORE_GITHUB_REPO}/releases/latest"

logger = logging.getLogger(__name__)


class LumaCoreUpdateChecker:
    def __init__(self, steam_path: Path):
        self._steam_path = steam_path

    def check_latest(self, timeout: float = 5.0) -> tuple[str, str, str]:
        installed = self._get_installed_version()
        try:
            resp = httpx.get(
                _LUMACORE_RELEASE_API,
                headers={"Accept": "application/vnd.github+json"},
                timeout=timeout,
                follow_redirects=True,
            )
            resp.raise_for_status()
            payload = resp.json()
            tag_name = (payload.get("tag_name") or "").strip()
            match = re.match(r"^V(\d+)$", tag_name)
            if not match:
                return installed, "", "unexpected tag format"
            latest = match.group(0)
            assets = payload.get("assets", [])
            asset_url = ""
            for a in assets:
                name = (a.get("name") or "").lower()
                if name == "release.zip" or name == "release.rar":
                    asset_url = a.get("browser_download_url") or ""
                    break
            if not asset_url:
                for a in assets:
                    if (a.get("name") or "").lower().endswith(".zip"):
                        asset_url = a.get("browser_download_url") or ""
                        break
            return installed, latest, ""
        except httpx.TimeoutException:
            return installed, "unknown", "GitHub API timed out"
        except Exception as exc:
            return installed, "unknown", str(exc)

    def _get_installed_version(self) -> str:
        try:
            dll_path = self._steam_path / "LumaCore.dll"
            if not dll_path.is_file():
                return ""
            import pywin32_system  # noqa: F401
            import win32api
            info = win32api.GetFileVersionInfo(str(dll_path), "\\")
            if info is None:
                return ""
            ms = info.get("FileVersionMS", 0)
            ls = info.get("FileVersionLS", 0)
            major = (ms >> 16) & 0xFFFF
            minor = ms & 0xFFFF
            patch = (ls >> 16) & 0xFFFF
            return f"V{major}"
        except Exception:
            return ""
