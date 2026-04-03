param(
    [ValidateSet("manual", "auto")]
    [string]$ModeOverride
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$ScriptsDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$RepoPath = Split-Path -Parent $ScriptsDir
$ConfigPath = Join-Path $RepoPath "updater.config.json"
$UpdateScript = Join-Path $ScriptsDir "Update-API.ps1"
$AutoScript = Join-Path $ScriptsDir "Auto-Update-API.ps1"

function Get-UpdaterConfig {
    if (-not (Test-Path $ConfigPath)) {
        throw "Config file not found: $ConfigPath"
    }

    $raw = Get-Content -Path $ConfigPath -Raw -Encoding utf8
    if ([string]::IsNullOrWhiteSpace($raw)) {
        throw "Config file is empty: $ConfigPath"
    }

    $cfg = $raw | ConvertFrom-Json
    if ($null -eq $cfg) {
        throw "Could not parse JSON config: $ConfigPath"
    }

    if ($null -eq $cfg.mode -or [string]::IsNullOrWhiteSpace([string]$cfg.mode)) {
        $cfg | Add-Member -NotePropertyName mode -NotePropertyValue "manual"
    }
    if ($null -eq $cfg.branch -or [string]::IsNullOrWhiteSpace([string]$cfg.branch)) {
        $cfg | Add-Member -NotePropertyName branch -NotePropertyValue "main"
    }
    if ($null -eq $cfg.checkIntervalSeconds) {
        $cfg | Add-Member -NotePropertyName checkIntervalSeconds -NotePropertyValue 120
    }
    if ($null -eq $cfg.scoreboardHost -or [string]::IsNullOrWhiteSpace([string]$cfg.scoreboardHost)) {
        $cfg | Add-Member -NotePropertyName scoreboardHost -NotePropertyValue "localhost"
    }
    if ($null -eq $cfg.scoreboardPort) {
        $cfg | Add-Member -NotePropertyName scoreboardPort -NotePropertyValue 8000
    }
    if ($null -eq $cfg.healthUrl -or [string]::IsNullOrWhiteSpace([string]$cfg.healthUrl)) {
        $cfg | Add-Member -NotePropertyName healthUrl -NotePropertyValue "http://localhost:5001/health"
    }

    return $cfg
}

try {
    Push-Location $RepoPath

    if (-not (Test-Path $UpdateScript)) {
        throw "Missing script: $UpdateScript"
    }
    if (-not (Test-Path $AutoScript)) {
        throw "Missing script: $AutoScript"
    }

    $cfg = Get-UpdaterConfig
    $mode = if ([string]::IsNullOrWhiteSpace($ModeOverride)) { [string]$cfg.mode } else { $ModeOverride }
    $mode = $mode.ToLowerInvariant()
    $healthUrl = ([string]$cfg.healthUrl)
    $apiPort = 5001
    $machineName = [System.Net.Dns]::GetHostName()

    if ($mode -eq "manual") {
        Write-Host "Running MANUAL update mode from config"
        & powershell -NoProfile -ExecutionPolicy Bypass -File $UpdateScript `
            -ScoreboardHost ([string]$cfg.scoreboardHost) `
            -ScoreboardPort ([int]$cfg.scoreboardPort) `
            -HealthUrl $healthUrl
        $exitCode = $LASTEXITCODE
        if ($exitCode -eq 0) {
            Write-Host ""
            Write-Host "=== API ENDPOINTS (share with clients) ==="
            Write-Host "  Health : http://$machineName`:$apiPort/health"
            Write-Host "  Live   : http://$machineName`:$apiPort/live"
            Write-Host "=========================================="
        }
        exit $exitCode
    }

    if ($mode -eq "auto") {
        Write-Host "Running AUTO update mode from config"
        & powershell -NoProfile -ExecutionPolicy Bypass -File $AutoScript `
            -Branch ([string]$cfg.branch) `
            -CheckIntervalSeconds ([int]$cfg.checkIntervalSeconds) `
            -ScoreboardHost ([string]$cfg.scoreboardHost) `
            -ScoreboardPort ([int]$cfg.scoreboardPort) `
            -HealthUrl $healthUrl
        exit $LASTEXITCODE
    }

    throw "Invalid mode '$mode' in $ConfigPath. Use 'manual' or 'auto'."
}
catch {
    Write-Host ("ERROR: " + $_.Exception.Message)
    exit 1
}
finally {
    Pop-Location
}
