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

"""
Game domain bridge functions extracted from web_bridge.py.

Each ``_bridge_*`` function takes a ``WebBridge`` instance as its first
parameter (named ``bridge``) in place of ``self``.
"""

import json
import logging
import os
import shutil
from pathlib import Path

from PyQt6.QtCore import QTimer

logger = logging.getLogger(__name__)

def _bridge_validate_game_files(bridge, app_id):
    """Validate game files using DDMod without downloading. Linux only."""
    if not app_id or not app_id.strip().isdigit():
        return
    def _do():
        try:
            from sff.core.storage.vdf import get_steam_libs, vdf_load
            libs = get_steam_libs(bridge._steam_path) if bridge._steam_path else []
            for lib in libs:
                acf_path = lib / "steamapps" / f"appmanifest_{app_id}.acf"
                if not acf_path.exists():
                    continue
                acf_data = vdf_load(acf_path)
                state = acf_data.get("AppState", {})
                installdir = state.get("installdir", "")
                installed = state.get("InstalledDepots", {})
                if not installdir or not installed:
                    continue
                game_dir = lib / "steamapps" / "common" / installdir
                if not game_dir.exists():
                    continue
                bridge.download_progress.emit(json.dumps({
                    "app_id": app_id, "status": "Validating game files...", "progress": 10
                }))
                from sff.downloads.depot_downloader import run_download, MANIFESTS_TMP
                import shutil, os
                for depot_id, info in installed.items():
                    manifest_id = info.get("manifest", "") if isinstance(info, dict) else str(info)
                    if not manifest_id:
                        continue
                    mf_src = lib / "depotcache" / f"{depot_id}_{manifest_id}.manifest"
                    if not mf_src.exists():
                        mf_src = lib / "steamapps" / "depotcache" / f"{depot_id}_{manifest_id}.manifest"
                    if not mf_src.exists():
                        continue
                    MANIFESTS_TMP.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(mf_src, MANIFESTS_TMP / mf_src.name)
                # Write depot keys from lua
                keys_dir = Path(os.environ.get("TEMP", "/tmp")) / "mistwalker_keys.vdf"
                with keys_dir.open("w") as f:
                    from sff.lua.manager import parse_lua_contents
                    for depot_id in installed:
                        f.write(f"{depot_id};\n")
                game_data = {
                    "appid": str(app_id),
                    "depots": {str(d): {} for d in installed},
                    "manifests": {},
                    "installdir": installdir,
                }
                selected = list(installed.keys())
                ok, _size = run_download(
                    game_data, selected, game_dir, lib,
                    print_fn=lambda m: None,
                )
                if ok:
                    return (True, f"Validation complete — no issues found")
                return (False, f"Validation found issues — check logs")
            return (False, "No ACF found for this game")
        except Exception as e:
            logger.exception("validate_game_files failed: %s", e)
            return (False, str(e))

    def _on_done(result):
        ok, msg = result if isinstance(result, tuple) else (False, str(result))
        bridge._emit_task_result("validate_files", ok, msg, app_id=app_id)

    bridge._run_async(_do, on_done=_on_done)

