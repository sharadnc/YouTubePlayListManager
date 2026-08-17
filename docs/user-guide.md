# YTPM Application User Guide

How to use YouTube Playlist Manager day to day after [setup](setup-guide.md).

YTPM only manages **playlists you own** through the official YouTube Data API. It is designed for **sparse writes**: titles, duplicates, and positions are updated only when they actually need to change. An already-clean, already-sorted playlist costs **zero write quota**.

---

## Start the app

| Launch | Result |
| --- | --- |
| `Run_YTPM.vbs` | **Preferred** GUI start — no black CMD window |
| `Run_YTPM.bat` | Starts the `.vbs` (a brief flash is possible); `--console` for debug |
| `Run_YTPM_CLI.bat …` | CLI (`python -m ytpm`). Same venv + dep check |
| `YTPM.exe` | Packaged GUI (`.env` next to the exe; no venv). Team zip: [distribute.md](distribute.md) |

Only one GUI instance runs; a second launch focuses the existing window.

Open **Tutorials / Help** anytime for the local product page (`docs.html`). Full button costs: [gui-buttons.md](gui-buttons.md). CLI: [cli.md](cli.md). Setup / `.env`: [setup-guide.md](setup-guide.md).

---

## Window layout

```text
┌──────────── Sidebar ────────────┬──────── Main ─────────────────────┐
│ Quota meter                     │ Playlists table + filter          │
│ Sort queue (Drop / Up / Down)   │ ───────────────────────────────── │
│ Google Account                  │ Videos bar + filter + actions     │
│ Playlist Actions                │ Videos table                      │
│ Progress / status / log         │                                   │
└─────────────────────────────────┴───────────────────────────────────┘
```

- **Playlists** (top): title, item count, privacy, playlist id. Default sort: **Title ▲**.
- **Videos** (bottom): position `#`, title, channel, duration, status, video id. Default sort: **# ▲**.
- First launch: playlists and videos each get **50%** of the main pane. Drag the split to change it. Closing the app writes window size, split (`sash_frac`), both filter boxes, and the last playlist to `gui_settings.json`; the next start restores them.
- Click a column header to sort that table locally (▲/▼). Filters reset to the default sort.

---

## Connect and refresh

1. **Connect Google Account** (or the banner button) on first use.
2. **Reconnect / Switch Account** clears the token and runs OAuth again.
3. **Refresh** reloads playlists from YouTube and clears the in-memory video cache.

Selecting a playlist loads its videos (~2 API units the first time). Switching back uses the **local cache** (0 units) until Refresh or a change that invalidates that playlist.

---

## Select and filter

| Action | How |
| --- | --- |
| Focus one playlist | Click its row (videos pane follows the focused row) |
| Multi-select playlists | Ctrl+click or Shift+click |
| Filter playlists | Type in **Filter playlists…** (title or id) |
| Filter videos | Type in **Filter videos…** (title, channel, or video id), or **Ctrl+F** |
| Select all videos | Ctrl+A in the videos table |

Multi-select playlist actions (run on **every** selected playlist): Trim, Sort, Clear Videos, Find Broken, Export JSON, Stats, List Mode Export.

---

## Playlist actions

| Goal | What to use |
| --- | --- |
| Create empty list | **New Playlist** (created private) |
| Rename | **Rename** or **F2** (box pre-filled; same name = no write) |
| Edit description | **Description…** (`playlists.update`, 50 units when text changes) |
| Public / unlisted / private | **Privacy** or right-click → Privacy |
| Delete the playlist | **Delete Playlist** — title must match **and** check **I understand this cannot be undone**. Videos stay on YouTube. |
| Empty the playlist | **Clear Videos** — keeps the playlist; confirm Apply / Dry run / Cancel |
| Open in Studio | **Open in Studio** or **Enter** — set **Sort → Manual** here before sorting in place |

Right-click a playlist row for rename, description, privacy, Studio, and delete.

---

## Video actions

| Goal | What to use |
| --- | --- |
| Watch on YouTube | **Open in Browser**, double-click, or **o** |
| Rename a video you uploaded | **Rename title…** or **F2** on the videos table — changes the title **everywhere**, not only in this playlist |
| Remove from this playlist | **Remove** or **Del** — video stays on YouTube |
| Copy to another playlist | **Copy…** — searchable destination; skips ids already there |
| Move to another playlist | **Move…** — insert into dest, delete from source |

Right-click a video row for rename, copy, move, remove, Browser, and Studio.

---

## Sort, trim, and the sort queue

### Before you sort

1. Select one or more playlists.
2. Open the playlist in Studio and set **Sort → Manual**.  
   Without Manual, YTPM may fall back to creating a **new** sorted copy (~2,550 units for 50 videos) instead of reordering the original.
3. Prefer a **dry run** first (dialog: Yes = apply, No = dry run, Cancel = abort). Dry run writes the intended order to List Mode with **0 write quota**.

### Sort modes

