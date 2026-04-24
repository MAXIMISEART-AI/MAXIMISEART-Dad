@echo off
REM MAXIMISEART-Dad daily workflow runner (Task Scheduler target)
REM Phase 0 stub. Phase 5 integration.

setlocal enabledelayedexpansion

REM Load paths from .env (DAD_RUNTIME_PATH must be set)
if "%DAD_RUNTIME_PATH%"=="" (
    echo ERROR: DAD_RUNTIME_PATH not set. Run init_wizard.py first.
    exit /b 1
)

cd /d "%~dp0.."

REM Activate venv
if exist .venv\Scripts\activate.bat (
    call .venv\Scripts\activate.bat
) else (
    echo ERROR: .venv not found. Run: python -m venv .venv ^&^& pip install -r requirements.txt
    exit /b 1
)

REM Today's date (YYYY-MM-DD)
for /f "tokens=2 delims==" %%a in ('wmic OS Get localdatetime /value') do set datetime=%%a
set TODAY=%datetime:~0,4%-%datetime:~4,2%-%datetime:~6,2%

REM Run
python scripts\daily_workflow.py --date %TODAY% >> "%DAD_RUNTIME_PATH%\logs\cron-%TODAY%.log" 2>&1

exit /b %errorlevel%
