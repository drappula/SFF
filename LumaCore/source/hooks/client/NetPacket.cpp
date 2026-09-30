// LumaCore - Steam client hook layer for SteaMidra.
// Copyright (c) 2025-2026 Midrag (https://github.com/Midrags).
// Distributed under the GNU General Public License v3 or later.
// See <https://www.gnu.org/licenses/> for the full license text.

#include "hooks/client/NetPacket.h"
#include "Steam/NetPacketLayout.h"
#include "hooks/client/NetPacket_AccessToken.h"
#include "hooks/client/NetPacket_UserStats.h"
#include "hooks/client/NetPacket_ETicket.h"
#include "hooks/client/NetPacket_Manifest.h"
#include "hooks/client/NetPacket_FamilySharing.h"
#include "hooks/client/NetPacket_OnlineFix.h"
#include "hooks/client/NetPacket_SteamStub.h"
#include "hooks/client/RichPresence.h"
#include "hooks/client/PacketRouter.h"
#include "runtime/Logger.h"
#include "config/LuaLoader.h"
#include "runtime/Ticket.h"
#include "runtime/ManifestFetch.h"
#include "hooks/capture/SteamCapture.h"
#include "runtime/LcFnvHash.h"
#include "hooks/Macros.h"

#include <algorithm>
#include <cstdint>
#include <unordered_map>
#include <mutex>

// ── Packet pool instances ──────────────────────────────────────────
namespace NetPacket {
    PacketPool<true>  s_rx;
    PacketPool<false> s_tx;
}

// ── Packet layout ───────────────────────────
static bool ParsePacket(const uint8_t* data, uint32_t size,
                        EMsg& eMsg, const uint8_t*& pHdr, uint32_t& cbHdr,
                        const uint8_t*& pBody, uint32_t& cbBody) {
    eMsg = static_cast<EMsg>(0);
    cbHdr = 0;
    pHdr = nullptr;
    pBody = nullptr;
    cbBody = 0;
    // Steam beta may use a non-null "no data" sentinel in m_pubData. Treat
    // every non-canonical/unreadable value as absent before dereferencing it.
    // Bound the span too: a plausible pointer plus a corrupt size must not
    // make protobuf parsing walk arbitrary memory.
    constexpr uint32_t kMaxReadablePacket = 64u * 1024u * 1024u;
    const uintptr_t addr = reinterpret_cast<uintptr_t>(data);
    if (!data || addr < 0x10000ull || addr >= 0x7FFFFFFF0000ull ||
        size < sizeof(MsgHdr) || size > kMaxReadablePacket ||
        !NetPkt::IsReadable(data, size))
        return false;
    const MsgHdr* hdr = reinterpret_cast<const MsgHdr*>(data);
    if (!(hdr->eMsg & kMsgHdrProtoFlag)) return false;
    eMsg  = static_cast<EMsg>(hdr->eMsg & ~kMsgHdrProtoFlag);
    cbHdr = hdr->headerLength;
    if (cbHdr > size - static_cast<uint32_t>(sizeof(MsgHdr))) return false;
    const uint32_t off = static_cast<uint32_t>(sizeof(MsgHdr)) + cbHdr;
    pHdr   = data + sizeof(MsgHdr);
    pBody  = data + off;
    cbBody = size - off;
    return true;
}

static std::mutex s_rxLock;
static std::mutex s_txLock;

// ── Hash constants for service dispatch ──────
constexpr uint32_t HASH_JOB_NotifyRunningApps      = LcFnvHash("FamilyGroupsClient.NotifyRunningApps#1");
constexpr uint32_t HASH_JOB_GetUserStats            = LcFnvHash("Player.GetUserStats#1");
constexpr uint32_t HASH_JOB_GetManifestRequestCode  = LcFnvHash("ContentServerDirectory.GetManifestRequestCode#1");

// ── TX service dispatch ──────────────────────
struct DispatchEntry {
    uint32_t hash;
    bool   (*handler)(const uint8_t*, uint32_t, const uint8_t*, uint32_t);
};

static constexpr DispatchEntry kTxServiceDispatch[] = {
    { HASH_JOB_GetUserStats,           NetPacket::Handlers::UserStats::HandleSend_GetUserStats },
    { HASH_JOB_GetManifestRequestCode, NetPacket::Handlers::DepotFallback::HandleSend },
};