| Button | Order |
| --- | --- |
| Sort by Title | A–Z (collapses extra spaces on titles **you own**, removes duplicates) |
| Sort by Date Added | Oldest first (keeps oldest duplicate) |
| Sort by Duration | Shortest first |
| Sort by Channel | Channel name A–Z |

Only items that actually need a title fix, duplicate delete, or position move spend write quota.

### Sort queue

Large sorts can stop when the local meter has fewer than 50 units left. Jobs appear in the sidebar **Sort queue** (playlist, key, pending/done).

- **Drop** — remove a job  
- **Up / Down** — change run order  
- **Resume unfinished sorts** — continue after Pacific midnight (or when quota remains)

Queueing Sort by Date on a playlist that already has a pending Sort by Title **replaces** that pending job’s key.

### Trim Duplicates

Keeps the first copy of each video id; deletes later playlist rows only. Applies to every selected playlist.

---

## List Mode and Undo

**List Mode** is a text-file workflow for offline editing and for saving intended order without spending write quota.

1. **List Mode: Export selected** — writes tab-separated files under `list_mode/`.
2. Edit the files in any text editor (order, remove lines, add video ids).
3. **List Mode: Apply** — Yes = push to YouTube, No = dry run (show plan, 0 writes).

Before Sort, Clear, or Apply, YTPM often writes a **snapshot** under `list_mode/snapshots/`.

**Undo…** opens a picker of the last 20 snapshots for the focused playlist (newest first). Restoring uses the same write cost as Apply. Pick carefully.

---

## Export, broken rows, and stats

| Button | Result |
| --- | --- |
| Export JSON | Metadata snapshot under `exports/` (~2 read units per selected playlist) |
| Find Broken | Rows titled like `Deleted video` / `Private video`; optional remove from the playlist |
| Stats | Total duration and unique channels for the selection |

---

## Quota and the log

- Sidebar **quota meter** ≈ units left today (local ledger). Google does **not** expose remaining Data API quota.
- Each write is logged as `WRITE method id=… units=50` so you can reconcile with [Google Cloud quotas](https://console.cloud.google.com/apis/api/youtube.googleapis.com/quotas).
- Default pool: **10,000 / day**. **10,000 ÷ 50 = 200 writes** per day.
- Prefer dry runs and List Mode when planning large cleanups across multiple days.

Official quota increase / audit links are in Help (`docs.html`) and Google’s YouTube API docs.

---

## Keyboard shortcuts

| Key | Action |
| --- | --- |
| **F2** | Rename playlist or video title (last-clicked table) |
| **Del** | Remove selected videos from this playlist |
| **Ctrl+F** | Focus videos filter |
| **Enter** | Open focused playlist in YouTube Studio |
| **o** | Open selected video in the browser |
| **Ctrl+A** | Select all rows in the focused tree |

Shortcuts are ignored while typing in a filter or text field.

---

## Safety reminders

- **Delete Playlist** is permanent for the playlist object; videos remain on YouTube. Requires matching title + checkbox.
- **Clear Videos** removes every playlist row; use dry run and Undo snapshots when unsure.
- **Rename title…** updates the video on YouTube globally — only works for videos **you** uploaded.
- Do not use unofficial YouTube “web” APIs to dodge quota; YTPM stays on Data API v3 only.

---

## Typical workflows

### Alphabetical year playlist

1. Studio → **Sort → Manual**.
2. Select the playlist → **Sort by Title** → No (dry run) → inspect List Mode file.
3. Sort by Title again → Yes (apply).
4. If quota runs out, wait until Pacific midnight → **Resume unfinished sorts**.

### Clean duplicates without reordering

1. Multi-select playlists → **Trim Duplicates**.

### Move a batch into another list

1. Select videos → **Move…** → pick destination (filter by name or id).

### Recover after a bad sort

1. Select the playlist → **Undo…** → choose the snapshot from before the change → Restore.

---

## CLI (same operations)

Examples:

```text
Run_YTPM_CLI.bat playlists
Run_YTPM_CLI.bat sort "2024" --by title --dry-run
Run_YTPM_CLI.bat sort --resume
Run_YTPM_CLI.bat list export "2024"
Run_YTPM_CLI.bat playlists description "2024" "Favorites from 2024"
Run_YTPM_CLI.bat stats "2024"
Run_YTPM_CLI.bat version
```

Full command table: [cli.md](cli.md).

---

## Related docs

| Doc | Contents |
| --- | --- |
| [setup-guide.md](setup-guide.md) | Install, `.env`, first connect |
| [distribute.md](distribute.md) | Zip `YTPM.exe` for other Windows PCs |
| [oauth-setup.md](oauth-setup.md) | Google Cloud Client ID / Secret |
| [gui-buttons.md](gui-buttons.md) | Every button and unit cost |
| [cli.md](cli.md) | CLI reference (`stats`, `version`, sort `--reverse`, …) |
| [docs.html](../docs.html) | In-app Help |
