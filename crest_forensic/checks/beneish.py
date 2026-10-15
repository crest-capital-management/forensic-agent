"""J1-06 Beneish components, shown individually as directional hints only.

No combined M-score and no severity: the plan requires the forensic lead to
approve the weights, cut-off and Ind AS adaptation first (see check_config).
"""
from __future__ import annotations

from crest_forensic.checks import formulas
from crest_forensic.checks.base import (
    CheckResult, InputStore, Observation, Skip, finish, prior_fy, skip_from_missing,
)

_QUESTION = {
    "DSRI": "customer dues growing faster than sales",
    "GMI": "gross margin weakening",
    "AQI": "more costs treated as assets",
    "SGI": "revenue growth rate",
    "DEPI": "depreciation slowing",
    "SGAI": "overheads rising faster than sales",
    "LVGI": "debt level rising",
    "TATA": "profit not backed by cash",
}


def run_j1_06(store: InputStore, years: list[str], cfg: dict) -> CheckResult:
    obs, skipped = [], []
    for fy in years:
        p = prior_fy(fy)
        for comp, (fn, _) in formulas.BENEISH.items():
            specs = [
                (key, std, p if is_prior else fy)
                for key, std, is_prior in formulas.beneish_required_inputs(comp)
            ]
            inputs, missing = store.gather(specs)
            if missing:
                skipped.append(Skip(fy, "COMPONENT_UNAVAILABLE", f"{comp}: " + skip_from_missing(fy, missing).detail))
                continue
            values = {k: i.value for k, i in inputs.items()}
            if comp == "GMI" and (values["cost"] == 0 or values["cost_prior"] == 0):
                skipped.append(Skip(fy, "COMPONENT_UNAVAILABLE",
                                    "GMI: cost_of_materials_or_goods is zero, so gross margin cannot be derived "
                                    "(open decision for the forensic lead)"))
                continue
            value = fn(values)
            if value is None:
                skipped.append(Skip(fy, "NOT_COMPUTABLE", f"{comp}: a denominator is zero"))
                continue
            obs.append(Observation(
                check_id="J1-06", fy=fy, metric_name=comp, metric_value=value, severity=None,
                severity_rule_id=cfg["rule_id"], formula_id=f"J1-06.{comp}.v1",
                technique=f"Beneish component {comp} (directional hint only)",
                what_observed=f"In {fy}, the Beneish component {comp} ({_QUESTION[comp]}) is {value:.3f}.",
                inputs=list(inputs.values()), thresholds_applied={}, materiality={},
                figures={comp: round(value, 4)},
            ))
    result = finish("J1-06", cfg, obs, skipped, metric_only=True)
    result.notes.append("Combined M-score not shown: weights, cut-off and Ind AS adaptation need forensic lead approval.")
    return result
