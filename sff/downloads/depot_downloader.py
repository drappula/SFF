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
import shutil
import subprocess
import sys
import tempfile
import time
import logging
from pathlib import Path
from typing import Tuple

from colorama import Fore, Style

from sff.downloads.dotnet_utils import get_dotnet_path
from sff.core.utils import root_folder

logger = logging.getLogger(__name__)

KEYS_TMP = Path(tempfile.gettempdir()) / "mistwalker_keys.vdf"
MANIFESTS_TMP = Path(tempfile.gettempdir()) / "mistwalker_manifests"

_DDMOD_EXIT_HINTS = {
    3762504530: (
        "DepotDownloaderMod crashed with an unhandled .NET exception. "
        "The bundled DDMod may be outdated/corrupt, or the download "
        "folder is not writable."
    ),
    3221225781: (
        "DepotDownloaderMod failed to start (missing DLL). "
        "Reinstall .NET 9 or re-download DepotDownloaderMod."
    ),
}


def _find_openssl_lib_dir(dotnet_root: str) -> str:
    """Return the directory containing libcrypto.so.3 / libssl.so.3.

    Checks bundled .NET runtime first, then system library paths so
    DDMod can find OpenSSL on distros where the .NET runtime doesn't
    ship its own copy (Arch, CachyOS, etc.).
    """
    import glob as _glob, shutil
    # 1. Bundled .NET runtime
    pattern = os.path.join(dotnet_root, "shared", "Microsoft.NETCore.App", "*")
    for runtime_dir in sorted(_glob.glob(pattern), reverse=True):
        candidate = os.path.join(runtime_dir)
        if os.path.isfile(os.path.join(candidate, "libcrypto.so.3")):
            return candidate
    # 2. System library paths
    for system_dir in (
        "/usr/lib", "/usr/lib64", "/lib", "/lib64",
        "/usr/local/lib", "/usr/local/lib64",
        # Debian/Ubuntu multiarch
        "/usr/lib/x86_64-linux-gnu",
        "/usr/lib/aarch64-linux-gnu",
        "/usr/lib/arm-linux-gnueabihf",
        "/usr/lib/i386-linux-gnu",
        # Fedora-style alternatives
        "/usr/local/ssl/lib",
    ):
        if os.path.isfile(os.path.join(system_dir, "libcrypto.so.3")):
            return system_dir
    # 3. which-based fallback
    for soname in ("libcrypto.so.3", "libcrypto.so"):
        found = shutil.which(soname)
        if found:
            return os.path.dirname(found)
    return ""


def _add_bundled_openssl_to_env(env: dict, dotnet_root: str) -> None:
    lib_dir = _find_openssl_lib_dir(dotnet_root)
    if not lib_dir:
        return
    existing_ld = env.get("LD_LIBRARY_PATH", "")
    if lib_dir not in existing_ld.split(os.pathsep) if existing_ld else True:
        env["LD_LIBRARY_PATH"] = f"{lib_dir}{os.pathsep}{existing_ld}" if existing_ld else lib_dir


def get_deps_dir() -> Path:
    return root_folder() / "third_party" / "DDMod"


def get_ddmod_dll() -> Path:
    return get_deps_dir() / "DepotDownloaderMod.dll"


def _copy_manifests_to_temp(steam_path: Path, manifests: dict) -> None:
    MANIFESTS_TMP.mkdir(parents=True, exist_ok=True)

    # Check both depotcache locations — SteaMidra syncs manifests to config/depotcache
    # on Linux, while steamapps/depotcache is the standard Windows location.
    depotcache_candidates = [
        steam_path / "steamapps" / "depotcache",
        steam_path / "config" / "depotcache",
    ]

    for depot_id, manifest_id in manifests.items():
        filename = f"{depot_id}_{manifest_id}.manifest"
        dst = MANIFESTS_TMP / filename
        if dst.exists():
            continue  # already copied
        for depotcache in depotcache_candidates:
            src = depotcache / filename
            if src.exists():
                # A CDN error page saved as a manifest makes both engines
                # crash on it (-6 / "download failed"). Drop the poison so
                # the next fetch re-downloads real bytes.
                from sff.manifest.crypto import has_manifest_magic
                if not has_manifest_magic(src):
                    logger.debug("depot %s: deleting corrupt cached manifest %s", depot_id, src)
                    src.unlink(missing_ok=True)
                    continue
                shutil.copy2(src, dst)
                break

    # Also check the canonical staging folder (where ZIP-based providers
    # like Hubcap / Free Providers / Ryuu drop manifests after extraction).
    # Path.cwd() was wrong on AppImage launches and Web UI workers.
    from sff.core.utils import manifests_staging_dir
    staging = manifests_staging_dir()
    if staging.exists():
        for depot_id, manifest_id in manifests.items():
            filename = f"{depot_id}_{manifest_id}.manifest"
            src = staging / filename
            dst = MANIFESTS_TMP / filename
            if src.exists() and not dst.exists():
                shutil.copy2(src, dst)


