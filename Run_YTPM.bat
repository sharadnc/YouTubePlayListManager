@echo off
REM =============================================================================
REM PURPOSE:
REM   Compatibility stub: start the silent VBS launcher (no lingering CMD UI).
REM
REM INTERNAL LOGIC:
REM   Prefers Run_YTPM.vbs so users see no DOS prompt. A brief flash can still
REM   appear when this .bat is double-clicked; use Run_YTPM.vbs (or a shortcut
REM   to it) for a fully silent start. Optional --console runs the old visible
REM   ensure_deps path for troubleshooting.
REM
REM EXAMPLE INVOCATION:
REM   Double-click Run_YTPM.bat          → delegates to Run_YTPM.vbs
REM   Run_YTPM.bat --console             → visible dep check (debug)
REM =============================================================================

cd /d "%~dp0"
set "ROOT=%~dp0"

if /i "%~1"=="--console" goto :console

REM //B = batch mode (no script errors UI). wscript does not leave a console.
wscript.exe //nologo //B "%ROOT%Run_YTPM.vbs"
exit /b 0

:console
call "%ROOT%ytpm_resolve_venv.bat"
if errorlevel 1 (
  pause
  exit /b 1
)
if not exist "%PY%" (
  echo Venv python not found: %PY%
  echo Set YTPM_VENV in .env to your virtualenv root.
  pause
  exit /b 1
)
if not exist "%PYW%" (
  echo Venv pythonw not found: %PYW%
  echo Set YTPM_VENV in .env to your virtualenv root.
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
start "" /D "%ROOT%." "%PYW%" -B "%ROOT%ytpm_launch.pyw"
exit /b 0
