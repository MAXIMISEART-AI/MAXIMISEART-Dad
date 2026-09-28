@echo off
setlocal DisableDelayedExpansion
if not "%~1"=="-3" (
  >&2 echo This CI py shim only supports py -3.
  exit /b 2
)
shift
set "python_arguments="
:collect_arguments
if "%~1"=="" goto invoke_python
set python_arguments=%python_arguments% %1
shift
goto collect_arguments
:invoke_python
python.exe %python_arguments%
exit /b %ERRORLEVEL%
