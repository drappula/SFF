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
import threading
import time
from dataclasses import dataclass
from typing import Any

import gevent
from steam.client import SteamClient  # type: ignore

from sff.core.cache import get_cache
from sff.core.structs import DLCTypes, ProductInfo  # type: ignore
import logging

from sff.core.utils import enter_path

logger = logging.getLogger(__name__)


def get_product_info(provider: "SteamInfoProvider", app_ids):
    """Here for backwards compatibility"""
    return ProductInfo({"apps": provider.get_app_info(app_ids), "packages": {}})


_SESSION_CLIENT = None
_SESSION_PROVIDER = None
_SESSION_GUARD = threading.Lock()


def warm_steam_session():
    """Log in once in the background so GUI-thread lookups never pay
    the anonymous-login cost. Runs on the dedicated CM thread so the
    gevent hub stays thread-affine."""
    try:
        _run_on_cm_thread(
            lambda: _ensure_client_session(create_provider_for_current_thread().client),
            timeout=90,
        )
    except Exception as e:
        logger.debug("warm_steam_session failed: %r", e)


_APP_INFO_TIMEOUTS = (15, 30, 60)
_MAX_APP_INFO_RETRIES = len(_APP_INFO_TIMEOUTS)
_GEVENT_LOCK = threading.Lock()
_LOGIN_LOCK = threading.Lock()

# All Steam CM traffic runs on this single dedicated thread. gevent hubs
# are per-thread: using a SteamClient from a thread other than the one
# that first drove its hub raises "LoopExit: This operation would block
# forever". A one-worker pool pins every login/product-info call to the
# same thread for the life of the process.
from concurrent.futures import ThreadPoolExecutor as _ThreadPoolExecutor
_CM_EXECUTOR = _ThreadPoolExecutor(max_workers=1, thread_name_prefix="steamcm")
_CM_THREAD_IDENT = None


def _run_on_cm_thread(fn, timeout=None):
    return _CM_EXECUTOR.submit(fn).result(timeout=timeout)


def _make_session():
    global _SESSION_CLIENT, _SESSION_PROVIDER, _CM_THREAD_IDENT
    _CM_THREAD_IDENT = threading.get_ident()
    with _SESSION_GUARD:
        if _SESSION_PROVIDER is None:
            try:
                client = SteamClient(connection_timeout=30)
            except TypeError:
                client = SteamClient()
            _SESSION_CLIENT = client
            _SESSION_PROVIDER = SteamInfoProvider(client)
        return _SESSION_PROVIDER


def create_provider_for_current_thread():
    """Return the session-shared Steam client/provider pair.

    The Steam client is constructed AND used exclusively on the
    dedicated CM thread: gevent binds the client's hub to the thread
    that constructs it, and using it from any other thread raises
    "LoopExit: This operation would block forever".
    """
    global _SESSION_PROVIDER
    if _SESSION_PROVIDER is not None:
        return _SESSION_PROVIDER
    if threading.current_thread().name.startswith("steamcm"):
        return _make_session()
    return _run_on_cm_thread(_make_session, timeout=30)


def invalidate_app_info(app_id):
    """Drop cached app info so the next lookup refetches.

    The persistent cache serves app info stale-forever by design (fast
    UI reads), but fields like extended.listofdlc change when new DLC
    ships. Callers that must see fresh data invalidate first; the
    refetch goes through the SteamCMD HTTP mirror, so it's cheap.
    """
    from sff.core.cache import get_cache
    get_cache().invalidate(f"app_info_{int(app_id)}")
    if _SESSION_PROVIDER is not None:
        _SESSION_PROVIDER._cache.pop(int(app_id), None)


@dataclass
class _ProductInfoResult:
    info: ProductInfo
    complete: bool


def _steam_transient_errors():
    import socket
    try:
        from steam.exceptions import SteamError  # type: ignore
    except Exception:
        SteamError = ()  # type: ignore[assignment]

    errors = (
        gevent.Timeout,
        socket.timeout,
        ConnectionResetError,
        ConnectionAbortedError,
        ConnectionError,
        EOFError,
        OSError,
    )
    return errors + ((SteamError,) if SteamError else ())  # type: ignore[operator]


def _ensure_client_session(client):
    with _LOGIN_LOCK:
        if client.logged_on:
            return
        logger.debug("Logging in anonymously...")
        try:
            client.anonymous_login()
        except Exception as e:
            logger.exception("Steam anonymous login failed: %s", e)
            raise
        logger.debug("Anonymous login done")


def _client_state(client):
    return (
        f"logged_on={getattr(client, 'logged_on', None)!r}, "
        f"server={getattr(client, 'current_server_addr', None)!r}"
    )


