@echo off
setlocal
chcp 65001 >nul
set "PYTHONUTF8=1"
set "ROOT=%~dp0"

py -3 "%ROOT%install_centrum_shortcut.py" %*
set "EXITCODE=%ERRORLEVEL%"

if "%~1"=="" pause
exit /b %EXITCODE%
