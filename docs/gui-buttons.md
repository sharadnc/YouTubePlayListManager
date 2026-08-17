# YTPM GUI buttons

Costs assume **one playlist of 50 videos**, YouTube Data API v3, and the default **10,000 units/day** pool (resets midnight US Pacific). The sidebar quota meter is a **local estimate** (Google does not expose remaining Data API quota).

| Method | Units |
| --- | ---: |
| `playlists.list`, `playlistItems.list`, `videos.list`, `channels.list` | 1 per request (50 results/page) |
| `playlists.insert` / `update` / `delete` | 50 |
| `playlistItems.insert` / `update` / `delete` | 50 |
| `videos.update` | 50 |

Reads are cheap. Writes are **50 units each**. OAuth sign-in is **not** billed against this quota.

After several actions the app also **Refresh**es (listed separately below). Those extra units are included in the Cost column when the button always refreshes.

**Dry run** (Sort / Clear / List Mode Apply): Yes = apply, No = dry run (writes the list-mode file, **0 write quota**), Cancel = abort.

Rename Playlist, Rename title, and Delete Playlist open with the **current name already in the box**. Ok with the same playlist/video title skips the write.

---

| Button | Purpose | Functionality | YouTube API Costs (50-video playlist) |
| --- | --- | --- | --- |
| **Connect Google Account** (sidebar and startup banner) | Sign in so the app can read and edit your playlists. | Opens the Google OAuth browser flow, stores a local token, then loads playlists. Same action as the banner button. | **0 Data API units** for OAuth. After success it runs Refresh (~see Refresh). |
| **Reconnect / Switch Account** | Change Google account or force a new consent screen. | Clears the cached token, runs OAuth again, then loads playlists. | **0 Data API units** for OAuth. After success it runs Refresh. |
| **Quota meter** (sidebar label) | Show ~units left today. | Reads local `quota_ledger.json` (Pacific date). Not a Google API field. Each **write** is also logged as `WRITE method id=… units=50` so you can match Google Cloud’s quota graph. | **0 units**. |
| **Sort queue** (sidebar table) | See pending/done sort jobs; drop or reorder. | Playlist title, sort key, status. **Drop** removes a job. **Up/Down** change run order. Resume unfinished sorts still runs pending jobs in this order. | **0 units** (local). |
| **Refresh** | Reload the playlist list from YouTube and drop the local video cache. | Calls `playlists.list` (paginated). Selecting a playlist then loads its videos (`playlistItems.list` + `videos.list`) unless a cache hit. | Playlists: **1 unit per 50 playlists** you own. Loading the 50-video playlist: **~2 units**. Typical total **~3 units**. Cache hit when switching playlists: **0**. |
| **Filter playlists…** (table search) | Find year-named lists without scrolling. | Filters the playlists table by title or id as you type. Ctrl/Shift multi-select is kept for rows that stay visible. | **0 units** (local). |
| **Filter videos…** (table search) | Find a video in the current playlist. | Filters the videos table by title, channel, or video id as you type. | **0 units** (local). |
| **New Playlist** | Create an empty playlist. | Prompts for a title (empty box); `playlists.insert` (private); then Refresh. | **50** to create + Refresh (**~3**). Total **~53**. Independent of video count (new list is empty). |
| **Rename** | Change the selected playlist’s title. | Box is pre-filled. `playlists.list` then `playlists.update`; then Refresh. Same title: no write. **F2** on the playlists table. | **1 + 50** + Refresh **~3**. Total **~54**. Unchanged name: **0**. |
| **Description…** | Edit the playlist description. | Pre-filled text box. `playlists.update` (keeps title and privacy). Unchanged text: list only. | **1** if unchanged; **1 + 50** if saved. |
| **Privacy** | Set public / unlisted / private. | One `playlists.update` on the focused playlist. | **50**. |
| **Delete Playlist** | Permanently delete the selected playlist. | Box is pre-filled. Ok requires the checkbox **I understand this cannot be undone** and a matching title. One `playlists.delete` (videos stay on YouTube); then Refresh. | **50** + Refresh **~3**. Total **~53**. Does **not** cost 50×50 to remove items. |
| **Clear Videos** | Empty every **selected** playlist but keep the playlists. | Quota confirm + dry run. Snapshots for Undo, then `playlistItems.delete` on every row. | **1** (list) + **50 × 50 deletes = 2,500** per playlist. Dry run: list + snapshot file, **0 writes**. |
| **Trim Duplicates** | Keep the first copy of each video id; remove later repeats. | Lists items, deletes duplicate playlist rows only. Applies to every **selected** playlist. | Reads: **~1–2** + **1** (items). Writes: **50 × (number of duplicate rows)**. No duplicates: **~3**. |
| **Sort by Title** | A–Z after collapsing extra spaces in titles you own and removing duplicates. | Queued sparse sort (see Notes). Dry run writes list-mode with 0 writes. Per-item progress. Studio **Sort → Manual** for in-place moves; otherwise a **new** sorted copy. | **Best (already A–Z, clean):** **0 writes** + **~2–4 reads**. **Typical:** **50 × (collapsed titles + deleted dupes + moved items)**. **Copy fallback:** **~2,550** plus any title/dupe writes. |
| **Sort by Date Added** | Oldest-first by date added, after the same cleanup as Sort by Title. | Same sparse writes. Duplicate rows keep the **oldest** copy. Copy fallback if Sort is not Manual. A later sort on the same playlist **replaces** the queued key (Title → Date). | Same write rules as Sort by Title. |
| **Sort by Duration** | Shortest-first (same 50-unit position writes). | Enriches durations (`videos.list`), then the same sparse move/dedupe path. Still needs Studio **Sort → Manual**. | Enrich **~1** extra read + same write rules as Sort by Title. |
| **Sort by Channel** | Channel name A–Z (same 50-unit position writes). | Enriches channel titles, then sparse moves. Still needs Studio **Sort → Manual**. | Enrich **~1** extra read + same write rules as Sort by Title. |
| **Resume unfinished sorts** | Continue the sort job queue after quota runs out. | List Mode already saved intended order. Stops when local remaining units < 50. Resume after Pacific midnight. | Same as the remaining sort writes. **0** if the queue is empty. |
| **Undo…** | Restore the focused playlist from a chosen list-mode snapshot. | Picker lists the last 20 snapshots (newest first). Applies that file (same writes as List Mode Apply). | Same as List Mode Apply for that playlist. |
| **List Mode: Export selected** | Save **selected** playlists as tab-separated text files. | `playlistItems.list` for each selected playlist only (not every playlist you own). | **~1 per selected playlist** (50 videos = 1 page). **0 writes**. |
| **List Mode: Apply** | Push edits from those text files back to YouTube. | Quota confirm + dry run. Diffs each file, then deletes/inserts/moves. | Per 50-video file: **~2 lists**. Writes: **50 × (deletes + inserts + moved items)**. Dry run: reads only. |
| **Export JSON** | Snapshot every **selected** playlist to JSON. | Lists items, `videos.list` for metadata, writes under the export folder. | **~2 units** per selected playlist. **0 writes**. |
| **Find Broken** | Find deleted / private-unavailable rows in every **selected** playlist. | Lists items, enriches, reports placeholder titles. Optionally removes those playlist rows. | Scan: **~2 units** per playlist. Removing *B* rows: **+50 × B**. |
| **Stats** | Duration totals and unique channels for every **selected** playlist. | Lists items, `videos.list` for durations, combined dialog. | **~2 units** per selected playlist. **0 writes**. |
| **Tutorials / Help** | Open this product guide in the browser. | Opens local `docs.html` (no YouTube API). Available even when not connected. | **0 units**. |
| **Open in Browser** | Watch the selected video on YouTube. | Opens `https://www.youtube.com/watch?v=…` for the first selected row. Double-click / `o` key. | **0 units**. |
| **Open in Studio** | Open the focused playlist in YouTube Studio. | `https://studio.youtube.com/playlist/{id}/videos` (set **Sort → Manual** here). **Enter** on a playlist or video row. | **0 units**. |
| **Rename title…** | Change the YouTube title of a selected video you uploaded. | Box is pre-filled. `videos.update`. Not a playlist-only nickname — the title changes everywhere. Other channels are rejected. Same title: no write. **F2** on the videos table. | **1** (`videos.list`) + **50** write. Already the same title: **0 writes**. |
| **Remove** | Remove selected videos from **this** playlist. | Confirms, `playlistItems.delete` for each selected playlist item (videos stay on YouTube), reloads. **Del** on the videos table. | **50 × (selected rows)** + reload **~2**. |
| **Copy…** | Copy selected videos onto another playlist (skips ids already there). | Searchable destination picker (filter as you type; IDs shown so duplicate titles cannot collide). Destination cache is dropped so the dest list is fresh next time you open it. | Destination list: **1**. Writes: **50 × (videos actually copied)**. |
| **Move…** | Move selected videos from this playlist to another. | Same searchable picker; insert into dest then delete from source; reloads source. | **100 × (moved videos)** + reload **~2**. |

