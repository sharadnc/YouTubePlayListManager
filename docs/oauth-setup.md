# Get YOUTUBE_CLIENT_ID and YOUTUBE_CLIENT_SECRET (OAuth setup)

YTPM talks to **your** channel through the official **YouTube Data API v3**. Google does **not** hand out a Client ID on youtube.com itself. You create an OAuth **Desktop** app in [Google Cloud Console](https://console.cloud.google.com/), put the ID and secret in `.env`, then let YTPM create `token.json` after you sign in once in the browser.

| File | What goes there | Who creates it |
| --- | --- | --- |
| `.env` | `YOUTUBE_CLIENT_ID`, `YOUTUBE_CLIENT_SECRET` | You (copy from Cloud Console) |
| `token.json` | Refresh/access tokens for *your* Google account | YTPM after **Connect Google Account** / `ytpm auth` |

Never put the Client Secret into `token.json` by hand. Never commit `.env` or `token.json`.

---

## 1. Create a Google Cloud project

1. Open [Google Cloud Console](https://console.cloud.google.com/).
2. Sign in with the Google account that owns (or will manage) the YouTube channel.
3. Top bar → **Select a project** → **New Project**.
4. Name it (for example `YTPM`) → **Create**.
5. Make sure that project is selected in the top bar.

---

## 2. Enable YouTube Data API v3

1. Open [APIs & Services → Library](https://console.cloud.google.com/apis/library).
2. Search for **YouTube Data API v3**.
3. Open it → **Enable**.

Direct overview (replace `YOUR_PROJECT_ID`):

`https://console.developers.google.com/apis/api/youtube.googleapis.com/overview?project=YOUR_PROJECT_ID`

If YTPM later fails with `403` / `accessNotConfigured`, this step was skipped.

---

## 3. Configure the OAuth consent screen

1. Open [APIs & Services → OAuth consent screen](https://console.cloud.google.com/apis/credentials/consent).
2. Choose **External** (unless you only use Google Workspace Internal) → **Create**.
3. Fill required fields:
   - **App name**: e.g. `YouTube Playlist Manager`
   - **User support email**: your address
   - **Developer contact**: your address
4. **Save and Continue**.
5. **Scopes** → **Add or Remove Scopes** → add:
   - `https://www.googleapis.com/auth/youtube.force-ssl`  
     (same scope YTPM uses; may appear as “Manage your YouTube account”)
6. **Save and Continue**.
7. **Test users** (while the app is in **Testing**):
   - **Add users** → add the Google account you will use in YTPM.
   - Without this, Google can block sign-in with “access blocked” / “app has not completed verification”.
8. **Save and Continue** → back to Dashboard.

You can leave the app in **Testing**. For personal use that is enough. Publishing for production verification is only needed if many outside users must sign in.

---

## 4. Create OAuth Client ID + Client Secret

1. Open [APIs & Services → Credentials](https://console.cloud.google.com/apis/credentials).
2. **+ Create Credentials** → **OAuth client ID**.
3. **Application type**: **Desktop app** (not Web, not Android).
4. Name it (e.g. `YTPM Desktop`) → **Create**.
5. Copy:
   - **Client ID** → this becomes `YOUTUBE_CLIENT_ID`
   - **Client secret** → this becomes `YOUTUBE_CLIENT_SECRET`

You can reopen them later: Credentials → your OAuth client → copy ID/secret (or download JSON; YTPM only needs the two values in `.env`).

---

## 5. Save credentials in `.env` (not in `token.json`)

In the YTPM project folder:

1. If `.env` does not exist, copy `.env.example` → `.env`.
2. Edit `.env`:

```env
YOUTUBE_CLIENT_ID=1234567890-xxxxxxxx.apps.googleusercontent.com
YOUTUBE_CLIENT_SECRET=GOCSPX-xxxxxxxxxxxxxxxx
YOUTUBE_TOKEN_PATH=./token.json
YTPM_LIST_DIR=./list_mode
YTPM_EXPORT_DIR=./exports
YTPM_VENV=C:\PythonVenvs\venv
```

3. Save the file. Do **not** paste these into `token.json`.

`YTPM_VENV` is the Python virtualenv **root** used by `Run_YTPM.bat` / `Run_YTPM_CLI.bat` / `Build_YTPM.bat`. Packaged `YTPM.exe` ignores it. Full install notes: [setup-guide.md](setup-guide.md).

For a packaged `YTPM.exe`, put `.env` **next to the exe** (Client ID/Secret still required).

**Several users on one team:** you can share **one** Desktop client (same Client ID/Secret in every `.env`). Add each Google account as an OAuth **Test user**, or publish the consent screen. Quota is **one 10,000-unit pool per Cloud project**. Each person still signs in once and keeps their own `token.json`. Shipping zip: [distribute.md](distribute.md).

---

## 6. Sign in once — YTPM writes `token.json`

### GUI

1. Run **`Run_YTPM.vbs`** (no DOS window). Or `Run_YTPM.bat` (starts the same `.vbs`). Packaged: double-click **`YTPM.exe`**.
2. Click **Connect Google Account**.
3. Browser opens → pick the Google account that was added as a **Test user**.
4. Approve YouTube access (you may see “Google hasn’t verified this app” → **Advanced** → **Go to … (unsafe)** while the consent screen is in Testing).
5. When the browser says success, return to YTPM.

### CLI

```text
Run_YTPM_CLI.bat auth
```

or:

```text
python -m ytpm auth
```

Use `auth --force` / **Reconnect / Switch Account** to clear the old token and consent again.

### What `token.json` is

After a successful login, YTPM creates `./token.json` (or whatever `YOUTUBE_TOKEN_PATH` points to — next to `YTPM.exe` when packaged). That file holds OAuth **tokens** (including a refresh token) so you are not asked to sign in every launch. YTPM refreshes expired access tokens automatically.

Treat `token.json` like a password:

- Do not email it or commit it to git (already in `.gitignore`).
- To revoke access: delete `token.json` and/or revoke the app under [Google Account → Security → Third-party access](https://myaccount.google.com/permissions).

---

## 7. Quick checklist

| Step | Done when… |
| --- | --- |
| Cloud project created | Project selected in the Console top bar |
| YouTube Data API v3 enabled | API shows **Enabled** for the project |
| Consent screen + test user | Your Google account is listed under Test users |
| Desktop OAuth client | You have Client ID + Client secret |
| `.env` filled | `YOUTUBE_CLIENT_ID`, `YOUTUBE_CLIENT_SECRET`, and (for source) `YTPM_VENV` set |
| First Connect / `auth` | `token.json` exists; GUI shows Connected |

---

## Common problems

| Symptom | Fix |
| --- | --- |
| `YOUTUBE_CLIENT_ID and YOUTUBE_CLIENT_SECRET must be set` | `.env` missing or empty; restart the app after editing |
| Venv python not found | Set `YTPM_VENV` in `.env` to your venv root (see [setup-guide.md](setup-guide.md)) |
| `accessNotConfigured` / API 403 | Enable YouTube Data API v3 on **this** project |
| “Access blocked” / app not verified | Add your account under OAuth consent → **Test users**, or use Advanced → continue while Testing |
| Wrong channel’s playlists | Reconnect with the Google account that owns the channel (`Reconnect / Switch Account` or `ytpm auth --force`) |
| Token refresh SSL errors | Use a current Windows CA store / truststore setup (YTPM injects OS certs on Windows) |

---

## Related docs

- Setup (install + first run): [`setup-guide.md`](setup-guide.md)
- Multi-user zip: [`distribute.md`](distribute.md)
- Application user guide: [`user-guide.md`](user-guide.md)
- Product guide: [`docs.html`](../docs.html)
- Button costs: [`gui-buttons.md`](gui-buttons.md)
- CLI: [`cli.md`](cli.md)
- Env template: [`.env.example`](../.env.example)
