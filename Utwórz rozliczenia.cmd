@echo off
setlocal
chcp 65001 >nul
set "PYTHONUTF8=1"
set "ROOT=%~dp0"

if "%~1"=="" (
    py -3 "%ROOT%run.py"
) else (
    py -3 "%ROOT%run.py" --source "%~1"
)
set "EXITCODE=%ERRORLEVEL%"

if "%~1"=="" pause
exit /b %EXITCODE%
