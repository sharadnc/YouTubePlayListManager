"""
PURPOSE:
    Generate docs.html fragments from docs/gui-buttons.md and docs/cli.md.

INTERNAL LOGIC:
    Parses markdown tables and notes; replaces BEGIN/END:GUI_BUTTONS and
    BEGIN/END:CLI markers in docs.html so the HTML help page stays in sync.

EXAMPLE INVOCATION:
    python scripts/sync_docs.py
    # Expected: docs.html button and CLI sections match the markdown sources.
"""

from __future__ import annotations

import html
import re
import sys
from pathlib import Path
from typing import List

ROOT = Path(__file__).resolve().parent.parent
HTML_PATH = ROOT / "docs.html"
# Each (begin, end, markdown) triple is injected independently so docs.html
# can stay in sync with more than one source file.
FRAGMENTS: List[tuple[str, str, Path]] = [
    (
        "<!-- BEGIN:GUI_BUTTONS -->",
        "<!-- END:GUI_BUTTONS -->",
        ROOT / "docs" / "gui-buttons.md",
    ),
    (
        "<!-- BEGIN:CLI -->",
        "<!-- END:CLI -->",
        ROOT / "docs" / "cli.md",
    ),
]


def _cells(line: str) -> List[str]:
    """
    PURPOSE:
        Split a markdown table row into cell texts.

    INTERNAL LOGIC:
        Strips leading/trailing pipes and splits on |.

    EXAMPLE INVOCATION:
        _cells("| a | b |")  # ["a", "b"]
    """
    parts = [p.strip() for p in line.strip().strip("|").split("|")]
    return parts


def _is_sep(line: str) -> bool:
    """
    PURPOSE:
        Detect a markdown table separator row.

    INTERNAL LOGIC:
        Cells are only dashes and optional colons.

    EXAMPLE INVOCATION:
        _is_sep("| --- | ---: |")
    """
    if "|" not in line:
        return False
    return all(re.fullmatch(r":?-{3,}:?", c.replace(" ", "")) for c in _cells(line) if c)


def _inline(text: str) -> str:
    """
    PURPOSE:
        Convert a subset of markdown inline markup to HTML.

    INTERNAL LOGIC:
        Escapes, then bold, code, and a few HTML entities for < in prose.

    EXAMPLE INVOCATION:
        _inline("**Refresh** and `playlists.list`")
    """
    escaped = html.escape(text)
    escaped = re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", escaped)
    escaped = re.sub(r"`([^`]+)`", r"<code>\1</code>", escaped)
    return escaped


def md_tables_to_html(markdown: str) -> str:
    """
    PURPOSE:
        Turn a docs markdown file into the HTML fragment used by docs.html.

    INTERNAL LOGIC:
        Walks lines: skip H1, convert H2 to h3, tables, bullet notes, paragraphs.

    EXAMPLE INVOCATION:
        html_fragment = md_tables_to_html(Path("docs/gui-buttons.md").read_text())
    """
    lines = markdown.splitlines()
    body: List[str] = []
    i = 0
    while i < len(lines):
        line = lines[i]
        if line.startswith("# "):
            i += 1
            continue
        if line.startswith("## "):
            body.append(f"<h3>{html.escape(line[3:].strip())}</h3>")
            i += 1
            continue
        if line.strip() == "---":
            i += 1
            continue
        if line.startswith("|"):
            rows: List[List[str]] = []
            while i < len(lines) and lines[i].startswith("|"):
                if not _is_sep(lines[i]):
                    rows.append(_cells(lines[i]))
                i += 1
            if not rows:
                continue
            header, data = rows[0], rows[1:]
            last_header = header[-1].lower() if header else ""
            cost_col = (
                len(header) - 1
                if "cost" in last_header or last_header == "units"
                else -1
            )
            body.append('<div class="table-wrap">')
            body.append("<table>")
            body.append("<thead>")
            body.append("<tr>" + "".join(f"<th>{_inline(h)}</th>" for h in header) + "</tr>")
            body.append("</thead>")
            body.append("<tbody>")
            for row in data:
                cells_html: List[str] = []
                for idx, cell in enumerate(row):
                    cls = ' class="cost"' if idx == cost_col else ""
                    cells_html.append(f"<td{cls}>{_inline(cell)}</td>")
                body.append("<tr>" + "".join(cells_html) + "</tr>")
            body.append("</tbody>")
            body.append("</table>")
            body.append("</div>")
            continue
        if line.startswith("- "):
            body.append('<ul class="notes">')
            while i < len(lines) and (lines[i].startswith("- ") or lines[i].startswith("  - ")):
                raw = lines[i]
                if raw.startswith("  - "):
                    # Nested items are flattened as extra list items with a prefix.
                    body.append(f"<li>{_inline(raw[4:].strip())}</li>")
                else:
                    body.append(f"<li>{_inline(raw[2:].strip())}</li>")
                i += 1
            body.append("</ul>")
            continue
        if line.strip():
            body.append(f"<p>{_inline(line.strip())}</p>")
        i += 1
    return "\n".join(body) + "\n"


def _inject(html_text: str, begin: str, end: str, markdown_path: Path) -> str:
    """
    PURPOSE:
        Replace one marked region in docs.html with HTML generated from markdown.

    INTERNAL LOGIC:
        Requires both markers; raises if either is missing.

    EXAMPLE INVOCATION:
        html = _inject(html, BEGIN, END, Path("docs/cli.md"))
    """
    if begin not in html_text or end not in html_text:
        raise RuntimeError(f"Missing {begin} / {end} markers in {HTML_PATH}")
    fragment = md_tables_to_html(markdown_path.read_text(encoding="utf-8"))
    start = html_text.index(begin) + len(begin)
    stop = html_text.index(end)
    return html_text[:start] + "\n" + fragment + html_text[stop:]


def sync_docs() -> None:
    """
    PURPOSE:
        Rewrite marked regions of docs.html from docs/*.md sources.

    INTERNAL LOGIC:
        Injects gui-buttons.md then cli.md. Requires BEGIN/END markers.

    EXAMPLE INVOCATION:
        sync_docs()
    """
    html_text = HTML_PATH.read_text(encoding="utf-8")
    for begin, end, md_path in FRAGMENTS:
        html_text = _inject(html_text, begin, end, md_path)
        print(f"Updated {HTML_PATH} from {md_path}")
    HTML_PATH.write_text(html_text, encoding="utf-8")


if __name__ == "__main__":
    try:
        sync_docs()
    except Exception as exc:
        print(f"sync_docs failed: {exc}", file=sys.stderr)
        raise SystemExit(1) from exc
