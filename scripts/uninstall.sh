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

# Fully remove SteaMidra and revert what it changed:
#   [1/3] optionally delete games it added (common folders + ACFs + entries)
#   [2/3] optionally remove SLSsteam injection
#   [3/3] remove the app, shortcuts, Steam-side entries (luas, ACFs left
#         over, marker, .desktop residue)
# Game saves outside steamapps/common and ~/.dotnet / system packages stay.
# Usage: bash uninstall.sh
set -uo pipefail

C_RED='\033[0;31m'; C_GREEN='\033[0;32m'; C_YELLOW='\033[1;33m'
C_CYAN='\033[0;36m'; C_BOLD='\033[1m'; C_OFF='\033[0m'
[ -t 1 ] || { C_RED=''; C_GREEN=''; C_YELLOW=''; C_CYAN=''; C_BOLD=''; C_OFF=''; }

info() { echo -e "${C_GREEN}[SteaMidra]${C_OFF} $1"; }
warn() { echo -e "${C_YELLOW}[SteaMidra]${C_OFF} $1"; }
step() { echo -e "${C_CYAN}${C_BOLD}==>${C_OFF} ${C_BOLD}$1${C_OFF}"; }
ask() { # ask <prompt> -> 0 on yes, 1 on no (default No)
    local ans
    read -r -p "$(echo -e "${C_YELLOW}$1 [y/N]: ${C_OFF}")" ans
    [[ "$ans" =~ ^[Yy]$ ]]
}

echo -e "${C_CYAN}${C_BOLD}"
echo "  ____  _             __  __ _     _           ";
echo " / ___|| |_ ___  __ _|  \/  (_) __| |_ __ __ _ ";
echo " \___ \| __/ _ \/ _\` | |\/| | |/ _\` | '__/ _\` |";
echo "  ___) | ||  __/ (_| | |  | | | (_| | | | (_| |";
echo " |____/ \__\___|\__,_|_|  |_|_|\__,_|_|  \__,_|";
echo -e "${C_OFF}"
echo -e "${C_RED}${C_BOLD}  uninstall${C_OFF}"

INSTALL_DIR="$HOME/.local/share/SteaMidra"
BIN_LINK="$HOME/.local/bin/steamidra"
DESKTOP_FILE="$HOME/.local/share/applications/steamidra.desktop"
ICON_FILE="$HOME/.local/share/icons/hicolor/256x256/apps/SteaMidra.png"
SLS_SHARE="$HOME/.local/share/SLSsteam"
SLS_CONF="$HOME/.config/SLSsteam"
SLS_SHARE_FLAT="$HOME/.var/app/com.valvesoftware.Steam/.local/share/SLSsteam"
SLS_CONF_FLAT="$HOME/.var/app/com.valvesoftware.Steam/.config/SLSsteam"

STEAM_ROOT=""
for c in "$HOME/.steam/steam" "$HOME/.local/share/Steam" \
         "$HOME/.var/app/com.valvesoftware.Steam/.local/share/Steam"; do
    if [ -d "$c/steamapps" ] || [ -d "$c/config" ]; then STEAM_ROOT="$c"; break; fi
done
[ -n "$STEAM_ROOT" ] && info "Steam found at $STEAM_ROOT" \
                    || warn "No Steam install found — Steam-side cleanup skipped."

