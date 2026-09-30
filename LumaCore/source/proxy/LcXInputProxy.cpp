// LumaCore — Steam client hook layer for SteaMidra.
// Copyright (c) 2025-2026 Midrag (https://github.com/Midrags).
// Distributed under the GNU General Public License v3 or later.
// See <https://www.gnu.org/licenses/> for the full license text.

// xinput1_4.dll HiJack Project — True Dynamic Wrapper (With Undocumented Ordinals)

#include <windows.h>
#include <cstring>
#include <string>
#include <cwchar>
#include <mutex>

// ── Exports (via xinput1_4.def) ──────────────────────────────────────

// ─── Real XInput Function Pointers ───────────────────────────────────
static HMODULE g_realXInput = nullptr;

typedef DWORD(WINAPI* XInputGetState_t)(DWORD, void*);
typedef DWORD(WINAPI* XInputSetState_t)(DWORD, void*);
typedef DWORD(WINAPI* XInputGetCapabilities_t)(DWORD, DWORD, void*);
typedef void (WINAPI* XInputEnable_t)(BOOL);
typedef DWORD(WINAPI* XInputGetAudioDeviceIds_t)(DWORD, LPWSTR, UINT*, LPWSTR, UINT*);
typedef DWORD(WINAPI* XInputGetBatteryInformation_t)(DWORD, BYTE, void*);
typedef DWORD(WINAPI* XInputGetKeystroke_t)(DWORD, DWORD, void*);

static XInputGetState_t         o_XInputGetState            = nullptr;
static XInputSetState_t         o_XInputSetState            = nullptr;
static XInputGetCapabilities_t  o_XInputGetCapabilities     = nullptr;
static XInputEnable_t           o_XInputEnable              = nullptr;
static XInputGetAudioDeviceIds_t o_XInputGetAudioDeviceIds  = nullptr;
static XInputGetBatteryInformation_t o_XInputGetBatteryInformation = nullptr;
static XInputGetKeystroke_t     o_XInputGetKeystroke        = nullptr;

// Undocumented ordinals
static FARPROC o_100 = nullptr;   // XInputGetStateEx
static FARPROC o_101 = nullptr;   // XInputWaitForGuideButton
static FARPROC o_102 = nullptr;   // XInputCancelGuideButtonWait
static FARPROC o_103 = nullptr;   // XInputPowerOffController
static FARPROC o_104 = nullptr;   // XInputGetBaseBusInformation
static FARPROC o_108 = nullptr;   // XInputGetAudioDeviceIdsEx

// ─── Core Initialisation — table-driven binding to real System32 XInput ──
static std::once_flag g_initOnce;

struct ExportSlot { FARPROC* target; const char* name; };

void LoadRealXInput()
{
    if (g_realXInput) return;

    char sysDir[MAX_PATH];
    GetSystemDirectoryA(sysDir, MAX_PATH);
    std::string realPath = std::string(sysDir) + "\\xinput1_4.dll";

    g_realXInput = LoadLibraryA(realPath.c_str());
    if (!g_realXInput) return;

    static ExportSlot kTable[] = {
        {(FARPROC*)&o_XInputGetState,            "XInputGetState"},
        {(FARPROC*)&o_XInputSetState,            "XInputSetState"},
        {(FARPROC*)&o_XInputGetCapabilities,     "XInputGetCapabilities"},
        {(FARPROC*)&o_XInputEnable,              "XInputEnable"},
        {(FARPROC*)&o_XInputGetAudioDeviceIds,   "XInputGetAudioDeviceIds"},
        {(FARPROC*)&o_XInputGetBatteryInformation,"XInputGetBatteryInformation"},
        {(FARPROC*)&o_XInputGetKeystroke,        "XInputGetKeystroke"},
        {&o_100,                                 (LPCSTR)100},
        {&o_101,                                 (LPCSTR)101},
        {&o_102,                                 (LPCSTR)102},
        {&o_103,                                 (LPCSTR)103},
        {&o_104,                                 (LPCSTR)104},
        {&o_108,                                 (LPCSTR)108},
    };
    for (auto& sl : kTable)
        *sl.target = GetProcAddress(g_realXInput, sl.name);
}