static bool RouteTxService(const char* targetJobName,
                           const uint8_t* pBody, uint32_t cbBody,
                           const uint8_t* pHdr, uint32_t cbHdr) {
    const uint32_t hash = LcFnvHash(targetJobName);
    for (const auto& entry : kTxServiceDispatch) {
        if (entry.hash == hash) return entry.handler(pBody, cbBody, pHdr, cbHdr);
    }
    return false;
}

static void RouteOutboundDispatch(EMsg eMsg, const uint8_t* pBody, uint32_t cbBody,
                                  const uint8_t* pHdr, uint32_t cbHdr) {
    NetPacket::s_tx.PatchBody = false;
    switch (eMsg) {
    case k_EMsgServiceMethodCallFromClient: {
        CMsgProtoBufHeader hdr;
        if (hdr.ParseFromArray(pHdr, cbHdr) && hdr.has_target_job_name()) {
            NetPacket::s_tx.PatchBody = RouteTxService(hdr.target_job_name().c_str(), pBody, cbBody, pHdr, cbHdr);
        }
        return;
    }
    case k_EMsgClientPICSProductInfoRequest:
        NetPacket::s_tx.PatchBody = NetPacket::Handlers::AccessToken::HandleSend(pBody, cbBody);
        return;
    case k_EMsgClientGamesPlayed:
    case k_EMsgClientGamesPlayedWithDataBlob:
        RichPresence::TrackGamesPlayed(pBody, cbBody, pHdr, cbHdr);
        NetPacket::s_tx.PatchBody = NetPacket::Handlers::SteamStub::HandleSend(pBody, cbBody);
        if (!NetPacket::s_tx.PatchBody)
            NetPacket::s_tx.PatchBody = NetPacket::Handlers::OnlineFix::HandleSend(pBody, cbBody);
        return;
    case k_EMsgClientRichPresenceUpload:
        RichPresence::TrackUpload(pBody, cbBody);
        return;
    case k_EMsgClientGetUserStats:
        NetPacket::s_tx.PatchBody = NetPacket::Handlers::UserStats::HandleSend_ClientGetUserStats(pBody, cbBody);
        return;
    case k_EMsgClientStoreUserStats2:
        NetPacket::s_tx.PatchBody = NetPacket::Handlers::UserStats::HandleSend_ClientStoreUserStats2(pBody, cbBody);
        return;
    case k_EMsgClientGetAppOwnershipTicket:
        return;
    }
}

struct RxDispatchEntry {
    uint32_t hash;
    void (*handler)(const uint8_t*, uint32_t, const uint8_t*, uint32_t);
};

static constexpr RxDispatchEntry kRxServiceDispatch[] = {
    { HASH_JOB_GetUserStats,           NetPacket::Handlers::UserStats::HandleRecv_GetUserStatsResponse },
    { HASH_JOB_GetManifestRequestCode, NetPacket::Handlers::DepotFallback::HandleRecv },
};

static void RouteRxService(const char* targetJobName,
                           const uint8_t* pBody, uint32_t cbBody,
                           const uint8_t* pHdr, uint32_t cbHdr) {
    const uint32_t hash = LcFnvHash(targetJobName);
    if (hash == HASH_JOB_NotifyRunningApps) {
        NetPacket::Handlers::FamilySharing::ClearBody(pBody, cbBody);
        return;
    }
    for (const auto& entry : kRxServiceDispatch) {
        if (entry.hash == hash) {
            entry.handler(pHdr, cbHdr, pBody, cbBody);
            return;
        }
    }
}

