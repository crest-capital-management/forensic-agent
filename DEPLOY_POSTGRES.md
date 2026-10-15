# Running the CREST forensic agent on a company server with PostgreSQL

For the IT person who sets up the server. Commands are for Ubuntu Linux (a Windows server works the same way, only the install and the service manager differ).
Every `<placeholder>` is something to replace. Do the steps in order and do not skip the checks.

## The shape of the setup

```
browser --HTTPS--> reverse proxy (443) --> web app (Next.js, port 3000) --> review API (Python, 127.0.0.1:8000) --> PostgreSQL (5432)
```

- Only the reverse proxy is reachable from the office network. The web app, the API and the database are not.
- The API listens on 127.0.0.1 only, on purpose. Do not change that.
- Sign-in is the tool's own (users, passwords, roles) and lives in the database. Nothing else to set up for it.

## Part A. The database server

1. **Install PostgreSQL 16 or newer** and start it.
   ```bash
   sudo apt install postgresql
   ```
2. **Create the database and a user that owns only it.** Use a long random password.
   ```bash
   sudo -u postgres psql
   ```
   ```sql
   CREATE ROLE crest_app LOGIN PASSWORD '<long-random-password>';
   CREATE DATABASE crest OWNER crest_app ENCODING 'UTF8';
   ```
3. **Network.** If the API runs on the same server, leave PostgreSQL listening on localhost only (the default) and stop here.
   If the API runs on another machine, allow only that machine in `pg_hba.conf` (for example `hostssl crest crest_app <api-server-ip>/32 scram-sha-256`),
   open port 5432 for that address only, and turn SSL on. Never open 5432 to the whole network.
4. **Backups.** A nightly dump, kept for at least 30 days, copied off the server. Test a restore once.
   ```bash
   pg_dump -Fc -U crest_app -h localhost crest > /backups/crest-$(date +%F).dump
   ```

## Part B. The application server

5. **Get the code** from GitHub and install it (Python 3.11 or newer, Node.js 20 or newer).
   ```bash
   git clone <repo-url> crest && cd crest
   ```
   ```bash
   python3 -m venv .venv && . .venv/bin/activate
   ```
   ```bash
   pip install -e ".[app,postgres]"
   ```
   ```bash
   cd app && npm ci && npm run build && cd ..
   ```
6. **Create the `.env` file** (copy `.env.example`; it must never be committed or shared). Set at least:
   ```
   DATABASE_URL=postgresql://crest_app:<password>@<db-host>:5432/crest
   CREST_COOKIE_SECURE=1
   GEMINI_API_KEY=<free-tier key>
   RAPIDAPI_KEY=<key>
   ```
   Restrict it: `chmod 600 .env`. If the password has special characters, URL-encode them.
7. **Create the empty tables, then mark them as up to date.** (Do NOT replay the old migrations on PostgreSQL: some were written for SQLite.)
   ```bash
   python -m crest_forensic.cli init-db
   ```
   ```bash
   alembic stamp head
   ```
   Later changes to the tables arrive as new Alembic migrations: `alembic upgrade head`.

## Part C. Moving the existing data from the PC

The copy tool checks everything first and changes nothing in the source. It refuses to copy into a database that already has data.

8. Run the check. It needs the SQLite file (`crest_forensic.db`) and the `DATABASE_URL` of the new database. Run it on the server after copying the file there securely, or on the PC if the PC can reach the database.
   ```bash
   python -m crest_forensic.cli copy-db --from sqlite:///./crest_forensic.db --to "postgresql://crest_app:<password>@<db-host>:5432/crest" --check-only
   ```
   It must end with `Check passed: every row fits the new database.` (It did on the pilot data, 3,030 rows in 32 tables.) If it lists problems, send them to the developer; do not force it.
9. Do the copy (same command without `--check-only`). It ends with `Copied and verified` and the row count of every table.
   Moving the data after the tables exist is intentional: it keeps the id counters correct, so ids are never reused.
10. **Check the app against the new database** before switching anyone over: start it (below), sign in, open a case, open the matrix and run the tests that need no keys:
    ```bash
    python -m pytest -m "not live" -q
    ```
    (The tests use their own temporary databases; they do not touch the server.)

## Part D. Running it for real

11. **Services.** Run the API and the web app as services that restart on failure (systemd). Example for the API (`/etc/systemd/system/crest-api.service`):
    ```
    [Unit]
    Description=CREST review API
    After=network.target postgresql.service
    [Service]
    WorkingDirectory=/opt/crest
    EnvironmentFile=/opt/crest/.env
    ExecStart=/opt/crest/.venv/bin/python -m crest_forensic.review.api
    Restart=on-failure
    User=crest
    [Install]
    WantedBy=multi-user.target
    ```
    And the web app: `WorkingDirectory=/opt/crest/app`, `ExecStart=/usr/bin/npm run start -- --port 3000`.
12. **HTTPS reverse proxy** (Caddy or nginx) with a certificate for the company hostname, forwarding to `127.0.0.1:3000`. Send the HTTP headers for the original address
    (`X-Forwarded-Proto`, `X-Forwarded-For`) so the sign-in log shows real addresses. With `CREST_COOKIE_SECURE=1` the sign-in cookie is only sent over HTTPS.
13. **Users.** Every user needs a password before they can sign in. The forensic lead can add users and reset passwords on the Users page, or from the command line:
    ```bash
    python -m crest_forensic.cli set-password <username>
    ```
14. **Updating later:** `git pull`, `pip install -e ".[app,postgres]"`, `alembic upgrade head`, rebuild the web app (`npm run build`), restart both services. Take a backup first.

## Things still to decide or do (not part of this runbook)

- Per-case permissions: today every signed-in user can READ every case. Writing is already limited by role.
- Who administers the server, the backup copy location, and how long data is kept.
- The free-tier API keys (Gemini, RapidAPI) are per project; keep them in `.env` on the server only.
- The SQLite file and its backups are NOT in GitHub. Keep the original until the new database has been used for a while.
