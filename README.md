# YouTube Playlist Manager (YTPM)

Desktop app and CLI to manage **your** YouTube playlists through the official YouTube Data API v3. Sparse writes: titles, duplicates, and positions are updated only when they actually change.

## Setup

→ **[`docs/setup-guide.md`](docs/setup-guide.md)** — install, `.env`, first launch  
→ **[`docs/oauth-setup.md`](docs/oauth-setup.md)** — Google Cloud Client ID / Secret (detailed)  
→ **[`docs/distribute.md`](docs/distribute.md)** — zip `YTPM.exe` for other Windows PCs (no Python)

Short version:

1. Copy `.env.example` → `.env` and set `YOUTUBE_CLIENT_ID` / `YOUTUBE_CLIENT_SECRET` from Google Cloud Console (Desktop OAuth client).
2. Set `YTPM_VENV` in `.env` to your virtualenv root (default `C:\PythonVenvs\venv`).
3. Run `Run_YTPM.vbs` (or `Run_YTPM_CLI.bat auth`) — missing packages from `requirements.txt` are installed automatically — then connect Google (`token.json` is written). Prefer the `.vbs` so no DOS window appears.

Do **not** commit `.env`, `token.json`, or OAuth client secret files. They are listed in `.gitignore`.

## Launch

| File | What it does |
| --- | --- |
| `Run_YTPM.vbs` | **Preferred GUI start** — no console / black CMD window |
| `Run_YTPM.bat` | Delegates to the `.vbs` (may flash briefly); `Run_YTPM.bat --console` for debug |
| `Run_YTPM_CLI.bat` | `python -m ytpm …`; uses `YTPM_VENV`; auto-installs missing deps |
| `Build_YTPM.bat` | Packaged `dist\YTPM\YTPM.exe`; `--zip` writes `release\YTPM-*-windows.zip`; add `--with-env` to include this PC’s OAuth `.env` |
| `ytpm_resolve_venv.bat` | Shared helper: read `YTPM_VENV` from `.env`, set `PY` / `PYW` |
| `ytpm_launch.pyw` | Silent bootstrap: ensure deps → open GUI (invoked by the `.vbs`) |

The packaged exe reads `.env` next to the exe for OAuth; it does **not** use `YTPM_VENV`.

## Docs

- **Setup guide:** [`docs/setup-guide.md`](docs/setup-guide.md)
- **Application user guide:** [`docs/user-guide.md`](docs/user-guide.md)
- **Distribute (Windows zip):** [`docs/distribute.md`](docs/distribute.md) — `Build_YTPM.bat --zip` / `--with-env`
- Product Help (GUI **Tutorials / Help**): [`docs.html`](docs.html) · PDF: [`docs/YTPM_Tutorials_Help.pdf`](docs/YTPM_Tutorials_Help.pdf)
- OAuth credentials: [`docs/oauth-setup.md`](docs/oauth-setup.md)
- GUI button costs: [`docs/gui-buttons.md`](docs/gui-buttons.md) — regenerate HTML with `python scripts/sync_docs.py`
- CLI: [`docs/cli.md`](docs/cli.md)
- Docs index: [`docs/README.md`](docs/README.md)

## Tests

```text
python -m pytest tests -q
```