static void RouteInboundDispatch(EMsg eMsg, const uint8_t* pBody, uint32_t cbBody,
                                 const uint8_t* pHdr, uint32_t cbHdr) {
    NetPacket::s_rx.PatchBody = false;
    NetPacket::s_rx.PatchHdr  = false;
    if (eMsg == k_EMsgMulti) return;

    switch (eMsg) {
    case k_EMsgServiceMethodResponse: {
        CMsgProtoBufHeader hdr;
        if (hdr.ParseFromArray(pHdr, cbHdr) && hdr.has_target_job_name())
            RouteRxService(hdr.target_job_name().c_str(), pBody, cbBody, pHdr, cbHdr);
        return;
    }
    case k_EMsgClientGetUserStatsResponse:
        NetPacket::s_rx.PatchBody = NetPacket::Handlers::UserStats::HandleRecv_ClientGetUserStatsResponse(pBody, cbBody);
        return;
    case k_EMsgClientGetAppOwnershipTicketResponse:
        return;
    case k_EMsgClientPersonaState:
    {
        uint32_t rpSize = 0;
        if (RichPresence::HandleRecv(pBody, cbBody, NetPacket::s_rx.Body, NetPacket::kBodyCap, &rpSize)) {
            NetPacket::s_rx.BodyLen = rpSize;
            NetPacket::s_rx.PatchBody = true;
        }
        return;
    }
    case k_EMsgClientSharedLibraryLockStatus:
    case k_EMsgClientSharedLibraryStopPlaying:
        NetPacket::Handlers::FamilySharing::ClearBody(pBody, cbBody);
        return;
    }
}

// ── CNetPacket layout detection ────────────────────────────
// The beta client shifted m_pubData/m_cubData by +8 (see Steam/NetPacketLayout.h),
// so the offsets are identified from a live packet instead of compiled in.
//
// The bar is deliberately high. A failed probe costs one packet — it is
// passed through untouched and the next one is tried. A wrong latch costs a
// wild pointer write into a live Steam object from several call sites plus a
// corrupted refcount, so every additional check is worth its deferral.

namespace NetPkt {

    bool IsReadable(const void* addr, size_t bytes)
    {
        if (!addr || bytes == 0) return false;

        const uintptr_t start = reinterpret_cast<uintptr_t>(addr);
        if (start > UINTPTR_MAX - bytes) return false;   // wraps
        const uintptr_t end = start + bytes;

        for (uintptr_t cursor = start; cursor < end; ) {
            MEMORY_BASIC_INFORMATION mbi{};
            if (VirtualQuery(reinterpret_cast<LPCVOID>(cursor), &mbi, sizeof(mbi)) != sizeof(mbi))
                return false;
            // Strip the modifier bits before comparing — they combine with the
            // base protection rather than replacing it. A guard page faults on
            // first touch, so reading it is not safe even though its base
            // protection says otherwise; PAGE_NOACCESS and bare PAGE_EXECUTE
            // (execute-only) are unreadable on purpose.
            const DWORD base = mbi.Protect & ~static_cast<DWORD>(PAGE_GUARD | PAGE_NOCACHE | PAGE_WRITECOMBINE);
            const bool readable =
                mbi.State == MEM_COMMIT &&
                !(mbi.Protect & PAGE_GUARD) &&
                (base == PAGE_READONLY || base == PAGE_READWRITE || base == PAGE_WRITECOPY ||
                 base == PAGE_EXECUTE_READ || base == PAGE_EXECUTE_READWRITE ||
                 base == PAGE_EXECUTE_WRITECOPY);
            if (!readable) return false;

            const uintptr_t regionEnd = reinterpret_cast<uintptr_t>(mbi.BaseAddress) + mbi.RegionSize;
            if (regionEnd <= cursor) return false;   // no forward progress; refuse to spin
            cursor = regionEnd;
        }
        return true;
    }

} // namespace NetPkt

namespace {

    constexpr uint32    kProbeMaxPacket   = 1u << 20;   // 1 MiB — NOT the pool cap:
                                                        // a large Multi must not fail the true candidate
    constexpr uint32    kProbeMaxHdrLen   = 8192;
    constexpr uintptr_t kProbeMinPtr      = 0x10000;
    constexpr uintptr_t kProbeMaxPtr      = 0x7FFFFFFF0000ull;
    constexpr int       kProbeMaxAttempts = 512;

    int   g_ProbeAttempts = 0;
    uint32 g_ProbeAgreed  = NetPkt::kUnresolved;   // candidate that won the previous packet
    bool  g_ProbeLogged   = false;