def _read_process_output(proc: subprocess.Popen, print_fn, depot_timeout: float | None = None, cancel_check=None) -> None:
    """Read subprocess stdout with an optional per-depot timeout (in seconds).

    Spawns a reader thread so a hanging DDMod process doesn't freeze the
    entire download chain. If depot_timeout is None, no timeout is enforced.
    Progress extends the deadline so active downloads are never killed.
    """
    import queue as _q
    import threading as _t
    if not proc.stdout:
        return
    pre_alloc_count = 0
    validate_count = 0
    progress_count = 0
    last_pre_alloc_t = 0.0
    last_progress_t = 0.0
    last_validate_t = 0.0
    last_progress_pct: float = -1.0
    _SUMMARY_INTERVAL = 2.0
    _lineq: _q.Queue = _q.Queue()
    _stop = _t.Event()

    def _reader():
        # DDMod writes per-file progress with '\r' (no newline until the
        # file completes), so iterating stdout lines would go silent for
        # the entire download phase. Split on both terminators.
        import select as _sel
        try:
            buf = b""
            fd = proc.stdout.fileno()
            while not _stop.is_set():
                if _sel.select([fd], [], [], 0.5)[0]:
                    chunk = os.read(fd, 4096)
                    if not chunk:
                        break
                    buf += chunk
                    while True:
                        i_n = buf.find(b"\n")
                        i_r = buf.find(b"\r")
                        if i_n < 0 and i_r < 0:
                            break
                        if i_r >= 0 and (i_n < 0 or i_r < i_n):
                            cut, keep = i_r, i_r + 1
                        else:
                            cut, keep = i_n, i_n + 1
                        _lineq.put(buf[:cut] + b"\n")
                        buf = buf[keep:]
                elif proc.poll() is not None:
                    break
            if buf:
                _lineq.put(buf if buf.endswith(b"\n") else buf + b"\n")
        except ValueError:
            pass
        finally:
            _lineq.put(None)

    _reader_t = _t.Thread(target=_reader, daemon=True)
    _reader_t.start()

    deadline = None if depot_timeout is None else (time.monotonic() + depot_timeout)
    while True:
        if cancel_check and cancel_check():
            print_fn(Fore.YELLOW + "\n[cancelled] Killing depot process" + Style.RESET_ALL)
            _stop.set()
            proc.kill()
            break
        if deadline is not None:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                print_fn(Fore.RED + f"\n[timeout] Depot download exceeded {depot_timeout:.0f}s, killing process" + Style.RESET_ALL)
                _stop.set()
                proc.kill()
                break
        else:
            remaining = 0.5
        try:
            raw_line = _lineq.get(timeout=min(remaining, 0.5) if deadline is not None else 0.5)
        except _q.Empty:
            if proc.poll() is not None:
                _stop.set()
                raw_line = _lineq.get() if not _lineq.empty() else None
                if raw_line is None:
                    break
            else:
                continue
        if raw_line is None:
            break
        line = raw_line.decode("utf-8", errors="replace").strip()
        if not line:
            continue
        now = time.monotonic()

        if line.startswith("Pre-allocating"):
            pre_alloc_count += 1
            if now - last_pre_alloc_t >= _SUMMARY_INTERVAL:
                print_fn(f"[Pre-allocating files... {pre_alloc_count} so far]")
                last_pre_alloc_t = now
            if depot_timeout is not None:
                deadline = time.monotonic() + depot_timeout
            continue

        lower = line.lower()
        if "validating chunk" in lower or lower.startswith("validated "):
            validate_count += 1
            if now - last_validate_t >= _SUMMARY_INTERVAL:
                print_fn(f"[Validating chunks... {validate_count} so far]")
                last_validate_t = now
            if depot_timeout is not None:
                deadline = time.monotonic() + depot_timeout
            continue

        m = _DDMOD_PROGRESS_RE.match(line)
        if m:
            progress_count += 1
            try:
                pct = float(m.group(1))
            except ValueError:
                pct = -1.0
            crossed_pct = (pct >= 0 and (last_progress_pct < 0
                                         or int(pct) != int(last_progress_pct)))
            elapsed = now - last_progress_t >= _SUMMARY_INTERVAL
            if crossed_pct or elapsed:
                print_fn(line)
                last_progress_pct = pct
                last_progress_t = now
            if crossed_pct and depot_timeout is not None:
                deadline = time.monotonic() + depot_timeout
            continue

        print_fn(line)

    _reader_t.join(timeout=3)

    if pre_alloc_count > 0:
        print_fn(f"[Pre-allocation complete: {pre_alloc_count} file(s)]")
    if validate_count > 0:
        print_fn(f"[Validation complete: {validate_count} chunk(s)]")


