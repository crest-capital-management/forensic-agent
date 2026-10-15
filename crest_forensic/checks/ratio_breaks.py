"""J2-05 year-on-year breaks in the plain ratios (Job 2 result set 1: "year-on-year breaks flagged").

Uses the same eight ratios and definitions as the Ratios table (review/ratios.py), from the same saved figures. A break is a large move
from one year to the next, in either direction:
  - margins, tax rate and revenue growth (shown as percentages): the change in percentage points;
  - receivable days, inventory days, current ratio and cash conversion: the change as a percent of last year's value.
The limits are proposals for the lead (the spec says "breaks flagged" but gives no number). Medium above the limit, high above
HIGH_MULTIPLE times the limit. A flag is a lead for a person, not a conclusion: a break often has an ordinary explanation.
"""
from __future__ import annotations

from crest_forensic.checks.base import (
    STATUS_COMPLETED, STATUS_NEEDS_DEFINITION, STATUS_NOT_ENOUGH_DATA, CheckResult, Input, InputStore, Missing, Observation,
    Skip, prior_fy, skip_from_missing,
)
from crest_forensic.review.ratios import _defs

FORMULA_PREFIX = "J2-05."


def _val(cfg: dict, key: str) -> float | None:
    v = (cfg.get(key) or {}).get("value")
    return None if v is None else float(v)


def ratio_at(store: InputStore, d: dict, fy: str) -> tuple[float, list[Input]] | Missing | None:
    """(value, inputs) of one ratio in one year; Missing if figures are unavailable; None if the ratio is undefined."""
    specs = [(n, std, (prior_fy(fy) if prior else fy)) for n, std, prior in d["inputs"]]
    inputs, missing = store.gather(specs)
    if missing:
        return Missing(missing[0].standard_field, fy, "NOT_ENOUGH_DATA", "; ".join(m.text() for m in missing))
    out = d["calc"]({n: i.value for n, i in inputs.items()})
    if out is None:
        return None
    return out[0], list(inputs.values())


def change(kind: str, current: float, prior: float) -> float | None:
    """Percentage points for percentage-type ratios, percent of last year's value for the others. None when undefined."""
    if kind == "pct":
        return round((current - prior) * 100, 6)
    if prior == 0:
        return None
    return round((current / prior - 1) * 100, 6)


def severity_of(delta: float, limit: float, multiple: float) -> str | None:
    if abs(delta) > limit * multiple:
        return "high"
    if abs(delta) > limit:
        return "medium"
    return None


def _fmt(kind: str, v: float) -> str:
    return f"{v * 100:.1f}%" if kind == "pct" else (f"{v:.0f} days" if kind == "days" else f"{v:.2f}x")


def run_j2_05(store: InputStore, years: list[str], cfg: dict) -> CheckResult:
    pp, rel, mult = _val(cfg, "pct_points_limit"), _val(cfg, "relative_limit_pct"), _val(cfg, "high_multiple")
    if pp is None or rel is None or mult is None:
        res = CheckResult("J2-05", cfg.get("check_version", 1), STATUS_NEEDS_DEFINITION)
        res.notes.append("The limits for year-on-year breaks are not set (percentage points for margins, percent for days and ratios, and the high multiple).")
        return res
    obs, skipped = [], []
    for d in _defs():
        limit = pp if d["kind"] == "pct" else rel
        unit = "percentage points" if d["kind"] == "pct" else "%"
        for fy in years:
            prev = prior_fy(fy)
            cur, old = ratio_at(store, d, fy), ratio_at(store, d, prev)
            if isinstance(cur, Missing) or isinstance(old, Missing):
                bad = cur if isinstance(cur, Missing) else old
                skipped.append(Skip(fy, "NOT_ENOUGH_DATA", f"{d['name']}: {bad.detail}"))
                continue
            if cur is None or old is None:
                skipped.append(Skip(fy, "NOT_COMPUTABLE", f"{d['name']}: the ratio is undefined in {fy if cur is None else prev}"))
                continue
            delta = change(d["kind"], cur[0], old[0])
            if delta is None:
                skipped.append(Skip(fy, "NOT_COMPUTABLE", f"{d['name']}: last year's value is zero"))
                continue
            inputs = [Input(**{**i.__dict__, "name": f"cur:{i.name}"}) for i in cur[1]] + [Input(**{**i.__dict__, "name": f"prev:{i.name}"}) for i in old[1]]
            sev = severity_of(delta, limit, mult)
            text = (f"{d['name']} moved from {_fmt(d['kind'], old[0])} in {prev} to {_fmt(d['kind'], cur[0])} in {fy}, a change of "
                    f"{delta:+.1f} {unit}" + (f", beyond the limit of {limit:g} {unit}." if sev else "; the limit is " + f"{limit:g} {unit}."))
            obs.append(Observation(
                check_id="J2-05", fy=fy, metric_name=f"change in {d['name'].lower()} ({unit})", metric_value=delta, severity=sev,
                severity_rule_id=cfg["rule_id"], formula_id=f"{FORMULA_PREFIX}{d['key']}.v1",
                technique="Year-on-year change in a plain ratio", what_observed=text, inputs=inputs,
                thresholds_applied={"limit": {"value": limit, "unit": unit, "source": (cfg.get('pct_points_limit' if d['kind'] == 'pct' else 'relative_limit_pct') or {}).get("source")},
                                    "high_multiple": {"value": mult, "source": (cfg.get("high_multiple") or {}).get("source")}},
                materiality={"basis": "year-on-year change in a ratio, not an amount", "label": "unassessed"},
                figures={"ratio": d["key"], "ratio_name": d["name"], "value": round(cur[0], 6), "prior_value": round(old[0], 6), "prior_fy": prev,
                         "change": delta, "unit": unit, "definition": d["rule"]},
            ))
    return CheckResult("J2-05", cfg.get("check_version", 1), STATUS_COMPLETED if obs else STATUS_NOT_ENOUGH_DATA, obs, skipped)
