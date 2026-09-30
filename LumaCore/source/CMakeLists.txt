cmake_minimum_required(VERSION 3.20)
project(LumaCore VERSION 1.0.0 LANGUAGES C CXX)

set(CMAKE_CXX_STANDARD 20)
set(CMAKE_CXX_STANDARD_REQUIRED ON)
set(CMAKE_C_STANDARD 11)

if(POLICY CMP0091)
    cmake_policy(SET CMP0091 NEW)
endif()

set(CMAKE_CONFIGURATION_TYPES "Debug;Release" CACHE STRING "" FORCE)
set(CMAKE_MSVC_RUNTIME_LIBRARY "MultiThreaded$<$<CONFIG:Debug>:Debug>")
set(BUILD_SHARED_LIBS OFF CACHE BOOL "" FORCE)

list(APPEND CMAKE_MODULE_PATH "${CMAKE_CURRENT_SOURCE_DIR}/cmake")
include(LcLua)
include(LcDetours)
include(LcSpdlog)
include(LcProtobuf)
include(LcTomlplusplus)
include(LcLogMacros)

# protobuf may already have supplied its runtime targets without exposing the
# executable target under the unqualified name "protoc". Resolve the compiler
# independently so code generation works with either the locally built target
# or a package-provided protobuf::protoc / protoc executable.
if(TARGET protoc)
    set(LUMACORE_PROTOC_COMMAND "$<TARGET_FILE:protoc>")
    set(LUMACORE_PROTOC_DEPENDENCY protoc)
elseif(TARGET protobuf::protoc)
    set(LUMACORE_PROTOC_COMMAND "$<TARGET_FILE:protobuf::protoc>")
    set(LUMACORE_PROTOC_DEPENDENCY protobuf::protoc)
else()
    if(DEFINED Protobuf_PROTOC_EXECUTABLE AND EXISTS "${Protobuf_PROTOC_EXECUTABLE}")
        set(_LUMACORE_PROTOC_EXE "${Protobuf_PROTOC_EXECUTABLE}")
    elseif(DEFINED protobuf_PROTOC_EXE AND EXISTS "${protobuf_PROTOC_EXE}")
        set(_LUMACORE_PROTOC_EXE "${protobuf_PROTOC_EXE}")
    else()
        find_program(_LUMACORE_PROTOC_EXE NAMES protoc protoc.exe)
    endif()

    if(NOT _LUMACORE_PROTOC_EXE)
        message(FATAL_ERROR
            "Protobuf runtime targets were found, but no protoc compiler is available. "
            "Install a protoc executable compatible with the protobuf runtime or "
            "remove the external protobuf targets so LcProtobuf can build its pinned protoc.")
    endif()

    set(LUMACORE_PROTOC_COMMAND "${_LUMACORE_PROTOC_EXE}")
    set(LUMACORE_PROTOC_DEPENDENCY "${_LUMACORE_PROTOC_EXE}")
    message(STATUS "LumaCore protobuf compiler: ${_LUMACORE_PROTOC_EXE}")
endif()

set(PROTO_SRC "${CMAKE_CURRENT_SOURCE_DIR}/proto/steam_messages.proto")
set(PROTO_GEN_DIR       "${CMAKE_CURRENT_BINARY_DIR}/proto")
set(PROTO_GEN_LITE_DIR  "${CMAKE_CURRENT_BINARY_DIR}/proto_lite")

add_custom_command(
    OUTPUT "${PROTO_GEN_DIR}/steam_messages.pb.cc"
           "${PROTO_GEN_DIR}/steam_messages.pb.h"
    COMMAND ${CMAKE_COMMAND} -E make_directory "${PROTO_GEN_DIR}"
    COMMAND "${LUMACORE_PROTOC_COMMAND}"
        "--cpp_out=${PROTO_GEN_DIR}"
        "-I${CMAKE_CURRENT_SOURCE_DIR}/proto"
        "${PROTO_SRC}"
    DEPENDS "${PROTO_SRC}" ${LUMACORE_PROTOC_DEPENDENCY}
    COMMENT "Generating protobuf full-Message sources (Debug)"
)

add_custom_command(
    OUTPUT "${PROTO_GEN_LITE_DIR}/steam_messages.pb.cc"
           "${PROTO_GEN_LITE_DIR}/steam_messages.pb.h"
    COMMAND ${CMAKE_COMMAND} -E make_directory "${PROTO_GEN_LITE_DIR}"
    COMMAND "${LUMACORE_PROTOC_COMMAND}"
        "--cpp_out=lite:${PROTO_GEN_LITE_DIR}"
        "-I${CMAKE_CURRENT_SOURCE_DIR}/proto"
        "${PROTO_SRC}"
    DEPENDS "${PROTO_SRC}" ${LUMACORE_PROTOC_DEPENDENCY}
    COMMENT "Generating protobuf lite-MessageLite sources (Release)"
)

