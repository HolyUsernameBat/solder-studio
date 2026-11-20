# Solder Studio

Local Streamlit dashboard for solder literature search, PDF audit, measurement tables, and three-lens synthesis. Model calls use the Codex CLI on a ChatGPT subscription; this project does not store an API key.

## Run on Windows

Double-click `Start_Research_Studio.bat` in this folder.

The launcher looks for `uv` on PATH, then `%USERPROFILE%\.local\bin\uv.exe`, then installs via Astral if needed. It checks that Codex reports logged in with ChatGPT, then runs Streamlit. The first run may take two to three minutes while dependencies download.

Requirements on the machine: [uv](https://docs.astral.sh/uv/) and the [Codex CLI](https://github.com/openai/codex) signed in with ChatGPT (`codex login`).

Open the app at **http://localhost:8501**.

## Vault spec

Product spec (Obsidian): `Agentic Work/Solder Studio/app/spec` in the Nucleus vault (`B:\Work\Obsidian-Notes\Nucleus`).

## Not in git

The following stay local and are not committed:

- `.env` (not used by the current build; no env file is required)
- `solder_lit.db`
- `pdfs/*.pdf`
- `.venv`

No API key belongs in this repository.