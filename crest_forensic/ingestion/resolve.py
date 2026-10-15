"""Source resolution: which value should a check use when several exist?

Implements config/source_precedence.yaml (Developer Review 3.4). Nothing here
silently picks between disagreeing sources — a disagreement beyond tolerance
returns value=None with status SOURCE_CONFLICT and every candidate preserved.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

import yaml
from sqlalchemy import select
from sqlalchemy.orm import Session

from crest_forensic.db.models import DataQualityEvent, LineItem, Snapshot
from crest_forensic.ingestion.quality import SEVERITY_WARNING, SOURCE_CONFLICT, log_quality_event

DEFAULT_POLICY_PATH = Path(__file__).resolve().parent.parent / "config" / "source_precedence.yaml"

SINGLE_SOURCE = "SINGLE_SOURCE"
AGREE = "AGREE"
CONFLICT = "SOURCE_CONFLICT"
DERIVED_ESTIMATE = "DERIVED_ESTIMATE"
NO_DATA = "NO_DATA"


@dataclass
class Resolved:
    status: str
    value: float | None = None
    provider: str | None = None
    candidates: dict[str, float] = field(default_factory=dict)
    # The exact saved rows behind `value`, so a flag can cite them.
    line_item_id: int | None = None
    snapshot_id: int | None = None


def load_policy(path: str | Path = DEFAULT_POLICY_PATH) -> dict:
    with open(path, "r", encoding="utf-8") as fh:
        return yaml.safe_load(fh)


def _load_sourced(session: Session, company_id: int, standard_field=None, fy=None, basis=None):
    """{(field, fy, basis): {provider: (value, line_item_id, snapshot_id)}}, latest snapshot per provider."""
    stmt = (
        select(LineItem, Snapshot.source_provider)
        .join(Snapshot, Snapshot.snapshot_id == LineItem.snapshot_id)
        .where(LineItem.company_id == company_id)
        .where(LineItem.period_type == "annual")
        .where(LineItem.derivation_method.is_(None))
        .where(LineItem.normalized_value.is_not(None))
        .order_by(LineItem.snapshot_id)
    )
    if standard_field:
        stmt = stmt.where(LineItem.standard_field == standard_field)
    if fy:
        stmt = stmt.where(LineItem.financial_year == fy)
    if basis:
        stmt = stmt.where(LineItem.basis == basis)

    out: dict[tuple, dict[str, tuple]] = {}
    for li, provider in session.execute(stmt).all():
        out.setdefault((li.standard_field, li.financial_year, li.basis), {})[provider] = (
            li.normalized_value, li.value_id, li.snapshot_id)
    return out


def _disagree(values: list[float], tolerance_pct: float) -> bool:
    scale = max(abs(v) for v in values)
    if scale == 0:
        return False
    return (max(values) - min(values)) / scale * 100 > tolerance_pct


def resolve_value(
    session: Session, company_id: int, standard_field: str, fy: str, basis: str, policy: dict | None = None
) -> Resolved:
    policy = policy or load_policy()
    refs = _load_sourced(session, company_id, standard_field, fy, basis).get(
        (standard_field, fy, basis), {}
    )
    candidates = {p: v[0] for p, v in refs.items()}

    if candidates:
        if len(candidates) == 1:
            provider, value = next(iter(candidates.items()))
            return Resolved(SINGLE_SOURCE, value, provider, candidates, refs[provider][1], refs[provider][2])
        if _disagree(list(candidates.values()), policy["conflict_tolerance_pct"]):
            return Resolved(CONFLICT, None, None, candidates)
        order = policy["provider_order"]
        provider = sorted(candidates, key=lambda p: order.index(p) if p in order else len(order))[0]
        return Resolved(AGREE, candidates[provider], provider, candidates, refs[provider][1], refs[provider][2])

    derived = session.execute(
        select(LineItem)
        .where(LineItem.company_id == company_id, LineItem.standard_field == standard_field)
        .where(LineItem.financial_year == fy, LineItem.basis == basis)
        .where(LineItem.derivation_method.is_not(None), LineItem.normalized_value.is_not(None))
        .order_by(LineItem.snapshot_id.desc())
    ).scalars().first()
    if derived is not None:
        return Resolved(DERIVED_ESTIMATE, derived.normalized_value, derived.derivation_method, {},
                        derived.value_id, derived.snapshot_id)

    return Resolved(NO_DATA)


def detect_source_conflicts(session: Session, company_id: int, policy: dict | None = None) -> list[dict]:
    """Log a SOURCE_CONFLICT event for every (field, year, basis) where two
    providers disagree beyond tolerance. Replaces any earlier conflict events
    for this company so repeated runs don't pile up duplicates."""
    policy = policy or load_policy()
    session.query(DataQualityEvent).filter(
        DataQualityEvent.company_id == company_id,
        DataQualityEvent.issue_type == SOURCE_CONFLICT,
    ).delete()

    conflicts = []
    for (standard_field, fy, basis), refs in _load_sourced(session, company_id).items():
        by_provider = {p: v[0] for p, v in refs.items()}
        if len(by_provider) < 2 or not _disagree(list(by_provider.values()), policy["conflict_tolerance_pct"]):
            continue
        values = ", ".join(f"{p}={v:,.0f}" for p, v in sorted(by_provider.items()))
        log_quality_event(
            session, company_id=company_id, field_name=standard_field,
            issue_type=SOURCE_CONFLICT, severity=SEVERITY_WARNING,
            note=f"{fy} ({basis}): sources disagree beyond {policy['conflict_tolerance_pct']}% — {values}. No value selected.",
        )
        conflicts.append({"field": standard_field, "fy": fy, "basis": basis, "values": by_provider})
    return conflicts
