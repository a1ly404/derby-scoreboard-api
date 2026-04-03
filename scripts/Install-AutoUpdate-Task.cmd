@echo off
setlocal

set "SCRIPT_DIR=%~dp0"
set "PS_SCRIPT=%SCRIPT_DIR%Auto-Update-API.ps1"
set "TASK_NAME=DerbyScoreboardAPIAutoUpdate"

echo Creating scheduled task %TASK_NAME% ...
schtasks /Create /TN "%TASK_NAME%" /SC ONSTART /RL HIGHEST /F /TR "powershell -NoProfile -ExecutionPolicy Bypass -File \"%PS_SCRIPT%\""

if %ERRORLEVEL% EQU 0 (
    echo Task created successfully.
    echo Starting task now...
    schtasks /Run /TN "%TASK_NAME%"
) else (
    echo Failed to create task. Run this file as Administrator.
)

echo.
pause
exit /b %ERRORLEVEL%
