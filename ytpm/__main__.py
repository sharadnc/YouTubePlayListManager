"""
PURPOSE:
    Allow ``python -m ytpm`` to launch the Typer CLI.

INTERNAL LOGIC:
    Delegates to ytpm.cli.app.

EXAMPLE INVOCATION:
    python -m ytpm --help
"""

from ytpm.cli import app
from ytpm.errors import PlaylistOrderError, QuotaExceededError

if __name__ == "__main__":
    try:
        app()
    except QuotaExceededError as exc:
        print(exc)
        raise SystemExit(1) from exc
    except PlaylistOrderError as exc:
        print(exc)
        raise SystemExit(1) from exc
