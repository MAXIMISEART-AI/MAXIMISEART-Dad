@echo off
REM MAXIMISEART-Dad daily workflow runner (Task Scheduler target)
REM Phase 5 gated deployment helper.

setlocal enabledelayedexpansion

REM Task Scheduler passes runtime path as first argument. Manual runs may use env var.
if not "%~1"=="" (
    set "DAD_RUNTIME_PATH=%~1"
)

REM Load paths from scheduler argument or env (DAD_RUNTIME_PATH must be set)
if "%DAD_RUNTIME_PATH%"=="" (
    echo ERROR: DAD_RUNTIME_PATH not set. Run init_wizard.py first.
    exit /b 1
)

cd /d "%~dp0.."

REM Use project venv explicitly so Task Scheduler does not depend on PATH.
if exist .venv\Scripts\python.exe (
    set "PYTHON_EXE=.venv\Scripts\python.exe"
) else (
    echo ERROR: .venv not found. Run: python -m venv .venv ^&^& pip install -r requirements.txt
    exit /b 1
)

REM Today's date (YYYY-MM-DD)
for /f "tokens=2 delims==" %%a in ('wmic OS Get localdatetime /value') do set datetime=%%a
set TODAY=%datetime:~0,4%-%datetime:~4,2%-%datetime:~6,2%

REM Run
"%PYTHON_EXE%" scripts\daily_workflow.py --date %TODAY% >> "%DAD_RUNTIME_PATH%\logs\cron-%TODAY%.log" 2>&1

exit /b %errorlevel%
