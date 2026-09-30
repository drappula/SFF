@echo off
setlocal EnableDelayedExpansion

set "SOURCE_DIR=%~dp0source"
set "BUILD_DIR=%~dp0build"
set "OUT_DIR=%~dp0Releases"
set "LOG_FILE=%~dp0build_log.txt"
> "%LOG_FILE%" echo LumaCore build started %DATE% %TIME%

:: --- Argument parsing ----------------------------------------------------
:: --no-pause      skip the trailing 'pause'
:: --debug-only    build Debug only
:: --release-only  build Release only
:: --clean         remove build dir before building
set "NO_PAUSE=0"
set "BUILD_RELEASE=1"
set "BUILD_DEBUG=0"
set "DO_CLEAN=1"
:parse_args
if "%~1"=="" goto args_done
if /I "%~1"=="--no-pause"     ( set "NO_PAUSE=1"      & shift & goto parse_args )
if /I "%~1"=="--debug-only"   ( set "BUILD_RELEASE=0" & shift & goto parse_args )
if /I "%~1"=="--release-only" ( set "BUILD_DEBUG=0"   & shift & goto parse_args )
if /I "%~1"=="--clean"        ( set "DO_CLEAN=1"      & shift & goto parse_args )
echo [WARN] Unknown argument: %~1
shift
goto parse_args
:args_done

echo.
echo ============================================================
echo  LumaCore Build
echo  Source  : %SOURCE_DIR%
echo  Build   : %BUILD_DIR%
echo  Output  : %OUT_DIR%
echo  Release : %BUILD_RELEASE%   Debug: %BUILD_DEBUG%
if "%DO_CLEAN%"=="1" ( echo  Clean  : YES ) else ( echo  Clean  : NO incremental )
echo ============================================================
echo.

:: --- Clean build only when --clean is passed -------------------------------
if "%DO_CLEAN%"=="1" (
    if exist "%BUILD_DIR%\NUL" (
        echo [STEP] Cleaning build directory...
        >> "%LOG_FILE%" echo.
        >> "%LOG_FILE%" echo [STEP] Cleaning build directory...
        rmdir /S /Q "%BUILD_DIR%" >> "%LOG_FILE%" 2>&1
        if exist "%BUILD_DIR%\NUL" (
            echo [WARN] First clean attempt failed, using PowerShell fallback...
            >> "%LOG_FILE%" echo [WARN] First clean attempt failed, using PowerShell fallback...
            powershell -NoProfile -ExecutionPolicy Bypass -Command "$p=[IO.Path]::GetFullPath('%BUILD_DIR%'); $root=[IO.Path]::GetFullPath('%~dp0'); if(-not $p.StartsWith($root,[StringComparison]::OrdinalIgnoreCase)){throw 'Refusing to delete outside LumaCore folder'}; for($i=1; $i -le 5 -and (Test-Path -LiteralPath $p); $i++){ try { Remove-Item -LiteralPath $p -Recurse -Force -ErrorAction Stop } catch { Write-Host ('delete attempt '+$i+' failed: '+$_.Exception.Message); Start-Sleep -Milliseconds 500 } }; if(Test-Path -LiteralPath $p){ exit 1 }" >> "%LOG_FILE%" 2>&1
            if exist "%BUILD_DIR%\NUL" (
                echo [ERROR] Failed to delete %BUILD_DIR% (file in use?)
                echo [ERROR] See %LOG_FILE% for details.
                if "%NO_PAUSE%"=="0" pause
                exit /b 1
            )
        )
    )
) else (
    echo [INFO] Incremental build. Pass --clean for full clean.
)

