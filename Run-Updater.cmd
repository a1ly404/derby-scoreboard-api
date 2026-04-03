@echo off
setlocal

set "SCRIPT_DIR=%~dp0"
set "PS_SCRIPT=%SCRIPT_DIR%scripts\Run-Updater.ps1"

echo Derby Scoreboard API Config-Driven Updater
echo Mode is read from updater.config.json (manual or auto)
echo.

powershell -NoProfile -ExecutionPolicy Bypass -File "%PS_SCRIPT%"
set "EXIT_CODE=%ERRORLEVEL%"

echo.
if "%EXIT_CODE%"=="0" (
    echo Updater finished successfully.
) else (
    echo Updater failed. Check logs in logs\updater\ or logs\autoupdater\
)

pause
exit /b %EXIT_CODE%
