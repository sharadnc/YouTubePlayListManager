# YTPM Setup Guide

YouTube Playlist Manager (YTPM) is a Windows desktop app (and CLI) for managing **your** YouTube playlists through the official YouTube Data API v3.

This guide gets you from a clean machine to a signed-in app. For day-to-day use after setup, see the [Application User Guide](user-guide.md).

---

## What you need

| Requirement | Notes |
| --- | --- |
| Windows 10/11 | Prefer `Run_YTPM.vbs` for a silent GUI start; CLI uses `.bat` |
| Google account | Must own (or manage) the YouTube channel |
| Google Cloud project | Free tier is enough for personal use |
| Python 3.10+ | Only if you run from source (not the packaged `.exe`) |
| Internet | Browser OAuth + YouTube API calls |

Quota default: **10,000 Data API units per day** per Google Cloud project (resets midnight US Pacific). OAuth sign-in itself costs **0** units. Writes cost **50** units each.

---

## Choose how you will run YTPM

### Option A — From source (developers / this repo)

1. Clone or copy the project folder (for example `AI_Youtube`).
2. Create or reuse a Python virtual environment. Set its **root** in `.env`:

   `YTPM_VENV=C:\PythonVenvs\venv`

   `Run_YTPM.vbs` is the silent GUI entry (no CMD window). It reads `YTPM_VENV`, runs `ytpm_launch.pyw` under `pythonw`, installs missing packages, then opens the app. `Run_YTPM.bat` / `Run_YTPM_CLI.bat` / `Build_YTPM.bat` still use `ytpm_resolve_venv.bat` for the same venv path.
3. Missing libraries from `requirements.txt` are installed automatically on startup (`ensure_deps`, with no console when launched via the `.vbs`).

### Option B — Packaged `YTPM.exe` (no Python on the user PC)