    // Does `dataOff` describe this packet? Reads nothing it has not first
    // proved readable.
    bool ProbeLayout(const void* base, uint32 dataOff)
    {
        const uint8* p = static_cast<const uint8*>(base);

        // Validate the packet object's own storage before forming/reading any
        // candidate field address. Includes both known layouts through +0x20.
        if (!NetPkt::IsReadable(base, static_cast<size_t>(dataOff) + 0x10)) return false;

        // data (8) + size (4) + cRef (4)
        if (!NetPkt::IsReadable(p + dataOff, 0x10)) return false;

        const uint8* ptr  = *reinterpret_cast<const uint8* const*>(p + dataOff);
        const uint32 size = *reinterpret_cast<const uint32*>(p + dataOff + 8);
        const int32  cRef = *reinterpret_cast<const int32*>(p + dataOff + 0x0C);

        const uintptr_t addr = reinterpret_cast<uintptr_t>(ptr);
        if (addr < kProbeMinPtr || addr >= kProbeMaxPtr)      return false;
        if (size < sizeof(MsgHdr) || size > kProbeMaxPacket)  return false;
        if (cRef < 1 || cRef > 4096)                          return false;

        if (!NetPkt::IsReadable(ptr, sizeof(MsgHdr))) return false;

        // Read the header dword raw. EMsg is an unscoped enum with a signed
        // underlying type, so testing 0x80000000 through MsgHdr::eMsg only
        // works by accident.
        const uint32 raw    = *reinterpret_cast<const uint32*>(ptr);
        const uint32 hdrLen = *reinterpret_cast<const uint32*>(ptr + 4);
        if (!(raw & kMsgHdrProtoFlag))                        return false;
        const uint32 eMsg = raw & ~kMsgHdrProtoFlag;
        if (eMsg == 0 || eMsg >= 0x10000)                     return false;
        if (hdrLen < 2 || hdrLen > (std::min)(size - static_cast<uint32>(sizeof(MsgHdr)), kProbeMaxHdrLen))
            return false;

        if (!NetPkt::IsReadable(ptr, sizeof(MsgHdr) + hdrLen)) return false;

        // Strongest signal available: the bytes actually are a Steam protobuf
        // header. Only ever runs while probing.
        CMsgProtoBufHeader hdr;
        if (!hdr.ParseFromArray(ptr + sizeof(MsgHdr), static_cast<int>(hdrLen))) return false;

        return true;
    }

    // Identify the layout from one packet. Latches only when exactly one
    // candidate matches and the same candidate also won the previous packet:
    // ambiguity is the one thing we must never latch on, and requiring two
    // agreeing packets costs at most one early proto message.
    bool TryResolveLayout(const CNetPacket* pPacket)
    {
        if (NetPkt::IsDisabled()) return false;

        if (++g_ProbeAttempts > kProbeMaxAttempts) {
            if (!g_ProbeLogged) {
                g_ProbeLogged = true;
                NetPkt::Disable();
                LOG_NETPACKET_ERROR(
                    "CNetPacket layout unidentified after {} packets - netpacket features "
                    "disabled for this session (no field will be touched). This means the "
                    "client's layout matches no known candidate; add one to NetPkt::kLayouts.",
                    kProbeMaxAttempts);
            }
            return false;
        }

        uint32 winner = NetPkt::kUnresolved;
        int    passes = 0;
        for (const auto& layout : NetPkt::kLayouts) {
            if (ProbeLayout(pPacket, layout.dataOff)) {
                ++passes;
                winner = layout.dataOff;
            }
        }

        if (passes == 0) {
            // No candidate matched, which is what a non-protobuf frame looks
            // like — it carries no evidence either way. Leave any standing
            // agreement intact: discarding it here would mean one interleaved
            // non-proto packet restarts the confirmation, which is exactly what
            // early connection traffic does.
            LOG_NETPACKET_TRACE("CNetPacket probe: no candidate matched (attempt {}), "
                                "likely a non-proto frame", g_ProbeAttempts);
            return false;
        }
        if (passes > 1) {
            // Genuine ambiguity — both layouts read as valid on the same
            // packet. That IS evidence, and it says do not trust the standing
            // agreement.
            LOG_NETPACKET_TRACE("CNetPacket probe: {} candidates matched, ambiguous (attempt {})",
                                passes, g_ProbeAttempts);
            g_ProbeAgreed = NetPkt::kUnresolved;
            return false;
        }
        if (g_ProbeAgreed != winner) {
            LOG_NETPACKET_TRACE("CNetPacket probe: candidate 0x{:X} matched, awaiting confirmation",
                                winner);
            g_ProbeAgreed = winner;
            return false;
        }

        const char* name = "?";
        for (const auto& layout : NetPkt::kLayouts)
            if (layout.dataOff == winner) name = layout.name;

        NetPkt::Latch(winner);
        LOG_NETPACKET_INFO("CNetPacket layout = {} (m_pubData +0x{:X}, m_cubData +0x{:X}), "
                           "confirmed on two consecutive packets after {} attempt(s)",
                           name, winner, winner + 8, g_ProbeAttempts);
        return true;
    }

} // namespace

