@REM SteaMidra - Steam game setup and manifest tool (SFF)
@REM Copyright (c) 2025-2026 Midrag (https://github.com/Midrags)
@REM
@REM This file is part of SteaMidra.
@REM
@REM SteaMidra is free software: you can redistribute it and/or modify
@REM it under the terms of the GNU General Public License as published by
@REM the Free Software Foundation, either version 3 of the License, or
@REM (at your option) any later version.
@REM
@REM SteaMidra is distributed in the hope that it will be useful,
@REM but WITHOUT ANY WARRANTY; without even the implied warranty of
@REM MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
@REM GNU General Public License for more details.
@REM
@REM You should have received a copy of the GNU General Public License
@REM along with SteaMidra.  If not, see <https://www.gnu.org/licenses/>.
@echo off
setlocal EnableDelayedExpansion
chcp 65001 >nul 2>&1

REM Fully remove SteaMidra: [1/3] optionally delete added games,
REM [2/3] optionally remove LumaCore DLLs, [3/3] remove the app,
REM shortcuts, registry keys and Steam-side entries. Game saves
REM outside steamapps\common stay. .NET / VC++ redist stay.

echo [36m[1m
echo   ____  _             __  __ _     _
echo  / ___^|^| ^|_ ___  __ _^|  \/  (_) __^| ^|_ __ __ _
echo  \___ \^| __/ _ \/ _` ^| ^|\/^| ^| ^|/ _` ^| '__/ _` ^|
echo   ___) ^| ^|^|  __/ (_^| ^| ^|  ^| ^| ^| (_^| ^| ^| ^| (_^| ^|
echo  ^|____/ \__\___^|\__,_^|_^|  ^|_^|_^|\__,_^|_^|  \__,_^|[0m
echo [31m[1m  uninstall[0m

REM Locate Steam via registry.
set "STEAM="
for /f "tokens=2*" %%A in ('reg query "HKCU\Software\Valve\Steam" /v SteamPath 2^>nul ^| findstr SteamPath') do set "STEAM=%%B"
if "%STEAM%"=="" for /f "tokens=2*" %%A in ('reg query "HKLM\SOFTWARE\WOW6432Node\Valve\Steam" /v InstallPath 2^>nul ^| findstr InstallPath') do set "STEAM=%%B"
if "%STEAM%"=="" (
  echo [33m[SteaMidra][0m No Steam install found - Steam-side cleanup skipped.
) else (
  echo [32m[SteaMidra][0m Steam found at %STEAM%
)

echo [36m[1m==^>[0m [1m[1/3] Games added through SteaMidra[0m
REM Only entries SteaMidra itself fetched (saved_lua record) count as its games.
set "IDS="
if not "%STEAM%"=="" if exist "%STEAM%\config\stplug-in\*.lua" (
  for %%F in ("%STEAM%\config\stplug-in\*.lua") do set "IDS=!IDS! %%~nF"
  set "KNOWN= "
  if exist "%LOCALAPPDATA%\SteaMidra\saved_lua\*.lua" for %%F in ("%LOCALAPPDATA%\SteaMidra\saved_lua\*.lua") do set "KNOWN=!KNOWN!%%~nF "
  if exist "%~dp0saved_lua\*.lua" for %%F in ("%~dp0saved_lua\*.lua") do set "KNOWN=!KNOWN!%%~nF "
  set "FILTERED="
  for %%I in (!IDS!) do (
    echo !KNOWN! | findstr /C:" %%I " >nul && (
      set "FILTERED=!FILTERED! %%I"
    ) || (
      echo   - %%I (not added through SteaMidra - left alone)
    )
  )
  set "IDS=!FILTERED!"
)
if "!IDS!"=="" (
  echo [32m[SteaMidra][0m No SteaMidra-added games found - nothing to delete here.
) else (
  echo [33mSteaMidra-added games:[0m[1m!IDS![0m
  set /p DELGAMES="[33mDelete these games (folders + manifests + entries)? [y/N]: [0m"
  if /i "!DELGAMES!"=="y" (
    for %%I in (!IDS!) do (
      set "ACF=%STEAM%\steamapps\appmanifest_%%I.acf"
      if exist "!ACF!" (
        for /f "tokens=2 delims=?" %%D in ('powershell -NoProfile -Command "$t = Get-Content '!ACF!' -Raw; if ($t -match '\"installdir\"\s*\"([^\"]+)\"') { $Matches[1] }"') do set "GDIR=%%D"
        if defined GDIR if exist "%STEAM%\steamapps\common\!GDIR!" (
          rmdir /s /q "%STEAM%\steamapps\common\!GDIR!" && echo [32m[SteaMidra][0m Deleted !GDIR! || echo [33m[SteaMidra][0m Could not delete !GDIR!
        )
        del "!ACF!" 2>nul && echo [32m[SteaMidra][0m Removed appmanifest_%%I.acf
      )
      del "%STEAM%\config\stplug-in\%%I.lua" 2>nul
      if exist "%STEAM%\config\stplug-in\%%I" rmdir /s /q "%STEAM%\config\stplug-in\%%I" 2>nul
      del "%STEAM%\config\%%I.lua" 2>nul
      del "%APPDATA%\Microsoft\Windows\Start Menu\Programs\Games\*%%I*.lnk" 2>nul
    )
  ) else (
    echo [32m[SteaMidra][0m Games kept on disk.
  )
)

echo [36m[1m==^>[0m [1m[2/3] LumaCore injection[0m
set "HASLC=0"
if not "%STEAM%"=="" (
  if exist "%STEAM%\LumaCore.dll" set "HASLC=1"
  if exist "%STEAM%\xinput1_4.dll" set "HASLC=1"
)
if "%HASLC%"=="1" (
  set /p DELLUMA="[33mRemove LumaCore files from %STEAM%? [y/N]: [0m"
  if /i "!DELLUMA!"=="y" (
    taskkill /F /IM steam.exe /T >nul 2>&1
    timeout /t 3 /nobreak >nul
    del "%STEAM%\LumaCore.dll" "%STEAM%\LumaCorePayload.dll" "%STEAM%\xinput1_4.dll" "%STEAM%\dwmapi.dll" "%STEAM%\version.dll" 2>nul
    del "%STEAM%\bin\lcoverlay.dll" 2>nul
    if exist "%STEAM%\lumacore" rmdir /s /q "%STEAM%\lumacore" 2>nul
    del "%STEAM%\.steamidra_gl_cleaned" 2>nul
    echo [32m[SteaMidra][0m LumaCore removed.
  ) else (
    echo [32m[SteaMidra][0m LumaCore kept.
  )
) else (
  echo [32m[SteaMidra][0m LumaCore not installed - nothing to do.
)

echo [36m[1m==^>[0m [1m[3/3] SteaMidra app and leftovers[0m
taskkill /F /IM SteaMidra_GUI.exe /T >nul 2>&1
if exist "%LOCALAPPDATA%\SteaMidra\Uninstall.exe" (
  echo [32m[SteaMidra][0m Running the bundled uninstaller first...
  "%LOCALAPPDATA%\SteaMidra\Uninstall.exe" /S
  timeout /t 5 /nobreak >nul
)
if exist "%LOCALAPPDATA%\SteaMidra" rmdir /s /q "%LOCALAPPDATA%\SteaMidra" 2>nul
del "%USERPROFILE%\Desktop\SteaMidra.lnk" 2>nul
del "%PUBLIC%\Desktop\SteaMidra.lnk" 2>nul
if exist "%APPDATA%\Microsoft\Windows\Start Menu\Programs\SteaMidra" rmdir /s /q "%APPDATA%\Microsoft\Windows\Start Menu\Programs\SteaMidra" 2>nul
reg delete "HKCU\Software\Microsoft\Windows\CurrentVersion\Uninstall\SteaMidra" /f >nul 2>&1
reg delete "HKCU\Software\Midrags\SteaMidra" /f >nul 2>&1
reg delete "HKCU\SOFTWARE\Classes\*\shell\SteaMidra" /f >nul 2>&1
reg delete "HKCU\SOFTWARE\Classes\*\shell\SFF" /f >nul 2>&1
if not "%STEAM%"=="" (
  del "%STEAM%\.steamidra_gl_cleaned" 2>nul
)
set /p DELDATA="[33mAlso delete SteaMidra user data (save backups, caches in %%APPDATA%%\SteaMidra)? [y/N]: [0m"
if /i "%DELDATA%"=="y" (
  if exist "%APPDATA%\SteaMidra" rmdir /s /q "%APPDATA%\SteaMidra" 2>nul
  echo [32m[SteaMidra][0m User data deleted.
) else (
  echo [32m[SteaMidra][0m User data kept.
)

echo [32m[1mDone.[0m
