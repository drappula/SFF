// LumaCore - Steam client hook layer for SteaMidra.
// Copyright (c) 2025-2026 Midrag (https://github.com/Midrags).
// Distributed under the GNU General Public License v3 or later.
// See <https://www.gnu.org/licenses/> for the full license text.

#include "core/entry.h"
#include "core/Orchestrator.h"
#include "hooks/capture/RuntimeCapture.h"
#include "hooks/client/PackagePatch.h"
#include "hooks/client/IpcMethodLoader.h"
#include "hooks/client/IpcDispatch.h"
#include "hooks/client/IpcHooks.h"
#include "hooks/client/DenuvoAuthenticator.h"
#include "patterns/PatternFetcher.h"
#include "runtime/DirWatch.h"
#include "runtime/Diagnostics.h"
#include "runtime/HookStatus.h"
#include "runtime/IpcSpecLoader.h"
#include "runtime/BootDiag.h"
#include "runtime/LibraryInjector.h"

#include <atomic>
#include <mutex>
#include <string.h>
#include <string>
#include <string_view>// ═══════════════════════════════════════════════════════════════════════
//  CoreInit — module SHA tracking + bootstrap pipeline
// ═══════════════════════════════════════════════════════════════════════

namespace CoreInit {

    // Latest-known cache-key SHA per module. HookStatus::SetShas takes the pair
    // at once, but the steamclient and steamui legs of the pattern fetch can
    // finish independently (the steamclient leg lands inline in Bootstrap::Run,
    // the steamui leg defers to LoadModuleWithPath when steamui.dll is not yet
    // mapped at bootstrap time). The helper threads each leg's update through
    // SetShas with the most recent pair so the on-disk Status File never
    // regresses an already-known SHA when only one module has just refreshed.
    struct ModuleShas {
        std::mutex  mtx;
        std::string clientSha;
        std::string uiSha;

        void Publish(std::string_view moduleName, std::string sha) {
            std::lock_guard<std::mutex> lk(mtx);
            if (moduleName == "steamclient") {
                clientSha = std::move(sha);
            } else if (moduleName == "steamui") {
                uiSha = std::move(sha);
            }
            HookStatus::SetShas(clientSha, uiSha);
        }
    };

    ModuleShas g_shas;

    // Set when the steamui leg has been resolved (either inline in Bootstrap::Run
    // when steamui.dll was already mapped, or via LoadModuleWithPath when
    // Steam's loader maps it later). Prevents the deferred-dispatch handler
    // in SteamUI::LoadModuleWithPath from running the fetch twice.
    std::atomic<bool> g_steamUiPatternDispatched{false};
    std::atomic<bool> g_steamUiRetryStarted{false};

    // ── Patterns ─────────────────────────────────────────────────────
    namespace Patterns {

        void TrySteamUiLateInstall(const char* reason) {
            HMODULE ui = GetModuleHandleA("steamui.dll");
            if (!ui) {
                HookStatus::RecordSteamUiLateRetry(
                    std::string(reason ? reason : "late") + ":waiting-module");
                return;
            }

            PatternFetcher::PatternResult r{};
            bool expected = false;
            if (g_steamUiPatternDispatched.compare_exchange_strong(expected, true)) {
                r = PatternFetcher::LoadFor(ui, "steamui");
            } else {
                r = PatternFetcher::Get(ui);
                if (r.sha.empty() || (!r.ok && (r.source.empty() || r.source == "none")))
                    r = PatternFetcher::LoadFor(ui, "steamui");
            }

            LOG_COREIN_INFO("\"stage\" \"Patterns\" \"module\" \"steamui\" \"deferred\" 1 \"sha\" \"{}\" \"entries\" {} \"ok\" {}",
                       r.sha.empty() ? "<unknown>" : r.sha,
                       static_cast<unsigned>(r.entries.size()),
                       r.ok ? 1 : 0);
            g_shas.Publish("steamui", r.sha);
            HookStatus::SetTomlAvailability("steamui", r.ok);
            HookStatus::RecordSteamUiLateRetry(
                std::string(reason ? reason : "late") + (r.ok ? ":toml-ok" : ":toml-missing"));
            if (r.ok) SteamUI::CoreHook();
        }

