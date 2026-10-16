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

REM Download the latest SteaMidra release from GitHub and run the installer.
REM Usage: install.bat [--pre]  (--pre = newest beta/prerelease, not just stable)
set "REPO=drappula/SFF"

echo [36m[1m
echo   ____  _             __  __ _     _           
echo  / ___^|^| ^|_ ___  __ _^|  \/  (_) __^| ^|_ __ __ _ 
echo  \___ \^| __/ _ \/ _` ^| ^|\/^| ^| ^|/ _` ^| '__/ _` ^|
echo   ___) ^| ^|^|  __/ (_^| ^| ^|  ^| ^| ^| (_^| ^| ^| ^| (_^| ^|
echo  ^|____/ \__\___^|\__,_^|_^|  ^|_^|_^|\__,_^|_^|  \__,_^|
echo [0m
echo [32m[1m  install[0m
echo [36m[1m==^>[0m [1m[1/2] Finding the latest release[0m
set "TMPJSON=%TEMP%\steamidra_release.json"
set "APIURL=https://api.github.com/repos/%REPO%/releases/latest"
set "PRE=0"
if /i "%~1"=="--pre" set "PRE=1"
if /i "%~1"=="--prerelease" set "PRE=1"
if /i "%~1"=="--beta" set "PRE=1"
if "%PRE%"=="1" set "APIURL=https://api.github.com/repos/%REPO%/releases?per_page=20"
powershell -NoProfile -ExecutionPolicy Bypass -Command "try { Invoke-WebRequest -Uri '%APIURL%' -OutFile '%TMPJSON%' -UseBasicParsing } catch { exit 1 }" || (
  echo [31m[SteaMidra][0m Could not reach GitHub releases. Check your connection.
  exit /b 1
)
set "PICK="
for /f "delims=" %%A in ('powershell -NoProfile -Command "$j = Get-Content '%TMPJSON%' -Raw ^| ConvertFrom-Json; if ($j -is [array]) { $r = $j ^| Where-Object { -not $_.draft } ^| Select-Object -First 1 } else { $r = $j }; $t = $r.tag_name; if ($r.prerelease) { $t = 'prerelease ' + $t }; $u = ($r.assets ^| Where-Object { $_.name -like '*-Setup.exe' } ^| Select-Object -First 1).browser_download_url; $t + '|' + $u"') do set "PICK=%%A"
del "%TMPJSON%" 2>nul
set "RTAG="
set "URL="
for /f "tokens=1* delims=|" %%T in ("!PICK!") do ( set "RTAG=%%T" & set "URL=%%U" )
if "!URL!"=="" (
  echo [31m[SteaMidra][0m No Setup.exe in the latest release. See https://github.com/%REPO%/releases
  exit /b 1
)
if "!RTAG:~0,11!"=="prerelease " (
  echo [33m[SteaMidra][0m Release !RTAG!: !URL!
) else (
  echo [32m[SteaMidra][0m Release !RTAG!: !URL!
)


echo [36m[1m==^>[0m [1m[2/2] Downloading and launching the installer[0m
set "SETUP=%TEMP%\SteaMidra-Setup.exe"
powershell -NoProfile -ExecutionPolicy Bypass -Command "try { Invoke-WebRequest -Uri '%URL%' -OutFile '%SETUP%' -UseBasicParsing } catch { exit 1 }" || (
  echo [31m[SteaMidra][0m Download failed. Retry or install manually from https://github.com/%REPO%/releases
  exit /b 1
)
echo [32m[SteaMidra][0m Starting the installer...
start "" "%SETUP%"
echo [32m[1mDone.[0m Finish setup in the installer window.