:: --- Locate cmake ---------------------------------------------------------
:: Search order: cmake on PATH first; otherwise the copy bundled with ANY
:: Visual Studio install (version folders 16..19 = VS2019..VS2026, all
:: editions). Keep every comment INSIDE if (...) blocks out of this file:
:: `::` labels abort the whole batch with "was unexpected at this time".
set "CMAKE_EXE=cmake"
where cmake >nul 2>&1
if !errorlevel! neq 0 (
    set "CMAKE_EXE="
    for %%R in ("%ProgramFiles%\Microsoft Visual Studio" "%ProgramFiles(x86)%\Microsoft Visual Studio") do (
        for /l %%V in (16,1,19) do (
            for %%E in (Community Professional Enterprise BuildTools Preview) do (
                if not defined CMAKE_EXE if exist "%%~R\%%V\%%E\Common7\IDE\CommonExtensions\Microsoft\CMake\CMake\bin\cmake.exe" set "CMAKE_EXE=%%~R\%%V\%%E\Common7\IDE\CommonExtensions\Microsoft\CMake\CMake\bin\cmake.exe"
            )
        )
    )
    if not defined CMAKE_EXE (
        echo [ERROR] cmake not found.
        echo [HINT]  Run:  winget install Kitware.CMake   then open a NEW terminal.
        echo [HINT]  Or:   Visual Studio Installer - Modify - Individual components -
        echo [HINT]        tick "C++ CMake tools for Windows", then re-run build.bat.
        if "%NO_PAUSE%"=="0" pause
        exit /b 1
    )
    echo [INFO] Using bundled cmake: !CMAKE_EXE!
)

:: --- Pick generator -------------------------------------------------------
:: Do NOT hardcode "Visual Studio 17 2022": that generator does not exist on
:: machines with only VS 2026 (folder 18). Strategy:
::   - Ninja Multi-Config only when ninja AND cl.exe are on PATH, i.e. we are
::     inside an MSVC Developer Prompt; otherwise Ninja cannot find cl.exe;
::   - otherwise pass NO -G at all: on Windows CMake picks the newest
::     installed Visual Studio automatically (17 = 2022, 18 = 2026, ...).
set "USE_NINJA=0"
where ninja >nul 2>&1
if !errorlevel! == 0 (
    where cl >nul 2>&1
    if !errorlevel! == 0 set "USE_NINJA=1"
)
if "!USE_NINJA!"=="1" (
    echo [INFO] Generator: Ninja Multi-Config
) else (
    echo [INFO] Generator: newest installed Visual Studio, platform x64
)
set "CMAKE_GENERATOR="
rem CMake 4.x bundled with VS 2026 dropped pre-3.5 policies and protobuf
rem v3.15.3 may still declare them; the variable below is the official escape
rem hatch. Older CMake versions simply ignore it.
set "CMAKE_POLICY_VERSION_MINIMUM=3.5"

:: --- Configure ------------------------------------------------------------
echo [STEP] Configuring...
>> "%LOG_FILE%" echo.
>> "%LOG_FILE%" echo [STEP] Configuring...
where git >nul 2>&1
if !errorlevel! neq 0 (
    echo [WARN] git not found - the FIRST configure downloads dependencies via git.
    echo [WARN] If configure fails with a git error, run:  winget install Git.Git
    echo [WARN] ...then open a NEW terminal and run build.bat again.
)
mkdir "%BUILD_DIR%" 2>nul
if "!USE_NINJA!"=="1" (
    "!CMAKE_EXE!" -S "%SOURCE_DIR%" -B "%BUILD_DIR%" -G "Ninja Multi-Config" >> "%LOG_FILE%" 2>&1
) else (
    "!CMAKE_EXE!" -S "%SOURCE_DIR%" -B "%BUILD_DIR%" -A x64 >> "%LOG_FILE%" 2>&1
)
if !errorlevel! neq 0 (
    echo [ERROR] Configure failed.
    type "%LOG_FILE%"
    if "%NO_PAUSE%"=="0" pause
    exit /b 1
)

:: --- Build ----------------------------------------------------------------
set "BUILD_FAILED=0"

if "%BUILD_RELEASE%"=="1" (
    echo.
    echo [STEP] Building Release...
    >> "%LOG_FILE%" echo.
    >> "%LOG_FILE%" echo [STEP] Building Release...
    "!CMAKE_EXE!" --build "%BUILD_DIR%" --config Release --parallel >> "%LOG_FILE%" 2>&1
    if !errorlevel! neq 0 (
        echo [WARN] Release build failed.
        set "BUILD_FAILED=1"
    )
)