        void StartSteamUiLateRetryLoop() {
            bool expected = false;
            if (!g_steamUiRetryStarted.compare_exchange_strong(expected, true))
                return;
            HANDLE h = CreateThread(nullptr, 0, [](LPVOID) -> DWORD {
                for (int i = 0; i < 60; ++i) {
                    if (GetModuleHandleA("steamui.dll")) {
                        TrySteamUiLateInstall("bootstrap-late-retry");
                        return 0;
                    }
                    HookStatus::RecordSteamUiLateRetry("bootstrap-late-retry:waiting-module");
                    Sleep(500);
                }
                HookStatus::SetSteamUiAttachState("steamui-not-loaded-after-retry", 60, false);
                HookStatus::RecordSteamUiLateRetry("bootstrap-late-retry:timeout");
                return 0;
            }, nullptr, 0, nullptr);
            if (h) CloseHandle(h);
        }

        // Fetches the steamui.dll TOML once SteamUI is mapped. Older code
        // passed nullptr into LoadFor here, so the deferred leg returned
        // before doing anything. Keep this tiny and let TrySteamUiLateInstall
        // own the real module lookup.
        void FetchSteamUIDeferred() {
            TrySteamUiLateInstall("loadmodulewithpath");
        }

    } // namespace Patterns

    // -- Steam client module -------------------------------------------------
    namespace Diversion {

        // Load the original Steam DLL by its absolute path and make it the
        // sole hook target. Do not copy it, rename it, or redirect SteamUI to
        // a second image: Steam and LumaCore must share this exact HMODULE.
        bool PrepareAndLoad()
        {
            HMODULE hSelf = nullptr;
            GetModuleHandleExA(
                GET_MODULE_HANDLE_EX_FLAG_FROM_ADDRESS |
                GET_MODULE_HANDLE_EX_FLAG_UNCHANGED_REFCOUNT,
                reinterpret_cast<LPCSTR>(&PrepareAndLoad), &hSelf);
            if (!GetModuleFileNameA(hSelf, SteamInstallPath, MAX_PATH))
                return false;
            char* lastSlash = strrchr(SteamInstallPath, '\\');
            if (lastSlash) *lastSlash = '\0';

            sprintf_s(SteamclientPath, MAX_PATH, "%s\\steamclient64.dll", SteamInstallPath);
            // Retained for diagnostics only; it names the original DLL, never
            // a copied or diverted file.
            strcpy_s(DiversionPath, MAX_PATH, SteamclientPath);
            sprintf_s(LuaDir, MAX_PATH, "%s\\config\\stplug-in", SteamInstallPath);
            sprintf_s(ConfigPath, MAX_PATH, "%s\\lumacore.toml", SteamInstallPath);
            sprintf_s(PayloadPath, MAX_PATH, "%s\\LumaCorePayload.dll", SteamInstallPath);

            diversion_hModule = LoadLibraryA(SteamclientPath);
            if (!diversion_hModule) {
                const DWORD err = GetLastError();
                LOG_COREIN_ERROR("\"stage\" \"Steamclient\" \"err\" \"load-original-failed\" \"path\" \"{}\" winerr={}",
                                 SteamclientPath, err);
                HookStatus::SetDiversionState(false, "load-original-failed");
                return false;
            }

            // ── Module-identity assertion ───────────────────────────
            // Ported from Aether's Diversion::LiveSteamclientMapped().
            // A successful LoadLibraryA is NOT proof that we hooked the
            // module Steam actually uses: a same-named DLL mapped from
            // another directory (or a stale copied image) would take the
            // hooks and never be called. Compare the mapped module's own
            // path against the Steam-root path we asked for, and publish
            // the verdict so status.json can settle the question alone.
            char modulePath[MAX_PATH] = {};
            const DWORD modulePathLen =
                GetModuleFileNameA(diversion_hModule, modulePath, MAX_PATH);
            const bool modulePathOk =
                modulePathLen > 0 && modulePathLen < MAX_PATH;
            const char* modulePathOut = modulePathOk ? modulePath : "<unresolved>";
            const bool pathMatches =
                modulePathOk && _stricmp(modulePath, SteamclientPath) == 0;

            HookStatus::SetDiversionState(
                true, pathMatches ? "original-live-module" : "module-path-mismatch");
            HookStatus::SetLoaderState(
                "lumacore",
                pathMatches ? "steamclient64-direct" : "steamclient64-MISMATCH",
                modulePathOut);

            // Publish the resolved paths so status.json names the exact image
            // the hooks were installed on. Re-issued in Bootstrap::Run once
            // the pattern legs have supplied the on-disk SHAs.
            if (!GetModuleFileNameA(nullptr, SteamExePath, MAX_PATH))
                SteamExePath[0] = '\0';
            sprintf_s(SteamUiPath, MAX_PATH, "%s\\steamui.dll", SteamInstallPath);
            HookStatus::SetBinarySnapshot(SteamExePath, SteamclientPath, SteamUiPath,
                                          DiversionPath, {}, {}, {});

            LOG_COREIN_INFO("\"stage\" \"Steamclient\" \"act\" \"original-loaded-direct\" \"path\" \"{}\" \"module\" 0x{:X} \"identity\" \"{}\"",
                            SteamclientPath, reinterpret_cast<uintptr_t>(diversion_hModule),
                            pathMatches ? "match" : "mismatch");
            if (!pathMatches) {
                LOG_COREIN_ERROR("\"stage\" \"Steamclient\" \"err\" \"module-path-mismatch\" \"asked\" \"{}\" \"mapped\" \"{}\"",
                                 SteamclientPath, modulePathOut);
            }
            return true;
        }

    } // namespace Diversion

