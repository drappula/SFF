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

import os
import re
import time
from pathlib import Path

from colorama import Fore, Style

from sff.core.storage.vdf import vdf_dump


def _sanitize_name(name: str) -> str:
    return re.sub(r'[<>:"/\\|?*]', "_", name).strip()


def _normalise_manifest_map(manifests: dict) -> dict[str, str]:
    clean: dict[str, str] = {}
    for depot_id, manifest_id in (manifests or {}).items():
        depot_str = str(depot_id).strip()
        manifest_str = str(manifest_id).strip()
        if depot_str.isdigit() and manifest_str.isdigit():
            clean[depot_str] = manifest_str
    return clean


def _depot_size(depots: dict, depot_id: str) -> str:
    info = depots.get(depot_id) or depots.get(int(depot_id) if depot_id.isdigit() else depot_id) or {}
    value = info.get("size", "0") if isinstance(info, dict) else "0"
    value_str = str(value).strip()
    return value_str if value_str.isdigit() else "0"


def create_acf(
    game_data: dict,
    dest_path: Path,
    selected_depots: list,
    size_on_disk: int = 0,
    print_fn=print,
) -> bool:
    appid = str(game_data["appid"])
    game_name = game_data.get("game_name", f"App {appid}")
    installdir = game_data.get("installdir") or _sanitize_name(game_name) or f"App_{appid}"
    buildid = str(game_data.get("buildid", "0"))
    manifests = _normalise_manifest_map(game_data.get("manifests", {}))
    depots = game_data.get("depots", {})

    steamapps_dir = dest_path / "steamapps"
    steamapps_dir.mkdir(parents=True, exist_ok=True)
    acf_path = steamapps_dir / f"appmanifest_{appid}.acf"

    installed_depots = {}
    for depot_id in selected_depots:
        depot_id_str = str(depot_id)
        manifest_gid = manifests.get(depot_id_str, "")
        if manifest_gid:
            depot_info = depots.get(depot_id_str) or depots.get(int(depot_id_str) if depot_id_str.isdigit() else depot_id_str) or {}
            entry = {"manifest": manifest_gid, "size": _depot_size(depots, depot_id_str)}
            dlcappid = depot_info.get("dlcappid") if isinstance(depot_info, dict) else None
            if dlcappid:
                entry["dlcappid"] = str(dlcappid)
            installed_depots[depot_id_str] = entry

    if selected_depots and not installed_depots:
        print_fn(Fore.RED + "No manifest IDs for selected depots to write ACF for." + Style.RESET_ALL)
        return False

    last_owner = "0"
    try:
        from sff.core.storage.settings import get_setting
        from sff.core.structs import Settings
        sid = get_setting(Settings.STEAM32_ID)
        if sid and str(sid).strip():
            last_owner = str(sid).strip()
    except Exception:
        pass

    app_state: dict = {
        "appid": appid,
        "Universe": "1",
        "name": game_name,
        "StateFlags": "4",
        "installdir": installdir,
        "LastUpdated": str(int(time.time())),
        "SizeOnDisk": str(size_on_disk),
        "StagingSize": "0",
        "buildid": buildid,
        "LastOwner": last_owner,
        "UpdateResult": "0",
        "BytesToDownload": "0",
        "BytesDownloaded": "0",
        "BytesToStage": "0",
        "BytesStaged": "0",
        "TargetBuildID": buildid,
        "AutoUpdateBehavior": "0",
        "AllowOtherDownloadsWhileRunning": "0",
        "ScheduledAutoUpdate": "0",
        "DownloadType": "1",
        "InstalledDepots": installed_depots,
        "UserConfig": {"language": "english"},
        "MountedConfig": {"language": "english"},
    }

    try:
        if acf_path.exists():
            os.chmod(acf_path, 0o644)  # make writable if previously locked
        vdf_dump(acf_path, {"AppState": app_state}, tabbed=True)
        os.chmod(acf_path, 0o444)
        print_fn(Fore.GREEN + f"ACF written: {acf_path}" + Style.RESET_ALL)
        return True
    except Exception as e:
        print_fn(Fore.RED + f"Failed to write ACF: {e}" + Style.RESET_ALL)
        return False
