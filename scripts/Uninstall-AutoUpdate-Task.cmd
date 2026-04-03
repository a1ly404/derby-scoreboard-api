@echo off
setlocal

set "TASK_NAME=DerbyScoreboardAPIAutoUpdate"

echo Removing scheduled task %TASK_NAME% ...
schtasks /Delete /TN "%TASK_NAME%" /F

if %ERRORLEVEL% EQU 0 (
    echo Task removed.
) else (
    echo Task was not found or could not be removed.
)

echo.
pause
exit /b %ERRORLEVEL%
