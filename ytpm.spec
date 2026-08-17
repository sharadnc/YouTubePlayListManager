# -*- mode: python ; coding: utf-8 -*-
"""
PURPOSE:
    PyInstaller spec for a windowed YTPM.exe that does not need the shared venv.

INTERNAL LOGIC:
    onedir build; bundles docs.html, icon, and CustomTkinter/google hidden imports.
    Writable .env / token live next to the exe (see ytpm.config PROJECT_ROOT).

EXAMPLE INVOCATION:
    pyinstaller --noconfirm ytpm.spec
"""

from __future__ import annotations

from pathlib import Path

from PyInstaller.utils.hooks import collect_all, collect_submodules

ROOT = Path(SPECPATH)
datas = [
    (str(ROOT / "docs.html"), "."),
    (str(ROOT / "assets" / "ytpm.ico"), "assets"),
    (str(ROOT / ".env.example"), "."),
]
binaries: list = []
hiddenimports = [
    "customtkinter",
    "PIL",
    "googleapiclient",
    "googleapiclient.discovery",
    "google.auth",
    "google.oauth2",
    "google_auth_oauthlib",
    "google_auth_httplib2",
    "httplib2",
    "pydantic",
    "pydantic_settings",
    "dotenv",
    "typer",
    "rich",
]
for pkg in ("customtkinter", "googleapiclient"):
    pkg_datas, pkg_binaries, pkg_hidden = collect_all(pkg)
    datas += pkg_datas
    binaries += pkg_binaries
    hiddenimports += pkg_hidden
hiddenimports += collect_submodules("ytpm")

a = Analysis(
    [str(ROOT / "ytpm_gui.py")],
    pathex=[str(ROOT)],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        "matplotlib",
        "boto3",
        "botocore",
        "IPython",
        "notebook",
        "pandas",
        "scipy",
        "zmq",
        "jupyter",
    ],
    noarchive=False,
)
pyz = PYZ(a.pure)
exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="YTPM",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False,
    disable_windowed_traceback=False,
    icon=str(ROOT / "assets" / "ytpm.ico"),
)
coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name="YTPM",
)