# DDMod's progress lines always start with optional whitespace, then a
# decimal percent followed by '%'. Tightened to require the percent to
# anchor at the start so we don't match unrelated lines that happen to
# contain a percent (e.g. depot summaries).
_DDMOD_PROGRESS_RE = re.compile(r"^\s*(\d{1,3}(?:\.\d+)?)%\s")


def _calculate_dir_size(path: Path) -> int:
    total = 0
    try:
        for f in path.rglob("*"):
            if f.is_file():
                try:
                    total += f.stat().st_size
                except OSError:
                    pass
    except OSError:
        pass
    return total


def _resolve_depot_owners(appid: str, depot_ids: list) -> dict:
    """Map each depot to the app that actually owns it.

    A DLC lua often lists the base game's depots. Downloading those under
    the DLC's appid makes DDMod abort (exit -6): the DLC's appinfo grants
    none of them, so it can't resolve a manifest. Steam's
    primary-depot==appid convention and the depotfromapp field identify
    the real owner. Anything unresolvable falls back to appid.
    """
    owners = {str(d): str(appid) for d in depot_ids}
    try:
        from sff.network.steam_client import create_provider_for_current_thread
        provider = create_provider_for_current_thread()
    except Exception:
        return owners

    def _info(aid):
        try:
            return provider.get_single_app_info(int(aid), quick=True) or {}
        except Exception:
            return {}

    app_depots = _info(appid).get("depots") or {}
    # Selected depots that are themselves real apps (base-game primary
    # depots like 3438850) are candidate owners for the rest of the set.
    candidates = {}
    for d in depot_ids:
        d = str(d)
        if d == str(appid):
            continue
        info = _info(d)
        if (info.get("common") or {}).get("name"):
            candidates[d] = info.get("depots") or {}
    for d in depot_ids:
        d = str(d)
        if d == str(appid) or d in app_depots:
            continue  # appid's own appinfo grants it (owner stays appid)
        meta = app_depots.get(d)
        if isinstance(meta, dict) and meta.get("depotfromapp"):
            owners[d] = str(meta["depotfromapp"])
        elif d in candidates:
            owners[d] = d  # depot id is its own app
        else:
            for cand, cand_depots in candidates.items():
                if d in cand_depots:
                    owners[d] = cand
                    break
            else:
                owners[d] = None  # nothing in the set grants it
    return owners


def _find_local_manifest_bytes(depot_id: str, manifest_id: str, steam_path=None):
    name = f"{depot_id}_{manifest_id}.manifest"
    dirs = [MANIFESTS_TMP, Path.cwd() / "manifests"]
    if steam_path:
        dirs += [Path(steam_path) / "depotcache", Path(steam_path) / "config" / "depotcache"]
    for d in dirs:
        p = d / name
        try:
            if p.is_file() and p.stat().st_size > 0:
                return p.read_bytes()
        except OSError:
            continue
    return None


def _write_ddmod_filelist(depot_id: str, manifest_id: str, key: str,
                          dirs: list, steam_path=None, print_fn=print):
    """Expand selected folder paths into DDMod's -filelist format (exact
    manifest file paths, one per line). Needs the manifest decrypted locally;
    returns None when that isn't possible and the caller falls back to the
    full depot."""
    raw = _find_local_manifest_bytes(depot_id, manifest_id, steam_path)
    if not raw or not key:
        return None
    try:
        from sff.downloads.native_downloader import (
            decode_manifest, _normalize_manifest_path, _path_selected)
        manifest = decode_manifest(raw, bytes.fromhex(key))
    except Exception as e:
        print_fn(Fore.YELLOW + f"DDMod filelist: manifest decode failed ({e})" + Style.RESET_ALL)
        return None
    prefixes = [str(d).replace("\\", "/").strip("/").lower() for d in dirs if d]
    lines = []
    for m in manifest.get("mappings", []):
        if m.get("flags", 0) & 0x40:
            continue
        fn = str(m.get("filename") or "")
        norm = _normalize_manifest_path(fn)
        if norm and _path_selected(norm, prefixes):
            lines.append(fn)
    if not lines:
        return None
    out = MANIFESTS_TMP / f"{depot_id}_{manifest_id}_filelist.txt"
    try:
        out.write_text("\n".join(lines) + "\n", encoding="utf-8")
    except OSError:
        return None
    print_fn(Fore.CYAN + f"DDMod filelist: {len(lines)} files selected" + Style.RESET_ALL)
    return out


