@echo off
setlocal

rem Usage:
rem   scripts\bot_service.bat start
rem   scripts\bot_service.bat stop
rem   scripts\bot_service.bat restart
rem   scripts\bot_service.bat status
rem   scripts\bot_service.bat logs

set "HOST=5.255.125.171"
set "USER=root"
set "PASS=ab41367ccf9e"
set "SERVICE=telegram-reminder-bot"

if "%~1"=="" goto :help

set "ACTION=%~1"
if /I "%ACTION%"=="start" goto :start
if /I "%ACTION%"=="stop" goto :stop
if /I "%ACTION%"=="restart" goto :restart
if /I "%ACTION%"=="status" goto :status
if /I "%ACTION%"=="logs" goto :logs

echo Unknown action: %ACTION%
goto :help

:start
plink -ssh %USER%@%HOST% -pw "%PASS%" -batch "systemctl start %SERVICE% && systemctl is-active %SERVICE%"
goto :eof

:stop
plink -ssh %USER%@%HOST% -pw "%PASS%" -batch "systemctl stop %SERVICE% && systemctl is-active %SERVICE% || true"
goto :eof

:restart
plink -ssh %USER%@%HOST% -pw "%PASS%" -batch "systemctl restart %SERVICE% && systemctl is-active %SERVICE%"
goto :eof

:status
plink -ssh %USER%@%HOST% -pw "%PASS%" -batch "systemctl status %SERVICE% --no-pager"
goto :eof

:logs
plink -ssh %USER%@%HOST% -pw "%PASS%" -batch "journalctl -u %SERVICE% -n 80 --no-pager"
goto :eof

:help
echo.
echo Usage: %~nx0 ^<start^|stop^|restart^|status^|logs^>
echo.
echo Before use, update HOST/USER/PASS in this file if needed.
exit /b 1
