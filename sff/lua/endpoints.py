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

"""API endpoints are in here"""

import io
import json
import logging
import re
from pathlib import Path

import httpx

from colorama import Fore, Style

from sff.network.http_utils import download_to_tempfile
from sff.lua.provider import load_provider, update_cache_from_lua_bytes
from sff.ui.prompts import prompt_confirm, prompt_secret, prompt_select
from sff.core.storage.settings import get_setting, set_setting
from sff.core.structs import Settings
from sff.zip import read_lua_from_zip

logger = logging.getLogger(__name__)

def _update_fallback_depotkeys(lua_bytes):
    try:
        update_cache_from_lua_bytes(lua_bytes)
    except Exception:
        pass


def _set_provider_key_flag(setting, dead):
    # Persisted "key rejected" flag the source pickers read; set on a
    # definite 401/403, cleared the moment a download proves the key works.
    try:
        from sff.core.storage.settings import set_setting, clear_setting
        if dead:
            set_setting(setting, True)
        else:
            clear_setting(setting)
    except Exception:
        logger.debug("provider key flag write failed", exc_info=True)


def _freelua_after_dead_key(dest, app_id, depotcache=None):
    # A rejected key is the provider's last word on this app; the free
    # chain is keyless and independent, so finish with it when present.
    print(Fore.YELLOW + f"API key rejected; falling back to Free Providers for {app_id}." + Style.RESET_ALL)
    try:
        return get_freelua(dest, app_id, depotcache=depotcache)
    except Exception:
        return None