def _bridge_run_game_action(bridge, app_id, action):
    """Routes to backend action (crack, dlc_check, etc.).
    Game-specific actions need an ACFInfo; non-game actions call ui methods directly.
    Emits task_finished signal."""
    # SteamAutoCrack must run on the main thread — it uses _start_worker internally.
    # Calling it from _run_async (background thread) causes immediate 'completed'
    # and a freeze/deadlock on the second click.
    if action == "steam_auto":
        from sff.game.steamauto import get_steamauto_cli_path
        if get_steamauto_cli_path() is None:
            bridge._emit_task_result("steam_auto", False, "SteamAutoCrack CLI not found")

            return
        acf = bridge._resolve_acf(app_id)
        if acf is None:
            bridge._emit_task_result("steam_auto", False, "No game found for the selected App ID")

            return
        parent = bridge.parent()
        if parent and hasattr(parent, '_run_steam_auto_with_acf'):
            # Web UI showed its own confirm dialog already — suppress the
            # Qt-side double-prompt for this single delegate call.
            if hasattr(parent, '_skip_next_achievement_warn'):
                parent._skip_next_achievement_warn = True
            else:
                setattr(parent, '_skip_next_achievement_warn', True)
            parent._run_steam_auto_with_acf(acf)

        return

    # Steamless / Remove DRM must also run on the main thread.
    # _run_steamless_for_acf calls _start_worker internally which
    # creates QThreads — doing that from _run_async's background
    # thread is unsafe and crashes Qt6.
    if action == "steamstub":
        acf = bridge._resolve_acf(app_id)
        if acf is None:
            bridge._emit_task_result("steamstub", False, "No game found for the selected App ID")
            return
        parent = bridge.parent()
        if parent and hasattr(parent, "_run_steamless_for_acf"):
            parent._run_steamless_for_acf(acf)
        return

    def _do():
        from sff.core.structs import MainMenu, MainReturnCode

        # Non-game-specific actions — call ui methods directly
        non_game_actions = {
            "download_games": lambda: bridge._ui.process_lua_full(),
            "download_manifests": lambda: bridge._ui.process_lua_minimal(),
            "recent_lua": lambda: bridge._ui.recent_files_menu(),
            "update_manifests": lambda: bridge._ui.update_all_manifests(),
            "injection_menu": lambda: bridge._ui.injection_menu(),
            "applist_menu": lambda: bridge._ui.injection_menu(),
            "remove_game": lambda: bridge._ui.remove_game_menu(),
            "context_menu": lambda: bridge._ui.manage_context_menu(),
            "check_updates": lambda: bridge._ui.check_updates(bridge._ui.os_type),
            "scan_library": lambda: bridge._ui.scan_library_menu(),
            "analytics": lambda: bridge._ui.analytics_dashboard_menu(),
        }

        if action in non_game_actions:
            try:
                from sff.core.structs import MainReturnCode
                result = non_game_actions[action]()
                if result is MainReturnCode.EXIT:
                    return f"Action '{action}' is not supported on this platform or configuration."
                if action == "check_updates":
                    bridge.task_finished.emit(json.dumps({"task":"app_update","status":"downloading","progress":10,"message":"Downloading update..."}))
                    from PyQt6.QtWidgets import QApplication
                    QApplication.processEvents()
                    try:
                        result = non_game_actions[action]()
                        return "__check_updates_done__"
                    except Exception as e:
                        bridge._emit_task_result("app_update", False, str(e))
                        return str(e)
                return None
            except Exception as e:
                return str(e)

        # Mute toggle — special handling, not a MainMenu choice
        if action == "mute_toggle":
            try:
                parent = bridge.parent()
                if parent and hasattr(parent, '_toggle_mute'):
                    parent._toggle_mute()
                elif bridge._ui and hasattr(bridge._ui, 'midi_player') and bridge._ui.midi_player:
                    bridge._ui.midi_player.set_muted(not bridge._ui.midi_player._muted)
                return None
            except Exception as e:
                return str(e)

        # Game-specific actions — need an ACFInfo from app_id
        game_action_map = {
            "crack": MainMenu.CRACK_GAME,
            "steamstub": MainMenu.REMOVE_DRM,
            "dlc_check": MainMenu.DLC_CHECK,
            "multiplayer": MainMenu.MULTIPLAYER_FIX,
            "community_fixes": MainMenu.CRACK_FIX,
            "dlc_unlockers": MainMenu.MANAGE_DLC_UNLOCKERS,
        }

        menu_choice = game_action_map.get(action)
        if menu_choice is None:
            return f"Unknown action: {action}"

        # Build ACFInfo from app_id
        acf = bridge._resolve_acf(app_id)
        if acf is None:
            return f"No game found for App ID: {app_id}"

        try:
            result = bridge._ui.run_game_action_with_selection(menu_choice, acf)
            if isinstance(result, tuple) and len(result) == 2:
                ok, msg = result
                bridge._emit_task_result(action, bool(ok), str(msg))
                return "__handled_no_toast__"
            if result is False or result is MainReturnCode.EXIT:
                return f"Action '{action}' failed"
            if result is MainReturnCode.LOOP:
                return "__handled_no_toast__"
            if result is MainReturnCode.LOOP_NO_PROMPT:
                return "__handled_no_toast__"
            return None
        except Exception as e:
            return str(e)

    def _on_done(error_msg):
        if error_msg == "__handled_no_toast__":
            return
        if error_msg == "__check_updates_done__":
            bridge._emit_task_result("check_updates", True, "Update check finished.")
            return
        if error_msg:
            bridge._emit_task_result(action, False, str(error_msg))
        # A None/empty result means the legacy menu flow either handled
        # its own UI, was cancelled, or did not report a result. Do not
        # show a green success toast for that ambiguous state.

    bridge._run_async(_do, on_done=_on_done)

