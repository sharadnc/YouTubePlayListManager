# Distribute YTPM to multiple users (Windows)

Recommended path: **one PyInstaller folder + zip**. Users do not install Python.

---

## What you ship

| Item | Role |
| --- | --- |
| `YTPM.exe` + `_internal\` | The app (keep them in the same folder) |
| `.env` | OAuth Client ID / Secret (template or pre-filled) |
| `README.txt` | End-user install steps |
| `YTPM_Tutorials_Help.pdf` | Offline Help (also in-app **Tutorials / Help**) |

Do **not** ship `token.json` (that is each person’s Google login). The zip also omits `gui_settings.json`, quota/sort ledgers, `list_mode/`, logs, and this PC’s `.env` unless you pass `--with-env`.

---

## Builder steps (this repo)

1. Fill `.env` on the **build** PC (`YTPM_VENV`, and optionally a shared OAuth client).
2. Double-click `Build_YTPM.bat --zip` (or `Build_YTPM.bat --zip --with-env`).
3. Collect `release\YTPM-<version>-windows.zip`.

`Build_YTPM.bat --zip` runs `scripts/package_release.py` after the exe is built. Refresh Help first so the zip includes current docs:

```text
python scripts/sync_docs.py
python scripts/export_docs_pdf.py
python scripts/package_release.py
python scripts/package_release.py --with-env
```

| Flag | `.env` in the zip |
| --- | --- |
| *(default)* | Copy of `.env.example` (empty Client ID/Secret) |
| `--with-env` | Copy of **this PC’s** `.env` — use only for a private org zip |

`--with-env` is how you hand everyone the **same** Desktop OAuth client without making each user create a Google Cloud project. Do not post that zip on a public site.

---

## OAuth for many users

Quota is **per Google Cloud project** (~10,000 units/day). One project = one shared pool.

| Model | How |
| --- | --- |
| **Shared client (typical for a team)** | One Cloud project, one Desktop OAuth client. Put ID/Secret in `.env` and zip with `--with-env`. Add each Google account under OAuth consent **Test users**, or **Publish** the app if Google requires it. |
| **Per-user client** | Ship empty `.env`. Each user follows [oauth-setup.md](oauth-setup.md). Separate quota pools. |

Never email someone else’s `token.json`.

---

## What each user does

1. Unzip `YTPM-*-windows.zip` (keep `YTPM.exe` and `_internal` together).
2. Edit `.env` if Client ID/Secret are blank.
3. Double-click **`YTPM.exe`**.
4. **Connect Google Account** → sign in with *their* Google account.

First launch: Playlists and Videos each use **50%** of the main pane. Drag the split; closing the app saves it for next time.

In-app Help: **Tutorials / Help** (`docs.html` is inside the folder). Full product PDF is in the zip when present.

---

## Updates

Send a new zip. Users can copy their old `.env` and `token.json` into the new folder to skip re-consent.

---

## Related

- End-user install text inside the zip: `packaging/README_SHIP.txt`
- Source-dev launch: [setup-guide.md](setup-guide.md) (`Run_YTPM.vbs`)
- Day-to-day GUI: [user-guide.md](user-guide.md)
- OAuth click-through: [oauth-setup.md](oauth-setup.md)
