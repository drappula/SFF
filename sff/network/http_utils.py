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

import asyncio
import logging
import os
from contextlib import contextmanager
from tempfile import TemporaryFile
from pathlib import Path

import httpx
from tqdm import tqdm  # type: ignore

from sff.ui.prompts import prompt_text
from typing import Literal, overload


logger = logging.getLogger(__name__)


# httpx supports http/https + socks5 (with httpx-socks). socks4 is NOT
# supported and raises ValueError("Unknown scheme for proxy URL ...") deep
# inside its config layer the moment ANY httpx.Client is built while a
# socks4://, socks5h-without-extras://, or anything else weird is sitting
# in HTTPS_PROXY / HTTP_PROXY / ALL_PROXY. A VPN user (NekoBox, v2rayN, etc)
# tripped this on hubcap's get_hubcap call and the whole download died.
# Sanitise the env once at process start so every later httpx.get path runs
# direct instead of crashing. The user gets a single WARN line in the log
# explaining what happened.
_HTTPX_OK_PROXY_SCHEMES = ("http", "https", "socks5", "socks5h")
_PROXY_ENV_KEYS = ("HTTPS_PROXY", "HTTP_PROXY", "ALL_PROXY",
                   "https_proxy", "http_proxy", "all_proxy")


def _strip_unsupported_proxy_env():
    for key in _PROXY_ENV_KEYS:
        raw = os.environ.get(key, "")
        if not raw:
            continue
        scheme = raw.split("://", 1)[0].strip().lower() if "://" in raw else ""
        if scheme and scheme not in _HTTPX_OK_PROXY_SCHEMES:
            logger.warning(
                "Unsupported proxy scheme %r in %s, falling back to direct connection",
                scheme, key,
            )
            os.environ.pop(key, None)


_strip_unsupported_proxy_env()


def _httpx_call_safe(call, *args, **kwargs):
    """Run an httpx.* callable, retry once with proxies disabled if the
    httpx config layer rejects an env-detected proxy URL.

    Catches the very specific ValueError httpx raises during Client/AsyncClient
    construction when HTTPS_PROXY contains an unsupported scheme (socks4 etc).
    First call is normal so existing trust_env / mounts still work; retry forces
    trust_env=False so the env proxy is ignored. Real network errors propagate.
    """
    try:
        return call(*args, **kwargs)
    except ValueError as e:
        if "Unknown scheme for proxy URL" not in str(e):
            raise
        logger.warning(
            "httpx rejected proxy env (%s); retrying with direct connection", e
        )
        kwargs = dict(kwargs)
        kwargs["trust_env"] = False
        return call(*args, **kwargs)


@overload
async def get_request(
    url: str,
    type = "text",
    timeout = 10,
    headers = None,
): ...


@overload
async def get_request(
    url: str,
    type: Literal["json"],
    timeout = 10,
    headers = None,
): ...


async def get_request(
    url: str,
    type = "text",
    timeout = 10,
    headers = None,
    *,
    redact_url: bool = False,
):
    log_url = "<redacted>" if redact_url else url
    try:
        try:
            client_cm = httpx.AsyncClient(timeout=timeout)
        except ValueError as e:
            if "Unknown scheme for proxy URL" not in str(e):
                raise
            logger.warning(
                "httpx rejected proxy env (%s); retrying with direct connection", e
            )
            client_cm = httpx.AsyncClient(timeout=timeout, trust_env=False)
        async with client_cm as client:
            logger.debug(f"Making request to {log_url}")
            response = await client.get(url, headers=headers)
        if response.status_code == 200:
            try:
                logger.debug(f"Received {len(response.content)} bytes")
                return response.text if type == "text" else response.json()
            except ValueError:
                return
        else:
            # Body redacted when the URL is redacted, otherwise the upstream
            # error page (e.g. openresty 503 HTML) leaks identifying details
            # back into the live log even though the URL itself was masked.
            if redact_url:
                logger.debug(f"Error {response.status_code} (body redacted)")
            else:
                logger.debug(f"Error {response.status_code}: {response.text[:200]}")

    except httpx.RequestError as e:
        logger.debug(f"Request error: {repr(e)}")