saved_lua_ids() { # echo ids SteaMidra itself fetched (its own record), one per line
    local d f id
    for d in "$INSTALL_DIR/saved_lua" "./saved_lua"; do
        [ -d "$d" ] || continue
        for f in "$d"/*.lua; do
            [ -f "$f" ] || continue
            id="$(basename "$f" .lua)"
            [[ "$id" =~ ^[0-9]+$ ]] && echo "$id"
        done
    done
    if [ -n "${STEAMIDRA_DATA_DIR:-}" ] && [ -d "$STEAMIDRA_DATA_DIR/saved_lua" ]; then
        for f in "$STEAMIDRA_DATA_DIR"/saved_lua/*.lua; do
            [ -f "$f" ] || continue
            id="$(basename "$f" .lua)"
            [[ "$id" =~ ^[0-9]+$ ]] && echo "$id"
        done
    fi
}
collect_ids() { # echo app ids currently injected into Steam, one per line
    local id
    if [ -n "$STEAM_ROOT" ] && [ -d "$STEAM_ROOT/config/stplug-in" ]; then
        for f in "$STEAM_ROOT"/config/stplug-in/*.lua; do
            [ -f "$f" ] || continue
            id="$(basename "$f" .lua)"
            [[ "$id" =~ ^[0-9]+$ ]] && echo "$id"
        done
    fi
    for cfg in "$SLS_CONF/config.yaml" "$SLS_CONF_FLAT/config.yaml" \
               "${XDG_CONFIG_HOME:-$HOME/.config}/SLSsteam/config.yaml"; do
        [ -f "$cfg" ] || continue
        grep -oE '^[[:space:]]*-[[:space:]]*[0-9]+' "$cfg" 2>/dev/null \
            | grep -oE '[0-9]+' || true
    done
}
acf_installdir() { # acf_installdir <acf> -> installdir
    grep -m1 '"installdir"' "$1" 2>/dev/null | sed -E 's/.*"installdir"[[:space:]]*"([^"]+)".*/\1/'
}
acf_name() { # acf_name <acf> <fallback>
    local n
    n="$(grep -m1 '"name"' "$1" 2>/dev/null | sed -E 's/.*"name"[[:space:]]*"([^"]+)".*/\1/')"
    echo "${n:-$2}"
}
lib_roots() { # echo steam library roots (steam root first)
    echo "$STEAM_ROOT"
    local vdf="$STEAM_ROOT/steamapps/libraryfolders.vdf"
    [ -f "$vdf" ] || return 0
    grep -oE '"path"[[:space:]]*"[^"]+"' "$vdf" 2>/dev/null \
        | sed -E 's/.*"path"[[:space:]]*"([^"]+)".*/\1/' || true
}
find_acf() { # find_acf <appid> -> first matching acf path
    local root acf
    while IFS= read -r root; do
        [ -n "$root" ] || continue
        acf="$root/steamapps/appmanifest_$1.acf"
        if [ -f "$acf" ]; then echo "$acf"; return 0; fi
    done < <(lib_roots)
    return 1
}
safe_delete_dir() { # safe_delete_dir <dir> <steamapps-base>
    [ -n "$1" ] || return 1
    case "$1" in
        "/"|"$2"|"$2/common"|"$2/steamapps") return 1;;
    esac
    case "$1" in *"..") return 1;; *"/../"*|*"/..") return 1;; esac
    [[ "$1" == "$2/"* ]] || return 1
    rm -rf "$1"
}

# ── [1/3] games ──────────────────────────────────────────────────────────
step "[1/3] Games added through SteaMidra"
# Only entries SteaMidra itself fetched (saved_lua record) count as its games.
# SLSsteam AdditionalApps also holds the user's whole library via the
# migrate-existing-install import, so injected-only would nuke legit games.
INJECTED="$(collect_ids | sort -u || true)"
KNOWN="$(saved_lua_ids | sort -u || true)"
IDS=""
if [ -n "$KNOWN" ] && [ -n "$INJECTED" ]; then
    IDS="$(comm -12 <(echo "$INJECTED") <(echo "$KNOWN") || true)"
    n_other="$(comm -23 <(echo "$INJECTED") <(echo "$KNOWN") | wc -l)"
    [ "$n_other" -gt 0 ] && info "$n_other other librar$([ "$n_other" -eq 1 ] && echo "y entry" || echo "ies") left alone (not added through SteaMidra)."
fi
if [ -z "$IDS" ]; then
    info "No SteaMidra-added games found — nothing to delete here."
