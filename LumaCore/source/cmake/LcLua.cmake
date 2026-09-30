# Defines a static `lua_static` target by fetching the official Lua 5.5
# source release. Idempotent.
if(TARGET lua_static)
    return()
endif()

include(LcFetchCache)
include(FetchContent)

FetchContent_Declare(
    lua
    URL https://www.lua.org/ftp/lua-5.5.0.tar.gz
    DOWNLOAD_EXTRACT_TIMESTAMP TRUE
    TLS_VERIFY OFF
)
FetchContent_MakeAvailable(lua)

# Locate the Lua sources: normally <lua_SOURCE_DIR>/src, but tolerate an
# archive that was extracted with its top-level lua-5.5.0/ folder intact.
set(LUA_SRC_DIR "${lua_SOURCE_DIR}/src")
if(NOT EXISTS "${LUA_SRC_DIR}/lua.h")
    file(GLOB _lua_nested "${lua_SOURCE_DIR}/*/src/lua.h")
    if(_lua_nested)
        get_filename_component(LUA_SRC_DIR "${_lua_nested}" DIRECTORY)
    endif()
endif()

# The Lua tarball ships only Makefiles, so we build a static library here.
file(GLOB LUA_CORE_SOURCES "${LUA_SRC_DIR}/*.c")
list(REMOVE_ITEM LUA_CORE_SOURCES
    "${LUA_SRC_DIR}/lua.c"
    "${LUA_SRC_DIR}/luac.c")

if(NOT LUA_CORE_SOURCES)
    message(FATAL_ERROR
        "Lua sources not found under '${lua_SOURCE_DIR}'. The cached copy in "
        "'<LumaCore>/.deps/lua-src' is incomplete. Delete that folder (or all "
        "of .deps) and re-run build.bat to re-download it.")
endif()

add_library(lua_static STATIC ${LUA_CORE_SOURCES})
target_include_directories(lua_static PUBLIC "${LUA_SRC_DIR}")
set_target_properties(lua_static PROPERTIES POSITION_INDEPENDENT_CODE ON)
