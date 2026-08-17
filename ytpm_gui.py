"""
PURPOSE:
    CustomTkinter GUI for YouTube Playlist Manager (PicVidMedia-style sidebar + trees).

INTERNAL LOGIC:
    1. Sets Windows AppUserModelID and window icon from assets/ytpm.ico.
    2. On launch, checks OAuth; shows Connect Google Account until authenticated.
    3. Loads playlists/videos on background threads; sidebar actions call ytpm.ops.

EXAMPLE INVOCATION:
    python ytpm_gui.py
    # Expected: dark blue-themed playlist manager window
"""

from __future__ import annotations

import json
import logging
import sys
import threading
import webbrowser
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple

import customtkinter as ctk
from tkinter import Menu, messagebox, ttk

ROOT = Path(__file__).resolve().parent
if getattr(sys, "frozen", False):
    ROOT = Path(sys.executable).resolve().parent
    BUNDLE_DIR = Path(getattr(sys, "_MEIPASS", ROOT))
else:
    BUNDLE_DIR = ROOT
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from ytpm.ssl_certs import configure_ssl

configure_ssl()

from ytpm.auth import AuthError, is_authenticated, run_oauth_flow
from ytpm.config import get_settings
from ytpm.errors import format_api_error
from ytpm.gui_prefs import merge_sash_into_settings, resolve_sash_pos
from ytpm.jobs import drop_job, list_jobs, move_job, pending_sorts
from ytpm.models import Playlist, PlaylistItem
from ytpm.ops import cleanup, export, items, playlists, sort, stats
from ytpm.ops.cleanup import broken_reason
from ytpm.ops.stats import format_duration
from ytpm.quota import WRITE_UNITS, meter_text, remaining_units
from ytpm.single_instance import acquire_or_activate
from ytpm.trim_mode import trim_playlists

ctk.set_appearance_mode("Dark")
ctk.set_default_color_theme("blue")

logger = logging.getLogger("ytpm.gui")
ICON_PATH = BUNDLE_DIR / "assets" / "ytpm.ico"
HELP_PATH = BUNDLE_DIR / "docs.html"
SETTINGS_PATH = ROOT / "gui_settings.json"
SNAPSHOT_PICK_LIMIT: int = 20


class _AuditLogHandler(logging.Handler):
    """
    PURPOSE:
        Forward write-audit log lines into the GUI sidebar log.

    INTERNAL LOGIC:
        Schedules App.log on the Tk thread so worker-thread writes appear live.

    EXAMPLE INVOCATION:
        logging.getLogger("ytpm.audit").addHandler(_AuditLogHandler(app))
    """

    def __init__(self, app: "App") -> None:
        super().__init__(level=logging.INFO)
        self._app = app

    def emit(self, record: logging.LogRecord) -> None:
        """
        PURPOSE:
            Deliver one audit record to the sidebar log.

        INTERNAL LOGIC:
            format() then after(0, log). Ignores errors if the window is gone.

        EXAMPLE INVOCATION:
            handler.emit(record)
        """
        try:
            msg = self.format(record)
            self._app.after(0, lambda m=msg: self._app.log(m))
        except Exception:
            pass


def set_windows_app_id(app_id: str = "AIYoutube.YTPM.1") -> None:
    """
    PURPOSE:
        Make the taskbar use this app's identity instead of pythonw.exe.

    INTERNAL LOGIC:
        Calls SetCurrentProcessExplicitAppUserModelID on Windows only.

    EXAMPLE INVOCATION:
        set_windows_app_id()
    """
    if sys.platform != "win32":
        return
    try:
        import ctypes

        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(app_id)
    except Exception as exc:
        logger.warning("Could not set AppUserModelID: %s", exc)


# Per-tree sort metadata: base heading labels, last sorted column, reverse flag.
_TREE_SORT: Dict[int, Dict[str, Any]] = {}


def _duration_to_seconds(raw: str) -> Optional[int]:
    """
    PURPOSE:
        Parse displayed duration (M:SS or H:MM:SS) into seconds for numeric sort.

    INTERNAL LOGIC:
        Splits on colon; 2 parts = minutes:seconds, 3 parts = hours:minutes:seconds.

    EXAMPLE INVOCATION:
        _duration_to_seconds("1:02:05")  # 3725
    """
    parts = (raw or "").strip().split(":")
    if not parts or any(not p.isdigit() for p in parts):
        return None
    try:
        nums = [int(p) for p in parts]
    except ValueError:
        return None
    if len(nums) == 2:
        return nums[0] * 60 + nums[1]
    if len(nums) == 3:
        return nums[0] * 3600 + nums[1] * 60 + nums[2]
    return None


def _sort_key(raw: str) -> Tuple[int, Any]:
    """
    PURPOSE:
        Build a comparable sort key from a Treeview cell value.

    INTERNAL LOGIC:
        Prefers duration, then number, then case-insensitive text. Tuple prefix
        keeps types from mixing (numbers before text).

    EXAMPLE INVOCATION:
        _sort_key("28:25")  # (0, 1705)
    """
    text = (raw or "").strip()
    seconds = _duration_to_seconds(text)
    if seconds is not None and ":" in text:
        return (0, seconds)
    try:
        return (0, float(text))
    except (TypeError, ValueError):
        return (1, text.lower())


def register_sortable_tree(tree: ttk.Treeview, headings: Dict[str, str]) -> None:
    """
    PURPOSE:
        Enable Windows-style header sort (click to toggle) with ▲/▼ indicators.

    INTERNAL LOGIC:
        Stores base labels; heading command + Button-1 identify_region (CustomTkinter
        often swallows ttk heading commands). Ctrl+A selects all rows.

    EXAMPLE INVOCATION:
        register_sortable_tree(tree, {"title": "Title", "count": "Items"})
    """
    _TREE_SORT[id(tree)] = {"labels": dict(headings), "col": None, "reverse": False}

    for col, text in headings.items():
        tree.heading(col, text=text, anchor="w", command=lambda: None)

    def on_click(event: Any) -> Optional[str]:
        region = tree.identify_region(event.x, event.y)
        if region != "heading":
            return None
        col_id = tree.identify_column(event.x)
        if not col_id or col_id == "#0":
            return None
        try:
            index = int(col_id.replace("#", "")) - 1
        except ValueError:
            return None
        columns = list(tree.cget("columns"))
        if index < 0 or index >= len(columns):
            return None
        treeview_sort_column(tree, str(columns[index]))
        return "break"

    tree.bind("<Button-1>", on_click, add="+")

    def select_all(_event: Any = None) -> str:
        children = tree.get_children("")
        if children:
            tree.selection_set(children)
            tree.focus(children[-1])
        return "break"

    tree.bind("<Control-a>", select_all)
    tree.bind("<Control-A>", select_all)


def apply_default_tree_sort(tree: ttk.Treeview, col: str) -> None:
    """
    PURPOSE:
        Restore the table's default ascending sort after a reload or filter.

    INTERNAL LOGIC:
        Calls treeview_sort_column with reverse=False so the heading shows ▲
        and rows are ordered by col (Title for playlists, # for videos).

    EXAMPLE INVOCATION:
        apply_default_tree_sort(self.pl_tree, "title")
        apply_default_tree_sort(self.vid_tree, "pos")
    """
    treeview_sort_column(tree, col, reverse=False)


def treeview_sort_column(tree: ttk.Treeview, col: str, reverse: Optional[bool] = None) -> None:
    """
    PURPOSE:
        Sort Treeview rows when a column heading is clicked.

    INTERNAL LOGIC:
        Numeric/duration-aware keys; toggles direction on the same column;
        updates heading labels with ▲/▼.

    EXAMPLE INVOCATION:
        treeview_sort_column(tree, "title")
    """
    state = _TREE_SORT.setdefault(id(tree), {"labels": {}, "col": None, "reverse": False})
    labels: Dict[str, str] = state["labels"]
    if reverse is None:
        reverse = bool(state["col"] == col and not state["reverse"])
    rows: List[Tuple[Any, str]] = []
    for iid in tree.get_children(""):
        rows.append((_sort_key(tree.set(iid, col)), iid))
    rows.sort(reverse=reverse)
    for index, (_key, iid) in enumerate(rows):
        tree.move(iid, "", index)
    state["col"] = col
    state["reverse"] = reverse
    arrow = " ▼" if reverse else " ▲"
    for name, base in labels.items():
        suffix = arrow if name == col else ""
        tree.heading(name, text=f"{base}{suffix}", anchor="w", command=lambda: None)


def style_treeview() -> None:
    """
    PURPOSE:
        Apply PicVidMedia-like dark styling to ttk.Treeview.

    INTERNAL LOGIC:
        Configures Treeview and Heading colors/fonts.

    EXAMPLE INVOCATION:
        style_treeview()
    """
    style = ttk.Style()
    try:
        style.theme_use("clam")
    except Exception:
        pass
    style.configure(
        "Treeview",
        background="#2b2b2b",
        foreground="white",
        fieldbackground="#2b2b2b",
        borderwidth=0,
        rowheight=30,
    )
    style.configure(
        "Treeview.Heading",
        background="#1f538d",
        foreground="white",
        relief="flat",
        font=("Segoe UI", 10, "bold"),
        anchor="w",
        padding=(8, 4),
    )
    style.map("Treeview", background=[("selected", "#1f538d")])
    style.map("Treeview.Heading", background=[("active", "#163a66")])


