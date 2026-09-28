@echo off
setlocal
chcp 65001 >nul
set "PYTHONUTF8=1"
set "ROOT=%~dp0"
set "NO_OBSERVER="
if /i "%~2"=="--no-observer" set "NO_OBSERVER=--no-observer"

if "%~1"=="" (
    py -3 "%ROOT%run.py" %NO_OBSERVER%
) else (
    py -3 "%ROOT%run.py" --source "%~1" %NO_OBSERVER%
)
set "EXITCODE=%ERRORLEVEL%"

if "%~1"=="" pause
exit /b %EXITCODE%
