@echo off
REM =============================================================================
REM PURPOSE:
REM   Build windowed YTPM.exe and optionally zip it for multi-user distribution.
REM
REM INTERNAL LOGIC:
REM   1. Resolve YTPM_VENV from .env (build interpreter only).
REM   2. ensure_deps.py + PyInstaller + sync_docs / Help PDF.
REM   3. PyInstaller --noconfirm ytpm.spec → dist\YTPM\YTPM.exe.
REM   4. Copy end-user README.txt and .env.example into dist (never copy this
REM      machine's secret .env into dist automatically).
REM   5. If this script is run as Build_YTPM.bat --zip, run
REM      scripts\package_release.py to write release\YTPM-<ver>-windows.zip.
REM      Add --with-env to put this PC's .env (shared OAuth client) in the zip.
REM
REM EXAMPLE INVOCATION:
REM   Build_YTPM.bat
REM   Build_YTPM.bat --zip
REM   Build_YTPM.bat --zip --with-env
REM   Expected: dist\YTPM\YTPM.exe; with --zip also release\YTPM-*-windows.zip
REM =============================================================================

cd /d "%~dp0"
set "ROOT=%~dp0"
set "PACK_ZIP=0"
set "PACK_WITH_ENV=0"
if /i "%~1"=="--zip" set "PACK_ZIP=1"
if /i "%~2"=="--zip" set "PACK_ZIP=1"
if /i "%~1"=="--with-env" set "PACK_WITH_ENV=1"
if /i "%~2"=="--with-env" set "PACK_WITH_ENV=1"

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

"%PY%" -m pip install -q pyinstaller
if errorlevel 1 (
  echo Could not install PyInstaller.
  pause
  exit /b 1
)

"%PY%" "%ROOT%scripts\sync_docs.py"
"%PY%" "%ROOT%scripts\export_docs_pdf.py"

"%PY%" -m PyInstaller --noconfirm "%ROOT%ytpm.spec"
if errorlevel 1 (
  echo PyInstaller failed.
  pause
  exit /b 1
)

REM End-user files next to the exe (local dist for testing).
if exist "%ROOT%packaging\README_SHIP.txt" copy /Y "%ROOT%packaging\README_SHIP.txt" "%ROOT%dist\YTPM\README.txt" >nul
if exist "%ROOT%.env.example" copy /Y "%ROOT%.env.example" "%ROOT%dist\YTPM\.env.example" >nul
if exist "%ROOT%docs\YTPM_Tutorials_Help.pdf" copy /Y "%ROOT%docs\YTPM_Tutorials_Help.pdf" "%ROOT%dist\YTPM\YTPM_Tutorials_Help.pdf" >nul
REM Template .env only when missing so a local test .env is not wiped.
if not exist "%ROOT%dist\YTPM\.env" (
  if exist "%ROOT%.env.example" copy /Y "%ROOT%.env.example" "%ROOT%dist\YTPM\.env" >nul
)

echo.
echo Built: %ROOT%dist\YTPM\YTPM.exe
echo Keep YTPM.exe and _internal together. The exe does not use YTPM_VENV.

if "%PACK_ZIP%"=="1" (
  echo Creating release zip...
  if "%PACK_WITH_ENV%"=="1" (
    "%PY%" "%ROOT%scripts\package_release.py" --with-env
  ) else (
    "%PY%" "%ROOT%scripts\package_release.py"
  )
  if errorlevel 1 (
    echo Zip failed.
    pause
    exit /b 1
  )
)

pause
exit /b 0