// ═══════════════════════════════════════════════════════════════════
//  Hooks
// ═══════════════════════════════════════════════════════════════════

LM_HOOK(BBuildAndAsyncSendFrame, bool,
        void* pObject, EWebSocketOpCode eWebSocketOpCode,
        uint8_t* pubData, uint32_t cubData)
{
    if (eWebSocketOpCode != k_eWebSocketOpCode_Binary)
        return oBBuildAndAsyncSendFrame(pObject, eWebSocketOpCode, pubData, cubData);

    EMsg eMsg;
    const uint8_t *pHdr, *pBody;
    uint32_t cbHdr, cbBody;
    if (ParsePacket(pubData, cubData, eMsg, pHdr, cbHdr, pBody, cbBody)) {
        RouteOutboundDispatch(eMsg, pBody, cbBody, pHdr, cbHdr);
        if (NetPacket::s_tx.PatchBody) {
            uint32_t newSize = 0;
            uint8_t* buf = NetPacket::s_tx.Build(pubData, cbHdr, pHdr,
                                                  NetPacket::s_tx.Body, NetPacket::s_tx.BodyLen,
                                                  &newSize, s_txLock);
            if (buf)
                return oBBuildAndAsyncSendFrame(pObject, eWebSocketOpCode, buf, newSize);
        }
    }
    return oBBuildAndAsyncSendFrame(pObject, eWebSocketOpCode, pubData, cubData);
}

LM_HOOK(RecvPkt, void*, void* pThis, CNetPacket* pPacket)
{
    // Identify the packet layout before anything reads or writes a field
    // (see Steam/NetPacketLayout.h). Until the layout is confirmed the packet
    // is handed straight back untouched, so a field is never accessed at an
    // unverified offset - this is what keeps Steam booting on the beta client.
    //
    // Skipping costs nothing meaningful: injections and replacements are only
    // delayed until the layout is known, not dropped, and RecvJob acts on
    // protobuf messages - exactly the set the probe latches on.
    if (!pPacket) return oRecvPkt(pThis, pPacket);
    if (!NetPkt::IsResolved() && !TryResolveLayout(pPacket))
        return oRecvPkt(pThis, pPacket);

    const uint32_t dataOff = NetPkt::State();
    if (dataOff == NetPkt::kUnresolved || dataOff == NetPkt::kDisabled ||
        !NetPkt::IsReadable(pPacket, static_cast<size_t>(dataOff) + 0x10))
        return oRecvPkt(pThis, pPacket);
    const uint8_t* packetData = NetPkt::Data(pPacket);
    const uint32_t packetSize = NetPkt::Size(pPacket);
    const uintptr_t packetAddr = reinterpret_cast<uintptr_t>(packetData);
    if (!packetData || packetAddr < 0x10000ull || packetAddr >= 0x7FFFFFFF0000ull ||
        packetSize < sizeof(MsgHdr) || packetSize > 64u * 1024u * 1024u ||
        !NetPkt::IsReadable(packetData, packetSize))
        return oRecvPkt(pThis, pPacket);

    RichPresence::DeliverPending(
        pThis, pPacket,
        [](void* pT, CNetPacket* pP) -> bool {
            return oRecvPkt(pT, pP) != nullptr;
        });

    EMsg eMsg;
    const uint8_t *pBody, *pHdr;
    uint32_t cbBody, cbHdr;
    if (ParsePacket(NetPkt::Data(pPacket), NetPkt::Size(pPacket),
                    eMsg, pHdr, cbHdr, pBody, cbBody)) {
        NetPacket::s_rx.Shrunk = false;
        RouteInboundDispatch(eMsg, pBody, cbBody, pHdr, cbHdr);

        if (NetPacket::s_rx.Shrunk && NetPacket::s_rx.PatchHdr) {
            NetPacket::s_rx.Replace(pPacket,
                NetPacket::s_rx.Hdr, NetPacket::s_rx.HdrLen,
                pBody, NetPacket::s_rx.NewBodySize, s_rxLock);
        } else if (NetPacket::s_rx.Shrunk) {
            NetPkt::Size(pPacket) = sizeof(MsgHdr) + cbHdr + NetPacket::s_rx.NewBodySize;
        } else if (NetPacket::s_rx.PatchHdr || NetPacket::s_rx.PatchBody) {
            NetPacket::s_rx.Replace(pPacket,
                NetPacket::s_rx.PatchHdr  ? NetPacket::s_rx.Hdr  : pHdr,
                NetPacket::s_rx.PatchHdr  ? NetPacket::s_rx.HdrLen : cbHdr,
                NetPacket::s_rx.PatchBody ? NetPacket::s_rx.Body : pBody,
                NetPacket::s_rx.PatchBody ? NetPacket::s_rx.BodyLen : cbBody, s_rxLock);
        }
    }
    return oRecvPkt(pThis, pPacket);
}

