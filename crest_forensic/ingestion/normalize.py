"""Turn one snapshot's raw payload into normalized LineItem rows.

Guiding rule (Build Plan section 5.4 / 6.4, Developer Review section 6):
never guess. Every place a value, unit, period or basis can't be confidently
determined, log a data_quality_event and either skip the value or store it
un-normalized rather than inventing a number.
"""
from __future__ import annotations

import re
from typing import Any

from sqlalchemy.orm import Session

from crest_forensic.db.models import LineItem, Snapshot
from crest_forensic.ingestion.extract import extract_periods, find_item_value, get_by_path
from crest_forensic.ingestion.mapping import FieldMappingConfig
from crest_forensic.ingestion.quality import (
    BASIS_UNKNOWN,
    FIELD_NOT_AVAILABLE_FROM_SOURCE,
    MISSING_FIELD,
    MISSING_YEAR,
    NEGATIVE_REVENUE,
    SEVERITY_ERROR,
    SEVERITY_INFO,
    SEVERITY_WARNING,
    UNIT_MISMATCH,
    log_quality_event,
)

_VALID_BASIS = {"standalone", "consolidated"}

# Confirmed empirically 2026-09-28 against TCS (snapshots 1-8): the "income"
# endpoint returns 5 quarterly periods; balance_sheet/cash_flow/ratios each
# return annual (March year-end) periods going back up to 20 years.
ENDPOINT_PERIOD_TYPE = {
    "income": "quarterly",
    "balance_sheet": "annual",
    "cash_flow": "annual",
    "ratios": "annual",
    # Yahoo Finance (yfinance) statements are all annual.
    "yf_income": "annual",
    "yf_balance_sheet": "annual",
    "yf_cash_flow": "annual",
}

_MONTH_TO_FY_OFFSET = {
    "january": 0, "february": 0, "march": 0,
    "april": 1, "may": 1, "june": 1, "july": 1, "august": 1,
    "september": 1, "october": 1, "november": 1, "december": 1,
}


def parse_numeric(raw: Any) -> float | None:
    if raw is None:
        return None
    if isinstance(raw, (int, float)):
        return float(raw)
    text = str(raw).strip()
    if not text:
        return None
    cleaned = re.sub(r"[^0-9.\-]", "", text.replace(",", ""))
    if cleaned in ("", "-", "."):
        return None
    try:
        return float(cleaned)
    except ValueError:
        return None


def financial_year_from_year_month(year_value: Any, month_value: Any) -> tuple[str, bool]:
    """Indian FY runs Apr Y to Mar (Y+1), labelled FY(Y+1).

    A period ending Jan/Feb/Mar of calendar year Y belongs to FY(Y) (it's the
    tail end of the FY that started the previous April). A period ending
    Apr-Dec of calendar year Y belongs to FY(Y+1) (it's the start of the FY
    that ends the following March). Confirmed against TCS: annual periods
    all end in March, e.g. year=2026/month=March => FY2026.

    Returns (label, confident). Not confident => label is the raw
    "{year}-{month}" text, never a guessed FYxxxx.
    """
    month_key = str(month_value).strip().lower()
    offset = _MONTH_TO_FY_OFFSET.get(month_key)
    try:
        year = int(str(year_value).strip())
    except (TypeError, ValueError):
        offset = None
        year = None

    if offset is None or year is None:
        return f"{year_value}-{month_value}", False
    return f"FY{year + offset}", True


