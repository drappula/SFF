// LumaCore — runtime CNetPacket layout detection for SteaMidra.
// Steam/NetPacket.h plus the probe in Hooks_NetPacket.cpp
// the fix for the Steam client beta that shifted CNetPacket's fields
// Copyright (c) 2025-2026 Midrag (https://github.com/Midrags).
// Distributed under the GNU General Public License v3 or later.
// See <https://www.gnu.org/licenses/> for the full license text.

#pragma once

#include "Steam/Types.h"

#include <atomic>
#include <cstddef>
#include <cstdint>

// CNetPacket's layout differs between Steam client builds, so it is opaque:
// never declare its fields and never take its sizeof. The two fields LumaCore
// uses are reached through Data()/Size(), which apply an offset detected at
// runtime from a live packet.
//
//   field                stable      beta (steamclient64 d2d085e7+)
//   m_hConnection        +0x00       +0x00
//   version stamps       --          +0x04, +0x08  (+ 4 bytes padding @ +0x0C)
//   m_pubData            +0x08       +0x10
//   m_cubData            +0x10       +0x18
//   m_cRef               +0x14       +0x1C
//   m_pubNetworkBuffer   +0x18       +0x20
//   m_pNext              +0x20       +0x28
//
// The beta client inserted two per-packet uint32 version stamps after
// m_hConnection, shifting everything below them by 8. They are written by
// the CNetPacket ctor and are not used by LumaCore.
//
// m_cubData always sits 8 bytes after m_pubData, so one offset describes the
// whole layout — which is what lets the detected state live in a single word.

struct CNetPacket;

namespace NetPkt {

    struct Layout {
        const char* name;
        uint32      dataOff;
    };

    // The candidates the probe considers (see ProbeLayout in
    // hooks/client/NetPacket.cpp). Kept as a table rather than two branches:
    // Valve will shift this again, and a new row should be the whole change.
    inline constexpr Layout kLayouts[] = {
        { "stable", 0x08 },
        { "beta",   0x10 },
    };

    inline constexpr uint32 kUnresolved = 0u;
    inline constexpr uint32 kDisabled   = 0xFFFFFFFFu;

    // The entire layout state, in one word so it can never be seen
    // half-published. A separate "resolved" flag beside the offsets would let
    // another thread observe the flag set while the offset was still zero, and
    // write a packet field at offset 0 — straight over m_hConnection. Relaxed
    // ordering is sufficient: the value is self-contained and nothing else is
    // published through it. constinit so a hook that fires before dynamic
    // initialization cannot read a garbage word.
    inline constinit std::atomic<uint32> g_dataOff{ kUnresolved };

    inline uint32 State()      { return g_dataOff.load(std::memory_order_relaxed); }
    inline bool   IsResolved() { const uint32 v = State(); return v != kUnresolved && v != kDisabled; }
    inline bool   IsDisabled() { return State() == kDisabled; }

    inline void Latch(uint32 dataOff) { g_dataOff.store(dataOff, std::memory_order_relaxed); }

    // Terminal state: the layout could not be identified, so no field is ever
    // touched again. Deliberately not "fall back to the compiled default" —
    // the default matches one client, and on the other it is precisely the
    // wild write this whole mechanism exists to prevent.
    inline void Disable() { g_dataOff.store(kDisabled, std::memory_order_relaxed); }

    // VirtualQuery-based readability check (defined in hooks/client/NetPacket.cpp):
    // rejects uncommitted, guard-page and execute-only memory before the probe
    // dereferences anything.
    bool IsReadable(const void* addr, size_t bytes);

    namespace detail {
        // Returned by the accessors while the layout is unknown. Every real
        // call site sits behind the gate in hkRecvPkt, so this is unreachable
        // today; it exists so that a call accidentally added above the gate
        // corrupts a dead global instead of a live Steam object. A plain
        // inline variable, not thread_local — Steam threads predate our
        // injection, and races on a discard sink are harmless by definition.
        inline uint8* g_trashData = nullptr;
        inline uint32 g_trashSize = 0;
    }

    // References, so reads, writes, save/restore pairs and in-place repoints
    // all work as a plain substitution at the call sites.
    inline uint8*& Data(CNetPacket* p) {
        const uint32 off = State();
        if (!p || off == kUnresolved || off == kDisabled) return detail::g_trashData;
        return *reinterpret_cast<uint8**>(reinterpret_cast<uint8*>(p) + off);
    }

    inline uint32& Size(CNetPacket* p) {
        const uint32 off = State();
        if (!p || off == kUnresolved || off == kDisabled) return detail::g_trashSize;
        return *reinterpret_cast<uint32*>(reinterpret_cast<uint8*>(p) + off + 8);
    }

    inline uint8* Data(const CNetPacket* p) { return Data(const_cast<CNetPacket*>(p)); }
    inline uint32 Size(const CNetPacket* p) { return Size(const_cast<CNetPacket*>(p)); }

} // namespace NetPkt