if "%BUILD_DEBUG%"=="1" (
    echo.
    echo [STEP] Building Debug...
    >> "%LOG_FILE%" echo.
    >> "%LOG_FILE%" echo [STEP] Building Debug...
    "!CMAKE_EXE!" --build "%BUILD_DIR%" --config Debug --parallel >> "%LOG_FILE%" 2>&1
    if !errorlevel! neq 0 (
        echo [WARN] Debug build failed.
        set "BUILD_FAILED=1"
    )
)

:: --- Refuse to publish stale artifacts after any failed configuration -----
:: The old flow still copied existing build outputs after a failed build,
:: which could make an old DLL look like a successful fresh Release build.
if "%BUILD_FAILED%"=="1" (
    echo [ERROR] At least one configuration failed; refusing to copy possibly stale DLLs.
    >> "%LOG_FILE%" echo [ERROR] Copy skipped: one or more builds failed; existing outputs may be stale.
    if "%NO_PAUSE%"=="0" pause
    exit /b 1
)

:: --- Copy DLLs to Releases ------------------------------------------------
echo.
echo [STEP] Copying DLLs to %OUT_DIR%...

if "%BUILD_RELEASE%"=="1" (
    if exist "%BUILD_DIR%\Release\LumaCore.dll" (
        mkdir "%OUT_DIR%\Release" 2>nul
        copy /Y "%BUILD_DIR%\Release\LumaCore.dll" "%OUT_DIR%\Release\" >nul
        if exist "%BUILD_DIR%\Release\dwmapi.dll" (
            copy /Y "%BUILD_DIR%\Release\dwmapi.dll" "%OUT_DIR%\Release\" >nul
        )
        if exist "%BUILD_DIR%\Release\xinput1_4.dll" (
            copy /Y "%BUILD_DIR%\Release\xinput1_4.dll" "%OUT_DIR%\Release\" >nul
        )
        if exist "%BUILD_DIR%\Release\LumaCorePayload.dll" (
            copy /Y "%BUILD_DIR%\Release\LumaCorePayload.dll" "%OUT_DIR%\Release\" >nul
        )
        echo [OK] Release DLLs copied to %OUT_DIR%\Release
    ) else (
        echo [SKIP] Release LumaCore.dll not produced.
    )
)

if "%BUILD_DEBUG%"=="1" (
    if exist "%BUILD_DIR%\Debug\LumaCore.dll" (
        mkdir "%OUT_DIR%\Debug" 2>nul
        copy /Y "%BUILD_DIR%\Debug\LumaCore.dll" "%OUT_DIR%\Debug\" >nul
        if exist "%BUILD_DIR%\Debug\dwmapi.dll" (
            copy /Y "%BUILD_DIR%\Debug\dwmapi.dll" "%OUT_DIR%\Debug\" >nul
        )
        if exist "%BUILD_DIR%\Debug\xinput1_4.dll" (
            copy /Y "%BUILD_DIR%\Debug\xinput1_4.dll" "%OUT_DIR%\Debug\" >nul
        )
        if exist "%BUILD_DIR%\Debug\LumaCorePayload.dll" (
            copy /Y "%BUILD_DIR%\Debug\LumaCorePayload.dll" "%OUT_DIR%\Debug\" >nul
        )
        echo [OK] Debug DLLs copied to %OUT_DIR%\Debug
    ) else (
        echo [SKIP] Debug LumaCore.dll not produced.
    )
)

echo.
echo ============================================================
echo  Done. DLLs are in:
if "%BUILD_RELEASE%"=="1" echo    %OUT_DIR%\Release
if "%BUILD_DEBUG%"=="1"   echo    %OUT_DIR%\Debug
echo ============================================================
echo.
>> "%LOG_FILE%" echo.
>> "%LOG_FILE%" echo Done. Build failed flag: %BUILD_FAILED%

if "%NO_PAUSE%"=="0" pause
endlocal
exit /b %BUILD_FAILED%
