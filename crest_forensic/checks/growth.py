"""J1-03 revenue vs receivables, J1-04 revenue vs inventory, J1-05 capacity mismatch."""
from __future__ import annotations

from crest_forensic.checks import formulas
from crest_forensic.checks.base import (
    CheckResult, InputStore, Observation, Skip, crore, finish, materiality,
    prior_fy, severity_for, skip_from_missing, threshold, thresholds_applied,
)


def _growth_check(
    check_id: str, store: InputStore, years: list[str], cfg: dict, *,
    item_field: str, item_label: str, formula_id: str, technique: str, metric_only: bool = False,
) -> CheckResult:
    obs, skipped = [], []
    fixed = (cfg.get("non_positive_revenue_growth_severity") or {}).get("value")

    for fy in years:
        p = prior_fy(fy)
        inputs, missing = store.gather([
            ("item", item_field, fy), ("item_prior", item_field, p),
            ("revenue", "revenue_from_operations", fy), ("revenue_prior", "revenue_from_operations", p)])
        if missing:
            skipped.append(skip_from_missing(fy, missing))
            continue
        v = {k: i.value for k, i in inputs.items()}
        res = formulas.growth_ratio(v["item"], v["item_prior"], v["revenue"], v["revenue_prior"])
        if res is None:
            skipped.append(Skip(fy, "NOT_COMPUTABLE", f"{item_label} or revenue at the prior year end is zero"))
            continue

        ratio, g_item, g_rev = res["ratio"], res["item_growth"], res["revenue_growth"]
        if metric_only:
            severity = None
        elif ratio is not None:
            severity = severity_for(ratio, cfg)
        else:  # revenue flat or falling: ratio undefined
            severity = fixed if g_item > 0 else None

        excess = formulas.excess_over_revenue_level(v["item"], v["item_prior"], v["revenue"], v["revenue_prior"]) or 0.0
        mat, mat_inputs = materiality(store, fy, excess, cfg) if not metric_only else ({}, [])

        if ratio is not None:
            text = (f"In {fy}, {item_label} changed {g_item:+.1%} while revenue grew {g_rev:+.1%} "
                    f"(growth ratio {ratio:.2f}x).")
        else:
            text = (f"In {fy}, {item_label} changed {g_item:+.1%} while revenue did not grow "
                    f"({g_rev:+.1%}); a growth ratio is undefined.")
        obs.append(Observation(
            check_id=check_id, fy=fy, metric_name=f"{item_label} growth / revenue growth", metric_value=ratio,
            severity=severity, severity_rule_id=cfg["rule_id"], formula_id=formula_id, technique=technique,
            what_observed=text, inputs=list(inputs.values()) + mat_inputs,
            thresholds_applied=thresholds_applied(cfg), materiality=mat,
            figures={f"{item_label}_growth_pct": round(g_item * 100, 2),
                     "revenue_growth_pct": round(g_rev * 100, 2),
                     "growth_ratio": None if ratio is None else round(ratio, 3),
                     f"{item_label}_cr": crore(v["item"]), "revenue_cr": crore(v["revenue"]), "unit": "INR crore"},
        ))
    return finish(check_id, cfg, obs, skipped, metric_only=metric_only)


def run_j1_03(store, years, cfg):
    return _growth_check("J1-03", store, years, cfg, item_field="trade_receivables",
                         item_label="trade receivables", formula_id="J1-03.v1",
                         technique="Growth mismatch: revenue vs receivables")


def run_j1_04(store, years, cfg):
    return _growth_check("J1-04", store, years, cfg, item_field="inventories",
                         item_label="inventories", formula_id="J1-04.v1",
                         technique="Growth mismatch: revenue vs inventory")


