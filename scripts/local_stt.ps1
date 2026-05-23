param(
    [Parameter(Mandatory = $true)]
    [ValidateSet("start", "stop", "restart", "status", "health", "logs")]
    [string]$Action
)

$Root = Split-Path -Parent $PSScriptRoot
$RunDir = Join-Path $Root "run"
$PidFile = Join-Path $RunDir "stt_local.pid"
$LogFile = Join-Path $RunDir "stt_local.log"
$ErrFile = Join-Path $RunDir "stt_local.err.log"
$Python311 = Join-Path $env:LocalAppData "Programs\Python\Python311\python.exe"

if (-not (Test-Path $RunDir)) {
    New-Item -ItemType Directory -Path $RunDir | Out-Null
}

function Get-SttPid {
    if (-not (Test-Path $PidFile)) { return $null }
    $pidText = (Get-Content $PidFile -ErrorAction SilentlyContinue | Select-Object -First 1).Trim()
    if (-not $pidText) { return $null }
    return [int]$pidText
}

function Stop-Stt {
    $sttPid = Get-SttPid
    if ($sttPid) {
        Stop-Process -Id $sttPid -Force -ErrorAction SilentlyContinue
        Start-Sleep -Milliseconds 300
    }
    Remove-Item $PidFile -Force -ErrorAction SilentlyContinue
}

function Start-Stt {
    if (-not (Test-Path $Python311)) {
        throw "Python 3.11 not found: $Python311"
    }
    Stop-Stt
    $proc = Start-Process -FilePath $Python311 -ArgumentList "scripts/local_stt_server.py" -WorkingDirectory $Root -RedirectStandardOutput $LogFile -RedirectStandardError $ErrFile -PassThru
    $proc.Id | Set-Content $PidFile -Encoding ascii
    Write-Output "started pid=$($proc.Id)"
}

switch ($Action) {
    "start" {
        Start-Stt
    }
    "stop" {
        Stop-Stt
        Write-Output "stopped"
    }
    "restart" {
        Start-Stt
    }
    "status" {
        $sttPid = Get-SttPid
        if (-not $sttPid) {
            Write-Output "stopped"
            break
        }
        $p = Get-Process -Id $sttPid -ErrorAction SilentlyContinue
        if ($p) { Write-Output "running pid=$sttPid" } else { Write-Output "stopped" }
    }
    "health" {
        try {
            $health = Invoke-RestMethod -Uri "http://127.0.0.1:18100/healthz" -Method GET -TimeoutSec 3
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