// Each exported function calls this once — thread-safe, zero-cost after init
void EnsureLoaded() { std::call_once(g_initOnce, LoadRealXInput); }

// ─── Native Exports ──────────────────────────────────────────────────
extern "C" {

// Standard Functions
DWORD WINAPI XInputGetState(DWORD dwUserIndex, void* pState)
{
    EnsureLoaded();
    return o_XInputGetState ? o_XInputGetState(dwUserIndex, pState) : ERROR_DEVICE_NOT_CONNECTED;
}

DWORD WINAPI XInputSetState(DWORD dwUserIndex, void* pVibration)
{
    EnsureLoaded();
    return o_XInputSetState ? o_XInputSetState(dwUserIndex, pVibration) : ERROR_DEVICE_NOT_CONNECTED;
}

DWORD WINAPI XInputGetCapabilities(DWORD dwUserIndex, DWORD dwFlags, void* pCapabilities)
{
    EnsureLoaded();
    return o_XInputGetCapabilities ? o_XInputGetCapabilities(dwUserIndex, dwFlags, pCapabilities) : ERROR_DEVICE_NOT_CONNECTED;
}

void WINAPI XInputEnable(BOOL enable)
{
    EnsureLoaded();
    if (o_XInputEnable) o_XInputEnable(enable);
}

DWORD WINAPI XInputGetAudioDeviceIds(DWORD dwUserIndex, LPWSTR pRenderDeviceId, UINT* pRenderCount, LPWSTR pCaptureDeviceId, UINT* pCaptureCount)
{
    EnsureLoaded();
    return o_XInputGetAudioDeviceIds ? o_XInputGetAudioDeviceIds(dwUserIndex, pRenderDeviceId, pRenderCount, pCaptureDeviceId, pCaptureCount) : ERROR_DEVICE_NOT_CONNECTED;
}

DWORD WINAPI XInputGetBatteryInformation(DWORD dwUserIndex, BYTE devType, void* pBatteryInformation)
{
    EnsureLoaded();
    return o_XInputGetBatteryInformation ? o_XInputGetBatteryInformation(dwUserIndex, devType, pBatteryInformation) : ERROR_DEVICE_NOT_CONNECTED;
}

DWORD WINAPI XInputGetKeystroke(DWORD dwUserIndex, DWORD dwReserved, void* pKeystroke)
{
    EnsureLoaded();
    return o_XInputGetKeystroke ? o_XInputGetKeystroke(dwUserIndex, dwReserved, pKeystroke) : ERROR_DEVICE_NOT_CONNECTED;
}

// Undocumented Ordinal Wrappers
DWORD WINAPI XInputOrdinal100(DWORD a1, void* a2)
{
    EnsureLoaded();
    return o_100 ? ((DWORD(WINAPI*)(DWORD, void*))o_100)(a1, a2) : ERROR_DEVICE_NOT_CONNECTED;
}

DWORD WINAPI XInputOrdinal101(DWORD a1, DWORD a2, void* a3)
{
    EnsureLoaded();
    return o_101 ? ((DWORD(WINAPI*)(DWORD, DWORD, void*))o_101)(a1, a2, a3) : ERROR_DEVICE_NOT_CONNECTED;
}

DWORD WINAPI XInputOrdinal102(DWORD a1)
{
    EnsureLoaded();
    return o_102 ? ((DWORD(WINAPI*)(DWORD))o_102)(a1) : ERROR_DEVICE_NOT_CONNECTED;
}

DWORD WINAPI XInputOrdinal103(DWORD a1)
{
    EnsureLoaded();
    return o_103 ? ((DWORD(WINAPI*)(DWORD))o_103)(a1) : ERROR_DEVICE_NOT_CONNECTED;
}

DWORD WINAPI XInputOrdinal104(DWORD a1, void* a2)
{
    EnsureLoaded();
    return o_104 ? ((DWORD(WINAPI*)(DWORD, void*))o_104)(a1, a2) : ERROR_DEVICE_NOT_CONNECTED;
}

DWORD WINAPI XInputOrdinal108(DWORD a1, void* a2, void* a3, void* a4, void* a5)
{
    EnsureLoaded();
    return o_108 ? ((DWORD(WINAPI*)(DWORD, void*, void*, void*, void*))o_108)(a1, a2, a3, a4, a5) : ERROR_DEVICE_NOT_CONNECTED;
}

} // extern "C"