    // ── BuildId ──────────────────────────────────────────────────────
    namespace BuildId {

        // Reads the current Steam build number from steam.exe.
        void Detect() {
            using GetBootstrapperVersion_t = int64_t (*)();
            HMODULE hSteam = GetModuleHandleA("steam.exe");
            if (!hSteam) {
                LOG_COREIN_WARN("\"stage\" \"BuildId\" \"err\" \"steam-not-loaded\"");
                return;
            }
            auto fn = reinterpret_cast<GetBootstrapperVersion_t>(
                GetProcAddress(hSteam, "GetBootstrapperVersion"));
            if (!fn) {
                LOG_COREIN_WARN("\"stage\" \"BuildId\" \"err\" \"no-export\"");
                return;
            }
            g_steamBuildId = std::to_string(fn());
            LOG_COREIN_INFO("\"stage\" \"BuildId\" \"value\" \"{}\"", g_steamBuildId);
        }

    } // namespace BuildId

    // ── Bootstrap ────────────────────────────────────────────────────
    namespace Bootstrap {

        // Worker thread that runs all real startup work outside of DllMain.
        // Windows holds the loader lock during DllMain, which means calling LoadLibrary, doing
        // file I/O, or installing Detours hooks from DllMain risks a deadlock. Spinning up a
        // separate thread lets us do all of that safely once the loader lock is released.
        DWORD Run(HMODULE selfModule)
        {
            Logger::Init(selfModule);

            // Compute SteamInstallPath and ConfigPath early
            if (GetModuleFileNameA(selfModule, SteamInstallPath, MAX_PATH)) {
                char* ls = strrchr(SteamInstallPath, '\\');
                if (ls) *ls = '\0';
            }
            sprintf_s(ConfigPath, MAX_PATH, "%s\\lumacore.toml", SteamInstallPath);

            // Load config and init ALL module loggers before any LOG_COREIN_* call
            Settings::Load(ConfigPath);
            Logger::InitModules();

            LOG_COREIN_INFO("\"stage\" \"Bootstrap\" \"act\" \"start\" \"build\" \"{} {}\"", __DATE__, __TIME__);
            HookStatus::SetStartupPhase("start");

            // Build id first so HookStatus has a value to surface even if
            // loading Steam's original steamclient64.dll fails.
            BuildId::Detect();
            HookStatus::SetBuildId(g_steamBuildId);

            if (!Diversion::PrepareAndLoad()) {
                LOG_COREIN_ERROR("\"stage\" \"Bootstrap\" \"err\" \"diversion-fail\"");
                HookStatus::SetTomlAvailability("steamclient", false);
                HookStatus::SetTomlAvailability("steamui", false);
                HookStatus::WriteToDisk();
                return 1;
            }


            // ── Steamclient leg: synchronous cache + network ─────────
            PatternFetcher::PatternResult pcResult =
                PatternFetcher::LoadFor(diversion_hModule, "steamclient");
            LOG_COREIN_INFO("\"stage\" \"Patterns\" \"module\" \"steamclient\" \"sha\" \"{}\" \"entries\" {} \"ok\" {}",
                       pcResult.sha.empty() ? "<unknown>" : pcResult.sha,
                       static_cast<unsigned>(pcResult.entries.size()),
                       pcResult.ok ? 1 : 0);

            // Install the critical steamclient hooks immediately after their
            // pattern table is ready; do this before SteamUI hook-up.
            HookStatus::SetStartupPhase("installing_critical_hooks");
            PackagePatch::Install();
            SteamCapture::Install();

            // ── Steamui leg ──────────────────────────────────────────
            PatternFetcher::PatternResult puResult{};
            bool steamUiMapped = (GetModuleHandleA("steamui.dll") != nullptr);
            if (steamUiMapped) {
                bool expected = false;
                if (g_steamUiPatternDispatched.compare_exchange_strong(expected, true)) {
                    puResult = PatternFetcher::LoadFor(
                        GetModuleHandleA("steamui.dll"), "steamui");
                    LOG_COREIN_INFO("\"stage\" \"Patterns\" \"module\" \"steamui\" \"sha\" \"{}\" \"entries\" {} \"ok\" {}",
                               puResult.sha.empty() ? "<unknown>" : puResult.sha,
                               static_cast<unsigned>(puResult.entries.size()),
                               puResult.ok ? 1 : 0);
                }
            } else {
                LOG_COREIN_INFO("\"stage\" \"Patterns\" \"module\" \"steamui\" \"act\" \"deferred\"");
                Patterns::StartSteamUiLateRetryLoop();
            }

            // ── IPC method spec loader ───────────────────────────────
            IpcSpecLoader::Load();

            // ── IPC method metadata (ipc_methods.toml) ─────────────
            IpcLoader::Load(SteamclientPath);

            // ── Diagnostics capture ──────────────────────────────────
            BootDiag::Capture();
            if (!IpcSpecLoader::IsLoaded() && !IpcLoader::IsLoaded())
                BootDiag::ReportMissing();

            // SHAs first, then per-module availability.
            {
                std::lock_guard<std::mutex> lk(g_shas.mtx);
                g_shas.clientSha = pcResult.sha;
                g_shas.uiSha     = puResult.sha;
            }
            HookStatus::SetShas(pcResult.sha, puResult.sha);
            // Re-publish the binary snapshot now that both pattern legs have
            // supplied the on-disk SHAs of the modules we are keyed to. Paths
            // plus SHAs make status.json self-proving: it names the exact
            // file Steam is running and the file LumaCore hooked. In direct
            // mode the "diversion" IS the original DLL, so its file SHA is by
            // definition the steamclient SHA.
            HookStatus::SetBinarySnapshot(SteamExePath, SteamclientPath, SteamUiPath,
                                          DiversionPath, pcResult.sha, puResult.sha,
                                          pcResult.sha);
            HookStatus::SetTomlAvailability("steamclient", pcResult.ok);
            HookStatus::SetTomlAvailability("steamui",     puResult.ok);
            HookStatus::SetStartupPhase("patterns_loaded");
            HookStatus::WriteToDisk();

            // steamclient patterns and hooks always target the original DLL
            // loaded directly from SteamclientPath; no copy/redirect fallback.

            // ── SteamUI hooks are retained for library UI refreshes; they no longer redirect steamclient ──
            HookStatus::SetStartupPhase("installing_hooks");
            SteamUI::CoreHook();

            std::vector<std::string> watchDirs = Settings::luaPaths;
            watchDirs.push_back(std::string(LuaDir));
            for (const auto& dir : watchDirs)
                LuaLoader::ParseDirectory(dir);

            SteamCapture::TryStartupPackageInjection("lua-loaded");

            DirWatch::Start(watchDirs);

            // ── IPC dispatch layer (ticket spoofing handlers) ──────
            IpcHooks::Install();

            // ── Denuvo authorization state machine ──────────────────
            DenuvoAuth::Init();

            LumaCore::Attach();
            g_HooksInstalled.store(true);
            HookStatus::SetStartupPhase("hooks_complete");
            HookStatus::WriteToDisk();
            LOG_COREIN_INFO("\"stage\" \"Bootstrap\" \"act\" \"complete\"");
            return 0;
        }

    } // namespace Bootstrap

} // namespace CoreInit