def get_hubcap(dest, app_id, depotcache = None, hubcap_key = None):
    if not app_id or not str(app_id).strip().isdigit():
        print(Fore.RED + f"Invalid App ID: '{app_id}'" + Style.RESET_ALL)
        return None
    url = f"https://hubcapmanifest.com/api/v1/manifest/{app_id}"

    # Loop to allow retry with new API key
    _attempts = 0
    _max_attempts = 3
    while True:
        if hubcap_key:
            pass  # pre-validated key passed in — skip prompt/validation
        elif not (hubcap_key := get_setting(Settings.HUBCAP_KEY)):
            hubcap_key = prompt_secret(
                "Paste your Hubcap API key here: ",
                lambda x: x.startswith("smm"),
                "That's not a Hubcap API key!",
                long_instruction=(
                    "Go to the Hubcap Manifest website and request an API key. It's free."
                ),
            ).strip()
            if not hubcap_key:
                print(Fore.YELLOW + "No Hubcap API key entered — skipping Hubcap." + Style.RESET_ALL)
                return None
            set_setting(Settings.HUBCAP_KEY, hubcap_key)
        headers = {
            "Authorization": f"Bearer {hubcap_key}",
        }
        try:
            stats_resp = httpx.get(
                "https://hubcapmanifest.com/api/v1/user/stats",
                headers=headers,
                timeout=15,
                follow_redirects=True,
            )
        except httpx.ConnectError:
            print(
                Fore.RED
                + "\nNetwork error: Cannot reach Hubcap Manifest API."
                  " Check your internet connection."
                + Style.RESET_ALL
            )
            return None
        except httpx.RequestError as e:
            print(Fore.RED + f"\nNetwork error connecting to Hubcap Manifest: {e}" + Style.RESET_ALL)
            return None
        if stats_resp.status_code == 401:
            print(Fore.RED + "\nHubcap API key is invalid or expired." + Style.RESET_ALL)
            _set_provider_key_flag(Settings.HUBCAP_KEY_DEAD, True)
            _attempts += 1
            if _attempts >= _max_attempts:
                print(Fore.YELLOW + f"Max API key entry attempts ({_max_attempts}) reached. Please update your key in Settings." + Style.RESET_ALL)
                return _freelua_after_dead_key(dest, app_id, depotcache)
            if prompt_confirm("Do you want to enter a new API key?"):
                set_setting(Settings.HUBCAP_KEY, "")
                hubcap_key = ""
                continue
            else:
                print(Fore.YELLOW + "\nYou can update your API key in Settings later." + Style.RESET_ALL)
                return _freelua_after_dead_key(dest, app_id, depotcache)
        elif stats_resp.status_code != 200:
            detail = ""
            try:
                detail = stats_resp.json().get("detail", "")
            except Exception:
                pass
            if detail:
                print(Fore.RED + f"\nHubcap error: {detail}" + Style.RESET_ALL)
                if "discord" in detail.lower():
                    print(
                        Fore.YELLOW
                        + "You must be a member of the Hubcap Discord server to use this API.\n"
                          "Join at: https://discord.gg/hubcap — then re-authenticate to get a valid key."
                        + Style.RESET_ALL
                    )
                elif "state" in detail.lower():
                    print(
                        Fore.YELLOW
                        + "OAuth state error — your authentication session expired or was already used.\n"
                          "Go to https://hubcapmanifest.com and log in again to get a fresh API key."
                        + Style.RESET_ALL
                    )
            else:
                print(
                    Fore.RED
                    + f"\nHubcap Manifest API returned HTTP {stats_resp.status_code}."
                    + Style.RESET_ALL
                )
            return None
        data = stats_resp.json()
        _set_provider_key_flag(Settings.HUBCAP_KEY_DEAD, False)
        break

    usage = data.get("daily_usage")
    limit = data.get("daily_limit")
    state = data.get("can_make_requests")

    if not state:
        print(
            Fore.RED
            + f"Daily limit exceeded! You used {usage}/{limit}"
            + Style.RESET_ALL
        )
        return None
    else:
        logger.debug(f"Downloading lua files from {url}")
        lua_bytes = b''
        while True:
            with download_to_tempfile(url, headers) as tf:
                if tf is None:
                    if prompt_confirm("Try again?"):
                        continue
                    break
                data = tf.read()
                print(
                    Fore.GREEN
                    + f"Hubcap Daily Limit: {usage+1}/{limit}"
                    + Style.RESET_ALL
                )
                lua_bytes = read_lua_from_zip(io.BytesIO(data), decode=False, depotcache=depotcache)
                if lua_bytes is None:
                    # Try to decode server response for a useful error message.
                    # Hubcap sometimes returns an HTML 404 page (or Cloudflare
                    # interstitial) wrapped in HTTP 200. Detect that shape
                    # specifically so users get a clear "not on Hubcap" line
                    # instead of a wall of HTML in the log.
                    try:
                        decoded = data.decode("utf-8", errors="replace")
                    except Exception:
                        decoded = repr(data[:200])
                    stripped = decoded.lstrip().lower()
                    looks_html = stripped.startswith("<!doctype") or stripped.startswith("<html")
                    if looks_html:
                        if "page not found" in decoded.lower() or "page-not-found" in decoded.lower():
                            print(
                                Fore.RED
                                + f"Hubcap: app {app_id} is not in the Hubcap database. "
                                "Try Ryuu or oureveryday for this game."
                                + Style.RESET_ALL
                            )
                        else:
                            print(
                                Fore.RED
                                + "Hubcap returned an HTML page instead of a Lua zip "
                                "(rate limit, Cloudflare challenge, or service down). "
                                "Try again in a minute or pick a different provider."
                                + Style.RESET_ALL
                            )
                        break
                    try:
                        parsed = json.loads(decoded)
                        print(
                            Fore.RED
                            + json.dumps(parsed, indent=2)
                            + Style.RESET_ALL
                        )
                    except json.JSONDecodeError:
                        print(
                            "Did not receive a ZIP file or JSON:\n"
                            + decoded[:500]
                        )
            break
        lua_path = dest / f"{app_id}.lua"
        if lua_bytes:
            with lua_path.open("wb") as f:
                f.write(lua_bytes)
            _update_fallback_depotkeys(lua_bytes)
            try:
                from sff.lua.dlc_appid_enricher import append_depotless_dlcs
                appended = append_depotless_dlcs(lua_path, app_id)
                if appended:
                    logger.debug(
                        "hubcap: appended %d depotless dlc line(s) for %s",
                        appended, app_id,
                    )
            except Exception as e:
                logger.debug("hubcap: dlc enricher raised for %s: %s", app_id, e)
            return lua_path
        return None


