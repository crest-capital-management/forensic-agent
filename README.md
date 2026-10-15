# CREST Forensic Agent (Job 1: screening)

Screens an NSE/BSE-listed company's public filings for warning signs. It **flags and cites; a human concludes**. It never says "fraud". Every flag carries a page citation, and all output is a lead, not proof.

Development example company: **TCS** (the only company ingested).

## Setup (Windows)

```
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e ".[dev]"
copy .env.example .env      # then fill in keys; .env is gitignored, never paste keys into chat
.\.venv\Scripts\python.exe -m crest_forensic.cli init-db
```

Sign-in: set a password for a user once with `.\.venv\Scripts\python.exe -m crest_forensic.cli set-password lead1` (hidden prompt). The forensic lead then adds users on the Users page.

Keys in `.env`: `RAPIDAPI_KEY` (free plan, tiny quota: no exploratory calls), `GEMINI_API_KEY` (development text reading, free tier = 20 requests/day per model; never enable billing), `ANTHROPIC_API_KEY` (production text reading, not yet available).

Run commands with `.\.venv\Scripts\python.exe -m crest_forensic.cli <command>`. Set `PYTHONIOENCODING=utf-8` on Windows.

## Flow for a new company

1. `ingest <id>` then `ingest-yahoo <id> --ticker X.NS` (numbers)
2. `ingest-document <id> <pdf> --fy FY2026` (each annual report; put PDFs in `Documents` yourself)
3. `extract-text <id> --fy FY2026 [--extractor claude|gemini|recorded --recorded FILE]` (J1-10/11/14/15 text checks)
4. `reprocess <id>` (rebuilds everything from saved data, zero network calls)
5. `run-screen <id> --basis consolidated|standalone --from FY2025 --to FY2026 --allow-draft-config`
6. `show-flags <id>`, `show-findings <id> --fy FY2026`, `show-quality`, `check-golden`

## Data sources and precedence

`annual_report_pdf` (audited, read deterministically) > `yfinance` > `rapidapi`. A disagreement beyond 0.1% is a `SOURCE_CONFLICT`; no value is picked. RapidAPI fields that are mislabeled are left unmapped in `config/` with evidence comments.

## Text findings: which model counts

Several models may read the same pages. Only one is the **main set** per check, set by `text_source_priority` in `config/llm.yaml` (recorded reading, then Claude, then Gemini). Others show as `cross-check, not counted` in `show-findings`. Every quote from any model is checked against the PDF page in code before it is usable; a reply that is blocked, truncated or malformed is an error, never "nothing found".

## Draft status

About 37 limits in `config/check_config.yaml` are unapproved proposals (`needs_lead`); runs need `--allow-draft-config` and are stamped DRAFT. Pending with the forensic lead: limit approval, hiding not-material flags, receivables definition, source precedence, what text may be sent to a model.

## Review app (Phase 4, in progress)

Two parts: a Python API (all rules and roles live here) and a Next.js front end in `app/`.

```
.\.venv\Scripts\python.exe -m pip install -e ".[app]"
.\.venv\Scripts\python.exe -m alembic upgrade head
.\.venv\Scripts\python.exe -m crest_forensic.review.api        # terminal 1: API on :8000
cd app; npm install; npm run dev                                   # terminal 2: app on :3000 (add `-- --port 3100` if 3000 is busy)
```