Recommended for multiple users: zip the whole `dist\YTPM\` folder (exe + `_internal`). See [distribute.md](distribute.md).

1. On a machine that already has the source + venv, run `Build_YTPM.bat --zip` (build interpreter still comes from `YTPM_VENV`). Use `Build_YTPM.bat --zip --with-env` only when shipping a **shared** Desktop OAuth client from this PC’s `.env`.
2. Send `release\YTPM-<version>-windows.zip`. Recipients unzip and keep `YTPM.exe` next to `_internal`.
3. Put a `.env` file **next to** `YTPM.exe` with Client ID/Secret (template is in the zip unless you used `--with-env`). The exe does **not** use `YTPM_VENV`.
4. Double-click `YTPM.exe`, then **Connect Google Account**. Each user gets their own `token.json`. First launch: Playlists and Videos each get **50%** of the main pane.

---

## Step 1 — Google Cloud and OAuth credentials

You create a **Desktop** OAuth client in Google Cloud Console, then store the Client ID and Client Secret in `.env`. YTPM creates `token.json` after the first browser sign-in.

**Full click-by-click guide:** [oauth-setup.md](oauth-setup.md)

Summary:

1. Create a Google Cloud project.
2. Enable **YouTube Data API v3**.
3. Configure the **OAuth consent screen** and add yourself as a **Test user** while the app is in Testing.
4. Create credentials → **OAuth client ID** → application type **Desktop app**.
5. Copy **Client ID** and **Client secret**.

Do **not** paste the Client Secret into `token.json`. That file is written automatically later.

---

## Step 2 — Create `.env`

In the project folder (or next to `YTPM.exe` for the packaged build):

1. Copy `.env.example` to `.env` if `.env` does not exist.
2. Fill in:

```env
YOUTUBE_CLIENT_ID=your-client-id.apps.googleusercontent.com
YOUTUBE_CLIENT_SECRET=your-client-secret
YOUTUBE_TOKEN_PATH=./token.json
YTPM_LIST_DIR=./list_mode
YTPM_EXPORT_DIR=./exports
YTPM_VENV=C:\PythonVenvs\venv
```

3. Save. Keep `.env` private (it is listed in `.gitignore`).

| Variable | Meaning |
| --- | --- |
| `YOUTUBE_CLIENT_ID` | OAuth Desktop client ID from Cloud Console |
| `YOUTUBE_CLIENT_SECRET` | OAuth client secret |
| `YOUTUBE_TOKEN_PATH` | Where refresh/access tokens are stored (default `./token.json`) |
| `YTPM_LIST_DIR` | List Mode text files and undo snapshots |
| `YTPM_EXPORT_DIR` | JSON export folder |
| `YTPM_VENV` | Virtualenv **root** for `.bat` launchers (`Scripts\python.exe` inside). Ignored by `YTPM.exe`. |

---

## Step 3 — First launch and Google sign-in

### GUI

1. Double-click **`Run_YTPM.vbs`** (preferred — no DOS prompt). `Run_YTPM.bat` also starts the `.vbs` but may flash a console briefly. Or use `YTPM.exe` if packaged.
2. Source launches install anything missing (`ensure_deps` via `ytpm_launch.pyw`) before the GUI appears.
3. Click **Connect Google Account**.
4. In the browser, pick the Google account that owns the channel (and that you added as a Test user).
5. Approve YouTube access. If you see “Google hasn’t verified this app”, use **Advanced** → continue while the consent screen is in Testing.
6. Return to YTPM. Status should show **Connected**, and playlists should load.

A second `Run_YTPM.vbs` / `Run_YTPM.bat` / `YTPM.exe` focuses the existing window instead of opening another instance.

### CLI

```text
Run_YTPM_CLI.bat auth
```

or:

```text
python -m ytpm auth
```

Use `auth --force` (or **Reconnect / Switch Account** in the GUI) to clear `token.json` and sign in again.

After success, `token.json` exists next to the app. Treat it like a password.

---

## Step 4 — Verify the install

| Check | Expected |
| --- | --- |
| GUI opens | Window title **YouTube Playlist Manager** |
| Split (first launch) | Playlists (top) and Videos (bottom) each ~**50%** height |
| Connected | Sidebar shows Connected; playlists appear after Refresh |
| Help | **Tutorials / Help** opens local `docs.html` |
| CLI list | `Run_YTPM_CLI.bat playlists` prints your playlists |
| Tests (source only) | `python -m pytest tests -q` |

If playlists fail with `403` / `accessNotConfigured`, enable YouTube Data API v3 on the **same** Cloud project as the OAuth client.

---

## Local files YTPM creates

| Path | Purpose | Commit to git? |
| --- | --- | --- |
| `.env` | Client ID / Secret, `YTPM_VENV`, paths | **No** |
| `token.json` | OAuth tokens | **No** |
| `gui_settings.json` | Window size, 50/50 default split (`sash` / `sash_frac`), filters, last playlist | No |
| `release/` | Builder zip (`YTPM-*-windows.zip`); not for git | No |
| `quota_ledger.json` | Local daily unit estimate + write audit | No |
| `sort_queue.json` | Unfinished sort jobs | No |
| `list_mode/` | List Mode files + `snapshots/` for Undo | No (runtime data) |
| `exports/` | JSON snapshots | No |
| `gui_crash.log` | Fatal GUI errors (especially under `pythonw`) | No |

---

## Updating

**Source:** pull or copy new files, keep your existing `.env` and `token.json`, run `Run_YTPM.vbs` (deps re-check automatically).

**Packaged:** send a new `release\YTPM-*-windows.zip` (`Build_YTPM.bat --zip`). Users can copy their old `.env` and `token.json` into the new folder.

---

## Setup troubleshooting

| Problem | What to try |
| --- | --- |
| Venv python not found | Set `YTPM_VENV` in `.env` to a folder that contains `Scripts\python.exe` |
| Dependency install failed | From the project folder run `"%YTPM_VENV%\Scripts\python.exe" ensure_deps.py` (or the path shown in the error) and read the console |
| Client ID / Secret must be set | `.env` missing, wrong folder, or empty values; restart after editing |
| Access blocked / app not verified | Add your Google account under OAuth consent → Test users |
| Wrong channel | Reconnect with the account that owns the playlists |
| SSL / token refresh errors | Ensure Windows CA store / truststore is available (YTPM injects OS certs on Windows) |
| Packaged exe will not start | Keep `YTPM.exe` in the same folder as `_internal`. Unzip the whole zip, not the exe alone. |

More OAuth detail: [oauth-setup.md](oauth-setup.md).

---

## Next steps

- [Application User Guide](user-guide.md) — playlists, sort, list mode, shortcuts, quota
- [gui-buttons.md](gui-buttons.md) — every button and API cost
- [cli.md](cli.md) — command-line reference
- [docs.html](../docs.html) — in-app Help page
- [distribute.md](distribute.md) — zip `YTPM.exe` for other PCs