def get_ryuu(dest, app_id, depotcache=None, request_update=None, branch=None, file_type=None):
    if not app_id or not str(app_id).strip().isdigit():
        print(Fore.RED + f"Invalid App ID: '{app_id}'" + Style.RESET_ALL)
        return None

    branch = (branch or "").strip() or "public"
    file_type = (file_type or "").strip().lower() or "zip"

    max_attempts = 3
    attempt = 0
    while attempt < max_attempts:
        reseller_key = get_setting(Settings.RYUU_KEY) or ""
        premium_key = get_setting(Settings.RYUU_API_KEY) or ""
        is_premium = False

        if reseller_key and premium_key:
            choice = prompt_select(
                "Which Ryuu key type do you want to use?",
                [("Reseller (auth_code)", "reseller"),
                 ("Premium (X-Auth-Key)", "premium")],
                cancellable=False,
            )
            is_premium = (choice == "premium")
        elif premium_key:
            is_premium = True
        elif reseller_key:
            is_premium = False
        else:
            choice = prompt_select(
                "What type of Ryuu key do you have?",
                [("Reseller key", "reseller"),
                 ("Premium API key", "premium")],
                cancellable=True,
            )
            if choice is None:
                return None
            is_premium = (choice == "premium")

        ryuu_key = premium_key if is_premium else reseller_key
        if not ryuu_key:
            prompt_msg = (
                "Paste your Ryuu premium API key:"
                if is_premium else
                "Paste your Ryuu reseller key:"
            )
            ryuu_key = prompt_secret(
                prompt_msg,
                lambda x: bool(x.strip()),
                "API key cannot be empty.",
                long_instruction="Contact Ryuu staff to get an API key.",
            ).strip()
            if not ryuu_key:
                return None
            if is_premium:
                set_setting(Settings.RYUU_API_KEY, ryuu_key)
            else:
                set_setting(Settings.RYUU_KEY, ryuu_key)

        # Route to correct endpoint based on type
        if is_premium:
            lua_bytes = _ryuu_download_new(app_id, ryuu_key, branch, file_type)
        else:
            lua_bytes = _ryuu_download_old(app_id, ryuu_key, dest, depotcache, file_type)
        if lua_bytes is not None:
            return _ryuu_save_lua(lua_bytes, dest, app_id)

        # If chosen endpoint failed, try the other one
        if is_premium:
            lua_bytes = _ryuu_download_old(app_id, ryuu_key, dest, depotcache, file_type)
        else:
            lua_bytes = _ryuu_download_new(app_id, ryuu_key, branch, file_type)
        if lua_bytes is not None:
            return _ryuu_save_lua(lua_bytes, dest, app_id)

        attempt += 1
        print(Fore.RED + f"ryuu: both endpoints failed (Attempt {attempt}/{max_attempts})" + Style.RESET_ALL)
        if attempt >= max_attempts:
            print(Fore.RED + "Ryuu: Max attempts reached. Check your API key in Settings." + Style.RESET_ALL)
            return None
        if prompt_confirm("Do you want to enter a new API key?"):
            set_setting(Settings.RYUU_KEY, "")
            set_setting(Settings.RYUU_API_KEY, "")
            continue
        return None
    return None


def _ryuu_download_old(app_id, ryuu_key, dest, depotcache, file_type):
    """Old endpoint: auth_code URL param. Works for normal users."""
    url = "https://generator.ryuu.lol/secure_download"
    params = {"appid": str(app_id), "auth_code": ryuu_key}
    if file_type == "lua":
        url = "https://generator.ryuu.lol/resellerlua"
    try:
        resp = httpx.get(url, params=params, timeout=60, follow_redirects=True)
    except Exception:
        return None
    if resp.status_code != 200:
        return None
    return _ryuu_extract_lua(resp, depotcache, file_type)


def _ryuu_download_new(app_id, ryuu_key, branch="public", file_type="zip"):
    """New endpoint: X-Auth-Key header. Works for premium users."""
    headers = {"X-Auth-Key": ryuu_key}
    params: dict = {"branch": branch}
    if file_type != "zip":
        params["file_type"] = file_type
    try:
        resp = httpx.get(
            "https://generator.ryuu.lol/api/download/" + str(app_id),
            params=params, headers=headers, timeout=60, follow_redirects=True,
        )
    except Exception:
        return None
    if resp.status_code != 200:
        return None
    return _ryuu_extract_lua(resp, None, file_type)


def _ryuu_extract_lua(resp, depotcache, file_type):
    if file_type == "lua":
        return resp.content
    return read_lua_from_zip(io.BytesIO(resp.content), decode=False, depotcache=depotcache)


