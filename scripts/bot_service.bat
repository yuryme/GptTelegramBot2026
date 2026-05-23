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
set "SERVICE=telegram-reminder-bot"
set "SSH=ssh -o BatchMode=yes"

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
%SSH% %USER%@%HOST% "systemctl start %SERVICE% && systemctl is-active %SERVICE%"
goto :eof

:stop
%SSH% %USER%@%HOST% "systemctl stop %SERVICE% && systemctl is-active %SERVICE% || true"
goto :eof

:restart
%SSH% %USER%@%HOST% "systemctl restart %SERVICE% && systemctl is-active %SERVICE%"
goto :eof

:status
%SSH% %USER%@%HOST% "systemctl status %SERVICE% --no-pager"
goto :eof

:logs
%SSH% %USER%@%HOST% "journalctl -u %SERVICE% -n 80 --no-pager"
goto :eof

:help
echo.
echo Usage: %~nx0 ^<start^|stop^|restart^|status^|logs^>
echo.
echo Requires SSH key access for %USER%@%HOST%.
exit /b 1
