# YTPM documentation

| Guide | Audience |
| --- | --- |
| [setup-guide.md](setup-guide.md) | Install, `YTPM_VENV`, `.env`, first Google sign-in |
| [distribute.md](distribute.md) | Zip `YTPM.exe` for other users (`Build_YTPM.bat --zip`) |
| [user-guide.md](user-guide.md) | GUI workflows, 50/50 split, shortcuts, quota |
| [oauth-setup.md](oauth-setup.md) | Google Cloud Client ID / Secret and `token.json` |
| [gui-buttons.md](gui-buttons.md) | Button reference and API costs (source for Help tables) |
| [cli.md](cli.md) | Command-line reference (`ytpm stats`, `ytpm version`, …) |
| [docs.html](../docs.html) | In-app **Tutorials / Help** page |
| [YTPM_Tutorials_Help.pdf](YTPM_Tutorials_Help.pdf) | PDF of `docs.html` |

Button and CLI tables in `docs.html` come from markdown. After editing `gui-buttons.md` or `cli.md`:

```text
python scripts/sync_docs.py
python scripts/export_docs_pdf.py
```

Purpose, Features, Install, and Quota in `docs.html` are edited in the HTML file itself. Rebuild the PDF after those edits too so the zip (`Build_YTPM.bat --zip`) ships current Help.

End-user text inside the Windows zip: `packaging/README_SHIP.txt`.
