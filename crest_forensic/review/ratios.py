"""Job 2 result set 1: plain multi-year ratios (margins, working capital, cash conversion), shown beside the matrix.

Information only. No limit exists for any of these, so a cell never carries a label and never counts in the matrix summary,
and the AI narrative does not see them. Each cell says which figures it used. Figures are read through the same source-precedence
policy as every check (InputStore), so a source conflict shows as "not enough data" rather than a guessed value.

Definitions are plain and stated on every row. They are the developer's reading, for the forensic lead to confirm (see LEAD_DECISIONS).
Inventory days use revenue (not cost of goods) because services companies report no cost of goods; balances are year-end, not averages.
"""
from __future__ import annotations

from crest_forensic.checks.base import InputStore, crore, prior_fy, skip_from_missing

DAYS = 365


def _pct(v: float) -> str:
    return f"{v * 100:.1f}%"


def _change(kind: str, v: float, pv: float | None, py: str) -> str:
    if pv is None:
        return ""
    d = v - pv
    if kind == "pct":
        return f" Change from {py}: {d * 100:+.1f} percentage points."
    if kind == "days":
        return f" Change from {py}: {d:+.0f} days."
    return f" Change from {py}: {d:+.2f}."


# key, name, question, rule text, caveat, kind, inputs (name -> standard field, prior year?), compute(vals) -> (value, working text) | None
def _defs() -> list[dict]:
    def growth(v):
        return None if v["rev_prior"] == 0 else (v["rev"] / v["rev_prior"] - 1,
                f"revenue {crore(v['rev'])} ÷ prior-year revenue {crore(v['rev_prior'])} − 1")

    def ratio(num: str, den: str, text: str, mult: float = 1.0, positive_den: bool = False):
        def f(v):
            if v[den] == 0 or (positive_den and v[den] < 0):
                return None
            return (v[num] / v[den] * mult, text(v))
        return f

    return [
        {"key": "rev_growth", "name": "Revenue growth", "question": "How fast sales grew", "kind": "pct",
         "rule": "Revenue from operations this year ÷ last year − 1.", "caveat": None,
         "inputs": [("rev", "revenue_from_operations", False), ("rev_prior", "revenue_from_operations", True)], "calc": growth},
        {"key": "pat_margin", "name": "Net profit margin", "question": "Profit after tax as a share of revenue", "kind": "pct",
         "rule": "Profit after tax ÷ revenue from operations.", "caveat": None,
         "inputs": [("pat", "profit_after_tax", False), ("rev", "revenue_from_operations", False)],
         "calc": ratio("pat", "rev", lambda v: f"profit after tax {crore(v['pat'])} ÷ revenue {crore(v['rev'])}")},
        {"key": "pbit_margin", "name": "Profit before interest and tax margin", "question": "Profit before finance cost and tax, as a share of revenue", "kind": "pct",
         "rule": "(Profit before tax + finance costs) ÷ revenue from operations.",
         "caveat": "Includes other income, so it is not a pure operating margin.",
         "inputs": [("pbt", "profit_before_tax", False), ("fin", "finance_cost", False), ("rev", "revenue_from_operations", False)],
         "calc": lambda v: None if v["rev"] == 0 else ((v["pbt"] + v["fin"]) / v["rev"],
                 f"(profit before tax {crore(v['pbt'])} + finance costs {crore(v['fin'])}) ÷ revenue {crore(v['rev'])}")},
        {"key": "tax_rate", "name": "Effective tax rate", "question": "Tax expense as a share of profit before tax", "kind": "pct",
         "rule": "Tax expense ÷ profit before tax. Shown only when profit before tax is above zero.",
         "caveat": "No peer comparison yet: peer sets need the forensic lead's approval.",
         "inputs": [("tax", "tax_expense", False), ("pbt", "profit_before_tax", False)],
         "calc": ratio("tax", "pbt", lambda v: f"tax expense {crore(v['tax'])} ÷ profit before tax {crore(v['pbt'])}", positive_den=True)},
        {"key": "recv_days", "name": "Receivable days", "question": "Days of revenue sitting in trade receivables", "kind": "days",
         "rule": "Year-end trade receivables ÷ revenue from operations × 365.",
         "caveat": "Year-end balance, not an average.",
         "inputs": [("recv", "trade_receivables", False), ("rev", "revenue_from_operations", False)],
         "calc": ratio("recv", "rev", lambda v: f"trade receivables {crore(v['recv'])} ÷ revenue {crore(v['rev'])} × {DAYS}", DAYS)},
        {"key": "inv_days", "name": "Inventory days (on revenue)", "question": "Days of revenue sitting in inventory", "kind": "days",
         "rule": "Year-end inventories ÷ revenue from operations × 365.",
         "caveat": "Uses revenue, not cost of goods, because services companies report no cost of goods. Year-end balance, not an average.",
         "inputs": [("inv", "inventories", False), ("rev", "revenue_from_operations", False)],
         "calc": ratio("inv", "rev", lambda v: f"inventories {crore(v['inv'])} ÷ revenue {crore(v['rev'])} × {DAYS}", DAYS)},
        {"key": "current_ratio", "name": "Current ratio", "question": "Short-term assets against short-term liabilities", "kind": "x",
         "rule": "Current assets ÷ current liabilities.", "caveat": None,
         "inputs": [("ca", "current_assets", False), ("cl", "current_liabilities", False)],
         "calc": ratio("ca", "cl", lambda v: f"current assets {crore(v['ca'])} ÷ current liabilities {crore(v['cl'])}")},
        {"key": "cash_conv", "name": "Cash conversion", "question": "Operating cash flow for each rupee of profit", "kind": "x",
         "rule": "Cash flow from operations ÷ profit after tax. Shown only when profit after tax is above zero.", "caveat": None,
         "inputs": [("cfo", "cash_flow_from_operations", False), ("pat", "profit_after_tax", False)],
         "calc": ratio("cfo", "pat", lambda v: f"cash flow from operations {crore(v['cfo'])} ÷ profit after tax {crore(v['pat'])}", positive_den=True)},
    ]


