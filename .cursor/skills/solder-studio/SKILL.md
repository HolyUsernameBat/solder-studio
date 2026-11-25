---
name: solder-studio
description: >-
  Runs Solder Studio agent CLI against solder_lit.db and pdfs/. Covers
  question-read, queue-list, search-openalex, audit-papers, audit-unlinked-pdfs,
  and screening-draft. Use when automating metallurgy literature search, triage,
  PDF audit, or screening criteria for Solder Studio without the Streamlit UI.
---

# Solder Studio (agent CLI)

## When to use

- Operator or task mentions **Solder Studio**, `solder_cli.py`, `solder_lit.db`, or the `pdfs/` folder beside the app.
- Work needs OpenAlex search, queue listing, PDF audit, or screening criteria draft **without** the browser.
- Do **not** use this skill for measurements plots or the three synthesis lenses (browser only).

## Prerequisites

- App root: directory containing `solder_cli.py` (default) or pass `--root`.
- Same **`solder_lit.db`** and **`pdfs/`** as Streamlit.
- **Codex** signed in with ChatGPT (`codex login`). No OpenAI Platform API key. No `.env` for models.
- Run commands from app root with `uv run python solder_cli.py ...`.

## Defaults

| Omitted flag | Resolves to |
| --- | --- |
| `--project` | **SAC bismuth joints** |
| `--question` | First question on that project (bismuth SAC copper joint default text) |

JSON on stdout; errors are JSON with `"error"` and `"code"`.

## Commands

### Read active question context

```bash
uv run python solder_cli.py question-read
uv run python solder_cli.py question-read --project "SAC bismuth joints" --question "exact question text"
```

### List filtered queue

Matches **Search & triage** filters. Default: hide abstract-only.

```bash
uv run python solder_cli.py queue-list
uv run python solder_cli.py queue-list --no-hide-abstract-only --triage "Not yet triaged" --order "Must Read first" --tag "All tags"
```

`--triage`: `All` | `Must Read (Deep Dive)` | `Data Source Only` | `Low Priority` | `Not yet triaged`

`--order`: `Library order` | `Must Read first`

### OpenAlex search

```bash
uv run python solder_cli.py search-openalex "solder IMC shear aging SAC305 bismuth"
uv run python solder_cli.py search-openalex "query" --model gpt-6.2-sol
```

Blank query fails. Saves PDFs as `AuthorName_Title.pdf` under `pdfs/`. Never rename operator-uploaded PDFs.

### Audit papers with local PDFs

```bash
uv run python solder_cli.py audit-papers 42
uv run python solder_cli.py audit-papers "Exact Paper Title From Database"
```

Requires full-text coverage and `pdf_path`. Default extract model: **`gpt-6.2-sol`** (`--model` overrides).

### Audit unlinked PDFs in folder

```bash
uv run python solder_cli.py audit-unlinked-pdfs
```

Creates paper rows for every `pdfs/*.pdf` not already linked, then audits for the named question.

### Draft screening criteria

```bash
uv run python solder_cli.py screening-draft
uv run python solder_cli.py screening-draft --save
```

Prints criteria text. Database updates **only** with `--save`. Default model **`gpt-6.2-sol`**.

## Help

```bash
uv run python solder_cli.py --help
uv run python solder_cli.py queue-list --help
```

## Boundaries

- Do not commit `solder_lit.db`, `pdfs/*.pdf`, or `.env`.
- CLI does not run synthesis lenses or the measurements plotter.
- OpenAlex search uses unauthenticated HTTP only (no Unpaywall in this version).