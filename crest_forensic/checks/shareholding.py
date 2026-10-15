"""J2-01 shareholding step change: the promoter group's holding compared between consecutive quarter-ends.

Source: the shareholding table filled from the NSE list and the exchange XBRL files
(ingestion/exchange_files.py). The limit (a step above 2 percentage points) is from the Job 2 spec.
Shareholding is a company-level fact, not a statement basis, so the check reports on the consolidated run only.
Pledging and the institution split are shown as figures; they raise no flag (the pledging rule is the lead's).
"""
from __future__ import annotations

import datetime as dt

from sqlalchemy.orm import Session

from crest_forensic.checks.base import (
    STATUS_COMPLETED, STATUS_NOT_ENOUGH_DATA, CheckResult, InputStore, Observation, Skip, severity_for,
    thresholds_applied,
)
from crest_forensic.checks.filing_dates import fy_quarter_ends
from crest_forensic.db.models import Shareholding
from crest_forensic.ingestion.exchange_files import quarter_label

FORMULA_ID = "shareholding:J2-01.v1"
STATUS_NOT_APPLICABLE = "NOT_APPLICABLE"


def prior_quarter_end(end: dt.date) -> dt.date:
    return {6: dt.date(end.year, 3, 31), 9: dt.date(end.year, 6, 30),
            12: dt.date(end.year, 9, 30), 3: dt.date(end.year - 1, 12, 31)}[end.month]


def step_points(current: float, prior: float) -> float:
    """Change in percentage points, to 4 decimals (the files show two)."""
    return round(current - prior, 4)


def _row(session: Session, company_id: int, end: dt.date) -> Shareholding | None:
    return (session.query(Shareholding).filter_by(company_id=company_id, quarter=quarter_label(end))
            .order_by(Shareholding.id.desc()).first())


def run_j2_01(store: InputStore, years: list[str], cfg: dict) -> CheckResult:
    if store.basis != "consolidated":
        res = CheckResult("J2-01", cfg.get("check_version", 1), STATUS_NOT_APPLICABLE)
        res.notes.append("Shareholding is not specific to a statement basis, so this check is reported once, on the consolidated run.")
        return res
    session, company_id = store.session, store.company_id
    obs, skipped = [], []
    for fy in years:
        found = 0
        for end in fy_quarter_ends(fy):
            cur, prev = _row(session, company_id, end), _row(session, company_id, prior_quarter_end(end))
            if cur is None or prev is None or cur.promoter_pct is None or prev.promoter_pct is None:
                continue
            found += 1
            step = step_points(cur.promoter_pct, prev.promoter_pct)
            label, prev_label = quarter_label(end), quarter_label(prior_quarter_end(end))
            what = (f"The promoter group's holding was {cur.promoter_pct:.2f}% at {end.isoformat()} ({label}) against "
                    f"{prev.promoter_pct:.2f}% at the previous quarter-end ({prev_label}): a change of {step:+.2f} percentage points.")
            figures = {"period_end": end.isoformat(), "quarter": label, "prior_quarter": prev_label,
                       "promoter_pct": cur.promoter_pct, "prior_promoter_pct": prev.promoter_pct, "step_points": step,
                       "shareholding_ids": [cur.id, prev.id], "snapshot_ids": [cur.snapshot_id, prev.snapshot_id]}
            if cur.pledged_pct is not None and prev.pledged_pct is not None:
                figures.update({"pledged_pct_of_promoter": cur.pledged_pct, "prior_pledged_pct_of_promoter": prev.pledged_pct})
            obs.append(Observation(
                check_id="J2-01", fy=fy, metric_name="change in promoter holding (percentage points)", metric_value=step,
                severity=severity_for(abs(step), cfg), severity_rule_id=cfg["rule_id"], formula_id=FORMULA_ID,
                technique="Promoter group holding compared between consecutive quarter-ends",
                what_observed=what, inputs=[], thresholds_applied=thresholds_applied(cfg),
                materiality={"basis": "change in percentage points, not an amount", "label": "unassessed"},
                figures=figures,
            ))
        if not found:
            skipped.append(Skip(fy, "NOT_ENOUGH_DATA", f"no two consecutive saved shareholding quarters in {fy}"))
    return CheckResult("J2-01", cfg.get("check_version", 1), STATUS_COMPLETED if obs else STATUS_NOT_ENOUGH_DATA, obs, skipped)
