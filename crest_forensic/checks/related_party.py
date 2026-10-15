"""J2-06 related-party concentration: how much of revenue and of expenses is with related parties.

Source: the 'Transactions with related parties' table of each annual report's notes (documents/related_party.py), read for the
basis being screened. Two measures per year:
  - revenue from related parties as a percent of revenue from operations;
  - purchases from related parties as a percent of total expenses.
The Job 2 spec names related-party concentration but gives no number, so the limits (medium above 25%, high above 50%) are PROPOSALS
for the lead. A high share is not wrong in itself: a company in a group often sells to and buys from its group. A flag is a lead
for a person, not a conclusion.
"""
from __future__ import annotations

from crest_forensic.checks.base import (
    STATUS_COMPLETED, STATUS_NOT_ENOUGH_DATA, CheckResult, InputStore, Missing, Observation, Skip, crore, severity_for, thresholds_applied,
)
from crest_forensic.documents.related_party import load_related_party

FORMULA_PREFIX = "relparty:J2-06."
CRORE = 1e7
MEASURES = {
    "revenue": ("revenue_cr", "revenue_from_operations", "revenue from related parties as a share of revenue from operations",
                "Revenue earned from related parties compared with revenue from operations"),
    "purchases": ("purchases_cr", "total_expenses", "purchases from related parties as a share of total expenses",
                  "Purchases of goods and services from related parties compared with total expenses"),
}


def share_pct(amount_cr: float, denominator_rupees: float) -> float | None:
    return None if denominator_rupees <= 0 else round(amount_cr * CRORE / denominator_rupees * 100, 6)


def run_j2_06(store: InputStore, years: list[str], cfg: dict) -> CheckResult:
    data, notes = load_related_party(store.session, store.company_id, store.basis)
    obs, skipped = [], []
    for fy in years:
        got = data.get(fy)
        if got is None:
            skipped.append(Skip(fy, "NOT_ENOUGH_DATA", f"no saved related-party totals for {fy} ({store.basis})"))
            continue
        for key, (field, denom_field, metric_name, technique) in MEASURES.items():
            den = store.get("denominator", denom_field, fy)
            if isinstance(den, Missing):
                skipped.append(Skip(fy, "NOT_ENOUGH_DATA", den.text()))
                continue
            pct = share_pct(got[field], den.value)
            if pct is None:
                continue
            what = (f"In {fy}, {'revenue from related parties' if key == 'revenue' else 'purchases from related parties'} were INR {got[field]:,} crore, "
                    f"{pct:.1f}% of {'revenue from operations' if key == 'revenue' else 'total expenses'} (INR {crore(den.value)} crore), on the {store.basis} basis.")
            obs.append(Observation(
                check_id="J2-06", fy=fy, metric_name=metric_name, metric_value=pct, severity=severity_for(pct, cfg),
                severity_rule_id=cfg["rule_id"], formula_id=f"{FORMULA_PREFIX}{key}.v1", technique=technique, what_observed=what,
                inputs=[den], thresholds_applied=thresholds_applied(cfg),
                materiality={"basis": "share of revenue or expenses, not an amount", "label": "unassessed"},
                figures={"measure": key, "related_party_cr": got[field], "denominator_cr": round(den.value / CRORE), "share_pct": pct,
                         "snapshot_id": got["snapshot_id"], "page": got["page"], "report_fy": got["report_fy"], "unit": "INR crore"},
            ))
    res = CheckResult("J2-06", cfg.get("check_version", 1), STATUS_COMPLETED if obs else STATUS_NOT_ENOUGH_DATA, obs, skipped)
    res.notes += notes
    return res
