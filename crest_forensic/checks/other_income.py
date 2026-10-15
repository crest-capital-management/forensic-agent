"""J1-07 unusual other income."""
from __future__ import annotations

from crest_forensic.checks import formulas
from crest_forensic.checks.base import (
    CheckResult, InputStore, Missing, Observation, Skip, crore, finish, materiality,
    prior_fy, severity_for, skip_from_missing, thresholds_applied,
)


def run_j1_07(store: InputStore, years: list[str], cfg: dict) -> CheckResult:
    obs, skipped = [], []
    for fy in years:
        inputs, missing = store.gather([
            ("other_income", "other_income", fy), ("pbt", "profit_before_tax", fy)])
        if missing:
            skipped.append(skip_from_missing(fy, missing))
            continue
        oi, pbt = inputs["other_income"].value, inputs["pbt"].value
        share = formulas.other_income_share(oi, pbt)
        if share is None:
            skipped.append(Skip(fy, "NOT_COMPUTABLE", "profit before tax is zero or negative, so the share is undefined"))
            continue

        used = list(inputs.values())
        figures = {"other_income_cr": crore(oi), "profit_before_tax_cr": crore(pbt),
                   "share_of_pbt_pct": round(share * 100, 2), "unit": "INR crore"}
        # Year-on-year jump is reported as a figure only; the plan sets no limit for it.
        prior = store.get("other_income_prior", "other_income", prior_fy(fy))
        if not isinstance(prior, Missing):
            jump = formulas.growth(oi, prior.value)
            if jump is not None:
                figures["other_income_yoy_pct"] = round(jump * 100, 2)
                used.append(prior)

        severity = severity_for(share, cfg)
        text = f"In {fy}, other income was {share:.1%} of profit before tax."
        jump_limit = (cfg.get("yoy_jump_threshold") or {}).get("value")      # percent; set by the lead
        if jump_limit is not None and figures.get("other_income_yoy_pct") is not None:
            figures["yoy_jump_limit_pct"] = jump_limit
            if figures["other_income_yoy_pct"] > jump_limit:
                text += f" Other income rose {figures['other_income_yoy_pct']:+.1f}% on the year before, above the limit of {jump_limit:g}%."
                severity = severity or "medium"
        mat, mat_inputs = materiality(store, fy, oi, cfg)
        obs.append(Observation(
            check_id="J1-07", fy=fy, metric_name="other_income / profit_before_tax", metric_value=share,
            severity=severity, severity_rule_id=cfg["rule_id"], formula_id="J1-07.v1",
            technique="Other income as a share of profit before tax",
            what_observed=text,
            inputs=used + mat_inputs, thresholds_applied=thresholds_applied(cfg), materiality=mat,
            figures=figures,
        ))
    return finish("J1-07", cfg, obs, skipped)