add_library(LumaCore SHARED
    core/entry.cpp
    core/Orchestrator.cpp

    runtime/Ticket.cpp
    runtime/Logger.cpp
    runtime/HookStatus.cpp
    runtime/DirWatch.cpp
    runtime/Diagnostics.cpp
    runtime/VehUtil.cpp
    runtime/RuntimeHttp.cpp
    runtime/ManifestFetch.cpp
    runtime/ProtectionProbe.cpp
    runtime/RemoteTools.cpp
    runtime/IpcSpecLoader.cpp
    runtime/BootDiag.cpp
    runtime/CredentialStore.cpp
    runtime/EticketFetcher.cpp
    runtime/TicketProvider.cpp
    runtime/ProcessInspect.cpp
    runtime/IntegrityScanner.cpp
    runtime/LibraryInjector.cpp

    patterns/ByteScan.cpp
    patterns/PatternSig.cpp
    patterns/PatternFetcher.cpp

    config/LuaState.cpp
    config/LuaBindings.cpp
    config/LuaQuery.cpp
    config/Settings.cpp

    hooks/client/DepotKeys.cpp
    hooks/client/IPCBus.cpp
    hooks/client/CmdUser.cpp
    hooks/client/CmdUtils.cpp
    hooks/client/ManifestBind.cpp
    hooks/client/PacketRouter.cpp
    hooks/client/NetPacket.cpp
    hooks/client/NetPacket_AccessToken.cpp
    hooks/client/NetPacket_UserStats.cpp
    hooks/client/NetPacket_ETicket.cpp
    hooks/client/NetPacket_Manifest.cpp
    hooks/client/NetPacket_FamilySharing.cpp
    hooks/client/NetPacket_OnlineFix.cpp
    hooks/client/NetPacket_SteamStub.cpp
    hooks/client/PackagePatch.cpp
    hooks/client/RichPresence.cpp
    hooks/client/LicenseHooks.cpp
    hooks/client/StringFind.cpp
    hooks/client/PipeWatch.cpp
    hooks/client/AuthWindow.cpp
    hooks/client/AsyncTicketMap.cpp
    hooks/client/DecryptionKeyHook.cpp
    hooks/client/PendingCallMap.cpp
    hooks/client/OnlineFixInject.cpp
    hooks/client/ProcessExtension.cpp
    hooks/client/SteamStubAuto.cpp
    hooks/client/SteamStubTicket.cpp
    hooks/client/IpcMethodLoader.cpp
    hooks/client/IpcDispatch.cpp
    hooks/client/IpcHooks.cpp
    hooks/client/IpcHandlers_ISteamUser.cpp
    hooks/client/IpcHandlers_ISteamUtils.cpp
    hooks/client/DenuvoAuthenticator.cpp

    hooks/capture/RuntimeCapture.cpp

    hooks/ui/SteamUI.cpp
    hooks/ui/StatusWriter.cpp

    $<$<CONFIG:Debug>:${PROTO_GEN_DIR}/steam_messages.pb.cc>
    $<$<CONFIG:Release>:${PROTO_GEN_LITE_DIR}/steam_messages.pb.cc>
)

target_include_directories(LumaCore PRIVATE
    ${CMAKE_CURRENT_SOURCE_DIR}
    ${CMAKE_CURRENT_BINARY_DIR}/generated
    $<$<CONFIG:Debug>:${PROTO_GEN_DIR}>
    $<$<CONFIG:Release>:${PROTO_GEN_LITE_DIR}>
)

target_link_libraries(LumaCore PRIVATE
    lua_static
    detours
    $<$<CONFIG:Debug>:libprotobuf>
    $<$<CONFIG:Release>:libprotobuf-lite>
    tomlplusplus::tomlplusplus
    $<$<CONFIG:Debug>:spdlog::spdlog>
    winhttp
    bcrypt
)

target_compile_definitions(LumaCore PRIVATE
    $<$<CONFIG:Debug>:LUMACORE_LOGGING_ENABLED>
    LUMACORE_DIAGNOSTICS_ENABLED
)

# ---------------------------------------------------------------------------
# LumaCorePayload — DLL injected into a game launched with -onlinefix
# ---------------------------------------------------------------------------
add_library(LumaCorePayload SHARED
    payload/LumaCorePayload/LumaCorePayloadEntry.cpp
    payload/LumaCorePayload/LcPayloadLogging.cpp
    payload/LumaCorePayload/EpicOnlineBridge.cpp
    payload/LumaCorePayload/PayloadPropagator.cpp
)
set_target_properties(LumaCorePayload PROPERTIES PREFIX "" OUTPUT_NAME "LumaCorePayload")
target_include_directories(LumaCorePayload PRIVATE
    ${CMAKE_CURRENT_SOURCE_DIR}
    ${CMAKE_CURRENT_SOURCE_DIR}/payload/LumaCorePayload
)
target_link_libraries(LumaCorePayload PRIVATE detours psapi)
target_compile_definitions(LumaCorePayload PRIVATE
    $<$<CONFIG:Debug>:LUMACORE_PAYLOAD_LOGGING_ENABLED>
)

add_library(dwmapi SHARED
    proxy/LcDwmProxy.cpp
)
set_target_properties(dwmapi PROPERTIES PREFIX "" OUTPUT_NAME "dwmapi")

# ---------------------------------------------------------------------------
# xinput1_4.dll hijack — secondary loader DLL placed alongside Steam.
# ---------------------------------------------------------------------------
add_library(xinput1_4 SHARED
    proxy/LcXInputProxy.cpp
    proxy/LcXInputProxy.def
)
set_target_properties(xinput1_4 PROPERTIES PREFIX "" OUTPUT_NAME "xinput1_4")