def _bridge_fix_game(bridge, config_json):
    """Apply emulator fix to a game. Emits task_finished."""
    def _do():
        try:
            config = json.loads(config_json)
            from sff.game.fix_game.service import FixGameService
            raw_id = config.get("app_id", "")
            app_id = int(raw_id) if str(raw_id).strip().isdigit() else 0
            svc = FixGameService()
            success = svc.fix_game(
                app_id=app_id,
                game_dir=config.get("game_path", ""),
                emu_mode=config.get("emu_mode", "regular"),
                skip_steamstub=not config.get("unpack_steamstub", True),
                steamless_experimental=config.get("use_experimental_steamless", True),
                skip_goldberg_update=not config.get("goldberg_update", False),
                create_launch_bat=config.get("create_launch_bat", False),
                player_name=config.get("username") or "Player",
                steam_id=config.get("steam_id") or "76561198001737783",
                avatar_path=config.get("avatar_path") or None,
                simple_settings=config.get("simple_settings", False),
                gse_auth_mode=config.get("gse_auth_mode", "anonymous"),
                gse_username=config.get("gse_username", ""),
                gse_password=config.get("gse_password", ""),
            )
            return success
        except Exception as e:
            logger.exception("fix_game failed: %s", e)
            return str(e)

    def _on_done(result):
        if result is True:
            bridge._emit_task_result("fix_game", True, "Game fix applied successfully")
        else:
            bridge._emit_task_result("fix_game", False, str(result) if result else "Fix failed")

    bridge._run_async(_do, on_done=_on_done)

def _bridge_revert_game(bridge, game_path):
    """Revert emulator changes."""
    def _do():
        try:
            from sff.game.fix_game.service import FixGameService
            # FixGameService is not stateless — instantiate then call.
            # Returns (success, message) tuple.
            svc = FixGameService()
            success, msg = svc.restore_game(game_path)
            return (bool(success), str(msg) if msg else "Changes reverted")
        except Exception as e:
            logger.exception("revert_game failed")
            return (False, f"Revert failed: {e}")

    def _on_done(result):
        if isinstance(result, tuple) and len(result) == 2:
            ok, msg = result
            bridge._emit_task_result("revert_game", bool(ok), str(msg))
        else:
            bridge._emit_task_result("revert_game", False, "Revert failed: unexpected result")

    bridge._run_async(_do, on_done=_on_done)

def _bridge_generate_gbe_token(bridge, config_json):
    """GBE token generation removed."""
    bridge._emit_task_result("generate_gbe_token", False, "GBE Token Generator has been removed.")