def _ryuu_save_lua(lua_bytes, dest, app_id):
    if lua_bytes is None:
        print(Fore.RED + "Ryuu: downloaded but no .lua content found." + Style.RESET_ALL)
        return None
    lua_path = dest / f"{app_id}.lua"
    with lua_path.open("wb") as f:
        f.write(lua_bytes)
    _update_fallback_depotkeys(lua_bytes)
    try:
        from sff.lua.dlc_appid_enricher import append_depotless_dlcs
        append_depotless_dlcs(lua_path, app_id)
    except Exception:
        pass
    print(Fore.GREEN + f"[OK] Ryuu: Downloaded Lua for {app_id}" + Style.RESET_ALL)
    return lua_path


_TRIONINE_KEYS_URL = "https://raw.githubusercontent.com/fylsdy/ManifestHub/main/depotkeys.json"
_TRIONINE_MANIFEST_REPO = "qwe213312/k25FCdfEOoEJ42S6"
_MH_BRANCH_REPOS = (
    ("steamtoolsapp/ManifestHub", "ManifestHub"),
    ("steamtools-games/ManifestHub3", "ManifestHub3"),
)


def _trionine_depotkeys(max_age: float = 24 * 3600) -> dict[str, str]:
    import time
    from sff.lua.provider import cache_dir
    path = cache_dir() / "trionine_depotkeys.json"
    try:
        if path.exists() and (time.time() - path.stat().st_mtime) < max_age:
            data = json.loads(path.read_text(encoding="utf-8"))
            if isinstance(data, dict) and data:
                return {str(k): v for k, v in data.items() if isinstance(v, str) and v}
    except Exception:
        logger.debug("trionine key cache read failed", exc_info=True)
    try:
        resp = httpx.get(_TRIONINE_KEYS_URL, timeout=60, follow_redirects=True)
        if resp.status_code != 200:
            return {}
        data = resp.json()
    except Exception:
        logger.debug("trionine key fetch failed", exc_info=True)
        return {}
    if not isinstance(data, dict):
        return {}
    out = {str(k): v for k, v in data.items() if isinstance(v, str) and v}
    try:
        path.write_text(json.dumps(out), encoding="utf-8")
    except Exception:
        logger.debug("trionine key cache write failed", exc_info=True)
    return out


def _steamcmd_appinfo(app_id):
    try:
        resp = httpx.get(
            f"https://api.steamcmd.net/v1/info/{app_id}",
            timeout=30, follow_redirects=True,
        )
        if resp.status_code != 200:
            return None
        data = resp.json()
        if data.get("status") == "success":
            return (data.get("data") or {}).get(str(app_id))
    except Exception:
        logger.debug("steamcmd appinfo fetch failed", exc_info=True)
    return None


def _seed_free_manifest(depot_id, gid, app_id, depotcache):
    # Pull the real .manifest bytes off the three keyless mirrors (first 200
    # wins) into depotcache + staging, so downloads and the depot file
    # explorer never need the GMRC cascade for these depots.
    urls = (
        f"https://raw.githubusercontent.com/{_TRIONINE_MANIFEST_REPO}/main/{depot_id}_{gid}.manifest",
        f"https://raw.githubusercontent.com/steamtoolsapp/ManifestHub/{app_id}/{depot_id}_{gid}.manifest",
        f"https://raw.githubusercontent.com/steamtools-games/ManifestHub3/{app_id}/{depot_id}_{gid}.manifest",
    )
    targets = []
    if depotcache is not None:
        targets.append(Path(depotcache) / f"{depot_id}_{gid}.manifest")
    try:
        from sff.core.utils import manifests_staging_dir
        targets.append(manifests_staging_dir() / f"{depot_id}_{gid}.manifest")
    except Exception:
        pass
    if not targets:
        return
    for url in urls:
        try:
            resp = httpx.get(url, timeout=20, follow_redirects=True)
        except Exception:
            continue
        if resp.status_code == 200 and resp.content:
            for t in targets:
                try:
                    t.parent.mkdir(parents=True, exist_ok=True)
                    t.write_bytes(resp.content)
                except Exception:
                    logger.debug("manifest seed write failed for %s", t, exc_info=True)
            return


