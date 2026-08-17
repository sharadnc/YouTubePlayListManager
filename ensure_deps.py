"""
PURPOSE:
    Ensure required Python packages are importable in the configured venv;
    install from requirements.txt when any dependency is missing.

INTERNAL LOGIC:
    1. Attempt to import each required module (any exception counts as missing,
       including TypeError from incompatible typer/click).
    2. If any import fails, run ``pip install -r requirements.txt`` without
       opening a console window on Windows (CREATE_NO_WINDOW).
    3. Re-run this script in a new interpreter so upgraded packages are not
       shadowed by in-process imports, then re-check.

EXAMPLE INVOCATION:
    python ensure_deps.py
    # Expected: exit 0 when all deps present (or after successful install)
    ensure_deps.main(silent=True)  # log only; for pythonw / VBS launch
"""

from __future__ import annotations

import importlib
import logging
import subprocess
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger("ytpm.ensure_deps")

# (import_name, pip_package hint for messages)
REQUIRED: List[Tuple[str, str]] = [
    ("customtkinter", "customtkinter"),
    ("googleapiclient", "google-api-python-client"),
    ("google_auth_oauthlib", "google-auth-oauthlib"),
    ("google.auth", "google-auth"),
    ("dotenv", "python-dotenv"),
    ("pydantic", "pydantic"),
    ("pydantic_settings", "pydantic-settings"),
    ("click", "click"),
    ("typer", "typer"),
    ("rich", "rich"),
    ("PIL", "Pillow"),
    ("certifi", "certifi"),
    ("truststore", "truststore"),
]


def _win_no_window_kwargs() -> Dict[str, Any]:
    """
    PURPOSE:
        Subprocess kwargs so pip does not flash a black console on Windows.

    INTERNAL LOGIC:
        CREATE_NO_WINDOW when available; empty dict on other platforms.

    EXAMPLE INVOCATION:
        subprocess.run(cmd, **_win_no_window_kwargs())
    """
    if sys.platform != "win32":
        return {}
    flag = getattr(subprocess, "CREATE_NO_WINDOW", 0x08000000)
    return {"creationflags": flag}


def _emit(message: str, *, silent: bool) -> None:
    """
    PURPOSE:
        Print or log a status line depending on silent mode.

    INTERNAL LOGIC:
        silent → logger.info; else print to stdout.

    EXAMPLE INVOCATION:
        _emit("Installing…", silent=True)
    """
    if silent:
        logger.info(message)
    else:
        print(message, flush=True)


def missing_modules() -> List[str]:
    """
    PURPOSE:
        Return human-readable names of packages that fail to import.

    INTERNAL LOGIC:
        Tries importlib.import_module for each REQUIRED entry.

    EXAMPLE INVOCATION:
        missing_modules()
        # Expected: [] or ["customtkinter", ...]
    """
    missing: List[str] = []
    for mod, pkg in REQUIRED:
        try:
            importlib.import_module(mod)
        except Exception as exc:
            # ImportError = missing. TypeError = installed but incompatible
            # (typer 0.25 + click 8.1: click.Choice is not subscriptable).
            logger.warning("Import check failed for %s (%s): %s", mod, pkg, exc)
            missing.append(pkg)
    return missing


def install_requirements(req_file: Path, *, silent: bool = False) -> int:
    """
    PURPOSE:
        Install pinned dependencies into the current interpreter's environment.

    INTERNAL LOGIC:
        ``python -m pip install -r requirements.txt`` with CREATE_NO_WINDOW
        on Windows so silent GUI launch does not show a DOS box.

    EXAMPLE INVOCATION:
        install_requirements(Path("requirements.txt"), silent=True)
        # Expected: 0 on success
    """
    _emit(f"Installing dependencies from {req_file} ...", silent=silent)
    result = subprocess.run(
        [sys.executable, "-m", "pip", "install", "-r", str(req_file)],
        check=False,
        **_win_no_window_kwargs(),
    )
    return int(result.returncode)


def main(*, silent: bool = False) -> int:
    """
    PURPOSE:
        CLI / silent entry for dependency ensure-or-install.

    INTERNAL LOGIC:
        Check → optional pip install → re-check → exit code.
        ``silent=True`` logs instead of printing (pythonw / VBS).

    EXAMPLE INVOCATION:
        raise SystemExit(main())
        ensure_deps.main(silent=True)
    """
    root = Path(__file__).resolve().parent
    req_file = root / "requirements.txt"
    if not silent:
        logging.basicConfig(
            level=logging.INFO, format="%(levelname)s %(name)s: %(message)s"
        )
    missing = missing_modules()
    if not missing:
        _emit("All required packages are available.", silent=silent)
        return 0
    _emit(f"Missing packages: {', '.join(missing)}", silent=silent)
    if not req_file.is_file():
        _emit(f"ERROR: {req_file} not found.", silent=silent)
        return 1
    code = install_requirements(req_file, silent=silent)
    if code != 0:
        _emit("pip install failed.", silent=silent)
        return code
    # Re-run in a new interpreter: a failed typer import can leave an old click
    # module cached, so in-process re-check would still look broken.
    if "--after-install" not in sys.argv:
        return int(
            subprocess.call(
                [sys.executable, str(Path(__file__).resolve()), "--after-install"],
                **_win_no_window_kwargs(),
            )
        )
    still = missing_modules()
    if still:
        _emit(f"Still missing after install: {', '.join(still)}", silent=silent)
        return 1
    _emit("Dependencies installed successfully.", silent=silent)
    return 0


if __name__ == "__main__":
    raise SystemExit(main(silent=False))