def run_j1_05(store, years, cfg):
    """Capacity mismatch: revenue growth divided by fixed-asset growth (formula J1-05.v2).

    Until the lead sets both limits it only shows the metric. A ratio exists only when both revenue and fixed assets grew;
    otherwise it is shown as undefined and never flagged. For service companies people, not fixed assets, are the capacity,
    so a high ratio there is a weak lead."""
    metric_only = threshold(cfg, "high") is None and threshold(cfg, "medium") is None
    obs, skipped = [], []
    for fy in years:
        p = prior_fy(fy)
        inputs, missing = store.gather([
            ("item", "property_plant_equipment", fy), ("item_prior", "property_plant_equipment", p),
            ("revenue", "revenue_from_operations", fy), ("revenue_prior", "revenue_from_operations", p)])
        if missing:
            skipped.append(skip_from_missing(fy, missing))
            continue
        v = {k: i.value for k, i in inputs.items()}
        g_item, g_rev = formulas.growth(v["item"], v["item_prior"]), formulas.growth(v["revenue"], v["revenue_prior"])
        if g_item is None or g_rev is None:
            skipped.append(Skip(fy, "NOT_COMPUTABLE", "fixed assets or revenue at the prior year end is zero"))
            continue
        ratio = formulas.capacity_ratio(v["item"], v["item_prior"], v["revenue"], v["revenue_prior"])
        severity = None if metric_only or ratio is None else severity_for(ratio, cfg)
        if ratio is not None:
            text = f"In {fy}, revenue grew {g_rev:+.1%} while fixed assets grew {g_item:+.1%} (revenue growth over fixed-asset growth {ratio:.2f}x)."
        else:
            text = (f"In {fy}, revenue changed {g_rev:+.1%} and fixed assets changed {g_item:+.1%}; the capacity ratio "
                    f"is undefined unless both grew.")
        mat, mat_inputs = ({}, []) if metric_only else materiality(store, fy, max(0.0, v["item"] - v["item_prior"]), cfg)
        obs.append(Observation(
            check_id="J1-05", fy=fy, metric_name="revenue growth / fixed-asset growth", metric_value=ratio, severity=severity,
            severity_rule_id=cfg["rule_id"], formula_id="J1-05.v2", technique="Growth mismatch: revenue vs fixed assets (capacity)",
            what_observed=text, inputs=list(inputs.values()) + mat_inputs, thresholds_applied=thresholds_applied(cfg), materiality=mat,
            figures={"fixed_assets_growth_pct": round(g_item * 100, 2), "revenue_growth_pct": round(g_rev * 100, 2),
                     "capacity_ratio": None if ratio is None else round(ratio, 3), "fixed_assets_cr": crore(v["item"]),
                     "revenue_cr": crore(v["revenue"]), "unit": "INR crore"},
        ))
    return finish("J1-05", cfg, obs, skipped, metric_only=metric_only)


def run_j1_08(store, years, cfg):
    """Cost capitalisation, option B (the plan's wording): growth of non-current assets (property, plant, equipment and
    soft assets) divided by growth of total expenses. Formula J1-08.v1. Purchases of other companies or investments also raise
    non-current assets, so a high ratio is a lead to read the notes, nothing more."""
    obs, skipped = [], []
    fixed = (cfg.get("non_positive_expense_growth_severity") or {}).get("value")
    for fy in years:
        p = prior_fy(fy)
        inputs, missing = store.gather([
            ("ta", "total_assets", fy), ("ca", "current_assets", fy), ("ta_prior", "total_assets", p), ("ca_prior", "current_assets", p),
            ("exp", "total_expenses", fy), ("exp_prior", "total_expenses", p)])
        if missing:
            skipped.append(skip_from_missing(fy, missing))
            continue
        v = {k: i.value for k, i in inputs.items()}
        res = formulas.assets_vs_expenses(v["ta"], v["ca"], v["ta_prior"], v["ca_prior"], v["exp"], v["exp_prior"])
        if res is None:
            skipped.append(Skip(fy, "NOT_COMPUTABLE", "non-current assets or expenses at the prior year end is zero"))
            continue
        ratio, g_a, g_e = res["ratio"], res["item_growth"], res["revenue_growth"]
        severity = severity_for(ratio, cfg) if ratio is not None else (fixed if g_a > 0 else None)
        nca, nca_prior = v["ta"] - v["ca"], v["ta_prior"] - v["ca_prior"]
        excess = formulas.excess_over_revenue_level(nca, nca_prior, v["exp"], v["exp_prior"]) or 0.0
        mat, mat_inputs = materiality(store, fy, excess, cfg)
        text = (f"In {fy}, non-current assets changed {g_a:+.1%} while total expenses changed {g_e:+.1%}"
                + (f" (ratio {ratio:.2f}x)." if ratio is not None else "; the ratio is undefined because expenses did not grow."))
        obs.append(Observation(
            check_id="J1-08", fy=fy, metric_name="non-current asset growth / expense growth", metric_value=ratio, severity=severity,
            severity_rule_id=cfg["rule_id"], formula_id="J1-08.v1", technique="Growth mismatch: assets vs expenses (cost capitalisation)",
            what_observed=text, inputs=list(inputs.values()) + mat_inputs, thresholds_applied=thresholds_applied(cfg), materiality=mat,
            figures={"non_current_assets_growth_pct": round(g_a * 100, 2), "expense_growth_pct": round(g_e * 100, 2),
                     "growth_ratio": None if ratio is None else round(ratio, 3), "non_current_assets_cr": crore(nca),
                     "total_expenses_cr": crore(v["exp"]), "unit": "INR crore"},
        ))
    return finish("J1-08", cfg, obs, skipped)
