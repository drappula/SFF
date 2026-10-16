#!/usr/bin/env bash
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

# Download the latest SteaMidra release from GitHub and install it.
# Usage: bash install.sh [--pre]
#   --pre   install the newest beta/prerelease instead of the latest stable
set -euo pipefail

REPO="drappula/SFF"
API="https://api.github.com/repos/$REPO/releases/latest"

C_RED='\033[0;31m'; C_GREEN='\033[0;32m'; C_YELLOW='\033[1;33m'
C_CYAN='\033[0;36m'; C_BOLD='\033[1m'; C_OFF='\033[0m'
[ -t 1 ] || { C_RED=''; C_GREEN=''; C_YELLOW=''; C_CYAN=''; C_BOLD=''; C_OFF=''; }

info() { echo -e "${C_GREEN}[SteaMidra]${C_OFF} $1"; }
warn() { echo -e "${C_YELLOW}[SteaMidra]${C_OFF} $1"; }
fail() { echo -e "${C_RED}[SteaMidra]${C_OFF} $1" >&2; exit 1; }
step() { echo -e "${C_CYAN}${C_BOLD}==>${C_OFF} ${C_BOLD}$1${C_OFF}"; }

echo -e "${C_CYAN}${C_BOLD}"
echo "  ____  _             __  __ _     _           ";
echo " / ___|| |_ ___  __ _|  \/  (_) __| |_ __ __ _ ";
echo " \___ \| __/ _ \/ _\` | |\/| | |/ _\` | '__/ _\` |";
echo "  ___) | ||  __/ (_| | |  | | | (_| | | | (_| |";
echo " |____/ \__\___|\__,_|_|  |_|_|\__,_|_|  \__,_|";
echo -e "${C_OFF}"
echo -e "${C_GREEN}${C_BOLD}  install${C_OFF}"

PRE=0
for a in "$@"; do
    case "$a" in
        --pre|--prerelease|--beta) PRE=1;;
        -h|--help)
            echo "Usage: bash install.sh [--pre]"
            echo "  --pre   install the newest beta/prerelease instead of the latest stable"
            exit 0;;
        *) fail "Unknown option: $a (try --help)";;
    esac
done

have() { command -v "$1" &>/dev/null; }
fetch() { # fetch <url> <dest>
    if have curl; then curl -fsSL --connect-timeout 30 "$1" -o "$2"
    elif have wget; then wget -q --timeout=30 -O "$2" "$1"
    else fail "Need curl or wget to download the release."; fi
}

step "[1/3] Finding the latest release"
JSON="$(mktemp)"; trap 'rm -f "$JSON"' EXIT
TAG=""
if [ "$PRE" -eq 1 ]; then
    have python3 || fail "--pre needs python3 to scan the release list."
    LIST="$(mktemp)"; trap 'rm -f "$JSON" "$LIST"' EXIT
    fetch "${API%/latest}?per_page=20" "$LIST"
    TAG="$(python3 -c "
import json
for r in json.load(open('$LIST')):
    if r.get('draft'):
        continue
    json.dump(r, open('$JSON', 'w'))
    print(('prerelease ' if r.get('prerelease') else '') + r.get('tag_name', ''))
    break
" 2>/dev/null || true)"
    [ -s "$JSON" ] || fail "No published releases found at https://github.com/$REPO/releases"
else
    fetch "$API" "$JSON"
    TAG="$(python3 -c "import json;print(json.load(open('$JSON')).get('tag_name',''))" 2>/dev/null || true)"
fi
pick_asset() { # pick_asset <suffix-pattern>
    if have python3; then
        python3 -c "
import json,sys
data = json.load(open('$JSON'))
for a in data.get('assets', []):
    n = a.get('name','')
    if n.endswith('.zip') and 'linux' in n.lower():
        print(a['browser_download_url'] + '|' + n); break
" 2>/dev/null
    else
        grep -o '"browser_download_url": *"[^"]*"' "$JSON" | tr -d '"' \
            | awk '{print $3}' | grep -i 'linux.*\.zip$\|\.zip$' | head -1
    fi
}
ASSET="$(pick_asset || true)"
[ -n "${ASSET%%|*}" ] || fail "No Linux release asset found at https://github.com/$REPO/releases"

URL="${ASSET%%|*}"; NAME="${ASSET##*|}"
[ "$URL" = "$NAME" ] && NAME="$(basename "$URL")"
if [ -n "$TAG" ]; then
    if [[ "$TAG" == prerelease* ]]; then warn "Release $TAG: $NAME"; else info "Release $TAG: $NAME"; fi
else info "Release asset: $NAME"; fi

mb() { awk -v b="$1" 'BEGIN{printf "%.1f MB", b/1048576}'; }
bar() { # bar <pct> <label> — block progress bar, no newline
    local pct=$1 label=$2 width=30 fill=0 i s=""
    fill=$(( pct * width / 100 ))
    for (( i=0; i<fill; i++ )); do s+="█"; done
    for (( i=fill; i<width; i++ )); do s+="░"; done
    printf "\r  [%s] %3d%%  %s" "$s" "$pct" "$label"
}
dl_progress() { # dl_progress <url> <dest> — curl with MB/total block bar
    local url="$1" dest="$2" total=0 size=0 pct=0 pid
    total="$(curl -fsSLI --connect-timeout 30 "$url" \
        | grep -i '^content-length:' | tail -1 | tr -dc '0-9' || true)"
    [ -z "$total" ] && total=0
    curl -fsSL --connect-timeout 30 "$url" -o "$dest" &
    pid=$!
    while kill -0 "$pid" 2>/dev/null; do
        size="$(stat -c%s "$dest" 2>/dev/null || echo 0)"
        if [ "$total" -gt 0 ]; then
            pct=$(( size * 100 / total ))
            [ "$pct" -gt 100 ] && pct=100
            bar "$pct" "$(mb "$size") / $(mb "$total")"
        else
            printf "\r  %s downloaded..." "$(mb "$size")"
        fi
        sleep 0.2
    done
    wait "$pid" || fail "Download failed — check your connection and retry."
    size="$(stat -c%s "$dest" 2>/dev/null || echo 0)"
    if [ "$total" -gt 0 ]; then
        bar 100 "$(mb "$size") / $(mb "$total")"
    else
        printf "\r  %s downloaded..." "$(mb "$size")"
    fi
    echo
    [ -s "$dest" ] || fail "Download is empty — check your connection and retry."
}

step "[2/3] Downloading $NAME"
WORK="$(mktemp -d)"; trap 'rm -f "$JSON" ${LIST:-}; rm -rf "$WORK"' EXIT
dl_progress "$URL" "$WORK/$NAME"

step "[3/3] Installing"
unzip -q -o "$WORK/$NAME" -d "$WORK/pkg" 2>/dev/null \
    || fail "Need 'unzip' to extract the release (sudo apt install unzip)."
[ -f "$WORK/pkg/steamidra_install.sh" ] \
    || fail "Release zip has no steamidra_install.sh — see https://github.com/$REPO/releases"
# Mute the bundled installer's desktop notifications for this run.
NOBIN="$WORK/nobin"
mkdir -p "$NOBIN"
printf '#!/bin/sh\nexit 0\n' > "$NOBIN/notify-send"
chmod +x "$NOBIN/notify-send"
PATH="$NOBIN:$PATH" bash "$WORK/pkg/steamidra_install.sh" install

echo -e "${C_GREEN}${C_BOLD}Done.${C_OFF} Launch with ${C_BOLD}steamidra${C_OFF} or from your app menu."
