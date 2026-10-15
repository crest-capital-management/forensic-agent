"""Copy the whole database from one URL to another (SQLite file -> PostgreSQL server), safely.

Steps (all in one run, nothing is changed in the SOURCE):
  1. PREFLIGHT: read every row of the source and check it against the column definitions of the new database. SQLite lets a text be
     longer than its column, a number sit in a text column and so on; PostgreSQL refuses. Every problem is listed and nothing is copied.
  2. The target must have no data (the tables are created if they do not exist yet).
  3. COPY in dependency order (parents before children), in batches. Timestamps that SQLite stored without a zone are UTC in this app, so
     they are written as UTC.
  4. On PostgreSQL the id counters are moved past the highest copied id, so new rows never reuse an id.
  5. VERIFY: the row count of every table must match.
Use --check-only to run step 1 and the counts without copying.
"""
from __future__ import annotations

import datetime as dt
from dataclasses import dataclass, field

from sqlalchemy import Boolean, DateTime, Float, Integer, JSON, String, Text, create_engine, func, select, text
from sqlalchemy.engine import Engine

from crest_forensic.db.models import Base
from crest_forensic.db.url import normalize_url

BATCH = 500
MAX_PROBLEMS = 50


@dataclass
class CopyReport:
    counts: dict[str, int] = field(default_factory=dict)
    problems: list[str] = field(default_factory=list)
    copied: bool = False
    verified: bool = False

    def ok(self) -> bool:
        return not self.problems


def _engine(url: str) -> Engine:
    url = normalize_url(url)
    return create_engine(url, connect_args={"check_same_thread": False} if url.startswith("sqlite") else {})


def check_value(table: str, column, value) -> str | None:
    """A message if `value` could not be stored in this column of the new database, else None."""
    if value is None:
        return None if column.nullable or column.primary_key or column.default is not None or column.server_default is not None else \
            f"{table}.{column.name}: empty value in a required column"
    t = column.type
    if isinstance(t, String) and not isinstance(t, Text) and t.length is not None and isinstance(value, str) and len(value) > t.length:
        return f"{table}.{column.name}: text of {len(value)} characters does not fit {t.length}"
    if isinstance(t, (String, Text)) and not isinstance(value, str):
        return f"{table}.{column.name}: expected text, found {type(value).__name__}"
    if isinstance(t, Integer) and not isinstance(value, int):
        return f"{table}.{column.name}: expected a whole number, found {type(value).__name__}"
    if isinstance(t, Float) and not isinstance(value, (int, float)):
        return f"{table}.{column.name}: expected a number, found {type(value).__name__}"
    if isinstance(t, Boolean) and not isinstance(value, bool):
        return f"{table}.{column.name}: expected true/false, found {type(value).__name__}"
    if isinstance(t, DateTime) and not isinstance(value, dt.datetime):
        return f"{table}.{column.name}: expected a date and time, found {type(value).__name__}"
    if isinstance(value, str) and "\x00" in value:
        return f"{table}.{column.name}: text contains a NUL character"
    return None


def as_utc(value):
    """SQLite returns the app's UTC timestamps without a zone; PostgreSQL would read them as local time. Mark them UTC."""
    if isinstance(value, dt.datetime) and value.tzinfo is None:
        return value.replace(tzinfo=dt.timezone.utc)
    return value


def _orphans(conn, report: CopyReport) -> None:
    """SQLite does not enforce foreign keys; PostgreSQL does. A row that points at a parent that no longer exists would stop the copy."""
    for table in Base.metadata.sorted_tables:
        for fk in table.foreign_keys:
            child, parent = fk.parent, fk.column
            n = conn.execute(select(func.count()).select_from(table).where(
                child.is_not(None), child.not_in(select(parent)))).scalar()
            if n and len(report.problems) < MAX_PROBLEMS:
                report.problems.append(f"{table.name}.{child.name}: {n} row(s) point at a {parent.table.name} row that does not exist")


def preflight(source: Engine, report: CopyReport) -> None:
    with source.connect() as conn:
        _orphans(conn, report)
        for table in Base.metadata.sorted_tables:
            n = 0
            for row in conn.execute(select(table)).mappings():
                n += 1
                for col in table.columns:
                    msg = check_value(table.name, col, row[col.name])
                    if msg and len(report.problems) < MAX_PROBLEMS:
                        pk = {c.name: row[c.name] for c in table.primary_key.columns}
                        report.problems.append(f"{msg} (row {pk})")
            report.counts[table.name] = n


def _reset_sequences(conn) -> None:
    for table in Base.metadata.sorted_tables:
        pk = list(table.primary_key.columns)
        if len(pk) == 1 and isinstance(pk[0].type, Integer):
            c = pk[0].name
            conn.execute(text(
                f"SELECT setval(pg_get_serial_sequence('{table.name}', '{c}'), COALESCE((SELECT MAX({c}) FROM {table.name}), 1), "
                f"(SELECT MAX({c}) FROM {table.name}) IS NOT NULL)"))


def copy_database(source_url: str, target_url: str, check_only: bool = False) -> CopyReport:
    source, target = _engine(source_url), _engine(target_url)
    report = CopyReport()
    preflight(source, report)
    if report.problems or check_only:
        return report
    Base.metadata.create_all(target)
    with target.connect() as conn:
        for table in Base.metadata.sorted_tables:
            if conn.execute(select(func.count()).select_from(table)).scalar():
                report.problems.append(f"the target already holds rows in {table.name}; copy into an empty database only")
    if report.problems:
        return report
    with source.connect() as src, target.begin() as dst:
        for table in Base.metadata.sorted_tables:
            rows = []
            for row in src.execute(select(table)).mappings():
                rows.append({c.name: as_utc(row[c.name]) for c in table.columns})
                if len(rows) >= BATCH:
                    dst.execute(table.insert(), rows)
                    rows = []
            if rows:
                dst.execute(table.insert(), rows)
        if target.dialect.name == "postgresql":
            _reset_sequences(dst)
    report.copied = True
    with target.connect() as conn:
        for table in Base.metadata.sorted_tables:
            got = conn.execute(select(func.count()).select_from(table)).scalar()
            if got != report.counts[table.name]:
                report.problems.append(f"{table.name}: {report.counts[table.name]} rows in the source, {got} in the target")
    report.verified = not report.problems
    return report
