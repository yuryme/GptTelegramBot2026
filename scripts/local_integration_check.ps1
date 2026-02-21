param(
    [switch]$SkipTests = $false
)

$ErrorActionPreference = "Stop"

function Assert-LastExitCode {
    param([string]$StepName)
    if ($LASTEXITCODE -ne 0) {
        throw "Шаг '$StepName' завершился с ошибкой (exit code: $LASTEXITCODE)."
    }
}

Write-Host "[1/6] Проверка .env"
if (-not (Test-Path ".env")) {
    throw ".env не найден. Создайте его на основе .env.example"
}

Write-Host "[2/6] Проверка Docker daemon"
docker version | Out-Null
Assert-LastExitCode "Проверка Docker daemon"

Write-Host "[3/7] Сборка и запуск контейнеров"
docker compose down
Assert-LastExitCode "docker compose down"
docker compose up -d --build
Assert-LastExitCode "docker compose up"

Write-Host "[4/7] Ожидание PostgreSQL"
Start-Sleep -Seconds 5

Write-Host "[5/7] Применение миграций"
docker compose exec app alembic upgrade head
Assert-LastExitCode "alembic upgrade head"

Write-Host "[6/7] Проверка healthcheck (с ретраями)"
$healthOk = $false
for ($i = 1; $i -le 20; $i++) {
    try {
        $health = Invoke-RestMethod -Uri "http://127.0.0.1:8000/healthz" -Method GET -TimeoutSec 3
        if ($health.status -eq "ok") {
            $healthOk = $true
            break
        }
    } catch {
        Start-Sleep -Seconds 1
    }
}
if (-not $healthOk) {
    Write-Host "Healthcheck не прошел. Логи app-контейнера:"
    docker compose logs --tail=200 app
    Assert-LastExitCode "docker compose logs app"
    throw "Healthcheck не прошел после ретраев."
}

if (-not $SkipTests) {
    Write-Host "[7/7] Запуск pytest в контейнере"
    docker compose exec app python -m pip install --no-cache-dir -e ".[dev]"
    Assert-LastExitCode "install dev dependencies"
    docker compose exec app python -m pytest
    Assert-LastExitCode "pytest"
} else {
    Write-Host "[7/7] Тесты пропущены (SkipTests)"
}

Write-Host "Локальная интеграционная проверка завершена."
