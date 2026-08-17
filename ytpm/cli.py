"""
PURPOSE:
    Typer CLI for YouTube Playlist Manager (auth, CRUD, list/trim, export, stats, gui).

INTERNAL LOGIC:
    Subcommands call ytpm.ops / list_mode / trim_mode; gui launches ytpm_gui.App.

EXAMPLE INVOCATION:
    python -m ytpm --help
    python -m ytpm auth
    python -m ytpm playlists
"""

from __future__ import annotations

import logging
import subprocess
import sys
from pathlib import Path
from typing import List, Optional

import typer
from rich.console import Console
from rich.table import Table

from ytpm import __version__
from ytpm.auth import AuthError, is_authenticated, run_oauth_flow
from ytpm.errors import PlaylistOrderError, QuotaExceededError
from ytpm.ops import cleanup, export, items, playlists, sort, stats
from ytpm.trim_mode import resolve_playlist_id, trim_all, trim_playlists

app = typer.Typer(
    name="ytpm",
    help="YouTube Playlist Manager — manage playlists via YouTube Data API.",
    no_args_is_help=True,
)
playlists_app = typer.Typer(help="Playlist CRUD")
items_app = typer.Typer(help="Playlist item add/remove")
list_app = typer.Typer(help="List mode (file-based edit)")
app.add_typer(playlists_app, name="playlists")
app.add_typer(items_app, name="items")
app.add_typer(list_app, name="list")

console = Console()
logger = logging.getLogger("ytpm")


def _setup_logging(verbose: bool = False) -> None:
    """
    PURPOSE:
        Configure root logging for CLI sessions.

    INTERNAL LOGIC:
        Sets INFO or DEBUG level with a simple format.

    EXAMPLE INVOCATION:
        _setup_logging(True)
    """
    level = logging.DEBUG if verbose else logging.INFO
    logging.basicConfig(level=level, format="%(levelname)s %(name)s: %(message)s")


def _require_auth() -> None:
    """
    PURPOSE:
        Abort CLI command if OAuth token is missing/invalid.

    INTERNAL LOGIC:
        Raises typer.Exit after printing guidance.

    EXAMPLE INVOCATION:
        _require_auth()
    """
    if not is_authenticated():
        console.print(
            "[red]Not authenticated.[/red] Run [bold]ytpm auth[/bold] "
            "or use Connect Google Account in the GUI."
        )
        raise typer.Exit(code=1)


@app.callback()
def main_callback(
    verbose: bool = typer.Option(False, "--verbose", "-v", help="Debug logging"),
) -> None:
    """
    PURPOSE:
        Global CLI options applied before subcommands.

    INTERNAL LOGIC:
        Configures logging from --verbose.

    EXAMPLE INVOCATION:
        ytpm -v playlists
    """
    _setup_logging(verbose)


@app.command("auth")
def cmd_auth(
    force: bool = typer.Option(False, "--force", help="Clear token and re-consent"),
) -> None:
    """Run Google OAuth browser consent for YouTube access."""
    try:
        run_oauth_flow(force=force)
    except AuthError as exc:
        console.print(f"[red]{exc}[/red]")
        raise typer.Exit(code=1) from exc
    console.print("[green]Authenticated successfully.[/green] Token saved.")


@app.command("gui")
def cmd_gui() -> None:
    """Launch the CustomTkinter GUI."""
    root = Path(__file__).resolve().parent.parent
    script = root / "ytpm_gui.py"
    if not script.is_file():
        console.print(f"[red]GUI script missing:[/red] {script}")
        raise typer.Exit(code=1)
    # Use current interpreter so shared-venv launches work.
    raise SystemExit(subprocess.call([sys.executable, str(script)]))


@playlists_app.callback(invoke_without_command=True)
def playlists_root(ctx: typer.Context) -> None:
    """List playlists when no subcommand is given."""
    if ctx.invoked_subcommand is None:
        list_cmd()


@playlists_app.command("list")
def list_cmd() -> None:
    """Print a table of the user's playlists."""
    _require_auth()
    rows = playlists.list_playlists()
    table = Table(title="Playlists")
    table.add_column("Title")
    table.add_column("Items", justify="right")
    table.add_column("Privacy")
    table.add_column("ID")
    for pl in rows:
        table.add_row(pl.title, str(pl.item_count), pl.privacy, pl.id)
    console.print(table)


@playlists_app.command("create")
def playlists_create(
    title: str = typer.Argument(..., help="Playlist title"),
    description: str = typer.Option("", "--description", "-d"),
    privacy: str = typer.Option("private", "--privacy", help="private|unlisted|public"),
) -> None:
    """Create a new playlist."""
    _require_auth()
    pl = playlists.create_playlist(title, description=description, privacy=privacy)
    console.print(f"[green]Created[/green] {pl.title} ({pl.id})")


@playlists_app.command("rename")
def playlists_rename(
    playlist: str = typer.Argument(..., help="Playlist id or exact title"),
    new_title: str = typer.Argument(..., help="New title"),
) -> None:
    """Rename a playlist by id or exact title."""
    _require_auth()
    pid = resolve_playlist_id(playlist)
    pl = playlists.rename_playlist(pid, new_title)
    console.print(f"[green]Renamed[/green] to {pl.title}")


