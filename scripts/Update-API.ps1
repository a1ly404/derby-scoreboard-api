param(
    [string]$HealthUrl = "http://localhost:5001/health",
    [string]$ProxyHealthUrl = "http://localhost:5001/_proxy/health",
    [string]$ScoreboardHost = "localhost",
    [int]$ScoreboardPort = 8000,
    [int]$PublicPort = 5001,
    [int]$BackendPortA = 5002,
    [int]$BackendPortB = 5003,
    [int]$StartupTimeoutSec = 60,
    [int]$PollIntervalMs = 1000
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$RepoPath = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
$LogDir = Join-Path $RepoPath "logs/updater"
$RuntimeDir = Join-Path $RepoPath "runtime"
$ActivePortFile = Join-Path $RuntimeDir "active_backend_port.txt"
$ProxyPidFile = Join-Path $RuntimeDir "proxy.pid"
New-Item -ItemType Directory -Path $LogDir -Force | Out-Null
New-Item -ItemType Directory -Path $RuntimeDir -Force | Out-Null
$LogFile = Join-Path $LogDir ("update-" + (Get-Date -Format "yyyyMMdd-HHmmss") + ".log")

function Write-Log {
    param([string]$Message)
    $line = "[{0}] {1}" -f (Get-Date -Format "yyyy-MM-dd HH:mm:ss"), $Message
    Write-Host $line
    Add-Content -Path $LogFile -Value $line
}

function Test-CommandExists {
    param([string]$Name)
    return $null -ne (Get-Command $Name -ErrorAction SilentlyContinue)
}

function Get-BackendPidFile {
    param([int]$Port)
    return (Join-Path $RuntimeDir ("backend-" + $Port + ".pid"))
}

function Get-PidFromFile {
    param([string]$PidFile)
    if (-not (Test-Path $PidFile)) {
        return $null
    }

    $raw = (Get-Content -Path $PidFile -ErrorAction SilentlyContinue | Select-Object -First 1)
    if ([string]::IsNullOrWhiteSpace($raw)) {
        return $null
    }

    $procId = 0
    if ([int]::TryParse($raw, [ref]$procId)) {
        return $procId
    }
    return $null
}

function Save-Pid {
    param(
        [string]$PidFile,
        [int]$Pid
    )
    Set-Content -Path $PidFile -Value $Pid -NoNewline -Encoding utf8
}

function Test-PidRunning {
    param([int]$Pid)
    try {
        $p = Get-Process -Id $Pid -ErrorAction Stop
        return $null -ne $p
    }
    catch {
        return $false
    }
}

function Stop-ProcessFromPidFile {
    param([string]$PidFile)

    $procId = Get-PidFromFile -PidFile $PidFile
    if ($null -eq $procId) {
        return
    }

    if (Test-PidRunning -Pid $procId) {
        try {
            Write-Log "Stopping PID $procId from $PidFile"
            Stop-Process -Id $procId -Force -ErrorAction Stop
        }
        catch {
            Write-Log "Warning: failed stopping PID ${procId}: $($_.Exception.Message)"
        }
    }

    if (Test-Path $PidFile) {
        Remove-Item -Path $PidFile -Force -ErrorAction SilentlyContinue
    }
}

function Wait-ForHealthy {
    param(
        [string]$Url,
        [int]$TimeoutSec
    )

    $deadline = (Get-Date).AddSeconds($TimeoutSec)
    while ((Get-Date) -lt $deadline) {
        try {
            $resp = Invoke-WebRequest -Uri $Url -Method Get -TimeoutSec 3 -UseBasicParsing
            if ($resp.StatusCode -ge 200 -and $resp.StatusCode -lt 300) {
                return $true
            }
        }
        catch {
            # Startup race is expected.
        }
        Start-Sleep -Milliseconds $PollIntervalMs
    }
    return $false
}

function Read-ActiveBackendPort {
    if (-not (Test-Path $ActivePortFile)) {
        return $BackendPortA
    }
    $raw = (Get-Content -Path $ActivePortFile -ErrorAction SilentlyContinue | Select-Object -First 1).Trim()
    $port = 0
    if ([int]::TryParse($raw, [ref]$port)) {
        return $port
    }
    return $BackendPortA
}

function Write-ActiveBackendPort {
    param([int]$Port)
    Set-Content -Path $ActivePortFile -Value $Port -NoNewline -Encoding utf8
}

function Start-ProxyIfNeeded {
    $existingPid = Get-PidFromFile -PidFile $ProxyPidFile
    if ($null -ne $existingPid -and (Test-PidRunning -Pid $existingPid)) {
        Write-Log "Proxy already running with PID $existingPid"
        return
    }

    Stop-ProcessFromPidFile -PidFile $ProxyPidFile
    Write-Log "Starting proxy on port $PublicPort"
    $args = @(
        "proxy.py",
        "--host", "0.0.0.0",
        "--port", "$PublicPort",
        "--state-file", "$ActivePortFile",
        "--backend-host", "127.0.0.1",
        "--default-backend-port", "$BackendPortA"
    )
    $p = Start-Process -FilePath "python" -ArgumentList $args -WorkingDirectory $RepoPath -PassThru
    Save-Pid -PidFile $ProxyPidFile -Pid $p.Id

    if (-not (Wait-ForHealthy -Url $ProxyHealthUrl -TimeoutSec $StartupTimeoutSec)) {
        throw "Proxy did not become healthy at $ProxyHealthUrl"
    }
}

function Start-Backend {
    param([int]$Port)

    $pidFile = Get-BackendPidFile -Port $Port
    Stop-ProcessFromPidFile -PidFile $pidFile

    Write-Log "Starting backend on port $Port"
    $args = @(
        "main.py",
        "--host", "127.0.0.1",
        "--port", "$Port",
        "--scoreboard-host", "$ScoreboardHost",
        "--scoreboard-port", "$ScoreboardPort"
    )
    $p = Start-Process -FilePath "python" -ArgumentList $args -WorkingDirectory $RepoPath -PassThru
    Save-Pid -PidFile $pidFile -Pid $p.Id

    $backendHealth = "http://127.0.0.1:$Port/health"
    if (-not (Wait-ForHealthy -Url $backendHealth -TimeoutSec $StartupTimeoutSec)) {
        throw "Backend on port $Port failed health check: $backendHealth"
    }
}

function Ensure-BackendHealthy {
    param([int]$Port)
    $backendHealth = "http://127.0.0.1:$Port/health"
    if (-not (Wait-ForHealthy -Url $backendHealth -TimeoutSec 2)) {
        Start-Backend -Port $Port
    }
}

function Invoke-Checked {
    param(
        [Parameter(Mandatory = $true)][string]$Command,
        [Parameter(Mandatory = $true)][string]$FailureMessage
    )

    Write-Log ("> " + $Command)
    $output = Invoke-Expression $Command 2>&1
    if ($output) {
        $output | ForEach-Object { Write-Log $_.ToString() }
    }

    if ($LASTEXITCODE -ne 0) {
        throw "$FailureMessage (exit code $LASTEXITCODE)"
    }
}

try {
    Write-Log "Starting blue/green update process"
    Push-Location $RepoPath

    if (-not (Test-CommandExists "git")) {
        throw "git was not found in PATH"
    }

    if (-not (Test-CommandExists "python")) {
        throw "python was not found in PATH"
    }

    Invoke-Checked -Command "git rev-parse --is-inside-work-tree" -FailureMessage "This folder is not a git repository"

    $dirty = (git status --porcelain)
    if ($dirty) {
        throw "Working tree has local changes. Commit or stash changes before running updater."
    }

    Invoke-Checked -Command "git fetch --all --prune" -FailureMessage "git fetch failed"
    Invoke-Checked -Command "git pull --ff-only" -FailureMessage "git pull failed"
    Invoke-Checked -Command "python -m pip install -r requirements.txt" -FailureMessage "Dependency install failed"

    $activePort = Read-ActiveBackendPort
    if ($activePort -ne $BackendPortA -and $activePort -ne $BackendPortB) {
        $activePort = $BackendPortA
    }
    $standbyPort = if ($activePort -eq $BackendPortA) { $BackendPortB } else { $BackendPortA }

    Write-Log "Current active backend: $activePort"
    Write-Log "Standby backend target: $standbyPort"

    Write-ActiveBackendPort -Port $activePort
    Start-ProxyIfNeeded
    Ensure-BackendHealthy -Port $activePort
    Start-Backend -Port $standbyPort

    Write-Log "Swapping proxy from backend $activePort to $standbyPort"
    Write-ActiveBackendPort -Port $standbyPort

    if (-not (Wait-ForHealthy -Url $HealthUrl -TimeoutSec $StartupTimeoutSec)) {
        throw "Public API health failed after swap: $HealthUrl"
    }

    $oldPidFile = Get-BackendPidFile -Port $activePort
    Stop-ProcessFromPidFile -PidFile $oldPidFile

    Write-Log "Blue/green update completed successfully"
    exit 0
}
catch {
    Write-Log ("ERROR: " + $_.Exception.Message)
    exit 1
}
finally {
    Pop-Location
    Write-Log "Log file: $LogFile"
}