def _display(kind: str, v: float) -> str:
    return _pct(v) if kind == "pct" else (f"{v:.0f} days" if kind == "days" else f"{v:.2f}x")


def build_ratios(store: InputStore, years: list[str]) -> list[dict]:
    rows = []
    for d in _defs():
        cells: dict[str, dict] = {}
        values: dict[str, float] = {}
        for fy in years:
            specs = [(n, std, (prior_fy(fy) if prior else fy)) for n, std, prior in d["inputs"]]
            inputs, missing = store.gather(specs)
            if missing:
                skip = skip_from_missing(fy, missing)
                cells[fy] = {"value": None, "display": "not enough data", "badge": None, "skipped": skip.reason, "what": skip.detail}
                continue
            out = d["calc"]({n: i.value for n, i in inputs.items()})
            if out is None:
                cells[fy] = {"value": None, "display": "not enough data", "badge": None, "skipped": "NOT_COMPUTABLE",
                             "what": "The figure it is divided by is zero or below zero, so the ratio would not be meaningful."}
                continue
            value, working = out
            values[fy] = value
            prev_fy = prior_fy(fy)
            change = _change(d["kind"], value, values.get(prev_fy) if prev_fy else None, prev_fy or "")
            cells[fy] = {"value": value, "display": _display(d["kind"], value), "badge": None,
                         "what": f"{fy}: {working} (INR crore).{change} Information only: no limit applies.",
                         "providers": sorted({p for i in inputs.values() for p in (i.providers or (i.provider,))})}
        rows.append({"key": d["key"], "name": d["name"], "question": d["question"], "rule": d["rule"], "caveat": d["caveat"], "cells": cells})
    return rows
