@echo off
REM =============================================================================
REM PURPOSE:
REM   Resolve YTPM_VENV from .env and set PY / PYW for the other launchers.
REM
REM INTERNAL LOGIC:
REM   1. Caller must set ROOT to the project folder (trailing backslash OK).
REM   2. Seed .env from .env.example when missing (never overwrite secrets).
REM   3. Parse YTPM_VENV= from .env (lines starting with # are ignored).
REM   4. Default venv root: C:\PythonVenvs\venv when unset or blank.
REM   5. Set PY and PYW to Scripts\python.exe and Scripts\pythonw.exe.
REM
REM EXAMPLE INVOCATION:
REM   set "ROOT=%~dp0"
REM   call "%ROOT%ytpm_resolve_venv.bat"
REM   Expected: PY and PYW point at the configured venv interpreters.
REM =============================================================================

if not defined ROOT (
  echo ytpm_resolve_venv.bat: ROOT is not set.
  exit /b 1
)

REM First-run config only; never overwrite an existing .env (secrets).
if not exist "%ROOT%.env" (
  if exist "%ROOT%.env.example" copy /Y "%ROOT%.env.example" "%ROOT%.env" >nul
)

set "YTPM_VENV="
if exist "%ROOT%.env" (
  for /f "usebackq eol=# tokens=1,* delims==" %%A in ("%ROOT%.env") do (
    if /i "%%~A"=="YTPM_VENV" set "YTPM_VENV=%%~B"
  )
)

REM Trim accidental spaces (common when editing .env in Notepad).
if defined YTPM_VENV for /f "tokens=* delims= " %%V in ("%YTPM_VENV%") do set "YTPM_VENV=%%V"

if not defined YTPM_VENV set "YTPM_VENV=C:\PythonVenvs\venv"
if "%YTPM_VENV%"=="" set "YTPM_VENV=C:\PythonVenvs\venv"

REM Strip a trailing backslash so Scripts joins cleanly.
if "%YTPM_VENV:~-1%"=="\" set "YTPM_VENV=%YTPM_VENV:~0,-1%"

set "PY=%YTPM_VENV%\Scripts\python.exe"
set "PYW=%YTPM_VENV%\Scripts\pythonw.exe"
exit /b 0