else
    echo "$IDS" | while read -r id; do
        acf="$(find_acf "$id" || true)"
        if [ -n "$acf" ]; then
            echo -e "${C_YELLOW}  - $id — $(acf_name "$acf" "$id") ($(acf_installdir "$acf"))${C_OFF}"
        else
            echo "  - $id (files already gone)"
        fi
    done
    if ask "Delete these games (folders + manifests + library entries)"; then
        while read -r id; do
            [ -n "$id" ] || continue
            acf="$(find_acf "$id" || true)"
            if [ -n "$acf" ]; then
                dir="$(acf_installdir "$acf")"
                base="$(dirname "$acf")"
                if [ -n "$dir" ] && [ -d "$base/common/$dir" ]; then
                    safe_delete_dir "$base/common/$dir" "$base" \
                        && info "Deleted $dir" || warn "Kept $dir (safety stop)"
                fi
                rm -f "$acf" && info "Removed appmanifest_$id.acf"
            fi
            rm -f "$STEAM_ROOT/config/stplug-in/$id.lua"
            rm -rf "$STEAM_ROOT/config/stplug-in/$id"
            rm -f "$STEAM_ROOT/config/$id.lua"
            for cfg in "$SLS_CONF/config.yaml" "$SLS_CONF_FLAT/config.yaml"; do
                [ -f "$cfg" ] || continue
                sed -i -E "/^[[:space:]]*-[[:space:]]*$id([[:space:]#]|$)/d" "$cfg" 2>/dev/null || true
            done
            for d in "$HOME/.local/share/applications" \
                     "$HOME/.var/app/com.valvesoftware.Steam/.local/share/applications"; do
                grep -rl "rungameid/$id" "$d" 2>/dev/null | while IFS= read -r df; do
                    rm -f "$df" && info "Removed shortcut $(basename "$df")"
                done || true
            done
            rm -f "$HOME/.local/share/icons/hicolor/256x256/apps/steam_icon_$id.png"
        done <<< "$IDS"
    else
        info "Games kept on disk."
    fi
fi

# ── [2/3] SLSsteam ───────────────────────────────────────────────────────
step "[2/3] SLSsteam injection"
if [ -d "$SLS_SHARE" ] || [ -d "$SLS_CONF" ] || [ -d "$SLS_SHARE_FLAT" ]; then
    if ask "Remove SLSsteam (injection .so files and config)"; then
        pkill -x steam 2>/dev/null || true
        rm -rf "$SLS_SHARE" "$SLS_CONF" "$SLS_SHARE_FLAT" "$SLS_CONF_FLAT"
        for sh in "$STEAM_ROOT/steam.sh" \
                  "$HOME/.var/app/com.valvesoftware.Steam/.local/share/Steam/steam.sh"; do
            [ -f "$sh" ] || continue
            grep -q "SLSsteam" "$sh" 2>/dev/null || continue
            sed -i '/SLSsteam/d; /LD_AUDIT/d' "$sh" 2>/dev/null || true
            info "Cleaned $(basename "$sh")"
        done
        if [ -f /usr/bin/steam-jupiter ] && grep -q "SLSsteam" /usr/bin/steam-jupiter 2>/dev/null; then
            if [ -f /usr/bin/steam-jupiter.bak ]; then
                sudo cp /usr/bin/steam-jupiter.bak /usr/bin/steam-jupiter \
                    && info "Restored steam-jupiter from backup" \
                    || warn "Could not restore steam-jupiter (sudo failed)"
            else
                warn "steam-jupiter has our patch but no .bak — edit it manually."
            fi
        fi
        info "SLSsteam removed."
    else
        info "SLSsteam kept."
    fi
else
    info "SLSsteam not installed — nothing to do."
fi

# ── [3/3] app + residue ──────────────────────────────────────────────────
step "[3/3] SteaMidra app and leftovers"
pkill -f "SteaMidra|Main_gui.py" 2>/dev/null || true
rm -rf "$INSTALL_DIR"
rm -f "$BIN_LINK" "$DESKTOP_FILE" "$ICON_FILE"
command -v update-desktop-database &>/dev/null && \
    update-desktop-database "$HOME/.local/share/applications" 2>/dev/null || true
if [ -n "$STEAM_ROOT" ]; then
    rm -f "$STEAM_ROOT/.steamidra_gl_cleaned"
fi
for rc in "$HOME/.bashrc" "$HOME/.zshrc"; do
    [ -f "$rc" ] || continue
    sed -i '/DOTNET_ROOT="$HOME\/.dotnet"/d; /PATH="$PATH:$HOME\/.dotnet"/d' "$rc" 2>/dev/null || true
done
if ask "Also delete SteaMidra user data (save backups, icon/fix caches)"; then
    rm -rf "$HOME/.local/share/SteaMidra"
    info "User data deleted."
else
    info "User data kept."
fi

echo -e "${C_GREEN}${C_BOLD}Done.${C_OFF}"