@playlists_app.command("delete")
def playlists_delete(
    playlist: str = typer.Argument(..., help="Playlist id or exact title"),
    yes: bool = typer.Option(False, "--yes", "-y", help="Skip interactive confirm"),
    confirm_name: Optional[str] = typer.Option(
        None, "--confirm-name", help="Must equal playlist title"
    ),
) -> None:
    """Delete a playlist after typing its exact title to confirm."""
    _require_auth()
    pid = resolve_playlist_id(playlist)
    all_pl = {p.id: p for p in playlists.list_playlists()}
    pl = all_pl.get(pid)
    if not pl:
        console.print("[red]Playlist not found[/red]")
        raise typer.Exit(1)
    name = confirm_name
    if not yes:
        name = typer.prompt(f'Type the playlist name "{pl.title}" to confirm deletion')
    elif name is None:
        name = pl.title
    try:
        playlists.delete_playlist(pid, confirm_title=name, expected_title=pl.title)
    except ValueError as exc:
        console.print(f"[red]{exc}[/red]")
        raise typer.Exit(1) from exc
    console.print(f"[green]Deleted[/green] {pl.title}")


@playlists_app.command("clear")
def playlists_clear(
    playlist: str = typer.Argument(...),
    yes: bool = typer.Option(False, "--yes", "-y"),
    dry_run: bool = typer.Option(False, "--dry-run", help="Snapshot only; 0 writes"),
) -> None:
    """Remove all videos from a playlist (keeps the playlist)."""
    _require_auth()
    pid = resolve_playlist_id(playlist)
    if not dry_run and not yes and not typer.confirm(f"Clear all videos from {pid}?"):
        raise typer.Abort()
    n = playlists.clear_playlist(pid, dry_run=dry_run)
    verb = "Would delete" if dry_run else "Cleared"
    console.print(f"[green]{verb}[/green] {n} items")


@playlists_app.command("privacy")
def playlists_privacy(
    playlist: str = typer.Argument(...),
    status: str = typer.Argument(..., help="public|unlisted|private"),
) -> None:
    """Set playlist privacy (one playlists.update)."""
    _require_auth()
    allowed = {"public", "unlisted", "private"}
    if status not in allowed:
        console.print("[red]status must be public, unlisted, or private[/red]")
        raise typer.Exit(1)
    pid = resolve_playlist_id(playlist)
    pl = playlists.set_privacy(pid, status)
    console.print(f"[green]Privacy[/green] {pl.title} → {pl.privacy}")


@playlists_app.command("description")
def playlists_description(
    playlist: str = typer.Argument(...),
    text: str = typer.Argument(..., help="New description (empty string clears it)"),
) -> None:
    """Set playlist description (one playlists.update when text changes)."""
    _require_auth()
    pid = resolve_playlist_id(playlist)
    pl = playlists.set_description(pid, text)
    console.print(f"[green]Description[/green] {pl.title} ({len(pl.description)} chars)")


@items_app.command("add")
def items_add(
    playlist: str = typer.Argument(...),
    video_id: str = typer.Argument(..., help="YouTube video id"),
) -> None:
    """Add a video to a playlist."""
    _require_auth()
    pid = resolve_playlist_id(playlist)
    item = items.add_video(pid, video_id)
    console.print(f"[green]Added[/green] {video_id} as {item.id}")


@items_app.command("remove")
def items_remove(
    playlist_item_id: str = typer.Argument(..., help="playlistItem id"),
) -> None:
    """Remove a playlist item by its playlistItem id."""
    _require_auth()
    items.remove_items([playlist_item_id])
    console.print("[green]Removed[/green] item")


@items_app.command("rename")
def items_rename(
    video_id: str = typer.Argument(..., help="YouTube video id"),
    title: str = typer.Argument(..., help="New title (you must own the video)"),
) -> None:
    """Rename a video you uploaded (changes it everywhere on YouTube)."""
    _require_auth()
    try:
        new_title = items.rename_video_title(video_id, title)
    except (ValueError, PermissionError) as exc:
        console.print(f"[red]{exc}[/red]")
        raise typer.Exit(1) from exc
    console.print(f"[green]Renamed[/green] {video_id} → {new_title}")


@app.command("sort")
def cmd_sort(
    playlists_ref: Optional[List[str]] = typer.Argument(None, help="Playlist ids or titles"),
    by: str = typer.Option("title", "--by", help="title|date|duration|channel"),
    reverse: bool = typer.Option(False, "--reverse"),
    dry_run: bool = typer.Option(False, "--dry-run", help="Save list-mode file; 0 writes"),
    resume: bool = typer.Option(False, "--resume", help="Continue unfinished queued sorts"),
) -> None:
    """Sort playlists, or resume the sort queue after quota reset."""
    _require_auth()
    allowed = {"title", "date", "duration", "channel"}
    if by not in allowed:
        console.print("[red]--by must be title, date, duration, or channel[/red]")
        raise typer.Exit(1)
    if resume:
        note = sort.resume_sorts()
        console.print(note)
        return
    if not playlists_ref:
        console.print("[red]Pass playlist ids/titles, or --resume.[/red]")
        raise typer.Exit(1)
    ids = [resolve_playlist_id(ref) for ref in playlists_ref]
    note = sort.sort_many(ids, by=by, reverse=reverse, dry_run=dry_run)  # type: ignore[arg-type]
    console.print(note)


