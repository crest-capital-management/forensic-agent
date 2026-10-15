"""J1-16 financial-stress score (Altman Z'' for emerging markets), computed in code from saved statement values.

Wording is deliberately a description and a prompt to review, never a verdict. The score is a published model
built for non-manufacturers and emerging markets; it is not a forecast about this company. X2 uses "Other equity"
(reserves and surplus, which include retained earnings) because retained earnings is not on the balance sheet;
that stand-in is stated on every observation.
"""
from __future__ import annotations

from crest_forensic.checks import formulas
from crest_forensic.checks.base import (
    CheckResult, InputStore, Observation, Skip, crore, finish, skip_from_missing, thresholds_applied,
)

_PROXY_NOTE = ('X2 uses "Other equity" (reserves and surplus, which include retained earnings) as the stand-in '
               "for retained earnings, which the balance sheet does not show.")


def _zone(z: float, cfg: dict) -> tuple[str, float | None, float | None]:
    safe = ((cfg.get("zones") or {}).get("safe_above") or {}).get("value")
    low = ((cfg.get("zones") or {}).get("stress_below") or {}).get("value")
    if low is not None and z < low:
        return "below", safe, low
    if safe is not None and z > safe:
        return "above", safe, low
    return "between", safe, low


def run_j1_16(store: InputStore, years: list[str], cfg: dict) -> CheckResult:
    obs, skipped = [], []
    sev_cfg = cfg.get("zone_severity") or {}
    for fy in years:
        inputs, missing = store.gather([
            ("current_assets", "current_assets", fy), ("current_liabilities", "current_liabilities", fy),
            ("total_assets", "total_assets", fy), ("other_equity", "other_equity", fy),
            ("pbt", "profit_before_tax", fy), ("finance_cost", "finance_cost", fy),
            ("total_equity", "total_equity", fy), ("total_liabilities", "total_liabilities", fy)])
        if missing:
            skipped.append(skip_from_missing(fy, missing))
            continue
        v = {k: i.value for k, i in inputs.items()}
        res = formulas.altman_z2(v["current_assets"], v["current_liabilities"], v["total_assets"], v["other_equity"],
                                 v["pbt"], v["finance_cost"], v["total_equity"], v["total_liabilities"])
        if res is None:
            skipped.append(Skip(fy, "NOT_COMPUTABLE", "total assets or total liabilities is zero"))
            continue
        z = res["z"]
        zone, safe, low = _zone(z, cfg)
        sev = (sev_cfg.get("below") or {}).get("value") if zone == "below" else \
              (sev_cfg.get("between") or {}).get("value") if zone == "between" else None
        if zone == "below":
            words = f"below {low}, the range this published model reads as a sign of financial stress worth a closer look"
        elif zone == "between":
            words = f"between {low} and {safe}, the middle range of the model"
        else:
            words = f"above {safe}, the range the model reads as financially comfortable"
        obs.append(Observation(
            check_id="J1-16", fy=fy, metric_name="Altman Z'' (emerging-market version)", metric_value=z,
            severity=sev, severity_rule_id=cfg["rule_id"], formula_id="J1-16.v1",
            technique="Financial-stress score from liquidity, reserves, operating return and leverage",
            what_observed=f"In {fy}, the Altman Z'' score was {z:.2f}, {words}. {_PROXY_NOTE}",
            inputs=list(inputs.values()), thresholds_applied={**thresholds_applied(cfg), "zones": cfg.get("zones")},
            materiality={"label": "not_assessed", "basis": "a score, not an amount"},
            figures={"z_score": round(z, 4), "zone": zone, "x1_working_capital_to_assets": round(res["x1"], 4),
                     "x2_reserves_to_assets": round(res["x2"], 4), "x3_ebit_to_assets": round(res["x3"], 4),
                     "x4_equity_to_liabilities": round(res["x4"], 4), "ebit_cr": crore(v["pbt"] + v["finance_cost"]),
                     "total_assets_cr": crore(v["total_assets"]), "unit": "INR crore",
                     "note": _PROXY_NOTE},
        ))
    return finish("J1-16", cfg, obs, skipped)
