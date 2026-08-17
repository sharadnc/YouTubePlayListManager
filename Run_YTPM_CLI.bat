@echo off
REM =============================================================================
REM PURPOSE:
REM   Run the YTPM Typer CLI (python -m ytpm) with the venv from .env.
REM
REM INTERNAL LOGIC:
REM   1. cd to this script's folder so .env and the ytpm package resolve.
REM   2. ytpm_resolve_venv.bat reads YTPM_VENV and sets PY.
REM   3. Abort if that python.exe is missing.
REM   4. ensure_deps.py installs any missing packages from requirements.txt.
REM   5. Forward every extra argument (%*) to `python -m ytpm` and propagate
REM      that process's exit code to the caller (scripts/CI).
REM
REM EXAMPLE INVOCATION:
REM   Run_YTPM_CLI.bat --help
REM   Run_YTPM_CLI.bat auth
REM   Run_YTPM_CLI.bat sort "2024" --by title --dry-run
REM   Expected: CLI output in this console; exit code matches ytpm.
REM =============================================================================

cd /d "%~dp0"
set "ROOT=%~dp0"
call "%ROOT%ytpm_resolve_venv.bat"
if errorlevel 1 (
  pause
  exit /b 1
)

if not exist "%PY%" (
  echo Venv python not found: %PY%
  echo Set YTPM_VENV in .env to your virtualenv root ^(e.g. C:\PythonVenvs\venv^).
  pause
  exit /b 1
)

echo Checking Python libraries...
"%PY%" "%ROOT%ensure_deps.py"
if errorlevel 1 (
  echo Dependency install/check failed.
  pause
  exit /b 1
)

REM %* preserves quoting for playlist titles with spaces.
"%PY%" -m ytpm %*
exit /b %ERRORLEVEL%