// ─── LumaCore Injection ──────────────────────────────────────────────────────
// Bootstrap rules, ported from Aether's dwmapi -> xinput1_4 switch
// (michelegoku3/Aether commit 14a6359): 
//   * xinput1_4.dll is the only bootstrap Steam still loads from its own
//     directory after the beta changes; treat it as the primary gate.
//   * NEVER LoadLibrary inside DllMain: the loader lock is held during
//     DLL_PROCESS_ATTACH, so the core is loaded from a worker thread that
//     runs after DllMain returns.
//   * inject only when the host is steam.exe AND this proxy sits beside it,
//     so a copy dropped in a game folder forwards but never injects.
//   * LumaCore.dll is loaded by ABSOLUTE path (this proxy's directory), so a
//     working-directory change cannot break the load.
//   * failures are non-fatal: DllMain always returns TRUE, a missing
//     LumaCore.dll must never stop Steam from booting.
static DWORD WINAPI LoadCoreWorker(LPVOID parameter)
{
    const HMODULE self = static_cast<HMODULE>(parameter);

    wchar_t exePath[MAX_PATH] = {};
    wchar_t proxyPath[MAX_PATH] = {};
    const DWORD exeLen = GetModuleFileNameW(nullptr, exePath, MAX_PATH);
    const DWORD proxyLen = GetModuleFileNameW(self, proxyPath, MAX_PATH);
    if (!exeLen || exeLen >= MAX_PATH || !proxyLen || proxyLen >= MAX_PATH) {
        OutputDebugStringW(L"[LumaCore] xinput1_4: module path unavailable; injection skipped.\n");
        return 0;
    }

    const wchar_t* exeSlash = std::wcsrchr(exePath, L'\\');
    wchar_t* proxySlash = wcsrchr(proxyPath, L'\\');
    if (!exeSlash || !proxySlash || _wcsicmp(exeSlash + 1, L"steam.exe") != 0)
        return 0;   // forward normally, but never inject into a game or helper.

    const size_t exeDirLen = static_cast<size_t>(exeSlash - exePath);
    const size_t proxyDirLen = static_cast<size_t>(proxySlash - proxyPath);
    if (exeDirLen != proxyDirLen || _wcsnicmp(exePath, proxyPath, exeDirLen) != 0) {
        OutputDebugStringW(L"[LumaCore] xinput1_4 is not beside steam.exe; injection skipped.\n");
        return 0;
    }

    if (GetModuleHandleW(L"LumaCore.dll"))
        return 0;   // already loaded by the other proxy.

    std::wstring core(proxyPath, proxyDirLen);
    core += L"\\LumaCore.dll";
    if (!LoadLibraryW(core.c_str()))
        OutputDebugStringW(L"[LumaCore] xinput1_4 could not load LumaCore.dll from Steam root.\n");
    return 0;
}

BOOL APIENTRY DllMain(HMODULE hModule, DWORD dwReason, PVOID pvReserved)
{
    switch (dwReason)
    {
    case DLL_PROCESS_ATTACH:
        DisableThreadLibraryCalls(hModule);
        // Real XInput resolves lazily via EnsureLoaded() on the first export
        // call (already outside DllMain in normal operation). Only the
        // bootstrap worker starts here - no waits, no I/O, no LoadLibrary.
        {
            HANDLE thread = CreateThread(nullptr, 0, LoadCoreWorker, hModule, 0, nullptr);
            if (thread)
                CloseHandle(thread);
            else
                OutputDebugStringW(L"[LumaCore] xinput1_4 could not start the bootstrap thread.\n");
        }
        break;
    case DLL_THREAD_ATTACH:
    case DLL_THREAD_DETACH:
    case DLL_PROCESS_DETACH:
        break;
    }
    return TRUE;  // A missing LumaCore.dll must not break Steam's load.
}