def get_freelua(dest, app_id, depotcache=None):
    """Keyless Lua from the free community providers, in priority order:
    Ryuu's generator (its download endpoint answers without a key and
    ships the lua plus real .manifest files), trionine ManifestHub (built
    client-side from depotkeys.json + steamcmd gids, like the site
    itself), revobd pre-built bundle, then the ManifestHub / ManifestHub3
    per-app git branches. Any bundled manifests are seeded into
    depotcache along the way."""
    if not app_id or not str(app_id).strip().isdigit():
        print(Fore.RED + f"Invalid App ID: '{app_id}'" + Style.RESET_ALL)
        return None
    app_id = str(app_id)
    lua_path = Path(dest) / f"{app_id}.lua"
    if lua_path.exists() and lua_path.stat().st_size > 0:
        print(Fore.GREEN + f"[Cached] Using existing Lua for {app_id}" + Style.RESET_ALL)
        return lua_path

    # 1) Ryuu, keyless: the /api/download endpoint serves the same zip the
    # premium route uses and ignores the auth key (verified: no key and a
    # bogus key return byte-identical bundles). Unknown appids answer 404
    # JSON fast, so a miss costs one round trip.
    try:
        resp = httpx.get(
            f"https://generator.ryuu.lol/api/download/{app_id}",
            timeout=60, follow_redirects=True,
        )
        if resp.status_code == 200 and resp.content:
            text = read_lua_from_zip(io.BytesIO(resp.content), decode=True, depotcache=depotcache)
            if text:
                lua_path.write_text(text, encoding="utf-8")
                _update_fallback_depotkeys(text.encode("utf-8", errors="ignore"))
                print(Fore.GREEN + f"[OK] Free Providers: Ryuu bundle for {app_id} (manifests included)" + Style.RESET_ALL)
                return lua_path
            logger.debug("freelua: ryuu HTTP 200 but no .lua in bundle for %s", app_id)
        elif resp.status_code != 404:
            logger.debug("freelua: ryuu bundle HTTP %s for %s", resp.status_code, app_id)
    except Exception as e:
        print(Fore.YELLOW + f"Ryuu bundle unreachable ({e})." + Style.RESET_ALL)

    # 2) trionine: depot keys from the shared dump, live gids from steamcmd
    info = _steamcmd_appinfo(app_id)
    if info:
        depots_info = info.get("depots") or {}
        depots = sorted(str(d) for d in depots_info if str(d).isdigit())
        keys = _trionine_depotkeys() if depots else {}
        # The bundled/local key DB (fallback_depotkeys.json + contributed
        # keys) covers games the shared dump is missing.
        if depots and any(not keys.get(d) for d in depots):
            try:
                for d, entry in load_provider().items():
                    k = entry.get("key") if isinstance(entry, dict) else entry
                    if d not in keys and k:
                        keys[str(d)] = str(k)
            except Exception:
                logger.debug("freelua local key DB load failed", exc_info=True)
        lines = [f"addappid({app_id})"]
        pins = {}
        if keys:
            for depot_id in depots:
                key = keys.get(depot_id)
                if not key:
                    continue
                lines.append(f'addappid({depot_id},0,"{key}")')
                mani = (depots_info.get(depot_id) or {}).get("manifests") or {}
                pub = mani.get("public") if isinstance(mani.get("public"), dict) else None
                gid = str((pub or {}).get("gid") or "")
                if gid.isdigit():
                    lines.append(f'setManifestid({depot_id},"{gid}")')
                    pins[depot_id] = gid
            for dlc in re.split(r"[,;\s]+", str((info.get("extended") or {}).get("listofdlc", ""))):
                if dlc.isdigit() and dlc != app_id and dlc not in depots:
                    lines.append(f"addappid({dlc})")
        if sum(1 for l in lines if ',0,"' in l) > 0:
            lua_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
            _update_fallback_depotkeys(lua_path.read_bytes())
            for d, g in pins.items():
                _seed_free_manifest(d, g, app_id, depotcache)
            print(Fore.GREEN + f"[OK] Free Providers: trionine data built Lua for {app_id} ({len(pins)} pinned manifest(s))" + Style.RESET_ALL)
            return lua_path

    # 3) revobd: pre-built zip with the lua + real manifest files
    try:
        resp = httpx.get(
            f"https://api.luagen.revobd.club/{app_id}.zip",
            timeout=30, follow_redirects=True,
        )
        if resp.status_code == 200 and resp.content:
            text = read_lua_from_zip(io.BytesIO(resp.content), decode=True, depotcache=depotcache)
            if text:
                lua_path.write_text(text, encoding="utf-8")
                print(Fore.GREEN + f"[OK] Free Providers: revobd bundle for {app_id} (manifests included)" + Style.RESET_ALL)
                return lua_path
    except Exception as e:
        print(Fore.YELLOW + f"revobd bundle unreachable ({e})." + Style.RESET_ALL)

    # 4+5) ManifestHub / ManifestHub3: one branch per app id with lua + key.vdf
    for repo, label in _MH_BRANCH_REPOS:
        try:
            resp = httpx.get(
                f"https://raw.githubusercontent.com/{repo}/{app_id}/{app_id}.lua",
                timeout=20, follow_redirects=True,
            )
        except Exception:
            continue
        if resp.status_code != 200 or not resp.text.lstrip().startswith("addappid"):
            continue
        lua_path.write_text(resp.text, encoding="utf-8")
        _update_fallback_depotkeys(resp.text.encode("utf-8", errors="ignore"))
        for d, g in re.findall(r'setManifestid\(\s*(\d+)\s*,\s*"?(\d+)"?\s*\)', resp.text):
            _seed_free_manifest(d, g, app_id, depotcache)
        print(Fore.GREEN + f"[OK] Free Providers: {label} Lua for {app_id}" + Style.RESET_ALL)
        return lua_path

    print(Fore.RED + f"No free provider has App {app_id}." + Style.RESET_ALL)
    return None


