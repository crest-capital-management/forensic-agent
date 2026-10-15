"""Small database administration helpers for a hosted PostgreSQL (Supabase and similar): a connection check and a security hardening step."""
from __future__ import annotations

from sqlalchemy import inspect, text
from sqlalchemy.engine import Engine

from crest_forensic.db.models import Base

PUBLIC_ROLES = ("anon", "authenticated")      # the roles Supabase's public web API uses


def db_check(engine: Engine) -> dict:
    """Connect and report what is there. Never returns the password."""
    with engine.connect() as conn:
        if engine.dialect.name == "sqlite":
            version = "SQLite " + conn.execute(text("select sqlite_version()")).scalar()
        else:
            version = conn.execute(text("select version()")).scalar()
        names = set(inspect(conn).get_table_names())
        stamp = conn.execute(text("select version_num from alembic_version")).scalar() if "alembic_version" in names else None
    expected = {t.name for t in Base.metadata.sorted_tables}
    return {"dialect": engine.dialect.name, "server": version, "tables_expected": len(expected), "tables_present": len(expected & names),
            "missing": sorted(expected - names), "alembic_version": stamp}


def harden(engine: Engine) -> list[str]:
    """PostgreSQL only. Turn on row-level security for every table and take the public web API roles' access away, so the data can be reached
    ONLY through this app's own connection. (Supabase exposes tables in the public schema through a web API by default.) Safe to run again."""
    if engine.dialect.name != "postgresql":
        return ["not a PostgreSQL database: nothing to do"]
    done = []
    with engine.begin() as conn:
        tables = [t.name for t in Base.metadata.sorted_tables]
        if "alembic_version" in set(inspect(conn).get_table_names()):
            tables.append("alembic_version")
        for t in tables:
            conn.execute(text(f'ALTER TABLE public."{t}" ENABLE ROW LEVEL SECURITY'))
        done.append(f"row-level security turned on for {len(tables)} tables")
        roles = [r for (r,) in conn.execute(text("select rolname from pg_roles where rolname = any(:r)"), {"r": list(PUBLIC_ROLES)})]
        for r in roles:
            conn.execute(text(f"REVOKE ALL ON ALL TABLES IN SCHEMA public FROM {r}"))
            conn.execute(text(f"REVOKE ALL ON ALL SEQUENCES IN SCHEMA public FROM {r}"))
            conn.execute(text(f"ALTER DEFAULT PRIVILEGES IN SCHEMA public REVOKE ALL ON TABLES FROM {r}"))
            conn.execute(text(f"ALTER DEFAULT PRIVILEGES IN SCHEMA public REVOKE ALL ON SEQUENCES FROM {r}"))
        done.append(("public web API roles locked out: " + ", ".join(roles)) if roles else "no public web API roles found (a plain PostgreSQL): nothing more to lock")
    return done