@app.command("export")
def cmd_export(
    playlist: str = typer.Argument(...),
    format: str = typer.Option("json", "--format", help="json"),
) -> None:
    """Export a playlist to structured JSON."""
    _require_auth()
    if format != "json":
        console.print("[red]Only json format is supported in v1[/red]")
        raise typer.Exit(1)
    pid = resolve_playlist_id(playlist)
    title = next((p.title for p in playlists.list_playlists() if p.id == pid), "")
    path = export.export_playlist_json(pid, title=title)
    console.print(f"[green]Exported[/green] {path}")


@list_app.command("export")
def list_export(
    playlists_ref: Optional[List[str]] = typer.Argument(
        None, help="Playlist ids/titles (default: all)"
    ),
) -> None:
    """Export selected playlists (or all) to list-mode text files."""
    _require_auth()
    from ytpm import list_mode

    if playlists_ref:
        wanted = [resolve_playlist_id(ref) for ref in playlists_ref]
        by_id = {p.id: p for p in playlists.list_playlists()}
        selected = [by_id[pid] for pid in wanted if pid in by_id]
        paths = list_mode.export_playlists(selected)
    else:
        paths = list_mode.export_all()
    console.print(f"[green]Wrote[/green] {len(paths)} list-mode files")


@list_app.command("apply")
def list_apply(
    dry_run: bool = typer.Option(False, "--dry-run", help="Print planned ops only"),
) -> None:
    """Apply list-mode file edits to remote playlists."""
    _require_auth()
    from ytpm import list_mode

    n = list_mode.apply_all(dry_run=dry_run)
    console.print(str(n))


@app.command("trim")
def cmd_trim(
    playlists_ref: Optional[List[str]] = typer.Argument(None, help="Playlist ids/titles"),
    all_playlists: bool = typer.Option(False, "--all", help="Trim every owned playlist"),
) -> None:
    """Remove duplicate videos from playlists (pass ids or --all)."""
    _require_auth()
    if playlists_ref:
        results = trim_playlists(playlists_ref)
    elif all_playlists:
        results = trim_all()
    else:
        console.print("[red]Pass playlist ids/titles, or --all to trim every playlist.[/red]")
        raise typer.Exit(1)
    for pid, removed in results:
        console.print(f"{pid}: removed {removed} duplicates")


@app.command("cleanup")
def cmd_cleanup(
    playlist: str = typer.Argument(...),
    remove: bool = typer.Option(False, "--remove", help="Delete broken items"),
    include_private: bool = typer.Option(False, "--private/--no-private", help="Also list videos that exist but are private"),
    include_unlisted: bool = typer.Option(False, "--unlisted/--no-unlisted", help="Also list videos that exist but are unlisted"),
) -> None:
    """Find (and optionally remove) deleted/unavailable playlist videos."""
    _require_auth()
    pid = resolve_playlist_id(playlist)
    if remove:
        n = cleanup.remove_broken(
            pid,
            include_private=include_private,
            include_unlisted=include_unlisted,
        )
        console.print(f"[green]Removed[/green] {n} broken items")
    else:
        broken = cleanup.find_broken(
            pid,
            include_private=include_private,
            include_unlisted=include_unlisted,
        )
        table = Table(title="Broken / restricted videos")
        table.add_column("Title")
        table.add_column("Status")
        table.add_column("Video ID")
        for item in broken:
            table.add_row(item.title, item.privacy_status, item.video_id)
        console.print(table)
        console.print(f"{len(broken)} item(s). Re-run with --remove to delete them.")


@app.command("stats")
def cmd_stats(playlist: str = typer.Argument(...)) -> None:
    """Print duration and channel statistics for a playlist."""
    _require_auth()
    pid = resolve_playlist_id(playlist)
    s = stats.playlist_stats(pid)
    console.print(f"Items: {s.item_count}")
    console.print(f"Total duration: {stats.format_duration(s.total_seconds)}")
    console.print(f"Average: {stats.format_duration(int(s.average_seconds))}")
    console.print(f"Longest: {s.longest_title} ({stats.format_duration(s.longest_seconds)})")
    console.print(f"Shortest: {s.shortest_title} ({stats.format_duration(s.shortest_seconds)})")
    console.print(f"Unique channels: {s.unique_channels}")


@app.command("version")
def cmd_version() -> None:
    """Print package version."""
    console.print(__version__)


if __name__ == "__main__":
    try:
        app()
    except QuotaExceededError as exc:
        console.print(f"[red]{exc}[/red]")
        raise SystemExit(1) from exc
    except PlaylistOrderError as exc:
        console.print(f"[red]{exc}[/red]")
        raise SystemExit(1) from exc
