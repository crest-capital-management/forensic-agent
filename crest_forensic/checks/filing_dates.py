"""J1-13 delayed filings: when each quarterly result reached the exchange versus its due date.

Source: the NSE results files saved by ingestion/exchange_files.py (snapshots). The due-date rule
(days after the period end) is a PROPOSAL in the config until the forensic lead confirms it against
SEBI LODR. Only the exchange's own received time is used. Revised filings are ignored: lateness is
judged on the first submission.
"""
from __future__ import annotations

import datetime as dt

from sqlalchemy.orm import Session

from crest_forensic.checks.base import (
    STATUS_COMPLETED, STATUS_NEEDS_DEFINITION, STATUS_NOT_ENOUGH_DATA, CheckResult, Observation, Skip, severity_for, thresholds_applied,
)
from crest_forensic.ingestion.exchange_files import IST, NSE_RESULTS, quarter_label
from crest_forensic.db.models import Snapshot

FORMULA_ID = "filing:J1-13.v1"


def due_days(period_end: dt.date, cfg: dict) -> int:
    key = "year_end_due_days" if period_end.month == 3 else "quarterly_due_days"
    return int(cfg[key]["value"])


def days_late(period_end: dt.date, received_at: str, due: int) -> int:
    """Whole days after the due date (negative = filed early). The date is the India calendar date."""
    received = dt.datetime.fromisoformat(received_at).astimezone(IST).date()
    return (received - (period_end + dt.timedelta(days=due))).days


def fy_quarter_ends(fy: str) -> list[dt.date]:
    y = int(fy[2:])
    return [dt.date(y - 1, 6, 30), dt.date(y - 1, 9, 30), dt.date(y - 1, 12, 31), dt.date(y, 3, 31)]


def first_filings(session: Session, company_id: int, basis: str) -> dict[str, dict]:
    """Earliest saved submission per period end for this basis, with its snapshot id."""
    best: dict[str, dict] = {}
    q = session.query(Snapshot).filter_by(company_id=company_id, source_provider=NSE_RESULTS).order_by(Snapshot.snapshot_id)
    for snap in q:
        for r in snap.raw_payload.get("rows", []):
            if r["basis"] != basis or not r.get("received_at") or r.get("submission_type") == "Revised":
                continue
            cur = best.get(r["period_end"])
            if cur is None or r["received_at"] < cur["received_at"]:
                best[r["period_end"]] = {**r, "snapshot_id": snap.snapshot_id}
    return best


def run_j1_13(session: Session, company_id: int, basis: str, years: list[str], cfg: dict) -> CheckResult:
    if not all(k in cfg for k in ("quarterly_due_days", "year_end_due_days")):
        res = CheckResult("J1-13", cfg.get("check_version", 1), STATUS_NEEDS_DEFINITION)
        res.notes.append("The saved limits have no due-date rule for J1-13 yet. Add the due days on the Limits page "
                         "(proposed: 45 days for quarters, 60 for the year end) and have the forensic lead confirm them.")
        return res
    filings = first_filings(session, company_id, basis)
    obs, skipped = [], []
    for fy in years:
        found = 0
        for end in fy_quarter_ends(fy):
            f = filings.get(end.isoformat())
            if f is None:
                continue
            found += 1
            due = due_days(end, cfg)
            late = days_late(end, f["received_at"], due)
            label = quarter_label(end)
            due_date = end + dt.timedelta(days=due)
            what = (f"The {basis} results for the quarter ended {end.isoformat()} ({label}) reached the exchange on "
                    f"{f['received_at'][:10]}, {abs(late)} day(s) {'after' if late > 0 else 'before'} the proposed due date "
                    f"of {due_date.isoformat()} ({due} days after the period end).") if late != 0 else (
                    f"The {basis} results for the quarter ended {end.isoformat()} ({label}) reached the exchange on "
                    f"{f['received_at'][:10]}, on the proposed due date ({due} days after the period end).")
            obs.append(Observation(
                check_id="J1-13", fy=fy, metric_name="days after due date", metric_value=float(late),
                severity=severity_for(float(late), cfg), severity_rule_id=cfg["rule_id"], formula_id=FORMULA_ID,
                technique="Exchange received time of the results compared with the due date",
                what_observed=what, inputs=[], thresholds_applied=thresholds_applied(cfg),
                materiality={"basis": "timeliness, not an amount", "label": "unassessed"},
                figures={"period_end": end.isoformat(), "quarter": label, "received_at": f["received_at"],
                         "due_days": due, "due_date": due_date.isoformat(), "days_after_due": late,
                         "snapshot_id": f["snapshot_id"], "xbrl_url": f.get("xbrl_url"),
                         "due_rule_source": cfg[("year_end_due_days" if end.month == 3 else "quarterly_due_days")].get("source")},
            ))
        if not found:
            skipped.append(Skip(fy, "NOT_ENOUGH_DATA", f"no saved exchange filing times for {basis} results in {fy}"))
    return CheckResult("J1-13", cfg.get("check_version", 1), STATUS_COMPLETED if obs else STATUS_NOT_ENOUGH_DATA, obs, skipped)