def run_download(
    game_data: dict,
    selected_depots: list,
    dest_path: Path,
    steam_path: Path,
    print_fn=print,
    os_name: str | None = None,
    force_ddmod: bool = False,
    file_filters: dict | None = None,
) -> Tuple[bool, int]:
    appid = str(game_data["appid"])
    depots = game_data.get("depots", {})
    manifests = dict(game_data.get("manifests", {}) or {})
    installdir = game_data.get("installdir") or f"App_{appid}"
    target_os = (os_name or "windows").lower()
    # Selective file download: file_filters maps depot id -> list of selected
    # folder paths ("" = whole depot, so no filtering for that depot).
    file_filters = {str(k): [p for p in (v or []) if p] for k, v in (file_filters or {}).items()}
    file_filters = {k: v for k, v in file_filters.items() if v}

    def _native_include_dirs(depot_id_str):
        return file_filters.get(depot_id_str) or None

    # Auto-fill manifests from the staging dir for any selected depot
    # the caller did not pin a manifest for. The staging dir is what
    # ZIP-based providers (Hubcap / Free Providers / Ryuu) drop manifests
    # into after extraction. Without this, DDMod gets called with
    # `-depot N` and no `-manifest N` and falls back to anonymous CDN
    # fetch, which 401s on most owned-game depots and aborts. The user
    # ends up with redists downloaded and zero game files.
    try:
        from sff.core.utils import manifests_staging_dir
        staging = manifests_staging_dir()
        if staging.exists():
            staged: dict[str, str] = {}
            for f in staging.glob("*.manifest"):
                parts = f.stem.split("_", 1)
                if len(parts) == 2 and parts[0].isdigit() and parts[1].isdigit():
                    staged[parts[0]] = parts[1]
            for depot_id in selected_depots:
                key = str(depot_id)
                if key not in manifests and key in staged:
                    manifests[key] = staged[key]
                    print_fn(
                        Fore.CYAN
                        + f"  [staging] picked up manifest {staged[key]} for depot {key}"
                        + Style.RESET_ALL
                    )
    except Exception as exc:
        print_fn(
            Fore.YELLOW
            + f"  [staging] could not scan staging dir ({exc}); continuing without auto-fill"
            + Style.RESET_ALL
        )
    game_data["manifests"] = manifests

    _copy_manifests_to_temp(steam_path, manifests)

    # ── Native downloader first (all platforms, no .NET needed) ────────
    # The pure-Python CDN downloader is the primary engine. DepotDownloaderMod
    # below acts as the backup for depots the native path cannot complete.
    download_dir = dest_path / "steamapps" / "common" / installdir
    download_dir.mkdir(parents=True, exist_ok=True)

    # Write probe: a dead/inaccessible destination should fail here with a
    # clear message instead of surfacing as a DDMod .NET crash later.
    try:
        _probe = download_dir / ".steamidra_write_probe"
        _probe.write_text("ok", encoding="utf-8")
        _probe.unlink(missing_ok=True)
    except Exception as e:
        print_fn(Fore.RED + f"ERROR: download folder is not writable: {download_dir} ({e})" + Style.RESET_ALL)
        try:
            KEYS_TMP.unlink(missing_ok=True)
        except Exception:
            pass
        return False, 0

    def _cancelled():
        try:
            from sff.game import download_queue as _dq
            return _dq.is_cancelled(appid)
        except Exception:
            return False

    # Pinned manifests fetch under any app, so the owning-app lookup is
    # only needed when some depot has no manifest (DDMod would otherwise
    # abort -6 on a DLC lua that lists the base game's depots).
    depot_owners: dict = {}
    if any(str(d) not in manifests for d in selected_depots):
        depot_owners = _resolve_depot_owners(appid, selected_depots)

    native_failed: list = []
    if force_ddmod:
        native_failed = list(selected_depots)
        print_fn(Fore.CYAN + "\nUsing DepotDownloaderMod (native CDN downloader skipped)" + Style.RESET_ALL)
    else:
        try:
            from sff.downloads.native_downloader import download_depot as _native_dl
            print_fn(Fore.CYAN + "\n[Native] Starting Steam CDN download (no .NET required)" + Style.RESET_ALL)
            for depot_id in selected_depots:
                if _cancelled():
                    print_fn(Fore.YELLOW + "\n[cancelled] Stopping download" + Style.RESET_ALL)
                    return False, 0
                depot_id_str = str(depot_id)
                manifest_id = manifests.get(depot_id_str)
                key_data = depots.get(depot_id_str, {})
                key = key_data.get("key", "") if isinstance(key_data, dict) else ""
                if not manifest_id or not key:
                    print_fn(Fore.YELLOW + f"Depot {depot_id_str}: native needs manifest+key, will download with DDMod" + Style.RESET_ALL)
                    native_failed.append(depot_id)
                    continue
                print_fn(
                    Fore.CYAN
                    + f"\n--- Downloading depot {depot_id_str} (native) ---"
                    + Style.RESET_ALL
                )
                try:
                    manifest_path = None
                    mf = MANIFESTS_TMP / f"{depot_id_str}_{manifest_id}.manifest"
                    if mf.exists():
                        manifest_path = mf
                    _inc = _native_include_dirs(depot_id_str)
                    ok, size = _native_dl(
                        depot_owners.get(depot_id_str) or appid, depot_id_str, manifest_id, key, download_dir,
                        print_fn=print_fn, os_filter=target_os,
                        steam_path=steam_path,
                        manifest_path=manifest_path,
                        cancel_app_id=appid,
                        include_dirs=_inc,
                    )
                    if ok:
                        print_fn(Fore.GREEN + f"Depot {depot_id_str} downloaded ({size:,} bytes)" + Style.RESET_ALL)
                    else:
                        print_fn(Fore.YELLOW + f"Depot {depot_id_str}: native download failed, will download with DDMod" + Style.RESET_ALL)
                        native_failed.append(depot_id)
                except Exception as e:
                    print_fn(Fore.RED + f"Native download failed for depot {depot_id_str}: {e}" + Style.RESET_ALL)
                    native_failed.append(depot_id)
            if not native_failed:
                try:
                    KEYS_TMP.unlink(missing_ok=True)
                except Exception:
                    pass
                total_size = _calculate_dir_size(download_dir)
                print_fn(Fore.CYAN + f"Total size on disk: {total_size:,} bytes" + Style.RESET_ALL)
                return True, total_size
            print_fn(Fore.YELLOW + f"[Native] {len(native_failed)} depot(s) failed — using DepotDownloaderMod as backup" + Style.RESET_ALL)
        except ImportError:
            native_failed = list(selected_depots)
            print_fn(Fore.YELLOW + "[Native] Native downloader not available, falling back to DDMod" + Style.RESET_ALL)
        except Exception as e:
            native_failed = list(selected_depots)
            print_fn(Fore.YELLOW + f"[Native] Init failed ({e}), falling back to DDMod" + Style.RESET_ALL)
    ddmod_depots = list(native_failed) if native_failed else list(selected_depots)

    dotnet_path = get_dotnet_path()
    if not dotnet_path:
        print_fn(Fore.RED + ".NET 9 not available. Cannot download." + Style.RESET_ALL)
        return False, 0

    dll_path = get_ddmod_dll()
    if not dll_path.exists():
        print_fn(Fore.RED + f"DepotDownloaderMod.dll not found at {dll_path}" + Style.RESET_ALL)
        return False, 0

    try:
        lines = []
        for depot_id in selected_depots:
            key = depots.get(str(depot_id), {}).get("key", "")
            if key:
                lines.append(f"{depot_id};{key}")
        KEYS_TMP.write_text("\n".join(lines), encoding="utf-8")
    except Exception as e:
        print_fn(Fore.RED + f"Failed to write depot keys: {e}" + Style.RESET_ALL)
        return False, 0

    dotnet_root = os.path.dirname(dotnet_path)
    env = os.environ.copy()
    env["DOTNET_ROOT"] = dotnet_root
    current_path = env.get("PATH", "")
    if dotnet_root not in current_path.split(os.pathsep):
        env["PATH"] = dotnet_root + os.pathsep + current_path

    if sys.platform.startswith("linux"):
        _add_bundled_openssl_to_env(env, dotnet_root)

    download_dir = dest_path / "steamapps" / "common" / installdir
    download_dir.mkdir(parents=True, exist_ok=True)

    MANIFESTS_TMP.mkdir(parents=True, exist_ok=True)
    deps_dir = get_deps_dir()
    total_depots = len(ddmod_depots)
    all_ok = True

    for i, depot_id in enumerate(ddmod_depots):
        if _cancelled():
            print_fn(Fore.YELLOW + "\n[cancelled] Stopping download" + Style.RESET_ALL)
            return False, 0
        depot_id_str = str(depot_id)
        manifest_id = manifests.get(depot_id_str)
        owner = depot_owners.get(depot_id_str, appid)
        if not manifest_id and owner is None:
            # No pinned manifest and no app in the set owns this depot —
            # DDMod would abort (-6) on all retries. Fail fast instead.
            print_fn(
                Fore.RED
                + f"Depot {depot_id_str}: no manifest and no owning app found, skipping"
                + Style.RESET_ALL
            )
            all_ok = False
            continue
        owner = owner or appid

        try:
            from sff.core.storage.settings import get_setting
            from sff.core.structs import Settings
            val = get_setting(Settings.DOWNLOAD_CONCURRENCY)
            max_dl = str(min(max(int(val) if val else 32, 8), 64))
        except Exception:
            max_dl = "32"

        cmd = [
            dotnet_path, str(dll_path),
            "-app", str(owner),
            "-depot", depot_id_str,
            "-depotkeys", str(KEYS_TMP),
            "-max-downloads", max_dl,
            "-validate",
            "-dir", str(download_dir),
        ]
        if target_os != "all":
            cmd += ["-os", target_os]

        if manifest_id:
            manifest_file = MANIFESTS_TMP / f"{depot_id_str}_{manifest_id}.manifest"
            # Always pass -manifestfile so DDMod writes the manifest there if it
            # doesn't exist yet — this avoids the "No manifest request code" error
            # that occurs when DDMod tries to fetch the manifest from Steam CDN
            # anonymously without a valid session.
            cmd += ["-manifest", str(manifest_id), "-manifestfile", str(manifest_file)]

        # Selective file download for DDMod: -filelist wants concrete file
        # paths, so expand the folder selection through the decrypted
        # manifest. If the manifest isn't local yet, fall back to the whole
        # depot rather than silently skipping the selection.
        if file_filters.get(depot_id_str) and manifest_id:
            _kd = depots.get(depot_id_str, {})
            _key = _kd.get("key", "") if isinstance(_kd, dict) else ""
            _fl = _write_ddmod_filelist(
                depot_id_str, manifest_id, _key, file_filters[depot_id_str],
                steam_path=steam_path, print_fn=print_fn)
            if _fl:
                cmd += ["-filelist", str(_fl)]
            else:
                print_fn(
                    Fore.YELLOW
                    + f"Depot {depot_id_str}: file selection could not be "
                    "applied here - downloading the full depot."
                    + Style.RESET_ALL
                )

        print_fn(
            Fore.CYAN
            + f"\n--- Downloading depot {depot_id_str} ({i + 1}/{total_depots}) ---"
            + Style.RESET_ALL
        )

        creation_flags = 0
        if sys.platform == "win32" and hasattr(subprocess, "CREATE_NO_WINDOW"):
            creation_flags = subprocess.CREATE_NO_WINDOW

        max_retries = 2
        attempt = 0
        depot_ok = False
        # DDMod exits 0 even when it downloaded nothing (e.g. the manifest
        # was never fetched). Measure bytes on disk around this depot's
        # run so a 0-byte depot can't be reported as a success.
        _bytes_before = _calculate_dir_size(download_dir)

        while attempt <= max_retries and not depot_ok:
            attempt += 1
            if attempt > 1:
                time.sleep(3)
                print_fn(
                    Fore.YELLOW
                    + f"\n[retry] Depot {depot_id_str} attempt {attempt}/{max_retries + 1}"
                    + Style.RESET_ALL
                )
            try:
                popen_kwargs = {
                    "stdout": subprocess.PIPE,
                    "stderr": subprocess.STDOUT,
                    "text": False,
                    "env": env,
                    "cwd": str(deps_dir),
                }
                if creation_flags:
                    popen_kwargs["creationflags"] = creation_flags

                logger.debug("DDMod launch (depot %s): %s", depot_id_str, " ".join(cmd))
                proc = subprocess.Popen(cmd, **popen_kwargs)
                _timeout = None
                try:
                    from sff.core.storage.settings import get_setting
                    from sff.core.structs import Settings
                    val = get_setting(Settings.DEPOT_DOWNLOAD_TIMEOUT)
                    if val:
                        _timeout = float(val) * 60.0  # stored in minutes
                except Exception:
                    pass
                _read_process_output(proc, print_fn, depot_timeout=_timeout, cancel_check=_cancelled)
                if _cancelled():
                    return False, 0
                try:
                    proc.wait(timeout=30)
                except subprocess.TimeoutExpired:
                    print_fn(
                        Fore.RED + f"\n[timeout] Depot {depot_id_str} did not exit after output ended, killing"
                        + Style.RESET_ALL
                    )
                    proc.kill()
                    proc.wait()

                if proc.returncode != 0:
                    print_fn(
                        Fore.YELLOW
                        + f"Depot {depot_id_str} exited with code {proc.returncode}"
                        + Style.RESET_ALL
                    )
                    _hint = _DDMOD_EXIT_HINTS.get(proc.returncode)
                    if _hint:
                        print_fn(Fore.YELLOW + f"  {_hint}" + Style.RESET_ALL)
                    if attempt <= max_retries:
                        continue
                    all_ok = False
                else:
                    # Exit 0 means nothing when Steam won't serve manifests:
                    # DDMod prints "missing public subsection" and exits 0
                    # with zero bytes written (war story: app 3438850,
                    # depot 3438850, "downloaded successfully" after a 4s
                    # no-op). A depot running with no pinned manifest can't
                    # validate anything, so zero new bytes = delivered
                    # nothing. With a manifest, 0 new bytes is just -validate
                    # passing, which is a legitimate success.
                    _after = _calculate_dir_size(download_dir)
                    if _after == _bytes_before and not manifest_id:
                        print_fn(
                            Fore.YELLOW
                            + f"Depot {depot_id_str} exited cleanly but had no manifest "
                              "and wrote 0 new bytes — treating as failed."
                            + Style.RESET_ALL
                        )
                        logger.warning(
                            "DDMod depot %s (app %s): exit 0, no manifest, 0 new bytes — marking failed",
                            depot_id_str, appid,
                        )
                        if attempt <= max_retries:
                            continue
                        all_ok = False
                    else:
                        depot_ok = True
                        print_fn(
                            Fore.GREEN
                            + f"Depot {depot_id_str} downloaded successfully."
                            + Style.RESET_ALL
                        )

            except FileNotFoundError:
                print_fn(
                    Fore.RED
                    + f"ERROR: '{dotnet_path}' not found. Ensure .NET 9 is installed."
                    + Style.RESET_ALL
                )
                all_ok = False
                break
            except (OSError, subprocess.SubprocessError) as e:
                is_winsock = sys.platform == "win32" and isinstance(e, OSError) and getattr(e, "winerror", 0) == 10038
                if is_winsock and attempt <= max_retries:
                    creation_flags = 0
                    time.sleep(5)
                    print_fn(
                        Fore.YELLOW
                        + f"\n[retry] Windows socket handle reset for depot {depot_id_str}"
                        + Style.RESET_ALL
                    )
                    continue
                print_fn(Fore.RED + f"Error downloading depot {depot_id_str}: {e}" + Style.RESET_ALL)
                if attempt <= max_retries:
                    continue
                all_ok = False
                break

    try:
        KEYS_TMP.unlink(missing_ok=True)
    except Exception:
        pass

    size_on_disk = _calculate_dir_size(download_dir)
    print_fn(
        Fore.CYAN
        + f"Total size on disk: {size_on_disk:,} bytes"
        + Style.RESET_ALL
    )

    return all_ok, size_on_disk


