@echo off
setlocal

echo Stopping auto-update watcher processes...
for /f "tokens=2 delims=," %%P in ('tasklist /FI "IMAGENAME eq powershell.exe" /FO CSV /NH') do (
    powershell -NoProfile -Command "$pidNum = [int]('%%~P'); $cmd = (Get-CimInstance Win32_Process -Filter \"ProcessId=$pidNum\" -ErrorAction SilentlyContinue).CommandLine; if ($cmd -like '*Auto-Update-API.ps1*') { Stop-Process -Id $pidNum -Force; Write-Host \"Stopped PID $pidNum\" }"
)

echo Done.
pause
exit /b 0
