"""
PURPOSE:
    Export docs.html to a PDF (YTPM Tutorials / Help).

INTERNAL LOGIC:
    1. Resolve docs.html and docs/YTPM_Tutorials_Help.pdf under the project root.
    2. Launch Chrome or Edge headless with --print-to-pdf (no header/footer).
    3. Fail with a clear message if neither browser is found or the PDF is missing.

EXAMPLE INVOCATION:
    python scripts/export_docs_pdf.py
    # Expected: docs/YTPM_Tutorials_Help.pdf is created/updated
"""

from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path
from typing import List, Optional

ROOT = Path(__file__).resolve().parent.parent
HTML_PATH = ROOT / "docs.html"
DEFAULT_PDF = ROOT / "docs" / "YTPM_Tutorials_Help.pdf"

BROWSER_CANDIDATES: List[Path] = [
    Path(r"C:\Program Files\Google\Chrome\Application\chrome.exe"),
    Path(r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe"),
    Path(r"C:\Program Files\Microsoft\Edge\Application\msedge.exe"),
    Path(r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe"),
]


def find_browser() -> Optional[Path]:
    """
    PURPOSE:
        Locate Chrome or Edge for headless PDF printing.

    INTERNAL LOGIC:
        Returns the first existing path in BROWSER_CANDIDATES.

    EXAMPLE INVOCATION:
        find_browser()  # Path(.../chrome.exe) or None
    """
    for path in BROWSER_CANDIDATES:
        if path.is_file():
            return path
    return None


def html_file_url(html_path: Path) -> str:
    """
    PURPOSE:
        Build a file:// URL Chrome accepts for a local HTML file.

    INTERNAL LOGIC:
        Uses Path.as_uri() so spaces and drive letters are escaped correctly.

    EXAMPLE INVOCATION:
        html_file_url(Path(r"G:\\My Drive\\AI_Youtube\\docs.html"))
    """
    return html_path.resolve().as_uri()


def export_pdf(
    html_path: Path = HTML_PATH,
    pdf_path: Path = DEFAULT_PDF,
    browser: Optional[Path] = None,
) -> Path:
    """
    PURPOSE:
        Render docs.html to a multi-page PDF via Chromium headless print.

    INTERNAL LOGIC:
        --headless --print-to-pdf --no-pdf-header-footer; creates parent dirs.

    EXAMPLE INVOCATION:
        export_pdf()  # writes docs/YTPM_Tutorials_Help.pdf
    """
    if not html_path.is_file():
        raise FileNotFoundError(f"HTML not found: {html_path}")
    exe = browser or find_browser()
    if exe is None:
        raise RuntimeError(
            "Chrome or Edge not found. Install Google Chrome or Microsoft Edge, "
            "or pass --browser path\\to\\chrome.exe"
        )
    pdf_path = pdf_path.resolve()
    pdf_path.parent.mkdir(parents=True, exist_ok=True)
    if pdf_path.is_file():
        pdf_path.unlink()
    cmd = [
        str(exe),
        "--headless=new",
        "--disable-gpu",
        "--no-first-run",
        "--no-default-browser-check",
        "--no-pdf-header-footer",
        f"--print-to-pdf={pdf_path}",
        html_file_url(html_path),
    ]
    result = subprocess.run(cmd, capture_output=True, text=True, check=False)
    if not pdf_path.is_file():
        detail = (result.stderr or result.stdout or "").strip()
        raise RuntimeError(
            f"PDF was not created (exit {result.returncode}). {detail or 'No browser output.'}"
        )
    return pdf_path


def main(argv: Optional[List[str]] = None) -> int:
    """
    PURPOSE:
        CLI entry for exporting the Help page to PDF.

    INTERNAL LOGIC:
        Parses --html / --out / --browser; prints the output path.

    EXAMPLE INVOCATION:
        python scripts/export_docs_pdf.py --out docs/help.pdf
    """
    parser = argparse.ArgumentParser(description="Export docs.html to PDF")
    parser.add_argument(
        "--html",
        type=Path,
        default=HTML_PATH,
        help="Source HTML (default: project docs.html)",
    )
    parser.add_argument(
        "--out",
        type=Path,
        default=DEFAULT_PDF,
        help="Output PDF path (default: docs/YTPM_Tutorials_Help.pdf)",
    )
    parser.add_argument(
        "--browser",
        type=Path,
        default=None,
        help="Optional chrome.exe / msedge.exe path",
    )
    args = parser.parse_args(argv)
    try:
        out = export_pdf(html_path=args.html, pdf_path=args.out, browser=args.browser)
    except Exception as exc:
        print(f"export_docs_pdf failed: {exc}", file=sys.stderr)
        return 1
    print(f"Wrote {out} ({out.stat().st_size:,} bytes)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
