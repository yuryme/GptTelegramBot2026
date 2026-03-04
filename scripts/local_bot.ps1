param(
    [Parameter(Mandatory = $true)]
    [ValidateSet("start", "stop", "restart", "status", "logs")]
    [string]$Action
)

$Root = Split-Path -Parent $PSScriptRoot
$RunDir = Join-Path $Root "run"
$PidFile = Join-Path $RunDir "bot_local.pid"
$LogFile = Join-Path $RunDir "bot_local.log"
$ErrFile = Join-Path $RunDir "bot_local.err.log"

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
        Stop-Bot
        $proc = Start-Process -FilePath "py" -ArgumentList "-m uvicorn --app-dir . app.main:app --host 0.0.0.0 --port 18010" -WorkingDirectory $Root -RedirectStandardOutput $LogFile -RedirectStandardError $ErrFile -PassThru
        $proc.Id | Set-Content $PidFile -Encoding ascii
        Write-Output "started pid=$($proc.Id)"
    }
    "stop" {
        Stop-Bot
        Write-Output "stopped"
    }
    "restart" {
        Stop-Bot
        $proc = Start-Process -FilePath "py" -ArgumentList "-m uvicorn --app-dir . app.main:app --host 0.0.0.0 --port 18010" -WorkingDirectory $Root -RedirectStandardOutput $LogFile -RedirectStandardError $ErrFile -PassThru
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
    "logs" {
        if (Test-Path $LogFile) { Get-Content $LogFile -Tail 80 }
        if (Test-Path $ErrFile) { Get-Content $ErrFile -Tail 80 }
    }
}