def _reopen_client_session(client):
    try:
        if getattr(client, "logged_on", False) and hasattr(client, "disconnect"):
            client.disconnect()
            time.sleep(0.5)
    except Exception as e:
        logger.debug("Steam appinfo reconnect disconnect failed: %r", e)
    try:
        client.anonymous_login()
        logger.debug("Steam appinfo reconnect ok (%s)", _client_state(client))
    except Exception as e:
        logger.debug("Steam appinfo reconnect failed: %r (%s)", e, _client_state(client))


def _empty_product_info():
    return ProductInfo({"apps": {}, "packages": {}})


def _request_app_info(client, app_ids, timeout):
    start = time.time()
    info = client.get_product_info(  # pyright: ignore[reportUnknownMemberType]
        apps=list(app_ids),
        timeout=timeout,
    )
    if info is None:
        raise gevent.Timeout(None, "get_product_info returned None")
    logger.debug(f"Product info request took: {time.time() - start}s")
    return ProductInfo(info)


def _get_product_info_result(client, app_ids, quick=False):
    if len(app_ids) == 0:
        raise ValueError("app_ids cannot be empty.")

    def _run():
        with _GEVENT_LOCK:
            _ensure_client_session(client)
            last_error: Exception | None = None
            transient = _steam_transient_errors()
            if quick:
                try:
                    with gevent.Timeout(35):
                        return _ProductInfoResult(
                            _request_app_info(client, app_ids, 25), True
                        )
                except gevent.Timeout as e:
                    last_error = e
                    logger.debug(
                        "App info quick path timed out (35s budget) for apps=%s: %r",
                        app_ids, e,
                    )
                    return _ProductInfoResult(_empty_product_info(), False)
            for attempt, timeout in enumerate(_APP_INFO_TIMEOUTS, start=1):
                try:
                    return _ProductInfoResult(_request_app_info(client, app_ids, timeout), True)
                except transient as e:
                    last_error = e
                    logger.debug(
                        "App info attempt %s/%s hit %s with timeout=%ss for apps=%s: %r (%s)",
                        attempt,
                        _MAX_APP_INFO_RETRIES,
                        type(e).__name__,
                        timeout,
                        app_ids,
                        e,
                        _client_state(client),
                    )
                    if attempt < _MAX_APP_INFO_RETRIES:
                        logger.debug(
                            "Request timed out after %ss. "
                            "Trying again (%s/%s)...",
                            timeout, attempt, _MAX_APP_INFO_RETRIES
                        )
                        _reopen_client_session(client)
                        time.sleep(2)
                        continue
                    logger.debug(
                        "Steam appinfo timed out after several attempts. "
                        "SteaMidra will use cached/local manifests if available."
                    )
                    return _ProductInfoResult(_empty_product_info(), False)
            # All retries exhausted without an exception we recognised.
            if last_error is not None:
                logger.warning(f"App info gave up after {_MAX_APP_INFO_RETRIES} attempts: {last_error}")
            return _ProductInfoResult(_empty_product_info(), False)

    if quick:
        return _run_on_cm_thread(_run, timeout=45)
    # Full ladder can take a while (15+30+60s + reconnects).
    return _run_on_cm_thread(_run, timeout=360)


def _get_product_info(client, app_ids, quick=False):
    return _get_product_info_result(client, app_ids, quick=quick).info


_APPINFO_HTTP_URL = "https://api.steamcmd.net/v1/info/{}"
_APPINFO_HTTP_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
)


def fetch_app_info_http(app_id):
    """Fetch one app's info from the SteamCMD HTTP mirror.

    api.steamcmd.net serves the same appinfo structure Valve ships
    through SteamCMD (depots, branches/build ids, manifests, common)
    as plain JSON. Used as the final fallback when the Steam CM path
    cannot produce the app in time. Returns the app payload dict or
    None. Nothing from the response is ever executed.
    """
    app_id = str(app_id).strip()
    if not app_id.isdigit() or len(app_id) > 12:
        return None
    try:
        import httpx
        resp = httpx.get(
            _APPINFO_HTTP_URL.format(app_id),
            headers={"User-Agent": _APPINFO_HTTP_UA, "Accept": "application/json"},
            timeout=10,
            follow_redirects=True,
        )
        if resp.status_code != 200:
            return None
        data = resp.json()
        if not isinstance(data, dict):
            return None
        if str(data.get("status", "")).lower() != "success":
            return None
        payload = (data.get("data") or {}).get(app_id)
        if not isinstance(payload, dict):
            return None
        if not isinstance(payload.get("depots"), dict):
            return None
        return payload
    except Exception as e:
        logger.debug("appinfo HTTP fallback failed for %s: %r", app_id, e)
        return None


