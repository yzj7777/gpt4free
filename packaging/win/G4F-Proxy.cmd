@echo off
rem ---------------------------------------------------------------------------
rem  g4f proxy - zero-build launcher for Windows 11
rem
rem  Double-click this file.  It installs uv on first run (per-user, no admin),
rem  then starts the OpenAI-compatible proxy with an API key and agent routes.
rem
rem  Everything after the script name is forwarded to `g4f-api`, e.g.
rem      G4F-Proxy.cmd --port 9000 --dsh
rem ---------------------------------------------------------------------------
setlocal EnableExtensions
title g4f proxy
chcp 65001 >nul

set "ROOT=%~dp0..\.."
pushd "%ROOT%" 2>nul || (echo [!] cannot enter %ROOT% & pause & exit /b 1)

where uv >nul 2>nul
if errorlevel 1 (
  echo [*] uv not found - installing it for the current user ...
  powershell -NoProfile -ExecutionPolicy Bypass -Command "irm https://astral.sh/uv/install.ps1 | iex"
  set "PATH=%USERPROFILE%\.local\bin;%PATH%"
  where uv >nul 2>nul
  if errorlevel 1 (
    echo [!] uv install failed. Install it manually: https://docs.astral.sh/uv/
    pause
    popd
    exit /b 1
  )
)

echo [*] starting g4f proxy (first run downloads dependencies, ~1-2 min) ...
echo.
uv run --python 3.12 --project "%CD%" g4f-api %*
set "CODE=%ERRORLEVEL%"

echo.
if not "%CODE%"=="0" (
  echo [!] g4f-api exited with code %CODE%
)
echo Press any key to close this window ...
pause >nul
popd
exit /b %CODE%
