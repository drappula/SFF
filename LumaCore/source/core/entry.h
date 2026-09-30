// LumaCore — Steam client hook layer for SteaMidra.
// Copyright (c) 2025-2026 Midrag (https://github.com/Midrags).
// Distributed under the GNU General Public License v3 or later.
// See <https://www.gnu.org/licenses/> for the full license text.

#ifndef ENTRY_H
#define ENTRY_H

#include <windows.h>
#include <string>
#include <fstream>
#include <filesystem>
#include <array>
#include <vector>
#include <unordered_set>
#include <unordered_map>
#include <memory>
#include <atomic>
#include <format>

#include "Steam/Types.h"
#include "Steam/Enums.h"
#include "Steam/Structs.h"
#include "Steam/Callback.h"
#include "config/LuaLoader.h"
#include "runtime/Logger.h"
#include "config/Settings.h"


// The only steamclient hook target: Steam's original root DLL. LumaCore no
// longer creates or loads a diverted copy. Null until the original module has
// been loaded from SteamclientPath.
inline HMODULE diversion_hModule = nullptr;

// InitThread handle retained so DLL_PROCESS_DETACH can wait for init to finish
// before unhooking. Closed after the wait completes.
inline HANDLE g_InitThread = nullptr;

// Set to true by InitThread after every hook has been installed.
// Consumed by DLL_PROCESS_DETACH to decide whether it is safe to unhook.
// It is deliberately NOT used as a gate inside SteamUI's LoadModuleWithPath
// hook: that wait only ever protected the removed diversion redirect.
inline std::atomic<bool> g_HooksInstalled{false};

// Runtime paths filled in by PrepareAndLoad() from LumaCore's Steam-root path.
inline char SteamInstallPath[MAX_PATH] = {};  // Steam root: the folder containing steam.exe
inline char SteamExePath[MAX_PATH]     = {};  // Full path of the running executable (diagnostics)
inline char SteamclientPath[MAX_PATH] = {};  // <SteamInstallPath>\steamclient64.dll
inline char SteamUiPath[MAX_PATH]     = {};  // <SteamInstallPath>\steamui.dll (diagnostics)
inline char DiversionPath[MAX_PATH]   = {};  // Diagnostics alias for the original Steam DLL
inline char LuaDir[MAX_PATH]          = {};  // <SteamInstallPath>\config\stplug-in
inline char ConfigPath[MAX_PATH]      = {};  // <SteamInstallPath>\lumacore.toml
inline char PayloadPath[MAX_PATH]    = {};  // <SteamInstallPath>\LumaCorePayload.dll

// Steam build number read at startup from steam.exe!GetBootstrapperVersion.
// ByteSearch uses this string to select the best-matching Signature entry in PatternDb.h
// before falling back to trying every other entry in order.
// Stays empty if steam.exe is not loaded or does not export GetBootstrapperVersion.
inline std::string g_steamBuildId;

// The fake AppId substituted when -onlinefix is active (Valve's SpaceWar lobby app).
constexpr AppId_t kOnlineFixAppId = 480;


// Dispatches the PatternFetcher worker for steamui.dll on a detached thread.
// Defined in entry.cpp. Idempotent: subsequent calls after the first are no-ops.
// Called from InitThread when steamui.dll is already mapped, and from the
// SteamUI::LoadModuleWithPath hook when Steam's loader maps it later.
void DispatchSteamUiPatternFetch();

#endif // ENTRY_H
