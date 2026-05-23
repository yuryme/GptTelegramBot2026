param(
    [Parameter(Mandatory = $true)]
    [ValidateSet("start", "stop", "restart", "status", "health", "logs")]
    [string]$Action
)

$Root = Split-Path -Parent $PSScriptRoot
$RunDir = Join-Path $Root "run"
$PidFile = Join-Path $RunDir "bot_local.pid"
$LogFile = Join-Path $RunDir "bot_local.log"
$ErrFile = Join-Path $RunDir "bot_local.err.log"
$VenvPython = Join-Path $Root ".venv\Scripts\python.exe"

if (-not (Test-Path $RunDir)) {
    New-Item -ItemType Directory -Path $RunDir | Out-Null
}

function Get-BotPid {
    if (-not (Test-Path $PidFile)) { return $null }
    $pidText = (Get-Content $PidFile -ErrorAction SilentlyContinue | Select-Object -First 1).Trim()
    if (-not $pidText) { return $null }
    return [int]$pidText
}

function Stop-Bot {
    $botPid = Get-BotPid
    if ($botPid) {
        Stop-Process -Id $botPid -Force -ErrorAction SilentlyContinue
        Start-Sleep -Milliseconds 300
    }
    Remove-Item $PidFile -Force -ErrorAction SilentlyContinue
}

switch ($Action) {
    "start" {
        if (-not (Test-Path $VenvPython)) {
            throw "Project venv Python not found: $VenvPython"
        }
        Stop-Bot
        $proc = Start-Process -FilePath $VenvPython -ArgumentList "scripts/local_run.py" -WorkingDirectory $Root -RedirectStandardOutput $LogFile -RedirectStandardError $ErrFile -PassThru
        $proc.Id | Set-Content $PidFile -Encoding ascii
        Write-Output "started pid=$($proc.Id)"
    }
    "stop" {
        Stop-Bot
        Write-Output "stopped"
    }
    "restart" {
        if (-not (Test-Path $VenvPython)) {
            throw "Project venv Python not found: $VenvPython"
        }
        Stop-Bot
        $proc = Start-Process -FilePath $VenvPython -ArgumentList "scripts/local_run.py" -WorkingDirectory $Root -RedirectStandardOutput $LogFile -RedirectStandardError $ErrFile -PassThru
        $proc.Id | Set-Content $PidFile -Encoding ascii
        Write-Output "restarted pid=$($proc.Id)"
    }
    "status" {
        $botPid = Get-BotPid
        if (-not $botPid) {
            Write-Output "stopped"
            break
        }
        $p = Get-Process -Id $botPid -ErrorAction SilentlyContinue
        if ($p) { Write-Output "running pid=$botPid" } else { Write-Output "stopped" }
    }
    "health" {
        try {
            $health = Invoke-RestMethod -Uri "http://127.0.0.1:18010/healthz" -Method GET -TimeoutSec 3
            $health | ConvertTo-Json -Compress
        } catch {
            Write-Output "health_failed: $($_.Exception.Message)"
            exit 1
        }
    }
    "logs" {
        if (Test-Path $LogFile) { Get-Content $LogFile -Tail 80 }
        if (Test-Path $ErrFile) { Get-Content $ErrFile -Tail 80 }
    }
}
