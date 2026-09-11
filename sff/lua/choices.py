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

import json
import logging
import re
from datetime import datetime
from pathlib import Path
from typing import Iterable

import httpx
from colorama import Fore, Style

from sff.fzf import run_fzf
from sff.network.http_utils import download_to_tempfile

logger = logging.getLogger(__name__)
from sff.lua.endpoints import get_hubcap, get_freelua, get_ryuu, get_depotbox
from sff.ui.prompts import prompt_confirm, prompt_file, prompt_select, prompt_text
from sff.core.storage.settings import get_setting, set_setting
from sff.core.strings import STEAM_WEB_API_KEY
from sff.core.structs import (
    LuaChoice,
    LuaChoiceReturnCode,
    LuaEndpoint,
    LuaResult,
    Settings,
)
from sff.core.utils import enter_path, root_folder
from sff.zip import read_lua_from_zip

APP_ID_RE = re.compile(r"(?<=store\.steampowered\.com/app/)\d+|\d+")
STEAM_APP_LIST_URL = "https://api.steampowered.com/IStoreService/GetAppList/v1/"


def _saved_lua_options(saved_lua: Path, named_ids) -> list[tuple[str, Path]]:
    return [(name, saved_lua / f"{app_id}.lua") for app_id, name in named_ids.items()]


def select_from_saved_luas(saved_lua, named_ids):
    if not named_ids:
        print("You don't have any saved .lua files. Try adding some first.")
        return LuaResult(None, None, LuaChoice.ADD_LUA)

    lua_path = prompt_select(
        "Choose a game:",
        _saved_lua_options(saved_lua, named_ids),
        fuzzy=True,
        max_height=10,
        cancellable=True,
    )
    if lua_path is None or not lua_path.exists():
        return LuaResult(None, None, LuaChoiceReturnCode.GO_BACK)
    return LuaResult(lua_path, None, LuaChoiceReturnCode.LOOP)


def _blank_file_choice(path: Path) -> bool:
    try:
        return path.samefile(Path.cwd())
    except OSError:
        return False


def add_new_lua(file=None):
    lua_path = file or prompt_file(
        "Drag a .lua file (or .zip w/ .lua inside) into here "
        "then press Enter.\n"
        "Leave it blank to go back:",
        allow_blank=True,
    )

    if _blank_file_choice(lua_path):
        return LuaResult(None, None, LuaChoiceReturnCode.GO_BACK)

    if lua_path.suffix.lower() != ".zip":
        return LuaResult(lua_path, None, LuaChoiceReturnCode.LOOP)

    lua_contents = read_lua_from_zip(lua_path)
    if lua_contents is None:
        print("Could not find .lua in ZIP file.")
        return LuaResult(None, None, LuaChoiceReturnCode.LOOP)
    return LuaResult(lua_path, lua_contents, LuaChoiceReturnCode.LOOP)


def _game_list_file() -> Path:
    return root_folder(outside_internal=True) / "all_games.txt"


def _should_refresh_game_list(path: Path) -> bool:
    return not path.exists()


def _steam_web_api_key() -> str:
    api_key = get_setting(Settings.STEAM_WEB_API_KEY)
    if api_key:
        return api_key
    return STEAM_WEB_API_KEY


def _fetch_steam_apps() -> list[dict]:
    params = {"key": _steam_web_api_key(), "max_results": "50000"}
    apps: list[dict] = []
    print("Fetching game list from Steam...")

    for _attempt in range(3):
        try:
            with download_to_tempfile(STEAM_APP_LIST_URL, params=params) as tf:
                if tf is None:
                    continue
                response = json.load(tf)
            apps.extend(enter_path(response, "response", "apps"))
            if not enter_path(response, "response", "have_more_results"):
                return apps
            params["last_appid"] = enter_path(response, "response", "last_appid")
        except Exception as _e:
            print(f"Steam API call failed ({_e})")

    # Fallback 1: GitHub mirrors (jsnli/steamappidlist, SteamTools-Team/GameList)
    print("Trying GitHub game list mirrors...")
    fallback_urls = [
        ("games_appid.json", "https://raw.githubusercontent.com/jsnli/steamappidlist/refs/heads/master/data/games_appid.json"),
        ("software_appid.json", "https://raw.githubusercontent.com/jsnli/steamappidlist/refs/heads/master/data/software_appid.json"),
        ("games.json", "https://raw.githubusercontent.com/SteamTools-Team/GameList/refs/heads/main/games.json"),
    ]
    for label, url in fallback_urls:
        try:
            resp = httpx.get(url, timeout=20, follow_redirects=True)
            if resp.status_code != 200:
                continue
            data = resp.json()
            fallback_apps = []
            if isinstance(data, dict):
                for app_id_str, name in data.items():
                    if app_id_str.isdigit():
                        fallback_apps.append({"appid": int(app_id_str), "name": str(name)})
            elif isinstance(data, list):
                for item in data:
                    if isinstance(item, dict) and "appid" in item:
                        fallback_apps.append(item)
            if fallback_apps:
                print(Fore.GREEN + f"Found {len(fallback_apps):,} games from {label}" + Style.RESET_ALL)
                return fallback_apps
        except Exception as e:
            logger.debug("Fallback %s failed: %s", label, e)
            continue

    if apps:
        print(Fore.YELLOW + f"Steam API partial success — got {len(apps):,} games before failure." + Style.RESET_ALL)
        return apps
    # Fallback 2: local cached all_games.txt
    all_games_file = _game_list_file()
    if all_games_file.exists():
        print(Fore.YELLOW + "Using cached all_games.txt instead." + Style.RESET_ALL)
        return []
    print(Fore.RED + "No game list available. Enter the App ID directly." + Style.RESET_ALL)
    return []


