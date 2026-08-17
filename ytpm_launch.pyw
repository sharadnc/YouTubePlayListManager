"""
PURPOSE:
    Silent GUI bootstrap for YTPM (no console window).

INTERNAL LOGIC:
    1. Seed .env from .env.example when missing.
    2. ensure_deps installs missing packages (pip runs without a console).
    3. Hand off to ytpm_gui.main() in this same pythonw process.

EXAMPLE INVOCATION:
    # Prefer Run_YTPM.vbs (picks pythonw from YTPM_VENV):
    wscript Run_YTPM.vbs
    # Or, already on the correct interpreter:
    pythonw -B ytpm_launch.pyw
"""

from __future__ import annotations

import logging
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

LOG_PATH = ROOT / "gui_crash.log"


def _seed_env() -> None:
    """
    PURPOSE:
        Create .env from .env.example on first run only.

    INTERNAL LOGIC:
        Skips when .env already exists so secrets are never overwritten.

    EXAMPLE INVOCATION:
        _seed_env()
    """
    env_path = ROOT / ".env"
    example = ROOT / ".env.example"
    if env_path.is_file() or not example.is_file():
        return
    shutil.copyfile(example, env_path)


def _configure_logging() -> None:
    """
    PURPOSE:
        Send bootstrap messages to gui_crash.log (pythonw has no console).

    INTERNAL LOGIC:
        File handler only; avoids StreamHandler under pythonw.

    EXAMPLE INVOCATION:
        _configure_logging()
    """
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
        handlers=[logging.FileHandler(LOG_PATH, encoding="utf-8")],
        force=True,
    )


def main() -> int:
    """
    PURPOSE:
        Ensure dependencies then open the YTPM window.

    INTERNAL LOGIC:
        ensure_deps.main(silent=True); on failure show MessageBox; else gui.main().

    EXAMPLE INVOCATION:
        raise SystemExit(main())
    """
    _seed_env()
    _configure_logging()
    log = logging.getLogger("ytpm.launch")
    try:
        import ensure_deps

        code = ensure_deps.main(silent=True)
        if code != 0:
            log.error("ensure_deps failed with code %s", code)
            try:
                from tkinter import messagebox

                messagebox.showerror(
                    "YouTube Playlist Manager",
                    "Could not install required Python packages.\n"
                    f"See details in:\n{LOG_PATH}",
                )
            except Exception:
                pass
            return code
    except Exception:
        log.exception("Dependency check failed")
        try:
            from tkinter import messagebox

            messagebox.showerror(
                "YouTube Playlist Manager",
                f"Startup dependency check failed.\nSee:\n{LOG_PATH}",
            )
        except Exception:
            pass
        return 1

    import ytpm_gui

    ytpm_gui.main()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