def resolve_target_os(
    selected_depots: list,
    app_info: dict,
    os_name: str | None = None,
    print_fn=print,
) -> str:
    """Pick the effective OS for both depot selection and file filtering.

    Defaults to Windows; Linux is only targeted when explicitly requested.

    Linux games with no Linux depot run through Proton, which needs the
    Windows depots AND the Windows file filter — same fallback Steam
    applies. Only triggers when the selection has platform-specific depots
    at all (empty oslist = shared content). Returns the possibly-adjusted
    target; callers must pass the result to both filter_depots_by_os and
    run_download so the two layers agree.
    """
    target = (os_name or "windows").lower()
    if target != "linux" or not app_info:
        return target
    depots_section = app_info.get("depots", {}) if isinstance(app_info, dict) else {}
    oslists = []
    for d in selected_depots:
        meta = depots_section.get(str(d), {})
        if isinstance(meta, dict):
            ol = (meta.get("config", {}) or {}).get("oslist", "") or ""
            if ol:
                oslists.append(ol.lower())
    if oslists and not any("linux" in o for o in oslists):
        print_fn(
            Fore.CYAN
            + "No Linux depot available — downloading Windows depots (run via Proton)."
            + Style.RESET_ALL
        )
        return "windows"
    return target


def filter_depots_by_os(
    selected_depots: list,
    app_info: dict,
    print_fn=print,
    os_name: str | None = None,
) -> list:
    """Return selected_depots with depots outside the target OS removed.

    Keeps a depot if its oslist is empty/missing (shared content) or contains
    the target OS. Skips depots whose oslist is non-empty and lacks the target.
    Also skips Steam China depots (contain platform-specific bundles not needed
    on global Steam).  Falls back to the original list when app_info is unavailable.
    """
    if not app_info:
        return selected_depots
    target_os = (os_name or "windows").lower()
    if target_os == "all":
        target_os = ""  # falsy skips the oslist/name-tag filters below; Steam China still filtered
    depots_section = app_info.get("depots", {}) if isinstance(app_info, dict) else {}

    # Build set of Steam China depot IDs from depots-level and top-level steamchina sections
    steamchina_ids: set[str] = set()
    sc_section = depots_section.get("steamchina", {})
    if isinstance(sc_section, dict):
        steamchina_ids |= {str(k) for k in sc_section if str(k).isdigit()}
    top_sc = app_info.get("steamchina", {}) if isinstance(app_info, dict) else {}
    if isinstance(top_sc, dict):
        steamchina_ids |= {str(k) for k in top_sc if str(k).isdigit()}

    filtered = []
    for depot_id in selected_depots:
        depot_meta = depots_section.get(str(depot_id), {})
        oslist = ""
        category = ""
        realm = ""
        ostype = ""
        depot_name = ""
        if isinstance(depot_meta, dict):
            depot_name = depot_meta.get("name", "") or ""
            config = depot_meta.get("config", {})
            if isinstance(config, dict):
                oslist = config.get("oslist", "") or ""
                category = config.get("category", "") or ""
                realm = config.get("realm", "") or ""
                ostype = config.get("ostype", "") or ""
        if target_os and oslist and target_os not in oslist.lower():
            print_fn(
                Fore.YELLOW
                + f"Skipping depot {depot_id} (oslist={oslist!r}, not {target_os})"
                + Style.RESET_ALL
            )
            continue
        # Fallback: when oslist is empty, check depot name for [WINDOWS]/[LINUX]/[Mac OSX] tags
        if target_os and not oslist and depot_name:
            name_lo = depot_name.lower()
            plat_tags = {
                "windows": ["[windows]", "[win]"],
                "linux": ["[linux]", "[steamos]"],
                "macos": ["[mac osx]", "[macosx]", "[macos]", "[mac]"],
            }
            tags = plat_tags.get(target_os, [])
            other_tags = set()
            for k, v in plat_tags.items():
                if k != target_os:
                    other_tags.update(v)
            # If the name has tags for OTHER platforms but NOT our tag, skip
            has_other = any(t in name_lo for t in other_tags)
            has_ours = any(t in name_lo for t in tags)
            if has_other and not has_ours:
                print_fn(
                    Fore.YELLOW
                    + f"Skipping depot {depot_id} (name tag doesn't match {target_os}: {depot_name!r})"
                    + Style.RESET_ALL
                )
                continue
        sc_flag = (
            str(depot_id) in steamchina_ids
            or "steamchina" in category.lower()
            or "steamchina" in realm.lower()
            or "steamchina" in ostype.lower()
        )
        if not sc_flag and depot_name:
            name_lc = depot_name.lower()
            name_up = depot_name.upper()
            sc_flag = (
                "steamchina" in name_lc
                or name_up.endswith(" SC")
                or name_up.endswith("_SC")
                or any("\u4e00" <= c <= "\u9fff" for c in depot_name)
            )
        if sc_flag:
            print_fn(
                Fore.YELLOW
                + f"Skipping depot {depot_id} (Steam China: realm={realm!r} category={category!r} name={depot_name!r})"
                + Style.RESET_ALL
            )
            continue
        filtered.append(depot_id)
    return filtered


def move_manifests_to_depotcache(dest_path: Path, manifests_dict: dict, print_fn=print) -> None:
    depotcache = dest_path / "depotcache"
    depotcache.mkdir(parents=True, exist_ok=True)

    if MANIFESTS_TMP.exists():
        for depot_id, manifest_id in manifests_dict.items():
            manifest_filename = f"{depot_id}_{manifest_id}.manifest"
            src = MANIFESTS_TMP / manifest_filename
            dst = depotcache / manifest_filename
            if src.exists():
                try:
                    shutil.move(str(src), str(dst))
                except Exception:
                    try:
                        shutil.copy2(src, dst)
                    except Exception:
                        pass

        try:
            shutil.rmtree(MANIFESTS_TMP, ignore_errors=True)
        except Exception:
            pass

    staging = Path.cwd() / "manifests"
    if staging.exists():
        for f in staging.glob("*.manifest"):
            dst = depotcache / f.name
            if not dst.exists():
                try:
                    shutil.copy2(f, dst)
                except Exception:
                    pass

    print_fn(Fore.GREEN + f"Manifests placed in depotcache: {depotcache}" + Style.RESET_ALL)
