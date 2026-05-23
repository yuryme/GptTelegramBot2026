@echo off
setlocal
if "%~1"=="" (
  echo Usage: %~nx0 ^<start^|stop^|restart^|status^|health^|logs^>
  exit /b 1
)
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0local_stt.ps1" %1
