# Caches FetchContent's downloaded *source trees* at the repo root so they
# survive a `rm -rf build/`. Done by setting FETCHCONTENT_SOURCE_DIR_<NAME>
# to point at the cached copies — that skips FetchContent's populate step
# entirely (no download, no subbuild), which is also what lets us share the
# cache across generators (Ninja for the main project, VS for SteamAPIProxy)
# without hitting the "generator mismatch in *-subbuild/" error.
#
# Layout:
#   <repo>/.deps/<name>-src/   <-- canonical source for each dependency
#
# First configure (cache empty): FETCHCONTENT_BASE_DIR is pinned so the
# initial populate lands at the shared location.
# Subsequent configures: FETCHCONTENT_SOURCE_DIR_<NAME> overrides take
# precedence — populate is bypassed, subbuild + build live in the per-tree
# default ${CMAKE_BINARY_DIR}/_deps and don't conflict across generators.
#
# Override the cache location at configure time:
#   cmake -S src -B build -DLUMACORE_DEPS_DIR=/path/to/shared/cache
#
# Idempotent.
if(_LC_FETCH_CACHE_INITIALISED)
    return()
endif()
set(_LC_FETCH_CACHE_INITIALISED TRUE)

if(NOT DEFINED LUMACORE_DEPS_DIR)
    # CMAKE_CURRENT_LIST_DIR is src/cmake; ../../.deps is the repo root.
    get_filename_component(LUMACORE_DEPS_DIR
        "${CMAKE_CURRENT_LIST_DIR}/../../.deps" ABSOLUTE)
endif()

# For each known dependency, if a source dir is already cached at the shared
# location, point FetchContent at it so populate becomes a no-op. Verify a
# well-known file first: an interrupted populate (or an antivirus sweep) can
# leave a directory behind that exists but has no sources - an override
# pointing at it skips the download and the configure dies much later at
# generate time with a cryptic "No SOURCES given to target". Broken entries
# are deleted here so the populate below re-downloads just those.
set(_LC_ALL_CACHED TRUE)
foreach(_dep IN ITEMS lua detours spdlog protobuf tomlplusplus)
    string(TOUPPER "${_dep}" _UPPER)
    set(_src "${LUMACORE_DEPS_DIR}/${_dep}-src")
    set(_valid FALSE)
    if(IS_DIRECTORY "${_src}")
        if(_dep STREQUAL "lua")
            # Accept the flat layout and an archive extracted with its
            # top-level lua-5.5.0/ folder intact - both are seen in the wild.
            file(GLOB _lua_hits "${_src}/src/lua.h" "${_src}/*/src/lua.h")
            if(_lua_hits)
                set(_valid TRUE)
            endif()
        elseif(_dep STREQUAL "detours")
            # Detours has no root CMakeLists (LcDetours builds it by hand).
            if(EXISTS "${_src}/src/detours.cpp")
                set(_valid TRUE)
            endif()
        elseif(_dep STREQUAL "protobuf")
            # protobuf v3.15.3 keeps its CMake project under cmake/ and is
            # intentionally added with SOURCE_SUBDIR cmake.
            if(EXISTS "${_src}/cmake/CMakeLists.txt" AND
               EXISTS "${_src}/src/google/protobuf/compiler/main.cc")
                set(_valid TRUE)
            endif()
        else()
            # spdlog / tomlplusplus: git checkouts with a root CMakeLists.
            if(EXISTS "${_src}/CMakeLists.txt")
                set(_valid TRUE)
            endif()
        endif()
    endif()

    if(_valid)
        set(FETCHCONTENT_SOURCE_DIR_${_UPPER} "${_src}" CACHE PATH
            "Pre-populated ${_dep} source dir" FORCE)
    else()
        if(IS_DIRECTORY "${_src}")
            message(STATUS "FetchContent: removing broken cache entry ${_src}")
            file(REMOVE_RECURSE "${_src}")
        endif()
        # Also clear any override left in CMakeCache.txt by an earlier run:
        # FetchContent treats an empty FETCHCONTENT_SOURCE_DIR_<NAME> as unset,
        # so the populate below becomes the only path for this dependency.
        set(FETCHCONTENT_SOURCE_DIR_${_UPPER} "" CACHE PATH
            "Pre-populated ${_dep} source dir" FORCE)
        set(_LC_ALL_CACHED FALSE)
    endif()
endforeach()

if(_LC_ALL_CACHED)
    message(STATUS "FetchContent: reusing cached sources at ${LUMACORE_DEPS_DIR}")
else()
    # At least one dep still needs to be downloaded. Direct the populate
    # output to the shared cache so the next configure can reuse it.
    set(FETCHCONTENT_BASE_DIR "${LUMACORE_DEPS_DIR}" CACHE PATH
        "Shared FetchContent cache (sources + first-time builds)" FORCE)
    message(STATUS "FetchContent: populating missing sources into ${LUMACORE_DEPS_DIR}")
endif()

# Skip the periodic git-fetch / tarball revalidation on configures after
# the initial populate.
set(FETCHCONTENT_UPDATES_DISCONNECTED ON CACHE BOOL
    "Skip FetchContent update step on subsequent configures" FORCE)
