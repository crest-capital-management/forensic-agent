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

- Per-case permissions are built: the forensic lead sees every case; everyone else only the cases they were added to (case page, panel "Who can open this case"). After moving to the server, the forensic lead should open each case and add the right people.
- Who administers the server, the backup copy location, and how long data is kept.
- The free-tier API keys (Gemini, RapidAPI) are per project; keep them in `.env` on the server only.
- The SQLite file and its backups are NOT in GitHub. Keep the original until the new database has been used for a while.

## Using a hosted PostgreSQL instead of your own server (Neon, Supabase, Aiven, a cloud provider)

The app only needs the connection address, so any standard PostgreSQL works. Parts A and the server steps of this runbook are replaced by the provider's console; Parts B to D stay the same.

1. Create the database in the provider's console. **Choose the region when you create it: it cannot be changed later.** Neon has no India region (nearest is Singapore); Supabase offers Mumbai.
2. Copy the connection address into `DATABASE_URL` in `.env`. It must end in `?sslmode=require`. Prefer the DIRECT address; the pooled one also works (the app does not use server-side prepared statements).
3. Run `init-db`, `alembic stamp head`, then `copy-db` exactly as in Parts B and C.
4. Free plans pause an idle database, so the first request after a pause is slow. Use a paid always-on plan for real use. Check the provider's current limits and prices.
5. Keep the connection address secret (it contains the password) and turn on the provider's automatic backups; test one restore.
6. The app itself (API and web app) still has to run somewhere: a small rented server, or an app-hosting service. Pick one in the same region as the database to keep it fast.

## Supabase (decided 2026-10-15: PostgreSQL on Supabase, Mumbai region)

Supabase is a hosted PostgreSQL. We use ONLY its database (not its sign-in, storage or web API). Steps, in order:

1. **Create the project** at supabase.com with the company account. Choose the region **South Asia (Mumbai)**. It cannot be changed afterwards. Set a long random **database password** and save it in the company password manager.
2. **Get the connection string:** open the project, click **Connect**, and copy the **Session pooler** string (it works over the ordinary internet, IPv4). The "Direct connection" string is IPv6 only on the standard plan and fails on many networks. The string looks like
   `postgresql://postgres.<project-ref>:<password>@aws-0-ap-south-1.pooler.supabase.com:5432/postgres`.
   If the password has special characters, URL-encode them.
3. **Put it in `.env`** as `DATABASE_URL=...` (the app adds the driver and SSL settings it needs). Never commit `.env` or share this string.
4. **Check the connection:**
   ```bash
   python -m crest_forensic.cli db-check
   ```
   It must say `connected: postgresql`. If it says CANNOT CONNECT, re-copy the string (the usual mistakes are the password and using the Direct string).
5. **Create the tables and mark them current:**
   ```bash
   python -m crest_forensic.cli init-db
   ```
   ```bash
   python -m alembic stamp head
   ```
6. **Lock the data away from Supabase's public web API. Do not skip this.** Supabase makes tables in the `public` schema reachable through a web API by default. This command turns on row-level security and takes that access away, so the data is reachable only through this app:
   ```bash
   python -m crest_forensic.cli harden-postgres
   ```
   Run it again after every `alembic upgrade head`. As a second lock, in the Supabase dashboard open **Project Settings, Data API** and turn the Data API off if the option is offered.
7. **Copy the existing data** from the PC (Part C of this runbook): `copy-db --check-only` first, then `copy-db`.
8. **Backups and plan.** Check what the plan includes: free projects may pause when idle and may have no daily backups. For real use choose a paid plan with daily backups, and test one restore. Also keep a periodic `pg_dump` copy off Supabase.
9. **Where the app runs.** Supabase holds only the database. The Python API and the web app still need a host in the same region (Mumbai) so they stay fast and the data stays in India.
