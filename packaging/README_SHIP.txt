YouTube Playlist Manager (YTPM)
Isha Analytiks LLC

INSTALL (Windows)
=================
1. Unzip this folder anywhere (keep YTPM.exe and the _internal folder together).
2. Open .env in Notepad.
   - If Client ID / Secret are already filled in, skip to step 3.
   - Otherwise copy them from your administrator, or follow docs in Help
     (Tutorials / Help after launch) / OAuth setup from your IT contact.
   - You do not need YTPM_VENV for this packaged app.
3. Double-click YTPM.exe (no Python install required).
4. Click Connect Google Account and sign in with YOUR Google/YouTube account.
   token.json is created next to the exe after a successful login. Do not share it.

Do not move YTPM.exe out of this folder without _internal.

UPDATES
=======
Replace the whole folder with a newer zip. Keep your existing .env and token.json
if you want to skip signing in again (copy them into the new folder).

SUPPORT
=======
In the app: Tutorials / Help
Quota: YouTube Data API v3, 10,000 units/day per Google Cloud project
  (shared if your org uses one project for everyone).