class SteamInfoProvider:

    def __init__(self, client):
        self.client = client
        self._cache: dict[int, Any] = {}
        self._persistent_cache = get_cache()

    def _cache_key(self, app_id):
        return f"app_info_{app_id}"

    def _load_cached_app(self, app_id) -> bool:
        cached_data = self._persistent_cache.get_stale(self._cache_key(app_id))
        if cached_data is None:
            return False
        self._cache[app_id] = cached_data
        logger.debug(f"Loaded app {app_id} from persistent cache")
        return True

    def _store_app_payloads(self, apps):
        for app_id, app_data in apps.items():
            self._cache[app_id] = app_data
            # App info changes rarely — keep it cached for 7 days so the
            # download modal stays instant across restarts instead of
            # re-paying a Steam CM login after the old 1-hour TTL.
            self._persistent_cache.set(self._cache_key(app_id), app_data, ttl=7 * 24 * 3600)

    def invalidate_app(self, app_id):
        """Drop an app from both the in-memory and persistent caches."""
        self._cache.pop(app_id, None)
        self._cache.pop(int(app_id), None)
        self._persistent_cache.invalidate(self._cache_key(app_id))

    def _fill_from_http(self, app_ids):
        """Fill as many missing apps as possible from the SteamCMD HTTP
        mirror. Returns the list of app ids that were filled."""
        filled = []
        for app_id in app_ids:
            if self._cache.get(app_id, {}):
                continue
            payload = fetch_app_info_http(app_id)
            if payload:
                self._store_app_payloads({app_id: payload})
                logger.debug(
                    "appinfo filled from SteamCMD HTTP mirror: %s", app_id
                )
                filled.append(app_id)
        return filled

    def get_app_info_http_only(self, app_ids):
        """SteamCMD HTTP mirror only — never touches Steam CM. Used by
        GUI-thread callers so they can never block on a CM login."""
        missing = []
        for app_id in app_ids:
            if app_id in self._cache:
                continue
            if not self._load_cached_app(app_id):
                missing.append(app_id)
        if missing:
            self._fill_from_http(missing)
        return {
            app_id: self._cache.get(app_id, {})
            for app_id in app_ids
            if self._cache.get(app_id, {})
        }

    def get_single_app_info_http_only(self, app_id):
        result = self.get_app_info_http_only([app_id])
        return result.get(app_id, {})

    def get_app_info(self, app_ids, quick=False):
        missing = []
        for app_id in app_ids:
            if app_id in self._cache:
                continue
            if not self._load_cached_app(app_id):
                missing.append(app_id)
        if missing:
            # SteamCMD HTTP mirror first — fast, bounded, no login.
            self._fill_from_http(missing)
            still_missing = [a for a in missing if not self._cache.get(a, {})]
            if still_missing:
                result = _get_product_info_result(self.client, still_missing, quick=quick)
                apps = result.info.get("apps", {})
                valid_ids = set(apps.keys())
                self._store_app_payloads(apps)
                if result.complete:
                    invalid_ids = set(still_missing) - valid_ids
                    for app_id in invalid_ids:
                        self._cache[app_id] = False
                else:
                    logger.debug(
                        "Steam appinfo fetch incomplete; leaving %s uncached for later retry",
                        sorted(set(still_missing) - valid_ids),
                    )
                # CM incomplete — one more HTTP attempt for leftovers.
                self._fill_from_http(
                    [a for a in still_missing if not self._cache.get(a, {})]
                )
        else:
            logger.debug("Reading app info from cache...")
        return {
            app_id: self._cache.get(app_id, {})
            for app_id in app_ids
            if self._cache.get(app_id, {})
        }

    def get_single_app_info(self, app_id, quick=False):
        result = self.get_app_info([app_id], quick=quick)
        return result.get(app_id, {})


class ParsedDLC:
    def __init__(
        self,
        depot_id: int,
        dlc_data,
        parent_data,
        local_ids: list[int],
    ):
        self.id = depot_id
        self.name: str = enter_path(dlc_data, "common", "name")
        depots = enter_path(dlc_data, "depots")
        parent_depots = enter_path(
            parent_data, "depots"
        )
        parent_depots_resolved = [
            (x.get("dlcappid") if isinstance(x, dict) else None)
            for x in parent_depots.values()
        ]
        self.release_state = enter_path(dlc_data, "common", "releasestate")
        self.type = (
            (
                DLCTypes.DEPOT
                if depots or str(depot_id) in parent_depots_resolved
                else DLCTypes.NOT_DEPOT
            )
            if self.release_state == "released"
            else DLCTypes.UNRELEASED
        )
        self.in_applist = True if depot_id in local_ids else False