---

## Notes

- **Selecting a playlist** in the left table costs **~2 units** the first time (`playlistItems.list` + `videos.list`). Switching back uses the **local item cache** (**0 units**) until Refresh or a mutation.
- **Column headers** (Title, Items, Duration, …) sort the table **locally** only: **0 units**. On startup, Refresh, and after a filter rebuild, Playlists default to **Title ▲** and Videos to **# ▲**. Click another heading to change it until the next rebuild.
- **Multi-select playlists** (Ctrl/Shift): Trim, Sort, Clear, Find Broken, Export JSON, Stats, and List Mode Export selected all run on **every selected playlist**.
- **Sort by Title / Date / Duration / Channel** share the same sparse writes:
  - **Titles:** `videos.update` only if the title still has extra spaces **and** you own the video.
  - **Duplicates:** `playlistItems.delete` only when a duplicate is found (same video id, or same title after space-collapse). Placeholder titles (`Deleted video` / `Private video`) are **not** merged with each other. Date sort keeps the **oldest** copy.
  - **Order:** `playlistItems.update` only for items that are not already in the right slot. Already-sorted playlists cost **0 write quota**.
- Set Studio **Sort → Manual** (Open in Studio) before sorting so the app can patch positions in place. Otherwise it spends copy-fallback quota (**~2,550** for 50 videos) and does not reorder the original.
- There is no cheaper official reorder method. **10,000 units/day ÷ 50 = 200 writes**. Do not use unofficial YouTube web APIs to dodge quota.
- **Keyboard:** **F2** rename (playlist or video title, last-clicked table), **Del** remove selected videos, **Ctrl+F** focus the videos filter, **Enter** open the playlist in Studio. Right-click a row for rename, privacy, copy/move, and Studio.
- Window size, the playlist/videos split, both filter boxes, and the last playlist are remembered in `gui_settings.json` (saved when you close the app). **First launch** (or a missing/invalid split): Playlists and Videos each get **50%** height. After you drag the divider, the ratio (`sash_frac`) is restored on the next start. A second `Run_YTPM.vbs` / `YTPM.exe` focuses the existing window instead of stacking another.
- Launch: Prefer **`Run_YTPM.vbs`** (no CMD window). It reads `YTPM_VENV` from `.env`, runs `ytpm_launch.pyw` under `pythonw`, and installs missing packages via `ensure_deps` (pip uses CREATE_NO_WINDOW). `Run_YTPM.bat` delegates to the `.vbs`. CLI/Build still use `ytpm_resolve_venv.bat`. Packaged **YTPM.exe** ignores `YTPM_VENV` — put `.env` next to the exe. Team zip: `Build_YTPM.bat --zip` (see `docs/distribute.md`).
- CLI (same ops as the GUI): `ytpm sort PLAYLIST --by title` (or date, duration, channel) with optional `--dry-run` / `--reverse`; `ytpm sort --resume`; `ytpm items rename VIDEO_ID "New title"`; `ytpm playlists description PLAYLIST "Text"`; `ytpm list export [ids…]`; `ytpm list apply [--dry-run]`; `ytpm playlists privacy PLAYLIST public`; `ytpm stats PLAYLIST`; `ytpm version`. See the CLI section (`docs/cli.md`).
