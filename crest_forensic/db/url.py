"""Database URL handling shared by the app and Alembic."""
from __future__ import annotations


def normalize_url(url: str) -> str:
    """Accept the usual PostgreSQL spellings (postgres://, postgresql://) and use the psycopg 3 driver for them."""
    if url.startswith("postgres://"):
        url = "postgresql://" + url[len("postgres://"):]
    if url.startswith("postgresql://"):
        url = "postgresql+psycopg://" + url[len("postgresql://"):]
    return url