class App(ctk.CTk):
    """
    PURPOSE:
        Main YouTube Playlist Manager window.

    INTERNAL LOGIC:
        Sidebar auth + actions; dual Treeviews for playlists and videos; worker threads.

    EXAMPLE INVOCATION:
        app = App()
        app.mainloop()
    """

    def __init__(self) -> None:
        """
        PURPOSE:
            Build UI, apply icon, restore settings, start auth gate.

        INTERNAL LOGIC:
            Constructs sidebar/main; disables actions until authenticated.

        EXAMPLE INVOCATION:
            App()
        """
        set_windows_app_id()
        super().__init__()

        self.title("YouTube Playlist Manager")
        self.geometry("1200x800")
        self.minsize(980, 700)
        self._apply_icon()

        self._busy: bool = False
        self._pending_playlist_id: Optional[str] = None
        self._item_cache: Dict[str, List[PlaylistItem]] = {}
        self._playlist_filter: str = ""
        self._video_filter: str = ""
        self._playlists: List[Playlist] = []
        self._items: List[PlaylistItem] = []
        self._item_by_iid: Dict[str, PlaylistItem] = {}
        self._playlist_by_iid: Dict[str, Playlist] = {}
        self._selected_playlist_id: Optional[str] = None
        self._last_table: str = "pl"
        self.settings: Dict[str, Any] = self._load_settings()

        geo = self.settings.get("geometry")
        if isinstance(geo, str) and "x" in geo:
            try:
                self.geometry(geo)
            except Exception as exc:
                logger.warning("Could not restore geometry: %s", exc)

        self.grid_columnconfigure(1, weight=1)
        self.grid_rowconfigure(0, weight=1)
        style_treeview()
        self._build_sidebar()
        self._build_main()
        self._restore_filters()
        self._bind_hotkeys()
        self._attach_audit_log()
        self._refresh_quota_meter()
        self.protocol("WM_DELETE_WINDOW", self._on_close)
        self.after(80, self._restore_sash)

        self.after(100, self._bootstrap_auth)

    def _apply_icon(self) -> None:
        """
        PURPOSE:
            Set window and taskbar icon from assets/ytpm.ico.

        INTERNAL LOGIC:
            iconbitmap + iconphoto fallback when file exists.

        EXAMPLE INVOCATION:
            self._apply_icon()
        """
        if not ICON_PATH.is_file():
            logger.warning("Icon missing: %s", ICON_PATH)
            return
        try:
            self.iconbitmap(default=str(ICON_PATH))
        except Exception:
            try:
                self.iconbitmap(str(ICON_PATH))
            except Exception as exc:
                logger.warning("iconbitmap failed: %s", exc)
        try:
            from PIL import Image, ImageTk

            img = Image.open(ICON_PATH)
            self._icon_photo = ImageTk.PhotoImage(img.resize((32, 32)))
            self.iconphoto(True, self._icon_photo)
        except Exception as exc:
            logger.warning("iconphoto failed: %s", exc)

    def _load_settings(self) -> Dict[str, Any]:
        """
        PURPOSE:
            Load gui_settings.json preferences.

        INTERNAL LOGIC:
            Returns {} on missing/invalid file.

        EXAMPLE INVOCATION:
            self._load_settings()
        """
        if SETTINGS_PATH.is_file():
            try:
                return json.loads(SETTINGS_PATH.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError) as exc:
                logger.warning("Settings load failed: %s", exc)
        return {}

    def _save_settings(self) -> None:
        """
        PURPOSE:
            Persist window layout, filters, and last playlist id.

        INTERNAL LOGIC:
            Captures geometry, paned sash (only if both panes are visible),
            and filter entry text; writes JSON.

        EXAMPLE INVOCATION:
            self._save_settings()
        """
        try:
            self.settings["geometry"] = self.winfo_geometry()
            if hasattr(self, "filter_entry"):
                self.settings["playlist_filter"] = self.filter_entry.get()
            if hasattr(self, "video_filter_entry"):
                self.settings["video_filter"] = self.video_filter_entry.get()
            if hasattr(self, "_split"):
                try:
                    merge_sash_into_settings(
                        self.settings,
                        int(self._split.sashpos(0)),
                        int(self._split.winfo_height()),
                    )
                except Exception:
                    pass
            SETTINGS_PATH.write_text(json.dumps(self.settings, indent=2), encoding="utf-8")
        except OSError as exc:
            logger.warning("Settings save failed: %s", exc)

    def _restore_filters(self) -> None:
        """
        PURPOSE:
            Put last filter strings back into the search boxes.

        INTERNAL LOGIC:
            Reads settings keys; updates _playlist_filter / _video_filter.

        EXAMPLE INVOCATION:
            self._restore_filters()
        """
        pf = str(self.settings.get("playlist_filter") or "")
        vf = str(self.settings.get("video_filter") or "")
        if pf:
            self.filter_entry.insert(0, pf)
            self._playlist_filter = pf.strip().lower()
        if vf:
            self.video_filter_entry.insert(0, vf)
            self._video_filter = vf.strip().lower()

    def _restore_sash(self, attempt: int = 0) -> None:
        """
        PURPOSE:
            Apply the playlist/videos split after the paned window is mapped.

        INTERNAL LOGIC:
            Retries until the pane has a real height. Uses the saved fraction
            or pixels; first launch and sash=0 become 50/50.

        EXAMPLE INVOCATION:
            self.after(80, self._restore_sash)
        """
        try:
            self.update_idletasks()
            height = int(self._split.winfo_height())
            pos = resolve_sash_pos(self.settings, height)
            if pos is None:
                if attempt < 25:
                    self.after(50, lambda: self._restore_sash(attempt + 1))
                return
            self._split.sashpos(0, pos)
        except Exception as exc:
            logger.warning("Could not restore sash: %s", exc)

    def _attach_audit_log(self) -> None:
        """
        PURPOSE:
            Show each API write (id, method, units) in the sidebar log.

        INTERNAL LOGIC:
            Adds _AuditLogHandler to ytpm.audit (idempotent per App).

        EXAMPLE INVOCATION:
            self._attach_audit_log()
        """
        audit = logging.getLogger("ytpm.audit")
        audit.setLevel(logging.INFO)
        self._audit_handler = _AuditLogHandler(self)
        self._audit_handler.setFormatter(logging.Formatter("%(message)s"))
        audit.addHandler(self._audit_handler)

    def _bind_hotkeys(self) -> None:
        """
        PURPOSE:
            F2 rename, Del remove, Ctrl+F videos filter, Enter opens Studio.

        INTERNAL LOGIC:
            bind_all with an entry-field guard so typing is not stolen.

        EXAMPLE INVOCATION:
            self._bind_hotkeys()
        """
        self.bind_all("<F2>", self._hotkey_f2)
        self.bind_all("<Delete>", self._hotkey_delete)
        self.bind_all("<Control-f>", self._hotkey_find)
        self.bind_all("<Control-F>", self._hotkey_find)
        self.pl_tree.bind("<Return>", self._hotkey_studio)
        self.vid_tree.bind("<Return>", self._hotkey_studio)
        self.pl_tree.bind("<Button-1>", lambda _e: setattr(self, "_last_table", "pl"), add="+")
        self.vid_tree.bind("<Button-1>", lambda _e: setattr(self, "_last_table", "vid"), add="+")

    def _typing_in_field(self) -> bool:
        """
        PURPOSE:
            Skip hotkeys while the user is editing a text field.

        INTERNAL LOGIC:
            Walks focus widget parents looking for filter entries or log/text.

        EXAMPLE INVOCATION:
            if self._typing_in_field(): return
        """
        widget: Any = self.focus_get()
        guarded = {self.filter_entry, self.video_filter_entry, self.log_box}
        while widget is not None:
            if widget in guarded:
                return True
            cls = str(widget.winfo_class()) if hasattr(widget, "winfo_class") else ""
            if cls in {"Entry", "TEntry", "Text"}:
                return True
            widget = getattr(widget, "master", None)
        return False

    def _hotkey_f2(self, _event: Any = None) -> Optional[str]:
        """
        PURPOSE:
            F2 renames a playlist or an owned video title.

        INTERNAL LOGIC:
            Videos table if it was last clicked; else playlist Rename.

        EXAMPLE INVOCATION:
            self._hotkey_f2()
        """
        if self._typing_in_field() or self._busy:
            return None
        if self._last_table == "vid":
            self.action_rename_video()
        else:
            self.action_rename()
        return "break"

    def _hotkey_delete(self, _event: Any = None) -> Optional[str]:
        """
        PURPOSE:
            Delete key removes selected videos from the current playlist.

        INTERNAL LOGIC:
            Ignored in text fields and unless the videos table was last focused.

        EXAMPLE INVOCATION:
            self._hotkey_delete()
        """
        if self._typing_in_field() or self._busy:
            return None
        if self._last_table != "vid":
            return None
        self.action_remove()
        return "break"

    def _hotkey_find(self, _event: Any = None) -> str:
        """
        PURPOSE:
            Ctrl+F focuses the videos filter box.

        INTERNAL LOGIC:
            focus + select-all on video_filter_entry.

        EXAMPLE INVOCATION:
            self._hotkey_find()
        """
        self.video_filter_entry.focus()
        try:
            self.video_filter_entry.select_range(0, "end")
        except Exception:
            pass
        return "break"

    def _hotkey_studio(self, _event: Any = None) -> str:
        """
        PURPOSE:
            Enter on a playlist/video row opens YouTube Studio.

        INTERNAL LOGIC:
            Delegates to open_studio.

        EXAMPLE INVOCATION:
            self._hotkey_studio()
        """
        if self._typing_in_field() or self._busy:
            return "break"
        self.open_studio()
        return "break"

    def _select_tree_row(self, tree: ttk.Treeview, event: Any) -> None:
        """
        PURPOSE:
            Select the row under a right-click before showing a context menu.

        INTERNAL LOGIC:
            identify_row; selection_set + focus if not already selected.

        EXAMPLE INVOCATION:
            self._select_tree_row(self.pl_tree, event)
        """
        row = tree.identify_row(event.y)
        if not row:
            return
        if row not in tree.selection():
            tree.selection_set(row)
        tree.focus(row)

    def _playlist_context_menu(self, event: Any) -> None:
        """
        PURPOSE:
            Right-click playlist actions (rename, privacy, description, Studio).

        INTERNAL LOGIC:
            Selects the row; tk Menu with playlist commands.

        EXAMPLE INVOCATION:
            self.pl_tree.bind("<Button-3>", self._playlist_context_menu)
        """
        self._last_table = "pl"
        self._select_tree_row(self.pl_tree, event)
        menu = Menu(self, tearoff=0)
        menu.add_command(label="Rename", command=self.action_rename)
        menu.add_command(label="Description…", command=self.action_description)
        priv = Menu(menu, tearoff=0)
        priv.add_command(label="Public", command=lambda: self.action_privacy("public"))
        priv.add_command(label="Unlisted", command=lambda: self.action_privacy("unlisted"))
        priv.add_command(label="Private", command=lambda: self.action_privacy("private"))
        menu.add_cascade(label="Privacy", menu=priv)
        menu.add_separator()
        menu.add_command(label="Open in Studio", command=self.open_studio)
        menu.add_command(label="Delete Playlist", command=self.action_delete)
        try:
            menu.tk_popup(event.x_root, event.y_root)
        finally:
            menu.grab_release()

    def _video_context_menu(self, event: Any) -> None:
        """
        PURPOSE:
            Right-click video actions (rename, copy/move, Studio, browser).

        INTERNAL LOGIC:
            Selects the row; tk Menu with video commands.

        EXAMPLE INVOCATION:
            self.vid_tree.bind("<Button-3>", self._video_context_menu)
        """
        self._last_table = "vid"
        self._select_tree_row(self.vid_tree, event)
        menu = Menu(self, tearoff=0)
        menu.add_command(label="Rename title…", command=self.action_rename_video)
        menu.add_command(label="Copy…", command=self.action_copy)
        menu.add_command(label="Move…", command=self.action_move)
        menu.add_command(label="Remove", command=self.action_remove)
        menu.add_separator()
        menu.add_command(label="Open in Browser", command=self.open_selected)
        menu.add_command(label="Open in Studio", command=self.open_studio)
        try:
            menu.tk_popup(event.x_root, event.y_root)
        finally:
            menu.grab_release()

    def _build_sidebar(self) -> None:
        """
        PURPOSE:
            Construct left control column (auth, playlist actions, log).

        INTERNAL LOGIC:
            CTkFrame with section labels and action buttons.

        EXAMPLE INVOCATION:
            self._build_sidebar()
        """
        self.sidebar = ctk.CTkFrame(self, width=300, corner_radius=0)
        self.sidebar.grid(row=0, column=0, sticky="nsew")
        self.sidebar.grid_rowconfigure(8, weight=1)
        self.sidebar.grid_rowconfigure(12, weight=1)

        ctk.CTkLabel(
            self.sidebar,
            text="YouTube\nPlaylist Manager",
            font=ctk.CTkFont(size=22, weight="bold"),
            justify="left",
        ).grid(row=0, column=0, padx=20, pady=(20, 8), sticky="w")

        self.quota_label = ctk.CTkLabel(
            self.sidebar,
            text=meter_text(),
            anchor="w",
            font=ctk.CTkFont(size=11),
            text_color="#7ec8f3",
            wraplength=260,
        )
        self.quota_label.grid(row=1, column=0, padx=20, pady=(0, 4), sticky="ew")

        jobs_wrap = ctk.CTkFrame(self.sidebar, fg_color="transparent")
        jobs_wrap.grid(row=2, column=0, padx=12, pady=(0, 6), sticky="ew")
        ctk.CTkLabel(
            jobs_wrap,
            text="SORT QUEUE",
            font=ctk.CTkFont(size=12, weight="bold"),
            text_color="gray70",
            anchor="w",
        ).pack(fill="x")
        self.jobs_tree = ttk.Treeview(
            jobs_wrap,
            columns=("title", "by", "status"),
            show="headings",
            height=4,
            selectmode="browse",
        )
        self.jobs_tree.heading("title", text="Playlist", anchor="w")
        self.jobs_tree.heading("by", text="Key", anchor="w")
        self.jobs_tree.heading("status", text="Status", anchor="w")
        self.jobs_tree.column("title", width=140, anchor="w")
        self.jobs_tree.column("by", width=70, anchor="w")
        self.jobs_tree.column("status", width=70, anchor="w")
        self.jobs_tree.pack(fill="x", pady=(2, 2))
        job_btns = ctk.CTkFrame(jobs_wrap, fg_color="transparent")
        job_btns.pack(fill="x")
        ctk.CTkButton(job_btns, text="Drop", width=70, height=24, command=self._jobs_drop).pack(
            side="left", padx=2
        )
        ctk.CTkButton(job_btns, text="Up", width=50, height=24, command=lambda: self._jobs_move(-1)).pack(
            side="left", padx=2
        )
        ctk.CTkButton(job_btns, text="Down", width=54, height=24, command=lambda: self._jobs_move(1)).pack(
            side="left", padx=2
        )

        ctk.CTkLabel(
            self.sidebar,
            text="GOOGLE ACCOUNT",
            font=ctk.CTkFont(size=12, weight="bold"),
            text_color="gray70",
            anchor="w",
        ).grid(row=3, column=0, padx=20, pady=(4, 0), sticky="ew")

        self.auth_status = ctk.CTkLabel(self.sidebar, text="Not connected", anchor="w", text_color="#e74c3c")
        self.auth_status.grid(row=4, column=0, padx=20, pady=(4, 6), sticky="ew")

        self.connect_btn = ctk.CTkButton(
            self.sidebar,
            text="Connect Google Account",
            height=36,
            font=ctk.CTkFont(weight="bold", size=13),
            command=self.connect_google,
        )
        self.connect_btn.grid(row=5, column=0, padx=20, pady=(0, 4), sticky="ew")

        self.reconnect_btn = ctk.CTkButton(
            self.sidebar,
            text="Reconnect / Switch Account",
            height=28,
            fg_color="gray30",
            hover_color="gray40",
            command=lambda: self.connect_google(force=True),
        )
        self.reconnect_btn.grid(row=6, column=0, padx=20, pady=(0, 8), sticky="ew")

        ctk.CTkLabel(
            self.sidebar,
            text="PLAYLIST ACTIONS",
            font=ctk.CTkFont(size=12, weight="bold"),
            text_color="gray70",
            anchor="w",
        ).grid(row=7, column=0, padx=20, pady=(4, 2), sticky="ew")

        scroll = ctk.CTkScrollableFrame(self.sidebar, fg_color="transparent")
        scroll.grid(row=8, column=0, padx=12, pady=2, sticky="nsew")
        self._action_buttons: List[ctk.CTkButton] = []
        actions = [
            ("Refresh", self.refresh_all),
            ("New Playlist", self.action_new),
            ("Rename", self.action_rename),
            ("Description…", self.action_description),
            ("Privacy", self.action_privacy),
            ("Delete Playlist", self.action_delete),
            ("Clear Videos", self.action_clear),
            ("Trim Duplicates", self.action_trim),
            ("Sort by Title", lambda: self.action_sort("title")),
            ("Sort by Date Added", lambda: self.action_sort("date")),
            ("Sort by Duration", lambda: self.action_sort("duration")),
            ("Sort by Channel", lambda: self.action_sort("channel")),
            ("Resume unfinished sorts", self.action_resume_sorts),
            ("Undo…", self.action_undo),
            ("List Mode: Export selected", self.action_list_export),
            ("List Mode: Apply", self.action_list_apply),
            ("Export JSON", self.action_export_json),
            ("Find Broken", self.action_find_broken),
            ("Stats", self.action_stats),
        ]
        for label, cmd in actions:
            btn = ctk.CTkButton(
                scroll,
                text=label,
                height=28,
                fg_color="gray30",
                hover_color="gray40",
                command=cmd,
            )
            btn.pack(fill="x", pady=2)
            self._action_buttons.append(btn)

        self.help_btn = ctk.CTkButton(
            self.sidebar,
            text="Tutorials / Help",
            height=30,
            fg_color="#1F538D",
            hover_color="#163a66",
            command=self.action_help,
        )
        self.help_btn.grid(row=9, column=0, padx=20, pady=(6, 2), sticky="ew")

        self.progress = ctk.CTkProgressBar(self.sidebar)
        self.progress.grid(row=10, column=0, padx=20, pady=(8, 4), sticky="ew")
        self.progress.set(0)
        self.status_label = ctk.CTkLabel(self.sidebar, text="Ready", anchor="w", text_color="gray70")
        self.status_label.grid(row=11, column=0, padx=20, pady=(0, 4), sticky="ew")

        self.log_box = ctk.CTkTextbox(self.sidebar, height=90, font=ctk.CTkFont(family="Consolas", size=11))
        self.log_box.grid(row=12, column=0, padx=16, pady=(0, 12), sticky="nsew")

    def _build_main(self) -> None:
        """
        PURPOSE:
            Construct playlist + video Treeviews and video action bar.

        INTERNAL LOGIC:
            Two stacked trees with scrollbars; Move/Copy/Remove/Open buttons.

        EXAMPLE INVOCATION:
            self._build_main()
        """
        self.main_frame = ctk.CTkFrame(self, fg_color="transparent")
        self.main_frame.grid(row=0, column=1, sticky="nsew", padx=12, pady=12)
        self.main_frame.grid_columnconfigure(0, weight=1)

        self.auth_banner = ctk.CTkFrame(self.main_frame)
        self.auth_banner.grid(row=0, column=0, sticky="ew", pady=(0, 8))
        ctk.CTkLabel(
            self.auth_banner,
            text="Connect your Google account to manage YouTube playlists.\n"
            "You will be asked to grant YouTube access in your browser.",
            justify="left",
            font=ctk.CTkFont(size=14),
        ).pack(side="left", padx=16, pady=12)
        ctk.CTkButton(
            self.auth_banner,
            text="Connect Google Account",
            width=200,
            height=40,
            command=self.connect_google,
        ).pack(side="right", padx=16, pady=12)

        self.main_frame.grid_rowconfigure(1, weight=1)

        self._split = ttk.Panedwindow(self.main_frame, orient="vertical")
        self._split.grid(row=1, column=0, sticky="nsew")
        top = ctk.CTkFrame(self._split, fg_color="transparent")
        bottom = ctk.CTkFrame(self._split, fg_color="transparent")
        top.grid_columnconfigure(0, weight=1)
        top.grid_rowconfigure(1, weight=1)
        bottom.grid_columnconfigure(0, weight=1)
        bottom.grid_rowconfigure(1, weight=1)
        self._split.add(top, weight=1)
        self._split.add(bottom, weight=1)

        header = ctk.CTkFrame(top, fg_color="transparent")
        header.grid(row=0, column=0, sticky="ew")
        self.playlists_header = ctk.CTkLabel(
            header,
            text="Playlists",
            font=ctk.CTkFont(size=16, weight="bold"),
            anchor="w",
        )
        self.playlists_header.pack(side="left")
        self.filter_entry = ctk.CTkEntry(header, placeholder_text="Filter playlists…", width=220)
        self.filter_entry.pack(side="right")
        self.filter_entry.bind("<KeyRelease>", self._on_filter_playlists)

        pl_frame = ctk.CTkFrame(top, fg_color="transparent")
        pl_frame.grid(row=1, column=0, sticky="nsew", pady=(4, 4))
        pl_frame.grid_columnconfigure(0, weight=1)
        pl_frame.grid_rowconfigure(0, weight=1)
        self._pl_frame = pl_frame

        pl_cols = ("title", "count", "privacy", "id")
        pl_headings = {"title": "Title", "count": "Items", "privacy": "Privacy", "id": "Playlist ID"}
        self.pl_tree = ttk.Treeview(
            pl_frame,
            columns=pl_cols,
            show="headings",
            selectmode="extended",
        )
        for col, w in (
            ("title", 360),
            ("count", 70),
            ("privacy", 90),
            ("id", 280),
        ):
            self.pl_tree.column(col, width=w, anchor="w")
        register_sortable_tree(self.pl_tree, pl_headings)
        pl_scroll = ttk.Scrollbar(pl_frame, orient="vertical", command=self.pl_tree.yview)
        self.pl_tree.configure(yscrollcommand=pl_scroll.set)
        self.pl_tree.grid(row=0, column=0, sticky="nsew")
        pl_scroll.grid(row=0, column=1, sticky="ns")
        self.pl_tree.bind("<<TreeviewSelect>>", self._on_playlist_select)
        self.pl_tree.bind("<Button-3>", self._playlist_context_menu)

        bar = ctk.CTkFrame(bottom, fg_color="transparent")
        bar.grid(row=0, column=0, sticky="ew", pady=(4, 4))
        ctk.CTkLabel(bar, text="Videos", font=ctk.CTkFont(size=16, weight="bold")).pack(side="left")
        self.video_filter_entry = ctk.CTkEntry(
            bar,
            placeholder_text="Filter videos…",
            width=200,
            height=26,
        )
        self.video_filter_entry.pack(side="left", padx=(12, 8))
        self.video_filter_entry.bind("<KeyRelease>", self._on_filter_videos)
        btn_h = 26
        self.open_btn = ctk.CTkButton(bar, text="Open in Browser", width=118, height=btn_h, command=self.open_selected)
        self.open_btn.pack(side="right", padx=2)
        self.studio_btn = ctk.CTkButton(bar, text="Open in Studio", width=108, height=btn_h, command=self.open_studio)
        self.studio_btn.pack(side="right", padx=2)
        self.remove_btn = ctk.CTkButton(bar, text="Remove", width=72, height=btn_h, fg_color="#8e2a2a", command=self.action_remove)
        self.remove_btn.pack(side="right", padx=2)
        self.rename_video_btn = ctk.CTkButton(bar, text="Rename title…", width=108, height=btn_h, command=self.action_rename_video)
        self.rename_video_btn.pack(side="right", padx=2)
        self.copy_btn = ctk.CTkButton(bar, text="Copy…", width=72, height=btn_h, command=self.action_copy)
        self.copy_btn.pack(side="right", padx=2)
        self.move_btn = ctk.CTkButton(bar, text="Move…", width=72, height=btn_h, command=self.action_move)
        self.move_btn.pack(side="right", padx=2)

        vid_frame = ctk.CTkFrame(bottom, fg_color="transparent")
        vid_frame.grid(row=1, column=0, sticky="nsew")
        vid_frame.grid_columnconfigure(0, weight=1)
        vid_frame.grid_rowconfigure(0, weight=1)

        vid_cols = ("pos", "title", "channel", "duration", "status", "video_id")
        vid_headings = {
            "pos": "#",
            "title": "Title",
            "channel": "Channel",
            "duration": "Duration",
            "status": "Status",
            "video_id": "Video ID",
        }
        self.vid_tree = ttk.Treeview(
            vid_frame,
            columns=vid_cols,
            show="headings",
            selectmode="extended",
        )
        for col, w in (
            ("pos", 50),
            ("title", 360),
            ("channel", 180),
            ("duration", 80),
            ("status", 90),
            ("video_id", 140),
        ):
            self.vid_tree.column(col, width=w, anchor="w")
        register_sortable_tree(self.vid_tree, vid_headings)
        vid_scroll = ttk.Scrollbar(vid_frame, orient="vertical", command=self.vid_tree.yview)
        self.vid_tree.configure(yscrollcommand=vid_scroll.set)
        self.vid_tree.grid(row=0, column=0, sticky="nsew")
        vid_scroll.grid(row=0, column=1, sticky="ns")
        self.vid_tree.bind("<Double-1>", lambda _e: self.open_selected())
        self.vid_tree.bind("<Button-3>", self._video_context_menu)
        self.bind("o", lambda _e: self.open_selected())
        self.bind("O", lambda _e: self.open_selected())

        self._set_actions_enabled(False)

    def log(self, message: str) -> None:
        """
        PURPOSE:
            Append a line to the sidebar log textbox.

        INTERNAL LOGIC:
            Inserts at end; auto-scrolls.

        EXAMPLE INVOCATION:
            self.log("Loaded 12 playlists")
        """
        self.log_box.insert("end", message + "\n")
        self.log_box.see("end")

    def set_status(self, text: str) -> None:
        """
        PURPOSE:
            Update the status label under the progress bar.

        INTERNAL LOGIC:
            Sets label text on UI thread.

        EXAMPLE INVOCATION:
            self.set_status("Loading…")
        """
        self.status_label.configure(text=text)

    def _set_actions_enabled(self, enabled: bool) -> None:
        """
        PURPOSE:
            Enable/disable playlist action buttons based on auth state.

        INTERNAL LOGIC:
            Toggles CTkButton state for action list and video buttons.

        EXAMPLE INVOCATION:
            self._set_actions_enabled(True)
        """
        state = "normal" if enabled else "disabled"
        for btn in self._action_buttons:
            btn.configure(state=state)
        for btn in (
            self.open_btn,
            self.studio_btn,
            self.remove_btn,
            self.rename_video_btn,
            self.copy_btn,
            self.move_btn,
        ):
            btn.configure(state=state)

    def _show_auth_banner(self, show: bool) -> None:
        """
        PURPOSE:
            Show or hide the connect-account banner over the main area.

        INTERNAL LOGIC:
            grid/grid_remove on auth_banner.

        EXAMPLE INVOCATION:
            self._show_auth_banner(True)
        """
        if show:
            self.auth_banner.grid(row=0, column=0, sticky="ew", pady=(0, 8))
        else:
            self.auth_banner.grid_remove()

    def _bootstrap_auth(self) -> None:
        """
        PURPOSE:
            On startup, detect existing token and either connect or load data.

        INTERNAL LOGIC:
            If authenticated, unlock UI and refresh; else show connect banner.

        EXAMPLE INVOCATION:
            self.after(100, self._bootstrap_auth)
        """
        settings = get_settings()
        if not settings.has_oauth_client():
            self.auth_status.configure(
                text="Missing Client ID/Secret in .env",
                text_color="#e74c3c",
            )
            self._show_auth_banner(True)
            self._set_actions_enabled(False)
            self.log("Configure YOUTUBE_CLIENT_ID and YOUTUBE_CLIENT_SECRET in .env")
            messagebox.showinfo(
                "Setup required",
                "Add YOUTUBE_CLIENT_ID and YOUTUBE_CLIENT_SECRET to .env\n"
                "(see .env.example), then click Connect Google Account.",
            )
            return
        if is_authenticated():
            self._on_authenticated()
        else:
            self.auth_status.configure(text="Not connected", text_color="#e74c3c")
            self.connect_btn.configure(text="Connect Google Account")
            self._show_auth_banner(True)
            self._set_actions_enabled(False)
            self.log("Click Connect Google Account to grant YouTube access.")

    def connect_google(self, force: bool = False) -> None:
        """
        PURPOSE:
            Start OAuth browser consent (optionally clearing cached token).

        INTERNAL LOGIC:
            Background thread runs run_oauth_flow; UI updates on success/failure.

        EXAMPLE INVOCATION:
            self.connect_google()
            self.connect_google(force=True)
        """
        if self._busy:
            return
        if not get_settings().has_oauth_client():
            messagebox.showerror(
                "Missing credentials",
                "Set YOUTUBE_CLIENT_ID and YOUTUBE_CLIENT_SECRET in .env first.",
            )
            return

        def work() -> None:
            try:
                def _start_progress() -> None:
                    self.set_status("Waiting for Google sign-in…")
                    self.progress.configure(mode="indeterminate")
                    self.progress.start()

                self.after(0, _start_progress)
                run_oauth_flow(force=force)
                self.after(0, self._on_authenticated)
            except Exception as exc:
                err_msg = format_api_error(exc)
                logger.exception("OAuth failed")
                self.after(0, lambda m=err_msg: self._oauth_failed(m))

        self._busy = True
        self._set_actions_enabled(False)
        self.log("Opening Google account permission dialog…")
        threading.Thread(target=work, daemon=True).start()

    def _oauth_failed(self, err: str) -> None:
        """
        PURPOSE:
            Handle OAuth failure on the UI thread.

        INTERNAL LOGIC:
            Stops progress; shows error; keeps actions disabled.

        EXAMPLE INVOCATION:
            self._oauth_failed("access denied")
        """
        self._busy = False
        self.progress.stop()
        self.progress.configure(mode="determinate")
        self.progress.set(0)
        self.set_status("Authentication failed")
        self.log(f"Auth error: {err}")
        messagebox.showerror("Authentication failed", err)

    def _on_authenticated(self) -> None:
        """
        PURPOSE:
            Unlock UI after successful OAuth and load playlists.

        INTERNAL LOGIC:
            Updates status labels; hides banner; calls refresh_all.

        EXAMPLE INVOCATION:
            self._on_authenticated()
        """
        self._busy = False
        self.progress.stop()
        self.progress.configure(mode="determinate")
        self.progress.set(0)
        self.auth_status.configure(text="Connected", text_color="#2ecc71")
        self.connect_btn.configure(text="Connected")
        self._show_auth_banner(False)
        self._set_actions_enabled(True)
        self.set_status("Connected")
        self.log("Google account connected. Loading playlists…")
        self.refresh_all()

    def run_task(self, label: str, fn: Callable[[], Any], on_done: Optional[Callable[[Any], None]] = None) -> None:
        """
        PURPOSE:
            Run a blocking API call on a daemon thread with progress feedback.

        INTERNAL LOGIC:
            Sets busy flag; invokes fn; schedules on_done/error via after().

        EXAMPLE INVOCATION:
            self.run_task("Load", lambda: playlists.list_playlists(), self._fill_playlists)
        """
        if self._busy:
            self.log("Busy — wait for the current task to finish.")
            return

        def work() -> None:
            try:
                def _start() -> None:
                    self.set_status(label)
                    self.progress.configure(mode="indeterminate")
                    self.progress.start()

                self.after(0, _start)
                result = fn()
                self.after(0, lambda r=result: self._task_success(label, r, on_done))
            except AuthError as exc:
                err_msg = format_api_error(exc)
                self.after(0, lambda m=err_msg: self._task_auth_error(m))
            except Exception as exc:
                err_msg = format_api_error(exc)
                logger.exception(label)
                self.after(0, lambda m=err_msg: self._task_error(label, m))

        self._busy = True
        self._set_actions_enabled(False)
        threading.Thread(target=work, daemon=True).start()

    def _task_success(self, label: str, result: Any, on_done: Optional[Callable[[Any], None]]) -> None:
        """
        PURPOSE:
            Finish a successful background task on the UI thread.

        INTERNAL LOGIC:
            Clears busy/progress; optional callback; logs completion.

        EXAMPLE INVOCATION:
            self._task_success("Load", data, callback)
        """
        self._busy = False
        self.progress.stop()
        self.progress.configure(mode="determinate")
        self.progress.set(1)
        self.set_status(f"Done: {label}")
        self.log(f"OK: {label}")
        self._set_actions_enabled(True)
        self._refresh_quota_meter()
        if on_done:
            on_done(result)
        if self._busy:
            return
        pending = self._pending_playlist_id
        if pending:
            self._pending_playlist_id = None
            self._selected_playlist_id = None
            self._on_playlist_select()

    def _task_error(self, label: str, err: str) -> None:
        """
        PURPOSE:
            Show a background task failure.

        INTERNAL LOGIC:
            Clears busy; messagebox + log.

        EXAMPLE INVOCATION:
            self._task_error("Sort", "quota exceeded")
        """
        self._busy = False
        self.progress.stop()
        self.progress.configure(mode="determinate")
        self.progress.set(0)
        self.set_status(f"Error: {label}")
        self.log(f"ERROR {label}: {err}")
        self._set_actions_enabled(True)
        self._refresh_quota_meter()
        messagebox.showerror(label, err)

    def _task_auth_error(self, err: str) -> None:
        """
        PURPOSE:
            Re-enter disconnected state when API reports auth failure.

        INTERNAL LOGIC:
            Disables actions; shows banner; prompts reconnect.

        EXAMPLE INVOCATION:
            self._task_auth_error("invalid_grant")
        """
        self._busy = False
        self.progress.stop()
        self.auth_status.configure(text="Not connected", text_color="#e74c3c")
        self._show_auth_banner(True)
        self._set_actions_enabled(False)
        self.log(err)
        messagebox.showwarning("Authentication required", err)

    def refresh_all(self) -> None:
        """
        PURPOSE:
            Reload playlist list from YouTube.

        INTERNAL LOGIC:
            Background list_playlists → fill tree.

        EXAMPLE INVOCATION:
            self.refresh_all()
        """
        self.run_task("Refresh playlists", playlists.list_playlists, self._fill_playlists)

    def _refresh_quota_meter(self) -> None:
        """
        PURPOSE:
            Update the sidebar quota label from the local ledger.

        INTERNAL LOGIC:
            meter_text() plus the sort-queue table (list_jobs).

        EXAMPLE INVOCATION:
            self._refresh_quota_meter()
        """
        text = meter_text()
        queued = len(pending_sorts())
        if queued:
            text = f"{text}\n{queued} unfinished sort(s)"
        self.quota_label.configure(text=text)
        self._fill_jobs_tree()

    def _fill_jobs_tree(self) -> None:
        """
        PURPOSE:
            Show queued sort jobs (playlist, key, pending/done).

        INTERNAL LOGIC:
            list_jobs(); uses job id as Treeview iid for drop/reorder.

        EXAMPLE INVOCATION:
            self._fill_jobs_tree()
        """
        selected = list(self.jobs_tree.selection())
        self.jobs_tree.delete(*self.jobs_tree.get_children())
        for job in list_jobs():
            jid = str(job.get("id") or "")
            if not jid:
                continue
            title = str(job.get("title") or job.get("playlist_id") or "")
            self.jobs_tree.insert(
                "",
                "end",
                iid=jid,
                values=(title[:48], str(job.get("by") or ""), str(job.get("status") or "")),
            )
        still = [iid for iid in selected if self.jobs_tree.exists(iid)]
        if still:
            self.jobs_tree.selection_set(still)

    def _selected_job_id(self) -> Optional[str]:
        """
        PURPOSE:
            Return the sort-queue row id under selection.

        INTERNAL LOGIC:
            First jobs_tree selection iid.

        EXAMPLE INVOCATION:
            jid = self._selected_job_id()
        """
        sel = self.jobs_tree.selection()
        return str(sel[0]) if sel else None

    def _jobs_drop(self) -> None:
        """
        PURPOSE:
            Remove the selected sort job from the queue.

        INTERNAL LOGIC:
            drop_job then refresh the table.

        EXAMPLE INVOCATION:
            self._jobs_drop()
        """
        jid = self._selected_job_id()
        if not jid:
            messagebox.showinfo("Sort queue", "Select a job to drop.")
            return
        drop_job(jid)
        self._fill_jobs_tree()
        self._refresh_quota_meter()

    def _jobs_move(self, delta: int) -> None:
        """
        PURPOSE:
            Move the selected sort job earlier (Up) or later (Down).

        INTERNAL LOGIC:
            move_job(delta); restore selection.

        EXAMPLE INVOCATION:
            self._jobs_move(-1)
        """
        jid = self._selected_job_id()
        if not jid:
            messagebox.showinfo("Sort queue", "Select a job to reorder.")
            return
        move_job(jid, delta)
        self._fill_jobs_tree()
        if self.jobs_tree.exists(jid):
            self.jobs_tree.selection_set(jid)
            self.jobs_tree.see(jid)

    def _invalidate_item_cache(self, playlist_id: Optional[str] = None) -> None:
        """
        PURPOSE:
            Drop cached video rows after a mutation or full refresh.

        INTERNAL LOGIC:
            Clears one id or the whole cache.

        EXAMPLE INVOCATION:
            self._invalidate_item_cache("PLxxx")
        """
        if playlist_id:
            self._item_cache.pop(playlist_id, None)
        else:
            self._item_cache.clear()

    def _on_filter_playlists(self, _event: Any = None) -> None:
        """
        PURPOSE:
            Filter the playlists table as the user types.

        INTERNAL LOGIC:
            Case-insensitive match on title or id; re-renders rows.

        EXAMPLE INVOCATION:
            self._on_filter_playlists()
        """
        self._playlist_filter = self.filter_entry.get().strip().lower()
        self._render_playlist_rows()

    def _on_filter_videos(self, _event: Any = None) -> None:
        """
        PURPOSE:
            Filter the videos table as the user types.

        INTERNAL LOGIC:
            Case-insensitive match on title, channel, or video id; re-renders rows.

        EXAMPLE INVOCATION:
            self._on_filter_videos()
        """
        self._video_filter = self.video_filter_entry.get().strip().lower()
        self._render_video_rows()

    def _fill_playlists(self, rows: List[Playlist]) -> None:
        """
        PURPOSE:
            Populate the playlists Treeview.

        INTERNAL LOGIC:
            Stores rows, drops video cache, re-renders with the current filter.

        EXAMPLE INVOCATION:
            self._fill_playlists(playlists)
        """
        self._playlists = rows
        self._invalidate_item_cache()
        self._items = []
        self._selected_playlist_id = None
        self._render_playlist_rows(consume_pending=True)

    def _render_playlist_rows(self, *, consume_pending: bool = False) -> None:
        """
        PURPOSE:
            Rebuild playlist table rows from self._playlists + filter text.

        INTERNAL LOGIC:
            Title/id substring match; sorts by Title A–Z; restores last/pending
            selection (iids survive the local sort).

        EXAMPLE INVOCATION:
            self._render_playlist_rows()
        """
        last = self.settings.get("last_playlist_id")
        prev_selected_ids: List[str] = []
        prev_focus_id: Optional[str] = None
        if not consume_pending:
            prev_selected_ids = [
                self._playlist_by_iid[i].id
                for i in self.pl_tree.selection()
                if i in self._playlist_by_iid
            ]
            focus_iid = self._focused_playlist_iid()
            if focus_iid and focus_iid in self._playlist_by_iid:
                prev_focus_id = self._playlist_by_iid[focus_iid].id
        if consume_pending and self._pending_playlist_id:
            last = self._pending_playlist_id
            self._pending_playlist_id = None
        self.pl_tree.unbind("<<TreeviewSelect>>")
        self.pl_tree.delete(*self.pl_tree.get_children())
        self._playlist_by_iid.clear()
        needle = self._playlist_filter
        visible = [
            pl
            for pl in self._playlists
            if not needle or needle in pl.title.lower() or needle in pl.id.lower()
        ]
        select_iids: List[str] = []
        focus_row: Optional[str] = None
        for pl in visible:
            iid = self.pl_tree.insert(
                "",
                "end",
                values=(pl.title, pl.item_count, pl.privacy, pl.id),
            )
            self._playlist_by_iid[iid] = pl
            if consume_pending:
                if last and pl.id == last:
                    focus_row = iid
                    select_iids = [iid]
            elif pl.id in prev_selected_ids:
                select_iids.append(iid)
                if pl.id == prev_focus_id:
                    focus_row = iid
        apply_default_tree_sort(self.pl_tree, "title")
        if consume_pending:
            self.log(f"Showing {len(visible)} / {len(self._playlists)} playlists")
        if select_iids:
            self.pl_tree.selection_set(select_iids)
            self.pl_tree.focus(focus_row or select_iids[0])
        elif visible:
            first = self.pl_tree.get_children()[0]
            self.pl_tree.selection_set(first)
            self.pl_tree.focus(first)
        self.pl_tree.bind("<<TreeviewSelect>>", self._on_playlist_select)
        focused_before = self._selected_playlist_id
        if consume_pending and self.pl_tree.selection():
            self._on_playlist_select()
        elif not consume_pending:
            iid = self._focused_playlist_iid()
            pl = self._playlist_by_iid.get(iid) if iid else None
            if pl and pl.id != focused_before:
                self._on_playlist_select()

    def _focused_playlist_iid(self) -> Optional[str]:
        """
        PURPOSE:
            Resolve which playlist row should drive the videos pane.

        INTERNAL LOGIC:
            Prefers keyboard/mouse focus; falls back to last selected row.

        EXAMPLE INVOCATION:
            iid = self._focused_playlist_iid()
        """
        focus = self.pl_tree.focus()
        if focus and focus in self._playlist_by_iid:
            return focus
        sel = self.pl_tree.selection()
        if sel:
            return sel[-1]
        return None

    def _on_playlist_select(self, _event: Any = None) -> None:
        """
        PURPOSE:
            Load videos when the focused playlist changes.

        INTERNAL LOGIC:
            Uses focus (Windows last-click) so Ctrl/Shift multi-select does not
            reload videos for every extra playlist added to the selection.

        EXAMPLE INVOCATION:
            self._on_playlist_select()
        """
        iid = self._focused_playlist_iid()
        if not iid:
            return
        pl = self._playlist_by_iid.get(iid)
        if not pl:
            return
        if self._busy:
            self._pending_playlist_id = pl.id
            self.log("Busy — will load this playlist when the current task finishes.")
            return
        if pl.id == self._selected_playlist_id and self._items:
            return
        pid = pl.id
        self._selected_playlist_id = pid
        self.settings["last_playlist_id"] = pid
        self._save_settings()
        cached = self._item_cache.get(pid)
        if cached is not None:
            self._fill_videos(cached, playlist_id=pid, log_load=False)
            self.log(f"Loaded {len(cached)} videos (cache)")
            return
        self.run_task(
            f"Load videos: {pl.title}",
            lambda: items.list_items(pid, enrich=True),
            lambda rows, playlist_id=pid: self._fill_videos(rows, playlist_id=playlist_id),
        )

    def _reload_videos(self, _result: Any = None) -> None:
        """
        PURPOSE:
            Force-reload the videos pane for the focused playlist.

        INTERNAL LOGIC:
            Clears cached playlist id so _on_playlist_select fetches again.

        EXAMPLE INVOCATION:
            self._reload_videos()
        """
        pid = self._selected_playlist_id
        if pid:
            self._invalidate_item_cache(pid)
        self._items = []
        self._selected_playlist_id = None
        self._on_playlist_select()

    def _fill_videos(
        self,
        rows: List[PlaylistItem],
        playlist_id: Optional[str] = None,
        log_load: bool = True,
    ) -> None:
        """
        PURPOSE:
            Populate the videos Treeview for the selected playlist.

        INTERNAL LOGIC:
            Ignores stale loads; clears tree; maps iid → PlaylistItem.

        EXAMPLE INVOCATION:
            self._fill_videos(item_list, playlist_id="PLxxx")
        """
        if playlist_id and self._selected_playlist_id and playlist_id != self._selected_playlist_id:
            logger.info("Ignoring stale video load for %s", playlist_id)
            return
        if playlist_id:
            self._item_cache[playlist_id] = list(rows)
        self._items = rows
        self._render_video_rows(log_load=log_load)
        self._sync_playlist_item_count(len(rows))

    def _render_video_rows(self, *, log_load: bool = False) -> None:
        """
        PURPOSE:
            Rebuild video table rows from self._items + filter text.

        INTERNAL LOGIC:
            Title/channel/video-id substring match. Sorts by playlist position
            (#) ascending. Item count stays the full list.

        EXAMPLE INVOCATION:
            self._render_video_rows()
        """
        self.vid_tree.delete(*self.vid_tree.get_children())
        self._item_by_iid.clear()
        needle = self._video_filter
        visible = [
            item
            for item in self._items
            if not needle
            or needle in (item.title or "").lower()
            or needle in (item.channel_title or "").lower()
            or needle in (item.video_id or "").lower()
        ]
        for item in visible:
            iid = self.vid_tree.insert(
                "",
                "end",
                values=(
                    item.position + 1,
                    item.title,
                    item.channel_title,
                    format_duration(item.duration_seconds),
                    item.privacy_status,
                    item.video_id,
                ),
            )
            self._item_by_iid[iid] = item
        apply_default_tree_sort(self.vid_tree, "pos")
        if log_load:
            self.log(f"Loaded {len(self._items)} videos")

    def _sync_playlist_item_count(self, count: int) -> None:
        """
        PURPOSE:
            Update the Items column for the focused playlist after a reload.

        INTERNAL LOGIC:
            Writes count onto the Playlist model and Treeview values.

        EXAMPLE INVOCATION:
            self._sync_playlist_item_count(12)
        """
        pid = self._selected_playlist_id
        if not pid:
            return
        for iid, pl in self._playlist_by_iid.items():
            if pl.id != pid:
                continue
            pl.item_count = count
            vals = list(self.pl_tree.item(iid, "values"))
            if len(vals) >= 2:
                vals[1] = str(count)
                self.pl_tree.item(iid, values=vals)
            break

    def _current_playlist(self) -> Optional[Playlist]:
        """
        PURPOSE:
            Return the Playlist model for the focused (primary) playlist row.

        INTERNAL LOGIC:
            Looks up focus/last-selected iid in _playlist_by_iid.

        EXAMPLE INVOCATION:
            pl = self._current_playlist()
        """
        iid = self._focused_playlist_iid()
        if not iid:
            return None
        return self._playlist_by_iid.get(iid)

    def _selected_playlists(self) -> List[Playlist]:
        """
        PURPOSE:
            Return all Windows-style multi-selected playlists (Ctrl/Shift).

        INTERNAL LOGIC:
            Maps pl_tree.selection() through _playlist_by_iid; falls back to focus.

        EXAMPLE INVOCATION:
            selected = self._selected_playlists()
        """
        rows = [self._playlist_by_iid[i] for i in self.pl_tree.selection() if i in self._playlist_by_iid]
        if rows:
            return rows
        current = self._current_playlist()
        return [current] if current else []

    def _selected_video_items(self) -> List[PlaylistItem]:
        """
        PURPOSE:
            Return PlaylistItem objects for multi-selected video rows.

        INTERNAL LOGIC:
            Maps vid_tree selection through _item_by_iid.

        EXAMPLE INVOCATION:
            vids = self._selected_video_items()
        """
        return [self._item_by_iid[i] for i in self.vid_tree.selection() if i in self._item_by_iid]

    def _prompt_text(self, title: str, prompt: str, initial: str = "") -> Optional[str]:
        """
        PURPOSE:
            Show an input dialog with the current name already in the box.

        INTERNAL LOGIC:
            CTkInputDialog builds its entry after a short delay; we insert
            ``initial`` and place the caret at the end so a typo can be edited.

        EXAMPLE INVOCATION:
            name = self._prompt_text("Rename Playlist", 'Rename "2024" to:', "2024")
        """
        dialog = ctk.CTkInputDialog(text=prompt, title=title)

        def fill() -> None:
            entry = getattr(dialog, "_entry", None)
            if entry is None:
                dialog.after(20, fill)
                return
            entry.delete(0, "end")
            if initial:
                entry.insert(0, initial)
                entry.icursor("end")
            entry.focus()

        dialog.after(20, fill)
        value = dialog.get_input()
        if value is None:
            return None
        return value

    def _quota_confirm_body(self, estimated_writes: int, detail: str) -> str:
        """
        PURPOSE:
            Build a confirm dialog that shows write estimate and local quota left.

        INTERNAL LOGIC:
            Multiplies writes by WRITE_UNITS; remaining_units() is local-only.

        EXAMPLE INVOCATION:
            self._quota_confirm_body(12, "Sort 2 playlists")
        """
        left = remaining_units()
        units = estimated_writes * WRITE_UNITS
        return (
            f"{detail}\n\n"
            f"Estimated writes: {estimated_writes} (~{units:,} units).\n"
            f"Local meter: ~{left:,} units left today "
            "(Google does not expose remaining Data API quota).\n"
            "Quota resets at midnight US Pacific.\n\n"
            "Yes = apply (uses write quota)\n"
            "No = dry run (list-mode file, 0 writes)\n"
            "Cancel = abort"
        )

    def _confirm_writes(self, title: str, body: str) -> Optional[str]:
        """
        PURPOSE:
            Ask Apply / Dry run / Cancel before Sort, Clear, or List Mode Apply.

        INTERNAL LOGIC:
            Yes → apply, No → dry, Cancel → None.

        EXAMPLE INVOCATION:
            choice = self._confirm_writes("Sort", body)
        """
        choice = messagebox.askyesnocancel(title, body)
        if choice is True:
            return "apply"
        if choice is False:
            return "dry"
        return None

    def _report_progress(self, done: int, total: int) -> None:
        """
        PURPOSE:
            Show per-item sort progress on the UI thread.

        INTERNAL LOGIC:
            Schedules a determinate bar update via after(0).

        EXAMPLE INVOCATION:
            self._report_progress(12, 40)
        """
        def _ui() -> None:
            self.progress.stop()
            self.progress.configure(mode="determinate")
            frac = (done / total) if total else 0.0
            self.progress.set(min(1.0, max(0.0, frac)))
            self.set_status(f"Moved {done} / {total}")

        self.after(0, _ui)

    def _estimate_sort_writes(self, selected: List[Playlist], by: str) -> int:
        """
        PURPOSE:
            Estimate sort write ops from cache, else worst-case item counts.

        INTERNAL LOGIC:
            plan_sort.write_ops when videos are cached; else item_count.

        EXAMPLE INVOCATION:
            n = self._estimate_sort_writes(selected, "title")
        """
        total = 0
        for pl in selected:
            cached = self._item_cache.get(pl.id)
            if cached is None:
                total += max(pl.item_count, 0)
                continue
            plan = sort.plan_sort(cached, by)  # type: ignore[arg-type]
            total += plan.write_ops
        return total

    def _pick_dest_playlist(self, title: str) -> Optional[str]:
        """
        PURPOSE:
            Pick a destination playlist from a searchable list.

        INTERNAL LOGIC:
            Modal tree of other playlists; filter-as-you-type on title/id.
            Duplicate titles keep the Playlist ID column visible.

        EXAMPLE INVOCATION:
            dest = self._pick_dest_playlist("Copy to playlist")
        """
        source_id = self._selected_playlist_id
        candidates = [p for p in self._playlists if p.id != source_id]
        if not candidates:
            messagebox.showinfo(title, "No other playlists available.")
            return None
        win = ctk.CTkToplevel(self)
        win.title(title)
        win.geometry("560x460")
        win.transient(self)
        chosen: Dict[str, Optional[str]] = {"id": None}

        ctk.CTkLabel(win, text="Filter as you type, then double-click or OK.").pack(
            anchor="w", padx=12, pady=(10, 0)
        )
        entry = ctk.CTkEntry(win, placeholder_text="Filter by title or playlist id…")
        entry.pack(fill="x", padx=12, pady=8)

        tree_frame = ctk.CTkFrame(win, fg_color="transparent")
        tree_frame.pack(fill="both", expand=True, padx=12, pady=(0, 8))
        tree_frame.grid_columnconfigure(0, weight=1)
        tree_frame.grid_rowconfigure(0, weight=1)
        tree = ttk.Treeview(tree_frame, columns=("title", "id"), show="headings", selectmode="browse")
        tree.heading("title", text="Title")
        tree.heading("id", text="Playlist ID")
        tree.column("title", width=280)
        tree.column("id", width=240)
        scroll = ttk.Scrollbar(tree_frame, orient="vertical", command=tree.yview)
        tree.configure(yscrollcommand=scroll.set)
        tree.grid(row=0, column=0, sticky="nsew")
        scroll.grid(row=0, column=1, sticky="ns")

        def refresh_rows(_event: Any = None) -> None:
            needle = entry.get().strip().lower()
            tree.delete(*tree.get_children())
            for pl in candidates:
                if needle and needle not in pl.title.lower() and needle not in pl.id.lower():
                    continue
                tree.insert("", "end", iid=pl.id, values=(pl.title, pl.id))

        def accept(_event: Any = None) -> None:
            sel = tree.selection()
            if not sel:
                return
            chosen["id"] = sel[0]
            win.destroy()

        def cancel() -> None:
            chosen["id"] = None
            win.destroy()

        refresh_rows()
        entry.bind("<KeyRelease>", refresh_rows)
        tree.bind("<Double-1>", accept)
        win.bind("<Return>", accept)
        win.protocol("WM_DELETE_WINDOW", cancel)
        btn_row = ctk.CTkFrame(win, fg_color="transparent")
        btn_row.pack(fill="x", padx=12, pady=(0, 12))
        ctk.CTkButton(btn_row, text="OK", width=100, command=accept).pack(side="right", padx=4)
        ctk.CTkButton(btn_row, text="Cancel", width=100, fg_color="gray30", command=cancel).pack(side="right")
        win.after(50, lambda: (win.lift(), entry.focus_set()))
        win.grab_set()
        self.wait_window(win)
        return chosen["id"]

    def open_selected(self) -> None:
        """
        PURPOSE:
            Open the focused/selected video in the default browser.

        INTERNAL LOGIC:
            Uses first selected video id with youtube watch URL.

        EXAMPLE INVOCATION:
            self.open_selected()
        """
        vids = self._selected_video_items()
        if not vids:
            return
        url = f"https://www.youtube.com/watch?v={vids[0].video_id}"
        webbrowser.open(url)
        self.log(f"Opened {url}")

    def open_studio(self) -> None:
        """
        PURPOSE:
            Open the focused playlist in YouTube Studio (Sort → Manual URL).

        INTERNAL LOGIC:
            studio.youtube.com/playlist/{id}/videos

        EXAMPLE INVOCATION:
            self.open_studio()
        """
        pl = self._current_playlist()
        if not pl:
            messagebox.showinfo("Open in Studio", "Select a playlist first.")
            return
        url = f"https://studio.youtube.com/playlist/{pl.id}/videos"
        webbrowser.open(url)
        self.log(f"Opened Studio {url}")

    def action_new(self) -> None:
        """
        PURPOSE:
            Create a new playlist from a title prompt.

        INTERNAL LOGIC:
            CTkInputDialog → create_playlist → refresh.

        EXAMPLE INVOCATION:
            self.action_new()
        """
        dialog = ctk.CTkInputDialog(text="New playlist title:", title="New Playlist")
        title = dialog.get_input()
        if not title:
            return
        self.run_task("Create playlist", lambda: playlists.create_playlist(title.strip()), lambda _r: self.refresh_all())

    def action_rename(self) -> None:
        """
        PURPOSE:
            Rename the selected playlist.

        INTERNAL LOGIC:
            Prompts for new title; rename_playlist.

        EXAMPLE INVOCATION:
            self.action_rename()
        """
        pl = self._current_playlist()
        if not pl:
            messagebox.showinfo("Rename", "Select a playlist first.")
            return
        new_title = self._prompt_text(
            "Rename Playlist",
            f'Rename "{pl.title}" to:',
            pl.title,
        )
        if not new_title:
            return
        new_title = new_title.strip()
        if new_title == pl.title:
            return
        self.run_task(
            "Rename playlist",
            lambda: playlists.rename_playlist(pl.id, new_title),
            lambda _r: self.refresh_all(),
        )

    def action_description(self) -> None:
        """
        PURPOSE:
            Edit the focused playlist's description (playlists.update, 50 units).

        INTERNAL LOGIC:
            Pre-filled text box; skip write when unchanged.

        EXAMPLE INVOCATION:
            self.action_description()
        """
        pl = self._current_playlist()
        if not pl:
            messagebox.showinfo("Description", "Select a playlist first.")
            return
        win = ctk.CTkToplevel(self)
        win.title("Playlist description")
        win.geometry("520x280")
        win.transient(self)
        ctk.CTkLabel(win, text=f'Description for "{pl.title}"').pack(anchor="w", padx=12, pady=(12, 4))
        box = ctk.CTkTextbox(win, wrap="word")
        box.pack(fill="both", expand=True, padx=12, pady=4)
        box.insert("1.0", pl.description or "")
        chosen: Dict[str, Optional[str]] = {"text": None}

        def ok() -> None:
            chosen["text"] = box.get("1.0", "end-1c")
            win.destroy()

        row = ctk.CTkFrame(win, fg_color="transparent")
        row.pack(fill="x", padx=12, pady=(4, 12))
        ctk.CTkButton(row, text="Cancel", width=90, fg_color="gray30", command=win.destroy).pack(
            side="right", padx=4
        )
        ctk.CTkButton(row, text="Save", width=90, command=ok).pack(side="right")
        win.grab_set()
        self.wait_window(win)
        if chosen["text"] is None:
            return
        new_text = chosen["text"]
        if new_text == (pl.description or ""):
            return
        pid = pl.id

        def after(updated: Playlist) -> None:
            pl.description = updated.description
            messagebox.showinfo("Description", f'Updated description for "{updated.title}".')

        self.run_task(
            "Update description",
            lambda: playlists.set_description(pid, new_text),
            after,
        )

    def action_privacy(self, status: Optional[str] = None) -> None:
        """
        PURPOSE:
            Set public / unlisted / private on the focused playlist.

        INTERNAL LOGIC:
            Modal three-button picker unless status is passed (context menu).

        EXAMPLE INVOCATION:
            self.action_privacy()
            self.action_privacy("unlisted")
        """
        pl = self._current_playlist()
        if not pl:
            messagebox.showinfo("Privacy", "Select a playlist first.")
            return
        if status not in {"public", "unlisted", "private"}:
            win = ctk.CTkToplevel(self)
            win.title("Playlist privacy")
            win.geometry("360x180")
            win.transient(self)
            ctk.CTkLabel(win, text=f'"{pl.title}" is currently {pl.privacy}.').pack(pady=(16, 8))
            chosen: Dict[str, Optional[str]] = {"status": None}

            def pick(value: str) -> None:
                chosen["status"] = value
                win.destroy()

            row = ctk.CTkFrame(win, fg_color="transparent")
            row.pack(pady=8)
            for value in ("public", "unlisted", "private"):
                ctk.CTkButton(row, text=value.title(), width=100, command=lambda s=value: pick(s)).pack(
                    side="left", padx=6
                )
            win.grab_set()
            self.wait_window(win)
            status = chosen["status"]
            if not status:
                return

        privacy_value = str(status)

        def after(updated: Playlist) -> None:
            pl.privacy = updated.privacy
            iid = self._focused_playlist_iid()
            if iid:
                vals = list(self.pl_tree.item(iid, "values"))
                if len(vals) >= 3:
                    vals[2] = updated.privacy
                    self.pl_tree.item(iid, values=vals)
            messagebox.showinfo("Privacy", f'Set "{updated.title}" to {updated.privacy}.')

        self.run_task(
            "Set privacy",
            lambda: playlists.set_privacy(pl.id, privacy_value),
            after,
        )

    def action_delete(self) -> None:
        """
        PURPOSE:
            Delete the selected playlist after title match + undo checkbox.

        INTERNAL LOGIC:
            Pre-filled title; Ok requires checkbox "I understand this cannot be undone".

        EXAMPLE INVOCATION:
            self.action_delete()
        """
        pl = self._current_playlist()
        if not pl:
            messagebox.showinfo("Delete", "Select a playlist first.")
            return
        win = ctk.CTkToplevel(self)
        win.title("Delete Playlist")
        win.geometry("460x240")
        win.transient(self)
        ctk.CTkLabel(
            win,
            text=f'Type "{pl.title}" to permanently delete this playlist.\n'
            "Videos stay on YouTube. This cannot be undone.",
            justify="left",
        ).pack(anchor="w", padx=16, pady=(16, 8))
        entry = ctk.CTkEntry(win, width=400)
        entry.pack(padx=16, pady=4)
        entry.insert(0, pl.title)
        understood = ctk.CTkCheckBox(
            win,
            text="I understand this cannot be undone",
        )
        understood.pack(anchor="w", padx=16, pady=8)
        chosen: Dict[str, Optional[str]] = {"typed": None}

        def ok() -> None:
            if not understood.get():
                messagebox.showwarning(
                    "Delete Playlist",
                    "Check “I understand this cannot be undone” before deleting.",
                )
                return
            typed = entry.get()
            if typed.strip() != pl.title.strip():
                messagebox.showwarning("Delete Playlist", "Title does not match.")
                return
            chosen["typed"] = typed
            win.destroy()

        row = ctk.CTkFrame(win, fg_color="transparent")
        row.pack(fill="x", padx=16, pady=(8, 16))
        ctk.CTkButton(row, text="Cancel", width=90, fg_color="gray30", command=win.destroy).pack(
            side="right", padx=4
        )
        ctk.CTkButton(row, text="Delete", width=90, fg_color="#8e2a2a", command=ok).pack(side="right")
        win.grab_set()
        entry.focus()
        self.wait_window(win)
        typed = chosen["typed"]
        if typed is None:
            return
        self.run_task(
            "Delete playlist",
            lambda: playlists.delete_playlist(
                pl.id, confirm_title=typed, expected_title=pl.title
            ),
            lambda _r: self.refresh_all(),
        )

    def action_clear(self) -> None:
        """
        PURPOSE:
            Clear all videos from every selected playlist.

        INTERNAL LOGIC:
            Quota confirm (apply / dry-run); snapshots for Undo.

        EXAMPLE INVOCATION:
            self.action_clear()
        """
        selected = self._selected_playlists()
        if not selected:
            return
        names = ", ".join(f'"{p.title}"' for p in selected[:6])
        extra = "" if len(selected) <= 6 else f" (+{len(selected) - 6} more)"
        writes = sum(max(p.item_count, 0) for p in selected)
        body = self._quota_confirm_body(
            writes,
            f"Remove ALL videos from {len(selected)} playlist(s): {names}{extra}?\n"
            "Playlists themselves are kept. Videos stay on YouTube.",
        )
        choice = self._confirm_writes("Clear Videos", body)
        if not choice:
            return
        dry = choice == "dry"
        ids = [p.id for p in selected]

        def work() -> str:
            notes: List[str] = []
            for pid in ids:
                n = playlists.clear_playlist(pid, dry_run=dry)
                verb = "Would delete" if dry else "Cleared"
                notes.append(f"{verb} {n} item(s) from {pid}")
            return "\n".join(notes)

        def done(note: str) -> None:
            for pid in ids:
                self._invalidate_item_cache(pid)
            messagebox.showinfo("Clear Videos", note)
            self._reload_videos()

        self.run_task("Clear playlists (dry-run)" if dry else "Clear playlists", work, done)

    def action_trim(self) -> None:
        """
        PURPOSE:
            Remove duplicate videos from the selected playlist.

        INTERNAL LOGIC:
            trim_playlists for current id.

        EXAMPLE INVOCATION:
            self.action_trim()
        """
        pl = self._current_playlist()
        if not pl:
            return
        selected = self._selected_playlists()
        ids = [p.id for p in selected]

        def done(_r: Any) -> None:
            for pid in ids:
                self._invalidate_item_cache(pid)
            self._reload_videos()

        self.run_task(
            "Trim duplicates",
            lambda: trim_playlists(ids),
            done,
        )

    def action_sort(self, by: str) -> None:
        """
        PURPOSE:
            Queue-sort every selected playlist (title/date/duration/channel).

        INTERNAL LOGIC:
            Quota confirm; sort_many with progress; dry-run writes list-mode only.

        EXAMPLE INVOCATION:
            self.action_sort("duration")
        """
        selected = self._selected_playlists()
        if not selected:
            return
        ids = [p.id for p in selected]
        titles = {p.id: p.title for p in selected}
        writes = self._estimate_sort_writes(selected, by)
        body = self._quota_confirm_body(
            writes,
            f"Sort {len(ids)} playlist(s) by {by}.\n"
            "If Studio Sort is Manual, only moved items are rewritten in place.\n"
            "Otherwise a NEW playlist copy is created — the original is not emptied.\n"
            "Jobs are queued so Resume unfinished sorts can continue after Pacific midnight.",
        )
        choice = self._confirm_writes(f"Sort by {by}", body)
        if not choice:
            return
        dry = choice == "dry"

        def done(note: str) -> None:
            messagebox.showinfo("Sort", note)
            self.refresh_all()

        self.run_task(
            f"Sort by {by}" + (" (dry-run)" if dry else ""),
            lambda: sort.sort_many(
                ids,
                by=by,  # type: ignore[arg-type]
                dry_run=dry,
                titles=titles,
                on_progress=self._report_progress,
            ),
            done,
        )

    def action_resume_sorts(self) -> None:
        """
        PURPOSE:
            Continue queued sorts that stopped at quota.

        INTERNAL LOGIC:
            pending_sorts; resume_sorts with per-item progress.

        EXAMPLE INVOCATION:
            self.action_resume_sorts()
        """
        jobs = pending_sorts()
        if not jobs:
            messagebox.showinfo("Resume sorts", "No unfinished sorts in the queue.")
            return
        lines = [f"- {job.get('title') or job.get('playlist_id')} ({job.get('by')})" for job in jobs[:12]]
        extra = "" if len(jobs) <= 12 else f"\n…and {len(jobs) - 12} more"
        body = self._quota_confirm_body(
            len(jobs),
            f"{len(jobs)} unfinished sort(s):\n" + "\n".join(lines) + extra + "\n\n"
            "Resume uses remaining local quota and stops before the next write if the pool is empty.",
        )
        choice = self._confirm_writes("Resume unfinished sorts", body)
        if choice != "apply":
            return

        def done(note: str) -> None:
            messagebox.showinfo("Resume sorts", note)
            self.refresh_all()

        self.run_task("Resume sorts", lambda: sort.resume_sorts(on_progress=self._report_progress), done)

    def action_undo(self) -> None:
        """
        PURPOSE:
            Restore the focused playlist from a chosen list-mode snapshot.

        INTERNAL LOGIC:
            Lists last N snapshots (newest first); apply uses write quota.

        EXAMPLE INVOCATION:
            self.action_undo()
        """
        pl = self._current_playlist()
        if not pl:
            messagebox.showinfo("Undo", "Select a playlist first.")
            return
        from ytpm import list_mode

        snaps = list_mode.list_snapshots(pl.id, limit=SNAPSHOT_PICK_LIMIT)
        if not snaps:
            messagebox.showinfo(
                "Undo",
                "No snapshot found for this playlist. Undo is available after Sort or Clear.",
            )
            return
        win = ctk.CTkToplevel(self)
        win.title("Undo — pick a snapshot")
        win.geometry("560x360")
        win.transient(self)
        ctk.CTkLabel(
            win,
            text=f'Restore "{pl.title}" from a local snapshot (same write cost as List Mode Apply).',
            justify="left",
            wraplength=520,
        ).pack(anchor="w", padx=12, pady=(12, 6))
        tree = ttk.Treeview(win, columns=("when", "file"), show="headings", height=10, selectmode="browse")
        tree.heading("when", text="Saved", anchor="w")
        tree.heading("file", text="File", anchor="w")
        tree.column("when", width=160, anchor="w")
        tree.column("file", width=360, anchor="w")
        tree.pack(fill="both", expand=True, padx=12, pady=4)
        for path in snaps:
            when = datetime.fromtimestamp(path.stat().st_mtime).strftime("%Y-%m-%d %H:%M:%S")
            tree.insert("", "end", iid=str(path), values=(when, path.name))
        first = tree.get_children()
        if first:
            tree.selection_set(first[0])
            tree.focus(first[0])
        chosen: Dict[str, Optional[Path]] = {"path": None}

        def ok() -> None:
            sel = tree.selection()
            if not sel:
                messagebox.showinfo("Undo", "Select a snapshot.")
                return
            chosen["path"] = Path(str(sel[0]))
            win.destroy()

        row = ctk.CTkFrame(win, fg_color="transparent")
        row.pack(fill="x", padx=12, pady=(4, 12))
        ctk.CTkButton(row, text="Cancel", width=90, fg_color="gray30", command=win.destroy).pack(
            side="right", padx=4
        )
        ctk.CTkButton(row, text="Restore", width=90, command=ok).pack(side="right")
        win.grab_set()
        self.wait_window(win)
        path = chosen["path"]
        if path is None:
            return

        def done(note: str) -> None:
            messagebox.showinfo("Undo", note)
            self._reload_videos()

        self.run_task("Undo", lambda: list_mode.undo_playlist(pl.id, snapshot=path), done)

    def action_list_export(self) -> None:
        """
        PURPOSE:
            Export selected playlists to list-mode text files.

        INTERNAL LOGIC:
            list_mode.export_playlists on the current selection.

        EXAMPLE INVOCATION:
            self.action_list_export()
        """
        selected = self._selected_playlists()
        if not selected:
            messagebox.showinfo("List Mode", "Select one or more playlists first.")
            return
        from ytpm import list_mode

        self.run_task(
            "List mode export",
            lambda: list_mode.export_playlists(selected),
            lambda paths: messagebox.showinfo(
                "List Mode",
                f"Wrote {len(paths)} file(s) to\n{get_settings().list_dir()}",
            ),
        )

    def action_list_apply(self) -> None:
        """
        PURPOSE:
            Apply list-mode file edits to remote playlists.

        INTERNAL LOGIC:
            Quota confirm; apply_all with optional dry-run.

        EXAMPLE INVOCATION:
            self.action_list_apply()
        """
        from ytpm import list_mode

        writes = list_mode.estimate_apply_writes()
        body = self._quota_confirm_body(
            writes,
            "Apply edits from list_mode/*.txt to your YouTube playlists?\n"
            "Write estimate is worst-case (every file line). Dry run lists deletes/inserts/moves.",
        )
        choice = self._confirm_writes("List Mode Apply", body)
        if not choice:
            return
        dry = choice == "dry"
        self.run_task(
            "List mode apply (dry-run)" if dry else "List mode apply",
            lambda: list_mode.apply_all(dry_run=dry),
            lambda note: (
                messagebox.showinfo("List Mode", str(note)),
                None if dry else self.refresh_all(),
            ),
        )

    def action_export_json(self) -> None:
        """
        PURPOSE:
            Export every selected playlist to JSON.

        INTERNAL LOGIC:
            export.export_playlist_json per selected playlist.

        EXAMPLE INVOCATION:
            self.action_export_json()
        """
        selected = self._selected_playlists()
        if not selected:
            return

        def work() -> str:
            paths = [
                str(export.export_playlist_json(pl.id, title=pl.title))
                for pl in selected
            ]
            return "\n".join(paths)

        self.run_task(
            "Export JSON",
            work,
            lambda text: messagebox.showinfo("Export", f"Saved:\n{text}"),
        )

    def action_find_broken(self) -> None:
        """
        PURPOSE:
            Scan every selected playlist for unplayable (deleted/unavailable) videos.

        INTERNAL LOGIC:
            find_broken per playlist; optional remove_broken on those ids.

        EXAMPLE INVOCATION:
            self.action_find_broken()
        """
        selected = self._selected_playlists()
        if not selected:
            return

        def scan() -> List[Tuple[Playlist, PlaylistItem]]:
            found: List[Tuple[Playlist, PlaylistItem]] = []
            for pl in selected:
                for item in cleanup.find_broken(pl.id):
                    found.append((pl, item))
            return found

        def after(broken: List[Tuple[Playlist, PlaylistItem]]) -> None:
            if not broken:
                messagebox.showinfo(
                    "Broken videos",
                    f"No deleted or unavailable videos in {len(selected)} selected playlist(s).\n\n"
                    "Only rows YouTube labels 'Deleted video' or 'Private video' count as broken.\n"
                    "Unlisted videos you can still open on YouTube are ignored.",
                )
                return
            lines: List[str] = []
            for pl, item in broken[:40]:
                why = broken_reason(item) or item.privacy_status
                lines.append(f"- [{pl.title}] {item.title} ({why})")
            extra = "" if len(broken) <= 40 else f"\n…and {len(broken) - 40} more"
            remove = messagebox.askyesno(
                "Broken videos",
                f"Found {len(broken)} deleted/unavailable item(s) across "
                f"{len(selected)} playlist(s):\n"
                + "\n".join(lines)
                + extra
                + "\n\nRemove them from those playlists? (Videos are not deleted from YouTube.)",
            )
            if not remove:
                return
            pids = list({pl.id for pl, _item in broken})
            self.run_task(
                "Remove broken",
                lambda: sum(cleanup.remove_broken(pid) for pid in pids),
                lambda _n: self._reload_videos(),
            )

        self.run_task("Find broken", scan, after)

    def action_stats(self) -> None:
        """
        PURPOSE:
            Show duration/channel stats for every selected playlist.

        INTERNAL LOGIC:
            playlist_stats per id; one combined dialog.

        EXAMPLE INVOCATION:
            self.action_stats()
        """
        selected = self._selected_playlists()
        if not selected:
            return

        def work() -> str:
            blocks: List[str] = []
            for pl in selected:
                s = stats.playlist_stats(pl.id)
                blocks.append(
                    f"{pl.title}\n"
                    f"  Items: {s.item_count}\n"
                    f"  Total: {format_duration(s.total_seconds)}\n"
                    f"  Average: {format_duration(int(s.average_seconds))}\n"
                    f"  Longest: {s.longest_title} ({format_duration(s.longest_seconds)})\n"
                    f"  Shortest: {s.shortest_title} ({format_duration(s.shortest_seconds)})\n"
                    f"  Unique channels: {s.unique_channels}"
                )
            return "\n\n".join(blocks)

        self.run_task("Stats", work, lambda text: messagebox.showinfo("Stats", text))

    def action_help(self) -> None:
        """
        PURPOSE:
            Open the local Tutorials / Help page (docs.html) in the browser.

        INTERNAL LOGIC:
            Resolves docs.html next to the app and opens its file URI.

        EXAMPLE INVOCATION:
            self.action_help()
        """
        if not HELP_PATH.is_file():
            messagebox.showerror(
                "Tutorials / Help",
                f"Help file not found:\n{HELP_PATH}",
            )
            return
        webbrowser.open(HELP_PATH.resolve().as_uri())
        self.log(f"Opened help: {HELP_PATH}")

    def action_rename_video(self) -> None:
        """
        PURPOSE:
            Rename the selected video if the user uploaded it.

        INTERNAL LOGIC:
            Prompts for a new title; videos.update (50 units). Other channels fail.

        EXAMPLE INVOCATION:
            self.action_rename_video()
        """
        vids = self._selected_video_items()
        if not vids:
            messagebox.showinfo("Rename title", "Select a video row first.")
            return
        item = vids[0]
        if len(vids) > 1:
            messagebox.showinfo(
                "Rename title",
                "Renaming uses the first selected video only.\n"
                "This changes the video on YouTube (every playlist), not a playlist-only label.",
            )
        new_title = self._prompt_text(
            "Rename video title",
            f'New title for "{item.title}"?\n\n'
            "You can only rename videos you uploaded. Cost: 50 units.",
            item.title,
        )
        if not new_title or not new_title.strip():
            return
        new_title = new_title.strip()
        if new_title == item.title:
            return

        def done(title: str) -> None:
            item.title = title
            pid = self._selected_playlist_id
            if pid:
                self._invalidate_item_cache(pid)
            self._reload_videos()
            messagebox.showinfo("Rename title", f"Updated title to:\n{title}")

        self.run_task(
            "Rename video title",
            lambda: items.rename_video_title(item.video_id, new_title),
            done,
        )

    def action_remove(self) -> None:
        """
        PURPOSE:
            Remove selected videos from the current playlist.

        INTERNAL LOGIC:
            Confirms; deletes playlistItem ids; reloads.

        EXAMPLE INVOCATION:
            self.action_remove()
        """
        vids = self._selected_video_items()
        if not vids:
            return
        if not messagebox.askyesno("Remove", f"Remove {len(vids)} video(s) from this playlist?"):
            return
        ids = [v.id for v in vids]
        self.run_task(
            "Remove videos",
            lambda: items.remove_items(ids),
            lambda _n: self._reload_videos(),
        )

    def action_copy(self) -> None:
        """
        PURPOSE:
            Copy selected videos to another playlist (skip duplicates).

        INTERNAL LOGIC:
            Destination picker → copy_videos.

        EXAMPLE INVOCATION:
            self.action_copy()
        """
        vids = self._selected_video_items()
        if not vids:
            return
        dest = self._pick_dest_playlist("Copy to playlist")
        if not dest:
            return

        def done(n: int) -> None:
            self._invalidate_item_cache(dest)
            self.log(f"Copied {n} videos")

        self.run_task(
            "Copy videos",
            lambda: items.copy_videos(dest, vids, skip_duplicates=True),
            done,
        )

    def action_move(self) -> None:
        """
        PURPOSE:
            Move selected videos to another playlist.

        INTERNAL LOGIC:
            Destination picker → move_videos → reload source.

        EXAMPLE INVOCATION:
            self.action_move()
        """
        pl = self._current_playlist()
        vids = self._selected_video_items()
        if not pl or not vids:
            return
        dest = self._pick_dest_playlist("Move to playlist")
        if not dest:
            return

        def done(_n: Any) -> None:
            self._invalidate_item_cache(dest)
            self._reload_videos()

        self.run_task(
            "Move videos",
            lambda: items.move_videos(pl.id, dest, vids),
            done,
        )

    def _on_close(self) -> None:
        """
        PURPOSE:
            Persist settings and destroy the window.

        INTERNAL LOGIC:
            save_settings then destroy.

        EXAMPLE INVOCATION:
            self.protocol("WM_DELETE_WINDOW", self._on_close)
        """
        if self._busy:
            if not messagebox.askyesno(
                "Busy",
                "A YouTube task is still running. Quit anyway? Incomplete writes may be left on YouTube.",
            ):
                return
        self._save_settings()
        audit = logging.getLogger("ytpm.audit")
        handler = getattr(self, "_audit_handler", None)
        if handler:
            audit.removeHandler(handler)
        self.destroy()


def main() -> None:
    """
    PURPOSE:
        GUI process entrypoint.

    INTERNAL LOGIC:
        Single-instance mutex; logging (including file log for pythonw);
        constructs App; mainloop. Uncaught exceptions go to gui_crash.log.

    EXAMPLE INVOCATION:
        python ytpm_gui.py
    """
    log_file = ROOT / "gui_crash.log"
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
        handlers=[
            logging.StreamHandler(sys.stderr),
            logging.FileHandler(log_file, encoding="utf-8"),
        ],
    )
    if not acquire_or_activate():
        return
    try:
        app = App()
        app.mainloop()
    except Exception:
        logger.exception("Fatal GUI error")
        # Re-raise so non-pythonw runs still show a traceback; pythonw users can open gui_crash.log
        try:
            messagebox.showerror(
                "YouTube Playlist Manager",
                f"A fatal error occurred. Details were written to:\n{log_file}",
            )
        except Exception:
            pass
        raise


if __name__ == "__main__":
    main()