def _app_search_lines(apps: Iterable[dict]) -> list[str]:
    return [
        f"{app.get('name', 'UNKNOWN GAME')} [ID={app.get('appid')}]"
        for app in apps
    ]


def _write_game_list(path: Path, apps: Iterable[dict]) -> list[str]:
    lines = _app_search_lines(apps)
    path.write_text("\n".join(lines), encoding="utf-8")
    return lines


def _selected_app_id(selection: str | None):
    if not selection:
        return None
    match = re.search(r"(?<=\[ID=)\d+(?=\]$)", selection)
    if match is None:
        return None
    print(f"{Fore.YELLOW + selection + Style.RESET_ALL} has been selected")
    return match.group()


def search_game(os_type):
    all_games_file = _game_list_file()
    if _should_refresh_game_list(all_games_file):
        apps = _fetch_steam_apps()
        if apps:
            games_source = _write_game_list(all_games_file, apps)
        elif all_games_file.exists():
            games_source = all_games_file
        else:
            print(Fore.YELLOW + "No game list available. Enter the App ID directly." + Style.RESET_ALL)
            return None
    else:
        games_source = all_games_file

    return _selected_app_id(run_fzf(games_source, os_type))


def _normalize_app_id(text: str) -> str:
    if not text:
        return text
    match = APP_ID_RE.search(text)
    if match is None:
        return ""
    return match.group()


def _valid_app_id(text: str) -> bool:
    return text == "" or bool(APP_ID_RE.search(text))


def _prompt_source():
    return prompt_select("Select an endpoint:", list(LuaEndpoint), cancellable=True)


def _prompt_app_id(os_type):
    app_id = prompt_text(
        "Enter the App ID or Store link. Leave it blank to search for games:",
        validator=_valid_app_id,
        invalid_msg="Not a valid format.",
        filter=_normalize_app_id,
    )
    if app_id:
        return app_id
    return search_game(os_type)


def _depotcache_for(steam_path):
    if not steam_path:
        return None
    return Path(steam_path) / "depotcache"


def _download_from_endpoint(dest, app_id, source, steam_path=None, request_update=None,
                            branch=None, file_type=None):
    if source == LuaEndpoint.FREELUA:
        return get_freelua(dest, app_id, depotcache=_depotcache_for(steam_path))
    if source == LuaEndpoint.HUBCAP:
        return get_hubcap(dest, app_id, depotcache=_depotcache_for(steam_path))
    if source == LuaEndpoint.RYUU:
        return get_ryuu(
            dest,
            app_id,
            depotcache=_depotcache_for(steam_path),
            request_update=request_update,
            branch=branch,
            file_type=file_type,
        )
    if source == LuaEndpoint.DEPOTBOX:
        return get_depotbox(dest, app_id)
    return None


def download_lua(dest, os_type):
    source = _prompt_source()
    if source is None:
        return LuaResult(None, None, LuaChoiceReturnCode.GO_BACK)

    app_id = _prompt_app_id(os_type)
    if not app_id:
        return LuaResult(None, None, LuaChoiceReturnCode.LOOP)

    lua_path = _download_from_endpoint(
        dest,
        app_id,
        source,
        steam_path=get_setting(Settings.STEAM_PATH),
    )
    if lua_path is None:
        return LuaResult(None, None, LuaChoiceReturnCode.GO_BACK)
    return LuaResult(lua_path, None, LuaChoiceReturnCode.LOOP, endpoint=source)


def download_lua_direct(dest, app_id, source, steam_path=None, request_update=None, branch=None, file_type=None):
    """Download Lua for a known app_id/source pair without CLI prompts."""
    return _download_from_endpoint(
        dest,
        str(app_id),
        source,
        steam_path=steam_path,
        request_update=request_update,
        branch=branch,
        file_type=file_type,
    )