// ═══════════════════════════════════════════════════════════════════════
//  DllMain
// ═══════════════════════════════════════════════════════════════════════

BOOL APIENTRY DllMain(HMODULE hModule, DWORD dwReason, PVOID pvReserved)
{
    if (dwReason == DLL_PROCESS_ATTACH)
    {
        DisableThreadLibraryCalls(hModule);
        // Pin the module so a stray FreeLibrary cannot unmap LumaCore while
        // hooks and worker threads are still live. Failure is non-fatal; we
        // just lose the unmap protection and continue attach.
        HMODULE selfPin = nullptr;
        if (!GetModuleHandleExA(
                GET_MODULE_HANDLE_EX_FLAG_PIN | GET_MODULE_HANDLE_EX_FLAG_FROM_ADDRESS,
                reinterpret_cast<LPCSTR>(&DllMain), &selfPin)) {
            LOG_COREIN_WARN("\"stage\" \"DllMain\" \"err\" \"pin-fail\" err={}", GetLastError());
        }
        // Start Bootstrap::Run on a worker thread to do all real work
        // outside the loader lock.
        // DllMain must return quickly and must not call LoadLibrary, open files,
        // or install hooks - doing so under the loader lock causes deadlocks.
        g_InitThread = CreateThread(nullptr, 0, [](LPVOID param) -> DWORD {
            return CoreInit::Bootstrap::Run(static_cast<HMODULE>(param));
        }, hModule, 0, nullptr);
    }
    else if (dwReason == DLL_PROCESS_DETACH)
    {
#ifdef LUMACORE_DIAGNOSTICS_ENABLED
        // A16 belt-and-suspenders: flush the achievement diagnostic ring
        // first thing on DLL detach so a crash inside CoreLoader::Detach
        // never loses the captured events. Defensive write-and-return.
        Diagnostics::DumpForDetach();
#endif
        if (g_InitThread) {
            WaitForSingleObject(g_InitThread, 5000);
            CloseHandle(g_InitThread);
            g_InitThread = nullptr;
        }
        if (g_HooksInstalled.load()) {
            DirWatch::Stop();
            if (pvReserved == nullptr) {
                SteamUI::CoreUnhook();
                LumaCore::Detach();
            }
        }
    }

    return TRUE;
}

void DispatchSteamUiPatternFetch() {
    static std::once_flag s_once;
    std::call_once(s_once, [] {
        HANDLE h = CreateThread(nullptr, 0, [](LPVOID) -> DWORD {
            CoreInit::Patterns::FetchSteamUIDeferred();
            return 0;
        }, nullptr, 0, nullptr);
        if (h) CloseHandle(h);
    });
}
