# YTPM CLI

Same YouTube Data API v3 operations as the GUI. Prefer `Run_YTPM_CLI.bat` (reads `YTPM_VENV` from `.env` and runs `ensure_deps.py` first). Or use `python -m ytpm` from that same venv. Global flag: `-v` / `--verbose` (debug logging).

## Auth and GUI

| Command | What it does |
| --- | --- |
| `ytpm auth` | Google OAuth browser consent. `--force` reconnects / switches account. |
| `ytpm auth --force` | Clears the token and re-consents. |
| `ytpm gui` | Launches `ytpm_gui.py`. |
| `ytpm version` | Prints the package version (also used in `release\YTPM-<version>-windows.zip`). |

OAuth is **0 Data API units**. Writes after that follow the same 50-unit costs as the GUI.

## Playlists

| Command | What it does |
| --- | --- |
| `ytpm playlists` | List owned playlists. |
| `ytpm playlists create "Title"` | Create a private playlist (**50**). |
| `ytpm playlists rename PLAYLIST "New title"` | Rename (**1 + 50**). |
| `ytpm playlists privacy PLAYLIST public` | One `playlists.update` (**50**). Also `unlisted` or `private`. |
| `ytpm playlists description PLAYLIST "Text"` | Update description (**1** if unchanged, else **1 + 50**). |
| `ytpm playlists delete PLAYLIST` | Type-to-confirm delete, or `--yes --confirm-name "Title"` (**50**). |
| `ytpm playlists clear PLAYLIST` | Remove all items. `--dry-run` snapshots only (**0 writes**). `--yes` skips the prompt. |

`PLAYLIST` may be a playlist id or an exact title.

## Items

| Command | What it does |
| --- | --- |
| `ytpm items add PLAYLIST VIDEO_ID` | Insert one video (**50**). |
| `ytpm items remove PLAYLIST_ITEM_ID` | Delete that playlist row (**50**). Video stays on YouTube. |
| `ytpm items rename VIDEO_ID "New title"` | `videos.update` on a video **you uploaded** (**1 + 50**). Changes the title everywhere, not only in one playlist. |

## Sort, trim, list mode

| Command | What it does |
| --- | --- |
| `ytpm sort PLAYLIST --by title` | Sparse sort. `--by` is `title`, `date`, `duration`, or `channel`. |
| `ytpm sort PLAYLIST --by title --dry-run` | Writes the list-mode file; **0 write quota**. |
| `ytpm sort PLAYLIST --by title --reverse` | Reverse the chosen key (Z–A, newest first, longest first, …). |
| `ytpm sort --resume` | Continues `sort_queue.json` after Pacific midnight. |
| `ytpm trim PLAYLIST [PLAYLIST…]` | Remove duplicate video ids. |
| `ytpm trim --all` | Trim every owned playlist. |
| `ytpm list export` | Export **all** playlists to list-mode text. |
| `ytpm list export PLAYLIST [PLAYLIST…]` | Export selected playlists only. |
| `ytpm list apply` | Apply `list_mode/*.txt`. |
| `ytpm list apply --dry-run` | Print planned deletes/inserts/moves; **0 writes**. |

## Export and cleanup

| Command | What it does |
| --- | --- |
| `ytpm export PLAYLIST` | JSON snapshot under the export folder (**~2** reads). |
| `ytpm stats PLAYLIST` | Duration totals, longest/shortest, unique channels (**~2** reads). |
| `ytpm cleanup PLAYLIST` | Find broken (placeholder) rows. |
| `ytpm cleanup PLAYLIST --remove` | Delete those playlist rows (**50 × count**). Optional `--private` / `--unlisted` to include those statuses in the scan. |

## Notes

- `--by` for sort: `title`, `date`, `duration`, `channel`. Add `--reverse` to invert.
- Dry-run sort/clear/apply still **reads** (list items). They do not spend **write** quota.
- Quota resets at midnight US Pacific. Google does not expose remaining Data API units; YTPM tracks a local ledger.
- `Run_YTPM_CLI.bat` uses `YTPM_VENV` from `.env` and installs missing libraries on startup (`ensure_deps.py`).
- Do not use unofficial YouTube web APIs to dodge quota.

See the button reference above (`docs/gui-buttons.md`) for GUI costs.
