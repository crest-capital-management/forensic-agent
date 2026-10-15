"""J2-03 auditor-fee jumps: the statutory audit fee and the total of all auditor fees, year on year.

Source: note 17 'Auditor's remuneration' of the STANDALONE notes of each annual report, saved as snapshots by
documents/auditor_fees.py. The limit (a rise of more than 30% in a year) is from the Job 2 spec. The fees are printed in
whole INR crore, so a small fee can swing the percentage by rounding alone: the observation says so and shows the range the
rounding allows. Reported on the consolidated run only (company-level fact, not a statement basis).
A flag is a lead for a person, not a conclusion.
"""
from __future__ import annotations

from crest_forensic.checks.base import (
    STATUS_COMPLETED, STATUS_NOT_ENOUGH_DATA, CheckResult, InputStore, Observation, Skip, severity_for,
    thresholds_applied,
)
from crest_forensic.db.models import Snapshot
from crest_forensic.documents.auditor_fees import ROWS, load_auditor_fees

FORMULA_PREFIX = "fees:J2-03."
STATUS_NOT_APPLICABLE = "NOT_APPLICABLE"
METRICS = {
    "audit": ("audit_fee_cr", "change in the statutory audit fee (%)", "Statutory audit fee compared with the year before"),
    "total": (None, "change in total auditor fees (%)", "All fees paid to the auditor (audit, taxation, other services, reimbursement) compared with the year before"),
}


def amount(values: dict, key: str) -> int:
    return values["audit_fee_cr"] if key == "audit" else sum(values[k] for k in ROWS.values())


def change_pct(current: float, prior: float) -> float | None:
    return None if prior == 0 else round((current / prior - 1) * 100, 4)


def rounding_range(current: int, prior: int) -> tuple[float, float] | None:
    """The change the printed whole-crore figures could stand for if each is off by up to half a crore."""
    if prior - 0.5 <= 0:
        return None
    return round(((current - 0.5) / (prior + 0.5) - 1) * 100, 1), round(((current + 0.5) / (prior - 0.5) - 1) * 100, 1)


def run_j2_03(store: InputStore, years: list[str], cfg: dict) -> CheckResult:
    if store.basis != "consolidated":
        res = CheckResult("J2-03", cfg.get("check_version", 1), STATUS_NOT_APPLICABLE)
        res.notes.append("Auditor fees come from the standalone notes and are not specific to a statement basis, so this check is reported once, on the consolidated run.")
        return res
    session, company_id = store.session, store.company_id
    fees, _notes = load_auditor_fees(session, company_id)
    obs, skipped = [], []
    for fy in years:
        prior = f"FY{int(fy[2:]) - 1}"
        if fy not in fees or prior not in fees:
            skipped.append(Skip(fy, "NOT_ENOUGH_DATA", f"auditor fees for {fy} and {prior} are not both saved"))
            continue
        cur, old = fees[fy], fees[prior]
        for key, (_f, metric_name, technique) in METRICS.items():
            a, b = amount(cur, key), amount(old, key)
            chg = change_pct(a, b)
            if chg is None:
                continue
            lo_hi = rounding_range(a, b)
            what = (f"The {'statutory audit fee' if key == 'audit' else 'total of all fees paid to the auditor'} was INR {a} crore in {fy} against INR {b} crore in {prior}, "
                    f"a change of {chg:+.1f}%."
                    + (f" The fees are printed in whole crores, so the true change could lie between {lo_hi[0]:+.1f}% and {lo_hi[1]:+.1f}%." if lo_hi else ""))
            obs.append(Observation(
                check_id="J2-03", fy=fy, metric_name=metric_name, metric_value=chg, severity=severity_for(chg, cfg),
                severity_rule_id=cfg["rule_id"], formula_id=f"{FORMULA_PREFIX}{key}.v1", technique=technique, what_observed=what,
                inputs=[], thresholds_applied=thresholds_applied(cfg),
                materiality={"basis": "change in a fee, not an amount of the accounts", "label": "unassessed"},
                figures={"metric": key, "amount_cr": a, "prior_amount_cr": b, "change_pct": chg, "rounding_range_pct": list(lo_hi) if lo_hi else None,
                         "prior_fy": prior, "fee_lines": {k: cur[k] for k in ROWS.values()}, "prior_fee_lines": {k: old[k] for k in ROWS.values()},
                         "snapshot_ids": [cur["snapshot_id"], old["snapshot_id"]], "pages": [cur["page"], old["page"]],
                         "report_fys": [cur["report_fy"], old["report_fy"]], "unit": "INR crore, standalone notes"},
            ))
    return CheckResult("J2-03", cfg.get("check_version", 1), STATUS_COMPLETED if obs else STATUS_NOT_ENOUGH_DATA, obs, skipped)


def reread_amounts(session, figures: dict, fy: str, prior: str) -> tuple[dict, dict] | None:
    """For the guardrail: the two fee-line dicts as saved in the cited snapshots."""
    out = []
    for snap_id, year in zip(figures["snapshot_ids"], (fy, prior)):
        snap = session.get(Snapshot, snap_id)
        vals = (snap.raw_payload.get("years") or {}).get(year) if snap is not None else None
        if vals is None:
            return None
        out.append(vals)
    return out[0], out[1]
