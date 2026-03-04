@echo off
setlocal
if "%~1"=="" (
  echo Usage: %~nx0 ^<start^|stop^|restart^|status^|logs^>
  exit /b 1
)
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0local_bot.ps1" %1