def get_game_name(app_id):
    # Local games.json cache first: instant, offline, and the store API
    # fails often enough that the interactive prompt fired on nearly
    # every download (and fired once per call site).
    try:
        from sff.game_list_fallback import get_app_name
        local = get_app_name(app_id)
    except Exception:
        local = ""
    if local:
        logger.debug("get_game_name(%s): local cache -> %s", app_id, local)
        return local
    official_info = asyncio.run(
        get_request(
            f"https://store.steampowered.com/api/appdetails/?appids={app_id}",
            "json",
        )
    )
    app_name = None
    if official_info:
        app_name = official_info.get(app_id, {}).get("data", {}).get("name")
        if app_name:
            logger.debug("get_game_name(%s): store API -> %s", app_id, app_name)
            return app_name
    # The name only feeds the ACF display field and install folder name.
    # In the GUI a blocking prompt is never worth it — fall back to a
    # generic name. CLI users can still type one for delisted apps.
    from sff.ui.prompts import _gui_backend
    if _gui_backend is not None:
        logger.debug("get_game_name(%s): unresolved, GUI fallback 'App %s'", app_id, app_id)
        return f"App {app_id}"
    return prompt_text("Request failed. Type the name of the game: ")


@contextmanager
def download_to_tempfile(
    url: str,
    headers = None,
    params = None,
    chunk_size = (1024**2) // 2,
):
    temp_f = TemporaryFile()
    try:
        try:
            stream_cm = httpx.stream(
                "GET",
                url,
                headers=headers,
                params=params,
                follow_redirects=True,
                timeout=120,
            )
        except ValueError as e:
            if "Unknown scheme for proxy URL" not in str(e):
                raise
            logger.warning(
                "httpx rejected proxy env (%s); retrying with direct connection", e
            )
            stream_cm = httpx.stream(
                "GET",
                url,
                headers=headers,
                params=params,
                follow_redirects=True,
                timeout=120,
                trust_env=False,
            )
        with stream_cm as response:
            try:
                total = int(response.headers.get("Content-Length", "0"))
            except Exception as e:
                print(f"Could not parse Content-Length header: {e}")
                total = 0
            logger.debug(f"Total size is {total}")
            with tqdm(
                desc="Downloading",
                total=total,
                unit="B",
                unit_scale=True,
                unit_divisor=1024,
                miniters=1,
            ) as pbar:
                for chunk in response.iter_bytes(chunk_size=chunk_size):
                    temp_f.write(chunk)
                    pbar.update(len(chunk))
        temp_f.seek(0)
        yield temp_f
    except httpx.HTTPError as e:
        print(f"Network error: {repr(e)}")
        yield None
    finally:
        temp_f.close()


def download_to_path(
    url: str,
    path: Path,
    headers = None,
    chunk_size = (1024**2) // 2,
    timeout: float | None = 60.0,
):
    try:
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        with httpx.stream(
            "GET",
            url,
            headers=headers or {},
            follow_redirects=True,
            timeout=httpx.Timeout(connect=30.0, read=timeout, write=30.0, pool=30.0) if timeout else None,
        ) as response:
            response.raise_for_status()
            try:
                total = int(response.headers.get("Content-Length", "0"))
            except (ValueError, TypeError):
                total = 0
            with path.open("wb") as f, tqdm(
                desc="Downloading",
                total=total or None,
                unit="B",
                unit_scale=True,
                unit_divisor=1024,
                miniters=1,
            ) as pbar:
                for chunk in response.iter_bytes(chunk_size=chunk_size):
                    f.write(chunk)
                    pbar.update(len(chunk))
        return True
    except httpx.HTTPError as e:
        print(f"Download error: {repr(e)}")
        return False