def _bridge_run_game_action_outside(bridge, game_path, game_name_or_app_id, app_id_or_action, action=None):
    """Run a game action against a folder outside the Steam library.
    Builds ACFInfo from the explicit path instead of scanning steamapps."""
    from pathlib import Path as _Path
    from sff.game.game_specific import ACFInfo

    if action is None:
        game_name = ""
        app_id = game_name_or_app_id
        action = app_id_or_action
    else:
        game_name = (game_name_or_app_id or "").strip()
        app_id = app_id_or_action

    p = _Path(game_path)
    if not p.is_dir():
        bridge._emit_task_result(action, False, f"Folder not found: {game_path}")
        return

    acf = ACFInfo(app_id or "0", p, game_name)

    if action == "steam_auto":
        from sff.game.steamauto import get_steamauto_cli_path
        if get_steamauto_cli_path() is None:
            bridge._emit_task_result("steam_auto", False, "SteamAutoCrack CLI not found")
            return
        parent = bridge.parent()
        if parent and hasattr(parent, '_run_steam_auto_with_acf'):
            # Web UI showed its own confirm dialog already — suppress the
            # Qt-side double-prompt for this single delegate call.
            setattr(parent, '_skip_next_achievement_warn', True)
            parent._run_steam_auto_with_acf(acf)
        return

    if action == "steamstub":
        parent = bridge.parent()
        if parent and hasattr(parent, "_run_steamless_for_acf"):
            parent._run_steamless_for_acf(acf)
        return

    def _do():
        from sff.core.structs import MainMenu, MainReturnCode
        game_action_map = {
            "crack": MainMenu.CRACK_GAME,
            "steamstub": MainMenu.REMOVE_DRM,
            "dlc_check": MainMenu.DLC_CHECK,
            "multiplayer": MainMenu.MULTIPLAYER_FIX,
            "community_fixes": MainMenu.CRACK_FIX,
            "dlc_unlockers": MainMenu.MANAGE_DLC_UNLOCKERS,
        }
        menu_choice = game_action_map.get(action)
        if menu_choice is None:
            return f"Unknown action: {action}"
        if action == "steamstub":
            parent = bridge.parent()
            if parent and hasattr(parent, "_run_steamless_for_acf"):
                parent._run_steamless_for_acf(acf)
                return "__handled_no_toast__"
        try:
            result = bridge._ui.run_game_action_with_selection(menu_choice, acf)
            if isinstance(result, tuple) and len(result) == 2:
                ok, msg = result
                bridge._emit_task_result(action, bool(ok), str(msg))
                return "__handled_no_toast__"
            if result is False or result is MainReturnCode.EXIT:
                return f"Action '{action}' failed"
            if result is MainReturnCode.LOOP_NO_PROMPT:
                return "__handled_no_toast__"
            return None
        except Exception as e:
            return str(e)

    def _on_done(error_msg):
        if error_msg == "__handled_no_toast__":
            return
        if error_msg:
            bridge._emit_task_result(action, False, str(error_msg))
        # A None/empty result means the legacy menu flow either handled
        # its own UI, was cancelled, or did not report a result. Do not
        # show a green success toast for that ambiguous state.

    bridge._run_async(_do, on_done=_on_done)

def _bridge_create_start_menu_entry(bridge, app_id, game_name):
    """Add a Start Menu / app menu entry that launches the game via steam://."""
    def _do():
        try:
            from sff.game.start_menu import create_start_menu_entry
            return create_start_menu_entry(str(app_id), str(game_name or ""), bridge._steam_path)
        except Exception as e:
            logger.exception("create_start_menu_entry failed: %s", e)
            return (False, str(e))

    def _on_done(result):
        ok, msg = result if isinstance(result, tuple) else (False, str(result))
        bridge._emit_task_result("start_menu", bool(ok), str(msg))

    bridge._run_async(_do, on_done=_on_done)

def _bridge_extract_vdf_keys(bridge, vdf_path):
    """Extract depot keys from config.vdf."""
    try:
        from sff.core.storage.vdf import extract_depot_keys
        keys = extract_depot_keys(vdf_path or None)
        return json.dumps(keys or [])
    except Exception:
        return "[]"

