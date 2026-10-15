"""Data-quality event logging.

Every place ingestion would otherwise have to guess, default, or silently
drop something, it logs one of these instead (Build Plan section 5.4:
"Mark missing data as missing. Never fill it in with a guess.").
"""
from __future__ import annotations

from sqlalchemy.orm import Session

from crest_forensic.db.models import DataQualityEvent

# Minimum required set (see Phase 1 spec).
MISSING_FIELD = "MISSING_FIELD"
FIELD_NOT_AVAILABLE_FROM_SOURCE = "FIELD_NOT_AVAILABLE_FROM_SOURCE"
UNIT_MISMATCH = "UNIT_MISMATCH"
NEGATIVE_REVENUE = "NEGATIVE_REVENUE"
BASIS_UNKNOWN = "BASIS_UNKNOWN"
PARSE_ERROR = "PARSE_ERROR"
SUSPICIOUS_VALUE = "SUSPICIOUS_VALUE"
MISSING_YEAR = "MISSING_YEAR"
ANNUAL_DATA_UNAVAILABLE = "ANNUAL_DATA_UNAVAILABLE"
SOURCE_CONFLICT = "SOURCE_CONFLICT"
DERIVED_VALUE = "DERIVED_VALUE"
DERIVATION_SKIPPED = "DERIVATION_SKIPPED"

SEVERITY_INFO = "info"
SEVERITY_WARNING = "warning"
SEVERITY_ERROR = "error"


def log_quality_event(
    session: Session,
    *,
    issue_type: str,
    severity: str,
    note: str,
    snapshot_id: int | None = None,
    company_id: int | None = None,
    field_name: str | None = None,
) -> DataQualityEvent:
    event = DataQualityEvent(
        snapshot_id=snapshot_id,
        company_id=company_id,
        field_name=field_name,
        issue_type=issue_type,
        severity=severity,
        note=note,
    )
    session.add(event)
    return event
