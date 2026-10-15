"""Supported-company boundary (Build Plan section 5.4, Developer Review 3.6).

Returns one of SUPPORTED / SUPPORTED_WITH_LIMITATIONS / INSUFFICIENT_DATA /
UNSUPPORTED_ENTITY_TYPE — the system should never silently attempt a screen
on a company type it wasn't built for.
"""
from __future__ import annotations

from pathlib import Path

import yaml
from sqlalchemy import select
from sqlalchemy.orm import Session

from crest_forensic.db.models import LineItem

SUPPORTED = "SUPPORTED"
SUPPORTED_WITH_LIMITATIONS = "SUPPORTED_WITH_LIMITATIONS"
INSUFFICIENT_DATA = "INSUFFICIENT_DATA"
UNSUPPORTED_ENTITY_TYPE = "UNSUPPORTED_ENTITY_TYPE"

_DEFAULT_EXCLUSIONS_PATH = (
    Path(__file__).resolve().parent.parent / "config" / "sector_exclusions.yaml"
)

# Standard fields Job 1's checks (J1-01 through J1-09) need at minimum.
_REQUIRED_FIELDS_FOR_FULL_SUPPORT = {
    "revenue_from_operations",
    "profit_after_tax",
    "cash_flow_from_operations",
    "trade_receivables",
    "total_assets",
}

_MIN_ANNUAL_YEARS = 3


def load_excluded_sector_keywords(path: str | Path = _DEFAULT_EXCLUSIONS_PATH) -> list[str]:
    with open(path, "r", encoding="utf-8") as fh:
        raw = yaml.safe_load(fh)
    return [kw.lower() for kw in raw.get("excluded_sector_keywords", [])]


def is_excluded_sector(sector: str | None, excluded_keywords: list[str]) -> bool:
    if not sector:
        return False
    sector_lower = sector.lower()
    return any(keyword in sector_lower for keyword in excluded_keywords)


def compute_supported_status(
    session: Session,
    company_id: int,
    sector: str | None,
    excluded_keywords: list[str] | None = None,
) -> str:
    keywords = excluded_keywords if excluded_keywords is not None else load_excluded_sector_keywords()

    if is_excluded_sector(sector, keywords):
        return UNSUPPORTED_ENTITY_TYPE

    rows = session.execute(
        select(LineItem.standard_field, LineItem.financial_year, LineItem.normalized_value)
        .where(LineItem.company_id == company_id)
        .where(LineItem.period_type == "annual")
    ).all()

    years_with_data = {r.financial_year for r in rows if r.normalized_value is not None}
    fields_with_data = {r.standard_field for r in rows if r.normalized_value is not None}

    if len(years_with_data) < _MIN_ANNUAL_YEARS:
        return INSUFFICIENT_DATA

    if not _REQUIRED_FIELDS_FOR_FULL_SUPPORT.issubset(fields_with_data):
        return SUPPORTED_WITH_LIMITATIONS

    return SUPPORTED