// ── PacketPool method implementations ────────
namespace NetPacket {

template<>
uint8_t* PacketPool<true>::Replace(CNetPacket* p, const uint8_t* newHdr, uint32_t cbNewHdr,
                                    const uint8_t* newBody, uint32_t cbNewBody, std::mutex& mtx) {
    uint32_t newSize = sizeof(MsgHdr) + cbNewHdr + cbNewBody;
    if (newSize > sizeof(Frame[0])) return nullptr;
    std::lock_guard<std::mutex> lock(mtx);
    uint8_t* buf = Frame[FrameIdx];
    const MsgHdr* orig = reinterpret_cast<const MsgHdr*>(NetPkt::Data(p));
    MsgHdr* out = reinterpret_cast<MsgHdr*>(buf);
    out->eMsg         = orig->eMsg;
    out->headerLength = cbNewHdr;
    memcpy(buf + sizeof(MsgHdr), newHdr, cbNewHdr);
    if (cbNewBody) memcpy(buf + sizeof(MsgHdr) + cbNewHdr, newBody, cbNewBody);
    NetPkt::Data(p) = buf;
    NetPkt::Size(p) = newSize;
    FrameIdx = (FrameIdx + 1) % kPoolSlots;
    return buf;
}

template<>
uint8_t* PacketPool<false>::Build(const uint8_t* pubData, uint32_t cbHdr, const uint8_t* pHdr,
                                   const uint8_t* newBody, uint32_t cbNewBody,
                                   uint32_t* pNewSize, std::mutex& mtx) {
    *pNewSize = sizeof(MsgHdr) + cbHdr + cbNewBody;
    if (*pNewSize > sizeof(Frame[0])) return nullptr;
    std::lock_guard<std::mutex> lock(mtx);
    uint8_t* buf = Frame[FrameIdx];
    const MsgHdr* orig = reinterpret_cast<const MsgHdr*>(pubData);
    MsgHdr* out = reinterpret_cast<MsgHdr*>(buf);
    out->eMsg         = orig->eMsg;
    out->headerLength = cbHdr;
    memcpy(buf + sizeof(MsgHdr), pHdr, cbHdr);
    memcpy(buf + sizeof(MsgHdr) + cbHdr, newBody, cbNewBody);
    FrameIdx = (FrameIdx + 1) % kPoolSlots;
    return buf;
}

} // namespace NetPacket

// ═══════════════════════════════════════════════════════════════════
//  NetPacket::Install / Uninstall
// ═══════════════════════════════════════════════════════════════════
namespace NetPacket {

void Install() {
    LM_TX_BEGIN();
    LM_INSTALL(BBuildAndAsyncSendFrame);
    LM_INSTALL(RecvPkt);
    LM_TX_COMMIT();
}

void Uninstall() {
    LM_TX_BEGIN();
    LM_REMOVE(BBuildAndAsyncSendFrame);
    LM_REMOVE(RecvPkt);
    LM_TX_COMMIT();
}

} // namespace NetPacket