Built: cases list, new case, case page (flags ranked by severity, filters, run details, data-quality notes), flag detail (observation, figures, source citation, accept/reject with a required reason, history), escalation with the adviser's approval for portfolio companies, dashboard. Also built: **Config** page (view every limit and severity rule with its source; the forensic lead edits, confirms proposals and approves; version history with before/after). Also built: **Compare runs** (pick two runs of the same company and basis: new, gone, changed and unchanged flags, which figures or records moved, what differed between the runs, and possible causes; earlier decisions are shown but never copied). Also built: **Ask the agent** (`/cases/<id>/ask`): a question box tied to a case. The agent has only read-only, case-scoped tools (`crest_forensic/agent/tools.py`); code checks every answer (cited sources must have been retrieved, banned wording is blocked, numbers not found in the data are marked, the leads-not-proof and public-data lines are added by code); leading questions such as "was this fraud?" are refused by code without calling a model; every question and answer is stored. It uses Claude when `ANTHROPIC_API_KEY` is set, else Gemini, with a daily cap on model requests (`agent.max_model_calls_per_day` in `config/llm.yaml`). The look is plain white and minimal (hairline borders, black accents, Inter for text, the "CREST" wordmark in the Maharlika font: put the font file at `app/public/fonts/Maharlika.woff2`, `.ttf` or `.otf`; until then a serif fallback is used). UI libraries: lucide-react (icons), Radix (menus, tooltips), TanStack Table v8 (the Home table), Framer Motion (transitions), Sonner (toasts). The layout: left icon rail, a Home table of companies (search, All / Portfolio / Watchlist filters, per-user watchlist, flag counts), and the agent docked on the right of every page (widen or hide it; it follows the case you are viewing). Not built: the plan's `run_check`/`run_screen`/`get_shareholding` tools, real sign-in (the "Working as" switcher uses placeholder users).

The config editor stores every change as a new database version (`crest_forensic/config_store.py`); once one exists it is the live config for `run-screen`, and the YAML file is only the starting copy. A change clears the approval; approval is refused while any limit is an unconfirmed `proposal`; only the forensic lead can edit or approve.

Rules enforced in `crest_forensic/review/service.py`: reviews are append-only; a reason is always required; only accepted flags can be escalated; analysts cannot approve escalations or edit limits.

## Tests

```
.\.venv\Scripts\python.exe -m pytest -m "not live" -q
```

## Added from the PRD overview

- **J1-16 Financial-stress score (Altman Z'', emerging-market version)**: computed in code from saved statement values. X2 uses the balance sheet's "Other equity" (reserves and surplus, which include retained earnings) as the stand-in for retained earnings, and says so on every observation. Zone limits (5.85 / 4.15) are proposals until the forensic lead confirms them. Needs the FY's annual report (total liabilities and other equity come from it).
- **J1-17 Digit pattern (Benford's Law)**: counts the leading digits of each DISTINCT amount in the statements and notes of each annual report; measured as mean absolute deviation, read against Nigrini's bands. A weak, low-confidence signal (severity at most low); skipped below 1,000 numbers. The guardrail recounts the document independently before a flag is created.
- **Multi-year matrix** (`/analysis/<company>`, also reachable from Home's row menu and a case page): the four measures (Beneish parts, Altman Z'', Benford, Sloan accruals) side by side for up to 10 years, consolidated or standalone, with fiscal-year toggles, a health summary for the chosen year, and badges Normal / Worth a look / Review first from the live limits. It reuses the check code, so cells equal what a screen produces; it is a live view that writes nothing. The combined Beneish M-score is deliberately not shown until the forensic lead approves its weights; the eight parts are.
- Both are shown with review wording ("worth a closer look", "outside the usual range"), never as a verdict. Not yet built from the PRD: the quick-action buttons, custom analyst methodology, and an AI narrative panel on the matrix; 10 years of data exist only for some standalone fields.

## Not built yet

J1-13 (no source for filing dates), J1-08 (no formula in the plan), a combined M-score (needs approved weights), Phase 4 review app, Jobs 2-4, golden datasets beyond TCS.

## Database

The tool runs on a SQLite file on one PC (the default, `DATABASE_URL=sqlite:///./crest_forensic.db`) and on **PostgreSQL** on a company server.
For the server setup, the one-time data copy (`python -m crest_forensic.cli copy-db ...`), HTTPS and backups, see [DEPLOY_POSTGRES.md](DEPLOY_POSTGRES.md).