def normalize_snapshot(
    session: Session,
    snapshot: Snapshot,
    mapping_config: FieldMappingConfig,
    basis: str,
    source_endpoint: str,
) -> list[LineItem]:
    """Create LineItem rows for one snapshot. Never mutates prior rows.

    `source_endpoint` is which RapidAPI endpoint this snapshot came from
    (income / balance_sheet / cash_flow / ratios) — NOT necessarily the same
    as a field's Build Plan statement_type category (see mapping.py).
    """
    effective_basis = basis
    if basis not in _VALID_BASIS:
        log_quality_event(
            session,
            snapshot_id=snapshot.snapshot_id,
            company_id=snapshot.company_id,
            field_name=None,
            issue_type=BASIS_UNKNOWN,
            severity=SEVERITY_ERROR,
            note=f"Caller passed unrecognized basis '{basis}'; storing as UNKNOWN rather than guessing.",
        )
        effective_basis = "UNKNOWN"

    period_type = ENDPOINT_PERIOD_TYPE.get(source_endpoint, "annual")
    periods = extract_periods(snapshot.raw_payload)

    created: list[LineItem] = []
    field_maps = mapping_config.for_endpoint(source_endpoint)

    for field_map in field_maps:
        if field_map.bases and effective_basis not in field_map.bases:
            continue  # this mapping is deliberately limited to other bases
        if not field_map.item_name_contains and not field_map.provider_field:
            log_quality_event(
                session,
                snapshot_id=snapshot.snapshot_id,
                company_id=snapshot.company_id,
                field_name=field_map.standard_field,
                issue_type=FIELD_NOT_AVAILABLE_FROM_SOURCE,
                severity=SEVERITY_INFO,
                note="No extraction strategy configured yet for this field — needs live discovery.",
            )
            continue

        if periods is None:
            # Fallback generic path strategy (e.g. for a future provider shape).
            if field_map.provider_field:
                val = get_by_path(snapshot.raw_payload, field_map.provider_field)
                if val is None:
                    log_quality_event(
                        session, snapshot_id=snapshot.snapshot_id, company_id=snapshot.company_id,
                        field_name=field_map.standard_field, issue_type=MISSING_FIELD,
                        severity=SEVERITY_WARNING,
                        note=f"Path '{field_map.provider_field}' not found in {source_endpoint} response.",
                    )
                    continue
                created.append(
                    _build_line_item(
                        snapshot, field_map, effective_basis, source_endpoint, period_type,
                        fy_label="UNKNOWN", raw_val=val, session=session,
                        mapping_version=mapping_config.mapping_version,
                    )
                )
            continue

        for period_entry in periods:
            fy_label, confident = financial_year_from_year_month(
                period_entry.get("year"), period_entry.get("month")
            )
            if not confident:
                log_quality_event(
                    session, snapshot_id=snapshot.snapshot_id, company_id=snapshot.company_id,
                    field_name=field_map.standard_field, issue_type=MISSING_YEAR,
                    severity=SEVERITY_WARNING,
                    note=f"Could not confidently map year={period_entry.get('year')!r} "
                         f"month={period_entry.get('month')!r} to a financial year.",
                )

            raw_val = None
            if field_map.item_name_contains:
                raw_val = find_item_value(period_entry, field_map.item_name_contains)

            if raw_val is None:
                log_quality_event(
                    session, snapshot_id=snapshot.snapshot_id, company_id=snapshot.company_id,
                    field_name=field_map.standard_field, issue_type=MISSING_FIELD,
                    severity=SEVERITY_WARNING,
                    note=(
                        f"'{field_map.item_name_contains}' not found (or not disclosed, e.g. '--') "
                        f"in {source_endpoint}/{effective_basis} for {fy_label}."
                    ),
                )
                continue

            created.append(
                _build_line_item(
                    snapshot, field_map, effective_basis, source_endpoint, period_type,
                    fy_label, raw_val, session,
                    mapping_version=mapping_config.mapping_version,
                )
            )

    return created


def _build_line_item(
    snapshot: Snapshot,
    field_map,
    effective_basis: str,
    source_endpoint: str,
    period_type: str,
    fy_label: str,
    raw_val: Any,
    session: Session,
    mapping_version: int = 1,
) -> LineItem:
    numeric = parse_numeric(raw_val)
    normalized_value = None
    unit = None

    if numeric is None:
        log_quality_event(
            session, snapshot_id=snapshot.snapshot_id, company_id=snapshot.company_id,
            field_name=field_map.standard_field, issue_type=MISSING_FIELD, severity=SEVERITY_WARNING,
            note=f"Value {raw_val!r} for {field_map.standard_field} ({fy_label}) is not numeric.",
        )
    else:
        if field_map.unit_multiplier is None:
            log_quality_event(
                session, snapshot_id=snapshot.snapshot_id, company_id=snapshot.company_id,
                field_name=field_map.standard_field, issue_type=UNIT_MISMATCH, severity=SEVERITY_WARNING,
                note="unit_multiplier not confirmed for this field yet; normalized_value left unset.",
            )
        else:
            normalized_value = numeric * field_map.unit_multiplier
            unit = "INR_absolute"

        if field_map.standard_field == "revenue_from_operations" and numeric < 0:
            log_quality_event(
                session, snapshot_id=snapshot.snapshot_id, company_id=snapshot.company_id,
                field_name=field_map.standard_field, issue_type=NEGATIVE_REVENUE, severity=SEVERITY_ERROR,
                note=f"Negative revenue reported: {numeric}",
            )

    line_item = LineItem(
        company_id=snapshot.company_id,
        snapshot_id=snapshot.snapshot_id,
        standard_field=field_map.standard_field,
        raw_value=str(raw_val),
        normalized_value=normalized_value,
        unit=unit,
        currency="INR",
        financial_year=fy_label,
        period_end_date=None,
        period_type=period_type,
        basis=effective_basis,
        semantics=field_map.semantics,
        statement_type=field_map.statement_type,
        source_field_name=field_map.item_name_contains or field_map.provider_field or "",
        source_ref=f"{source_endpoint}:{field_map.item_name_contains or field_map.provider_field}",
        mapping_version=mapping_version,
    )
    session.add(line_item)
    return line_item
