"""Answer-key ("golden dataset") comparison — Build Plan section 14/16 Phase 1.

Compares ingested, normalized line items against figures printed in a real,
audited annual report. Every figure is compared per source provider, so the
result says which source is right, not just whether "something" matched.

Golden file formats:
  new:  statements: {consolidated|standalone: {FYxxxx: {field: {value, ...}}}}
  old:  years: {FYxxxx: {field: {value, unit}}}      (single basis, kept for tests)
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml
from sqlalchemy import select
from sqlalchemy.orm import Session

from crest_forensic.db.models import LineItem, Snapshot

_UNIT_MULTIPLIERS = {
    "inr crore": 1e7,
    "inr lakh": 1e5,
    "inr absolute": 1.0,
    "inr": 1.0,
}

MATCH, MISMATCH, MISSING = "MATCH", "MISMATCH", "MISSING"
DEFAULT_TOLERANCE_PCT = 0.1


def load_golden(path: str | Path) -> dict[str, Any]:
    with open(path, "r", encoding="utf-8") as fh:
        return yaml.safe_load(fh)


def golden_bases(golden: dict[str, Any]) -> list[str]:
    return list(golden["statements"]) if "statements" in golden else []


def _years_for(golden: dict[str, Any], basis: str) -> dict[str, dict[str, Any]]:
    if "statements" in golden:
        return golden["statements"].get(basis, {})
    return golden.get("years", {})


def evaluate_golden(
    session: Session,
    company_id: int,
    golden: dict[str, Any],
    basis: str = "standalone",
    provider: str | None = None,
    tolerance_pct: float = DEFAULT_TOLERANCE_PCT,
) -> list[dict[str, Any]]:
    """One row per golden figure: MATCH, MISMATCH (value differs) or MISSING
    (the source has no value). `provider` limits the comparison to one source."""
    rows: list[dict[str, Any]] = []
    default_unit = golden.get("unit", "INR crore")

    for year, fields in _years_for(golden, basis).items():
        for field_name, expected in fields.items():
            unit = (expected.get("unit") or default_unit).strip().lower()
            multiplier = _UNIT_MULTIPLIERS.get(unit)
            base = {"field": field_name, "year": year, "basis": basis, "provider": provider,
                    "note": expected.get("note")}
            if multiplier is None:
                rows.append({**base, "status": MISMATCH, "expected": expected["value"], "actual": None,
                             "diff_pct": None, "note": f"Unrecognized golden unit '{unit}' — fix the golden file."})
                continue
            expected_abs = expected["value"] * multiplier

            stmt = (
                select(LineItem)
                .join(Snapshot, Snapshot.snapshot_id == LineItem.snapshot_id)
                .where(LineItem.company_id == company_id)
                .where(LineItem.standard_field == field_name)
                .where(LineItem.financial_year == year)
                .where(LineItem.basis == basis)
                .where(LineItem.period_type == "annual")
                .where(LineItem.derivation_method.is_(None))
                .where(LineItem.normalized_value.is_not(None))
                .order_by(LineItem.snapshot_id.desc())
            )
            if provider:
                stmt = stmt.where(Snapshot.source_provider == provider)
            actual_row = session.execute(stmt).scalars().first()

            if actual_row is None:
                rows.append({**base, "status": MISSING, "expected": expected_abs, "actual": None, "diff_pct": None})
                continue

            actual = actual_row.normalized_value
            diff_pct = (abs(actual - expected_abs) / abs(expected_abs) * 100) if expected_abs else (
                0.0 if actual == 0 else float("inf"))
            rows.append({**base, "status": MATCH if diff_pct <= tolerance_pct else MISMATCH,
                         "expected": expected_abs, "actual": actual, "diff_pct": round(diff_pct, 3)})
    return rows


def compare_to_golden(
    session: Session, company_id: int, golden: dict[str, Any], basis: str = "standalone",
    tolerance_pct: float = DEFAULT_TOLERANCE_PCT, provider: str | None = None,
) -> list[dict[str, Any]]:
    """Only the rows that are NOT a match (empty list = everything matched)."""
    return [r for r in evaluate_golden(session, company_id, golden, basis, provider, tolerance_pct)
            if r["status"] != MATCH]


def format_mismatch_table(mismatches: list[dict[str, Any]]) -> str:
    if not mismatches:
        return "All golden values matched within tolerance."
    lines = [f"{'field':30s} {'year':8s} {'expected':>18s} {'actual':>18s} {'diff%':>8s}  note"]
    for m in mismatches:
        lines.append(
            f"{m['field']:30s} {m['year']:8s} {str(m['expected']):>18s} "
            f"{str(m['actual']):>18s} {str(m['diff_pct']):>8s}  {m.get('note') or ''}"
        )
    return "\n".join(lines)
