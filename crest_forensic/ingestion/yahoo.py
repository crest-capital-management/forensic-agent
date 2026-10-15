"""Ingest Yahoo Finance (yfinance) statements as a second source.

Two things Yahoo does NOT tell us, so we never assume them:
  * currency/unit  -> checked from meta.currency; non-INR snapshots are skipped.
  * standalone vs consolidated -> inferred by matching Yahoo's revenue against
    the RapidAPI source's revenue for both bases (infer_basis). If it can't be
    decided from the data, the basis is stored as UNKNOWN.
"""
from __future__ import annotations

import uuid
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from crest_forensic.db.models import LineItem, Snapshot
from crest_forensic.ingestion.extract import extract_periods, find_item_value
from crest_forensic.ingestion.fetch_and_snapshot import save_snapshot
from crest_forensic.ingestion.mapping import FieldMappingConfig, load_field_mapping
from crest_forensic.ingestion.normalize import (
    financial_year_from_year_month,
    normalize_snapshot,
    parse_numeric,
)
from crest_forensic.ingestion.quality import (
    BASIS_UNKNOWN,
    SEVERITY_ERROR,
    UNIT_MISMATCH,
    log_quality_event,
)

YAHOO_PROVIDER = "yfinance"
RAPIDAPI_PROVIDER = "rapidapi_moneycontrol"
YAHOO_STATEMENTS = ("income", "balance_sheet", "cash_flow")
YAHOO_MAPPING_PATH = Path(__file__).resolve().parent.parent / "config" / "field_mapping_yfinance.yaml"

_BASIS_MATCH_TOLERANCE_PCT = 0.5
_MIN_OVERLAP_YEARS = 2


def load_yahoo_mapping() -> FieldMappingConfig:
    return load_field_mapping(YAHOO_MAPPING_PATH)


def _yahoo_revenue_by_fy(income_snapshot: Snapshot) -> dict[str, float]:
    out: dict[str, float] = {}
    for period in extract_periods(income_snapshot.raw_payload) or []:
        fy, confident = financial_year_from_year_month(period.get("year"), period.get("month"))
        value = parse_numeric(find_item_value(period, "Total Revenue"))
        if confident and value is not None:
            out[fy] = value
    return out


def _rapidapi_revenue_by_basis(session: Session, company_id: int) -> dict[str, dict[str, float]]:
    rows = session.execute(
        select(LineItem, Snapshot.snapshot_id)
        .join(Snapshot, Snapshot.snapshot_id == LineItem.snapshot_id)
        .where(LineItem.company_id == company_id)
        .where(LineItem.standard_field == "revenue_from_operations")
        .where(LineItem.period_type == "annual")
        .where(LineItem.derivation_method.is_(None))
        .where(LineItem.normalized_value.is_not(None))
        .where(Snapshot.source_provider == RAPIDAPI_PROVIDER)
        .order_by(Snapshot.snapshot_id)
    ).all()
    out: dict[str, dict[str, float]] = {}
    for li, _ in rows:
        out.setdefault(li.basis, {})[li.financial_year] = li.normalized_value
    return out


def infer_basis(session: Session, company_id: int, income_snapshot: Snapshot) -> tuple[str, str]:
    """Return (basis, explanation). basis is 'standalone', 'consolidated' or 'UNKNOWN'."""
    yahoo = _yahoo_revenue_by_fy(income_snapshot)
    reference = _rapidapi_revenue_by_basis(session, company_id)

    qualifying = []
    detail = []
    for basis in ("standalone", "consolidated"):
        ref = reference.get(basis, {})
        overlap = sorted(set(yahoo) & set(ref))
        matches = [
            fy for fy in overlap
            if ref[fy] and abs(yahoo[fy] - ref[fy]) / abs(ref[fy]) * 100 <= _BASIS_MATCH_TOLERANCE_PCT
        ]
        detail.append(f"{basis}: {len(matches)}/{len(overlap)} overlapping years match")
        if len(overlap) >= _MIN_OVERLAP_YEARS and len(matches) == len(overlap):
            qualifying.append(basis)

    if len(qualifying) == 1:
        return qualifying[0], "; ".join(detail)
    return "UNKNOWN", "; ".join(detail) or "no overlapping revenue to compare"


def normalize_yahoo_batch(
    session: Session,
    company_id: int,
    snapshots: list[Snapshot],
    mapping_config: FieldMappingConfig,
) -> tuple[str, list[LineItem]]:
    """Normalize one fetch batch (income + balance sheet + cash flow) with a
    single inferred basis. Returns (basis, created line items)."""
    usable = []
    for snap in snapshots:
        if "_parse_error" in snap.raw_payload:
            continue
        currency = (snap.raw_payload.get("meta") or {}).get("currency")
        if currency != "INR":
            log_quality_event(
                session, snapshot_id=snap.snapshot_id, company_id=company_id,
                issue_type=UNIT_MISMATCH, severity=SEVERITY_ERROR,
                note=f"yfinance reported currency {currency!r}, not INR — snapshot not normalized.",
            )
            continue
        usable.append(snap)

    income = next((s for s in usable if s.source_endpoint == "yfinance:income"), None)
    if income is not None:
        basis, why = infer_basis(session, company_id, income)
    else:
        basis, why = "UNKNOWN", "no usable yfinance income snapshot to infer basis from"

    if basis == "UNKNOWN":
        log_quality_event(
            session, snapshot_id=income.snapshot_id if income else None, company_id=company_id,
            issue_type=BASIS_UNKNOWN, severity=SEVERITY_ERROR,
            note=f"Could not determine whether yfinance data is standalone or consolidated ({why}).",
        )

    created: list[LineItem] = []
    for snap in usable:
        statement = snap.source_endpoint.split(":", 1)[1]
        created += normalize_snapshot(session, snap, mapping_config, basis, f"yf_{statement}")
    return basis, created


def ingest_yahoo(session: Session, connector, company, ticker: str) -> tuple[str, list[LineItem]]:
    """Fetch all three statements for `ticker`, save immutable snapshots, normalize."""
    batch = uuid.uuid4().hex[:12]
    snapshots = []
    for statement in YAHOO_STATEMENTS:
        response = connector.fetch_statement(ticker, statement)
        response.request_params = {**response.request_params, "batch": batch}
        snapshots.append(save_snapshot(session, company.company_id, response))
    session.flush()
    return normalize_yahoo_batch(session, company.company_id, snapshots, load_yahoo_mapping())
