# LumaCore

LumaCore is the DLL component that SteaMidra injects into Steam to handle family-sharing bypass, depot key loading, achievement spoofing, Denuvo authorization, and legacy CD-key suppression.

It ships as four files placed in the Steam installation directory:

- `xinput1_4.dll` — thin XInput 1.4 proxy; PRIMARY bootstrap. Loads LumaCore.dll from a worker thread after DllMain (Aether 14a6359 lesson: XInput is the only startup gate Steam still loads from its own directory)
- `dwmapi.dll` — thin DWM proxy; legacy/secondary gate, same safe worker-thread load
- `LumaCore.dll` — the main hook library
- `LumaCorePayload.dll` — injected into game processes for online-fix multiplayer (EOS bridge, lobby redirection)

## How it works

At Steam startup, the proxy DLLs load before any game code and load `LumaCore.dll`.  LumaCore then:

1. Copies `steamclient64.dll` to `bin\lcoverlay.dll` so it can be loaded and hooked independently of the live client.
2. Reads the current Steam build ID from `steam.exe!GetBootstrapperVersion` so byte-pattern searches pick the most accurate signature for the running build.
3. Fetches per-build pattern TOMLs from the network mirror chain, caches them locally, and primes the runtime pattern map.
4. Installs over 40 Detours hooks plus VEH captures into the loaded `lcoverlay.dll` copy, covering IPC dispatch, package ownership, license patching, Denuvo auth, manifest binding, network packet rewriting, and online-fix game language synchronization.
5. Starts a Lua directory watcher that monitors `config/stplug-in/` for `.lua` files written by SteaMidra.

When a Lua file appears or changes, LumaCore parses it, loads depot decryption keys and ownership records, and injects the new ownership data into Steam without restarting. For online-fix games, LumaCore synchronizes the game's language setting to Spacewar (480) and LumaCorePayload.dll is injected into the game process via CreateProcess hooks to handle EOS bridge and lobby redirection.

## Features

See [docs/LumaCore.md](docs/LumaCore.md) for a full description of every hook and feature.

## Building

Requirements: CMake 3.20+, MSVC (Visual Studio 2022), 64-bit target only.

```bat
build.bat
```

The build script downloads all dependencies (Lua 5.4, Microsoft Detours, spdlog, protobuf, toml++) via CMake FetchContent on the first run.  Subsequent runs are incremental.  Output DLLs are copied to `Releases/Release/` and `Releases/Debug/` beside `build.bat`.

## Credits

See [CREDITS.md](CREDITS.md).

Related projects on GitHub:

- [KoriaPolis/Steam-Auto-PT](https://github.com/KoriaPolis/Steam-Auto-PT)
- [KoriaPolis/LumaCore](https://github.com/KoriaPolis/LumaCore)

## License

LumaCore is part of SteaMidra and is distributed under the GNU General Public License v3.  See the root `LICENSE` file for the full text.
