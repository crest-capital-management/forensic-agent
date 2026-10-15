"""J1-01 profit vs cash, J1-02 accruals build-up."""
from __future__ import annotations

from crest_forensic.checks import formulas
from crest_forensic.checks.base import (
    CheckResult, InputStore, Observation, Skip, crore, finish, materiality,
    prior_fy, severity_for, skip_from_missing, thresholds_applied,
)

DISCLAIMER_FIGURE_UNIT = "INR crore"


def run_j1_01(store: InputStore, years: list[str], cfg: dict) -> CheckResult:
    obs, skipped = [], []
    for fy in years:
        inputs, missing = store.gather([
            ("pat", "profit_after_tax", fy), ("cfo", "cash_flow_from_operations", fy)])
        if missing:
            skipped.append(skip_from_missing(fy, missing))
            continue
        pat, cfo = inputs["pat"].value, inputs["cfo"].value
        gap = formulas.profit_cash_gap(pat, cfo)
        if gap is None:
            skipped.append(Skip(fy, "NOT_COMPUTABLE", "profit after tax is zero, so a percentage gap is undefined"))
            continue

        mat, mat_inputs = materiality(store, fy, abs(pat - cfo), cfg)
        direction = "below" if cfo < pat else "above"
        obs.append(Observation(
            check_id="J1-01", fy=fy, metric_name="abs(pat - cfo) / abs(pat)", metric_value=gap,
            severity=severity_for(gap, cfg), severity_rule_id=cfg["rule_id"], formula_id="J1-01.v1",
            technique="Profit vs operating cash flow divergence",
            what_observed=(
                f"In {fy}, cash flow from operations was {direction} profit after tax; "
                f"the gap is {gap:.1%} of profit after tax."),
            inputs=list(inputs.values()) + mat_inputs,
            thresholds_applied=thresholds_applied(cfg), materiality=mat,
            figures={"profit_after_tax_cr": crore(pat), "cash_flow_from_operations_cr": crore(cfo),
                     "gap_pct_of_pat": round(gap * 100, 2), "unit": DISCLAIMER_FIGURE_UNIT},
        ))
    return finish("J1-01", cfg, obs, skipped)


def run_j1_02(store: InputStore, years: list[str], cfg: dict) -> CheckResult:
    obs, skipped = [], []
    for fy in years:
        p = prior_fy(fy)
        inputs, missing = store.gather([
            ("pat", "profit_after_tax", fy), ("cfo", "cash_flow_from_operations", fy),
            ("total_assets", "total_assets", fy), ("total_assets_prior", "total_assets", p)])
        if missing:
            skipped.append(skip_from_missing(fy, missing))
            continue
        pat, cfo = inputs["pat"].value, inputs["cfo"].value
        ratio = formulas.accruals_ratio(pat, cfo, inputs["total_assets"].value, inputs["total_assets_prior"].value)
        if ratio is None:
            skipped.append(Skip(fy, "NOT_COMPUTABLE", "average total assets is zero"))
            continue

        mat, mat_inputs = materiality(store, fy, abs(pat - cfo), cfg)
        relation = "exceeded" if ratio > 0 else "was below"
        obs.append(Observation(
            check_id="J1-02", fy=fy, metric_name="(pat - cfo) / average total assets", metric_value=ratio,
            severity=severity_for(ratio, cfg), severity_rule_id=cfg["rule_id"], formula_id="J1-02.v1",
            technique="Sloan-style accruals: (profit - operating cash flow) / average total assets",
            what_observed=(
                f"In {fy}, profit after tax {relation} cash flow from operations by "
                f"{abs(ratio):.1%} of average total assets."),
            inputs=list(inputs.values()) + mat_inputs,
            thresholds_applied=thresholds_applied(cfg), materiality=mat,
            figures={"profit_after_tax_cr": crore(pat), "cash_flow_from_operations_cr": crore(cfo),
                     "average_total_assets_cr": crore((inputs["total_assets"].value + inputs["total_assets_prior"].value) / 2),
                     "accruals_ratio_pct": round(ratio * 100, 2), "unit": DISCLAIMER_FIGURE_UNIT},
        ))
    return finish("J1-02", cfg, obs, skipped)
