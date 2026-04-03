param(
    [string]$Branch = "main",
    [int]$CheckIntervalSeconds = 120,
    [switch]$RunOnce,
    [string]$ScoreboardHost = "localhost",
    [int]$ScoreboardPort = 8000,
    [string]$HealthUrl = "http://localhost:5001/health"
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$RepoPath = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
$UpdateScript = Join-Path (Split-Path -Parent $MyInvocation.MyCommand.Path) "Update-API.ps1"
$LogDir = Join-Path $RepoPath "logs/autoupdater"
$LockDir = Join-Path $RepoPath "runtime"
$LockFile = Join-Path $LockDir "autoupdate.lock"

New-Item -ItemType Directory -Path $LogDir -Force | Out-Null
New-Item -ItemType Directory -Path $LockDir -Force | Out-Null
$LogFile = Join-Path $LogDir ("autoupdate-" + (Get-Date -Format "yyyyMMdd") + ".log")

function Write-Log {
    param([string]$Message)
    $line = "[{0}] {1}" -f (Get-Date -Format "yyyy-MM-dd HH:mm:ss"), $Message
    Write-Host $line
    Add-Content -Path $LogFile -Value $line
}

function Invoke-GitChecked {
    param([string]$Args)
    $output = (& git $Args.Split(" ")) 2>&1
    if ($LASTEXITCODE -ne 0) {
        throw "git $Args failed: $output"
    }
    return ($output | Out-String).Trim()
}

function Get-BehindCount {
    param([string]$TargetBranch)

    & git fetch origin $TargetBranch --prune | Out-Null
    if ($LASTEXITCODE -ne 0) {
        throw "git fetch origin $TargetBranch failed"
    }

    $count = & git rev-list --count ("HEAD..origin/" + $TargetBranch)
    if ($LASTEXITCODE -ne 0) {
        throw "git rev-list failed"
    }

    $raw = ($count | Out-String).Trim()
    $behind = 0
    if (-not [int]::TryParse($raw, [ref]$behind)) {
        throw "Unable to parse behind count: '$raw'"
    }
    return $behind
}

function Acquire-Lock {
    if (Test-Path $LockFile) {
        return $false
    }
    Set-Content -Path $LockFile -Value $PID -NoNewline -Encoding utf8
    return $true
}

function Release-Lock {
    if (Test-Path $LockFile) {
        Remove-Item -Path $LockFile -Force -ErrorAction SilentlyContinue
    }
}

function Run-UpdateIfNeeded {
    if (-not (Test-Path $UpdateScript)) {
        throw "Missing updater script: $UpdateScript"
    }

    $currentBranch = (& git rev-parse --abbrev-ref HEAD | Out-String).Trim()
    if ($currentBranch -ne $Branch) {
        Write-Log "Skipping check: current branch '$currentBranch' is not target '$Branch'"
        return
    }

    $behind = Get-BehindCount -TargetBranch $Branch
    if ($behind -le 0) {
        Write-Log "No new commits on origin/$Branch"
        return
    }

    Write-Log "Detected $behind new commit(s) on origin/$Branch. Running blue/green updater."
    & powershell -NoProfile -ExecutionPolicy Bypass -File $UpdateScript -ScoreboardHost $ScoreboardHost -ScoreboardPort $ScoreboardPort -HealthUrl $HealthUrl
    if ($LASTEXITCODE -ne 0) {
        throw "Update-API.ps1 failed with exit code $LASTEXITCODE"
    }

    $newHead = (& git rev-parse --short HEAD | Out-String).Trim()
    Write-Log "Auto-update successful. HEAD is now $newHead"
}

try {
    Push-Location $RepoPath

    if (-not (Get-Command git -ErrorAction SilentlyContinue)) {
        throw "git not found in PATH"
    }
    if (-not (Get-Command powershell -ErrorAction SilentlyContinue)) {
        throw "powershell not found in PATH"
    }

    if (-not (Acquire-Lock)) {
        Write-Log "Another auto-update process is running. Exiting."
        exit 0
    }

    if ($RunOnce) {
        Run-UpdateIfNeeded
        exit 0
    }

    Write-Log "Starting auto-update watcher for origin/$Branch every $CheckIntervalSeconds seconds"
    while ($true) {
        try {
            Run-UpdateIfNeeded
        }
        catch {
            Write-Log ("Watcher iteration error: " + $_.Exception.Message)
        }
        Start-Sleep -Seconds $CheckIntervalSeconds
    }
}
catch {
    Write-Log ("ERROR: " + $_.Exception.Message)
    exit 1
}
finally {
    Release-Lock
    Pop-Location
}
