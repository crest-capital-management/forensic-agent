from __future__ import annotations

import os

from dotenv import load_dotenv
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from crest_forensic.db.models import Base
from crest_forensic.db.url import normalize_url

load_dotenv()

DATABASE_URL = normalize_url(os.environ.get("DATABASE_URL", "sqlite:///./crest_forensic.db"))

_engine = None
_SessionLocal: sessionmaker | None = None


def get_engine():
    global _engine
    if _engine is None:
        if DATABASE_URL.startswith("sqlite"):
            _engine = create_engine(DATABASE_URL, connect_args={"check_same_thread": False})
        else:   # a server database: check a pooled connection is alive before use (servers restart, firewalls drop idle links)
            _engine = create_engine(DATABASE_URL, pool_pre_ping=True, pool_size=5, max_overflow=10)
    return _engine


def init_db() -> None:
    """Create all tables. In production, use Alembic migrations instead."""
    Base.metadata.create_all(get_engine())


def get_session() -> Session:
    global _SessionLocal
    if _SessionLocal is None:
        _SessionLocal = sessionmaker(bind=get_engine(), expire_on_commit=False)
    return _SessionLocal()