def get_depotbox(dest, app_id, depotbox_key=None):
    """Download a .lua file from DepotBox.
    Uses the direct-lua endpoint which returns just the .lua text.
    Requires a DepotBox API key. Rate limit: 60/min (Starter) or 120/min (Pro).
    """
    if not app_id or not str(app_id).strip().isdigit():
        print(Fore.RED + f"Invalid App ID: '{app_id}'" + Style.RESET_ALL)
        return None

    if not depotbox_key:
        from sff.core.storage.settings import get_setting
        depotbox_key = get_setting(Settings.DEPOTBOX_KEY)
        if not depotbox_key:
            depotbox_key = prompt_secret(
                "Paste your DepotBox API key here: ",
                lambda x: len(x.strip()) >= 20,
                "That doesn't look like a DepotBox API key!",
                long_instruction=(
                    "Get an API key from https://depotbox.org — Starter (60 req/min) or Pro (120 req/min)."
                ),
            ).strip()
            set_setting(Settings.DEPOTBOX_KEY, depotbox_key)

    # Check rate limit plan
    from sff.core.storage.settings import get_setting
    rate_limit_str = get_setting(Settings.DEPOTBOX_RATE_LIMIT) or ""
    rate_limit = int(rate_limit_str) if rate_limit_str.strip().isdigit() else None
    if rate_limit is None:
        from sff.ui.prompts import prompt_select
        plan = prompt_select(
            "Select your DepotBox plan:",
            [("Starter — 60 requests / minute", 60), ("Pro — 120 requests / minute", 120)],
            cancellable=False,
        )
        rate_limit = plan if plan else 60
        set_setting(Settings.DEPOTBOX_RATE_LIMIT, str(rate_limit))

    headers = {"X-API-Key": depotbox_key}
    url = f"https://depotbox.org/api/direct-lua?appid={app_id}"

    try:
        resp = httpx.get(url, headers=headers, timeout=(10, 300), follow_redirects=True)
        if resp.status_code == 401:
            print(Fore.RED + "DepotBox: Invalid API key." + Style.RESET_ALL)
            set_setting(Settings.DEPOTBOX_KEY, "")
            _set_provider_key_flag(Settings.DEPOTBOX_KEY_DEAD, True)
            return _freelua_after_dead_key(dest, app_id)
        if resp.status_code == 403:
            print(Fore.RED + f"DepotBox: {resp.text[:300]}" + Style.RESET_ALL)
            return None
        if resp.status_code == 404:
            print(Fore.YELLOW + f"DepotBox: No depot keys for App {app_id}. Try another provider." + Style.RESET_ALL)
            return None
        if resp.status_code == 429:
            print(Fore.YELLOW + f"DepotBox: Rate limit ({rate_limit}/min) exceeded. {resp.text[:200]}" + Style.RESET_ALL)
            return None
        if resp.status_code != 200:
            print(Fore.RED + f"DepotBox: HTTP {resp.status_code} — {resp.text[:300]}" + Style.RESET_ALL)
            return None
        _set_provider_key_flag(Settings.DEPOTBOX_KEY_DEAD, False)

        lua_text = resp.text.strip()
        if not lua_text or not lua_text.startswith("--"):
            print(Fore.RED + "DepotBox: Response doesn't look like a valid .lua file." + Style.RESET_ALL)
            return None

        lua_path = dest / f"{app_id}.lua"
        lua_path.write_text(lua_text, encoding="utf-8")
        _update_fallback_depotkeys(lua_text.encode("utf-8"))
        try:
            from sff.lua.dlc_appid_enricher import append_depotless_dlcs
            append_depotless_dlcs(lua_path, app_id)
        except Exception:
            pass
        print(Fore.GREEN + f"[OK] DepotBox: Downloaded Lua for {app_id}" + Style.RESET_ALL)
        return lua_path

    except httpx.ConnectError:
        print(Fore.RED + "DepotBox: Cannot connect. Check your internet." + Style.RESET_ALL)
        return None
    except Exception as e:
        print(Fore.RED + f"DepotBox: Error — {e}" + Style.RESET_ALL)
        return None


