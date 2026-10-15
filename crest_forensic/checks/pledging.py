"""J2-04 promoter pledging: the share of the promoter group's holding that is pledged, at each quarter-end.

Source: the shareholding table (pledged shares on the promoter-group total row of the exchange XBRL files, see
ingestion/exchange_files.py). The Job 2 spec names pledging but states no level, so the limits (medium above 5%, high
above 20% of the promoter group's shares) are PROPOSALS for the lead. A quarter whose file has no pledge figure is skipped,
never assumed to be zero. Reported on the consolidated run only. A flag is a lead for a person, not a conclusion.
"""
from __future__ import annotations

from crest_forensic.checks.base import (
    STATUS_COMPLETED, STATUS_NOT_ENOUGH_DATA, CheckResult, InputStore, Observation, Skip, severity_for,
    thresholds_applied,
)
from crest_forensic.checks.filing_dates import fy_quarter_ends
from crest_forensic.checks.shareholding import STATUS_NOT_APPLICABLE, _row
from crest_forensic.ingestion.exchange_files import quarter_label

FORMULA_ID = "shareholding:J2-04.v1"


def run_j2_04(store: InputStore, years: list[str], cfg: dict) -> CheckResult:
    if store.basis != "consolidated":
        res = CheckResult("J2-04", cfg.get("check_version", 1), STATUS_NOT_APPLICABLE)
        res.notes.append("Shareholding is not specific to a statement basis, so this check is reported once, on the consolidated run.")
        return res
    session, company_id = store.session, store.company_id
    obs, skipped = [], []
    for fy in years:
        found = 0
        for end in fy_quarter_ends(fy):
            row = _row(session, company_id, end)
            if row is None or row.pledged_pct is None:
                continue
            found += 1
            label = quarter_label(end)
            what = (f"At {end.isoformat()} ({label}), {row.pledged_pct:.2f}% of the promoter group's shares were pledged "
                    f"(promoter group holding {row.promoter_pct:.2f}% of all shares).")
            obs.append(Observation(
                check_id="J2-04", fy=fy, metric_name="promoter shares pledged (% of the promoter group's holding)",
                metric_value=row.pledged_pct, severity=severity_for(row.pledged_pct, cfg), severity_rule_id=cfg["rule_id"],
                formula_id=FORMULA_ID, technique="Promoter pledging level at quarter-end", what_observed=what, inputs=[],
                thresholds_applied=thresholds_applied(cfg),
                materiality={"basis": "share of the promoter holding, not an amount", "label": "unassessed"},
                figures={"period_end": end.isoformat(), "quarter": label, "pledged_pct": row.pledged_pct,
                         "promoter_pct": row.promoter_pct, "shareholding_ids": [row.id], "snapshot_ids": [row.snapshot_id]},
            ))
        if not found:
            skipped.append(Skip(fy, "NOT_ENOUGH_DATA", f"no saved shareholding quarter with a pledge figure in {fy}"))
    return CheckResult("J2-04", cfg.get("check_version", 1), STATUS_COMPLETED if obs else STATUS_NOT_ENOUGH_DATA, obs, skipped)
