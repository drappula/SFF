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

"""Create a Start Menu / app menu entry that launches a game via steam://."""

import logging
import os
import re
import subprocess
import sys
from pathlib import Path

logger = logging.getLogger(__name__)


def _safe_filename(name: str) -> str:
    return re.sub(r'[<>:"/\\|?*\x00-\x1f$`]', "_", name).strip() or "game"


def _game_icon_ico(app_id: str) -> str:
    """Steam CDN header image cropped square and saved as .ico. '' on failure."""
    try:
        from io import BytesIO
        from PIL import Image
        from sff.core.utils import sff_data_dir
        from sff.linux.desktop_shortcuts import _fetch_icon_steam_cdn

        data = _fetch_icon_steam_cdn(app_id)
        if not data:
            return ""
        img = Image.open(BytesIO(data))
        icon_dir = sff_data_dir() / "icons"
        icon_dir.mkdir(exist_ok=True)
        ico = icon_dir / f"steam_icon_{app_id}.ico"
        img.save(ico, format="ICO", sizes=[(256, 256), (64, 64), (48, 48), (32, 32), (16, 16)])
        return str(ico)
    except Exception as e:
        logger.debug("game icon fetch failed: %s", e)
        return ""


def _windows_entry(app_id: str, game_name: str, steam_path) -> tuple[bool, str]:
    start_dir = (
        Path(os.environ.get("APPDATA", str(Path.home())))
        / "Microsoft" / "Windows" / "Start Menu" / "Programs" / "Games"
    )
    start_dir.mkdir(parents=True, exist_ok=True)
    lnk = start_dir / f"{_safe_filename(game_name)}.lnk"

    icon = _game_icon_ico(app_id)
    if not icon and steam_path:
        steam_exe = Path(steam_path) / "steam.exe"
        if steam_exe.is_file():
            icon = f"{steam_exe},0"
    icon_script = f'$s.IconLocation="{icon}";' if icon else ""

    script = (
        f'$s=(New-Object -COM WScript.Shell).CreateShortcut("{lnk}");'
        '$s.TargetPath="explorer.exe";'
        f'$s.Arguments="steam://rungameid/{app_id}";'
        f'$s.Description="Launch {_safe_filename(game_name)} through Steam";'
        f"{icon_script}"
        "$s.Save()"
    )
    try:
        r = subprocess.run(
            ["powershell", "-NoProfile", "-Command", script],
            capture_output=True, text=True, timeout=30,
            creationflags=0x08000000,  # CREATE_NO_WINDOW
        )
    except Exception as e:
        return False, f"PowerShell failed: {e}"
    if r.returncode != 0 or not lnk.is_file():
        return False, f"Shortcut creation failed: {r.stderr.strip() or lnk}"
    return True, f"Added to Start Menu: {lnk.name}"


def create_start_menu_entry(app_id: str, game_name: str, steam_path=None) -> tuple[bool, str]:
    if not str(app_id).isdigit():
        return False, f"Invalid app id: {app_id}"
    if sys.platform == "win32":
        return _windows_entry(str(app_id), game_name or f"App {app_id}", steam_path)
    from sff.linux.desktop_shortcuts import create_shortcut
    ok = create_shortcut(
        str(app_id), game_name or f"App {app_id}", print_fn=lambda m: None
    )
    if ok:
        apps = Path.home() / ".local" / "share" / "applications"
        return True, f"Added to the app menu ({apps / (_safe_filename(game_name or '') + '.desktop')})"
    return False, "Failed to create the .desktop entry"


if __name__ == "__main__":
    assert _safe_filename('Katana ZERO: Day of the Dead //!!') == "Katana ZERO_ Day of the Dead __!!"
    assert _safe_filename('a"b$c`d') == "a_b_c_d"
    assert _safe_filename("") == "game"
    print("start_menu self-check ok")