_BD_TONE_A = bytes([94, 42, 145, 199, 51, 141, 162, 17])
_BD_TONE_B = bytes([167, 78, 212, 25, 124, 240, 109, 8])
_BD_TONE_C = bytes([71, 83, 239, 42, 145, 191, 51, 197])
_BD_TONE_D = bytes([109, 8, 167, 94, 212, 25, 124, 240])
_BD_PART_0 = bytes([58, 72, 233, 183, 65, 228, 212, 78])
_BD_PART_1 = bytes([196, 43, 228, 123, 73, 200, 90, 63])
_BD_PART_2 = bytes([116, 69, 118, 70, 69, 70, 75, 72])
_BD_PART_3 = bytes([246, 11, 141, 162, 25, 223, 96, 127])
_BD_PART_4 = bytes([43, 94, 93, 49, 45, 45, 44, 46])
_BD_PART_5 = bytes([98, 53, 102, 52, 98, 97, 57, 51])
_BD_PART_6 = bytes([93, 48, 147, 105, 227, 32, 26, 199])


def _resolve_build_details_key():
    """Resolve the build-details access token. A deployed override takes
    precedence; otherwise the built-in token is reassembled on demand."""
    import os
    override = os.environ.get("STEAMIDRA_BUILD_TOKEN")
    if override and override.strip():
        return override.strip()
    p0 = "".join(chr(b ^ _BD_TONE_A[i % 8]) for i, b in enumerate(_BD_PART_0))
    p1 = "".join(chr(b ^ _BD_TONE_B[i % 8]) for i, b in enumerate(_BD_PART_1))[::-1]
    p2 = "".join(chr(b - 19) for b in _BD_PART_2)
    p3 = "".join(chr(b ^ _BD_TONE_C[i % 8]) for i, b in enumerate(_BD_PART_3[::-1]))
    p4 = "".join(chr(b + 7) for b in _BD_PART_4)
    p5 = "".join(chr(b) for b in _BD_PART_5)[::-1]
    p6 = "".join(chr(b ^ _BD_TONE_D[i % 8]) for i, b in enumerate(_BD_PART_6))
    return p0 + p1 + p2 + p3 + p4 + p5 + p6


def fetch_build_details(build_id):
    build_id = str(build_id).strip()
    if not build_id.isdigit() or build_id == "0" or len(build_id) > 12:
        return None
    url = f"https://depotbox.org/api/depotboxtool/v1/build-details?build_id={build_id}"
    headers = {"x-api-key": _resolve_build_details_key()}
    try:
        resp = httpx.get(url, headers=headers, timeout=(10, 120), follow_redirects=True)
    except Exception:
        return None
    if resp.status_code != 200:
        return None
    try:
        data = resp.json()
    except Exception:
        return None
    if not isinstance(data, dict) or not data.get("success"):
        return None
    pins = {}
    try:
        entries = data.get("depots") or []
        if not isinstance(entries, list):
            return None
        for entry in entries:
            if not isinstance(entry, dict):
                continue
            depot = str(entry.get("depot_id", "")).strip()
            manifest = str(entry.get("manifest_id", "")).strip()
            if (
                depot.isdigit() and manifest.isdigit()
                and len(depot) <= 12 and len(manifest) <= 22
            ):
                pins[depot] = manifest
    except Exception:
        return None
    return pins or None
