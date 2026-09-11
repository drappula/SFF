#!/usr/bin/env python3
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
"""Fetch the store_metadata seed files into the repo checkout.

The app refreshes these at runtime, but packaged builds bundle the folder
as an offline seed so a first launch without internet still resolves game
names. CI runs this before the build steps; the files are gitignored.
Stdlib only, best effort: a failed file is a warning, not a build break.
"""
import json
import sys
import urllib.request
from pathlib import Path

# Same URLs as sff/game_list_fallback.py; kept literal so this script
# never imports the app package.
FILES = {
    "games.json": [
        "https://raw.githubusercontent.com/SteamTools-Team/GameList/refs/heads/main/games.json",
    ],
    "games_appid.json": [
        "https://raw.githubusercontent.com/jsnli/steamappidlist/refs/heads/master/data/games_appid.json",
    ],
    "software_appid.json": [
        "https://raw.githubusercontent.com/jsnli/steamappidlist/refs/heads/master/data/software_appid.json",
    ],
    "dlc_appid.json": [
        "https://cdn.jsdelivr.net/gh/jsnli/steamappidlist@master/data/dlc_appid.json",
    ],
}


def main() -> int:
    out_dir = Path(sys.argv[1]) if len(sys.argv) > 1 else Path(__file__).resolve().parent.parent / "store_metadata"
    out_dir.mkdir(parents=True, exist_ok=True)
    failed = []
    for name, urls in FILES.items():
        dest = out_dir / name
        if dest.exists() and dest.stat().st_size > 0:
            print(f"{name}: already present ({dest.stat().st_size} bytes), keeping")
            continue
        for url in urls:
            try:
                req = urllib.request.Request(url, headers={"User-Agent": "SteaMidra/6.6"})
                with urllib.request.urlopen(req, timeout=60) as resp:
                    data = resp.read()
                json.loads(data)  # reject HTML error pages saved as .json
                tmp = dest.with_suffix(".tmp")
                tmp.write_bytes(data)
                tmp.replace(dest)
                print(f"{name}: {len(data)} bytes")
                break
            except Exception as e:
                print(f"{name}: {url} failed ({e})", file=sys.stderr)
        else:
            failed.append(name)
    if failed:
        print(f"WARNING: no seed for {', '.join(failed)}; builds ship without them", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
