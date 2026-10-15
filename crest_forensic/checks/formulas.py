"""Pure maths for every Job 1 number check. No database, no I/O.

Rule 6 of the Build Plan: Python does the maths, never Claude. These functions
are used twice — by the checks to compute a metric, and by the guardrail to
recompute it from freshly re-read database values. All edge cases (zero
denominators, missing inputs) return None; callers must treat None as
"cannot be computed", never as zero.
"""
from __future__ import annotations


def _div(numerator: float, denominator: float) -> float | None:
    if denominator == 0:
        return None
    return numerator / denominator


def growth(current: float, prior: float) -> float | None:
    """(current / prior) - 1. None when prior is zero."""
    ratio = _div(current, prior)
    return None if ratio is None else ratio - 1.0


# --- J1-01 / J1-02 ----------------------------------------------------------

def profit_cash_gap(pat: float, cfo: float) -> float | None:
    """abs(PAT - CFO) / abs(PAT)."""
    return _div(abs(pat - cfo), abs(pat))


def accruals_ratio(pat: float, cfo: float, total_assets: float, total_assets_prior: float) -> float | None:
    """(PAT - CFO) / average total assets. Positive = profit exceeds cash."""
    return _div(pat - cfo, (total_assets + total_assets_prior) / 2.0)


# --- J1-03 / J1-04 / J1-05 --------------------------------------------------

def growth_ratio(item: float, item_prior: float, revenue: float, revenue_prior: float) -> dict | None:
    """Growth of an item (receivables, inventory, fixed assets) vs revenue growth.

    Returns {"item_growth", "revenue_growth", "ratio"}; `ratio` is None when
    revenue growth is zero or negative (the ratio is then meaningless — the
    caller decides how to treat it). None overall when a prior value is zero.
    """
    g_item = growth(item, item_prior)
    g_rev = growth(revenue, revenue_prior)
    if g_item is None or g_rev is None:
        return None
    ratio = g_item / g_rev if g_rev > 0 else None
    return {"item_growth": g_item, "revenue_growth": g_rev, "ratio": ratio}


def capacity_ratio(item: float, item_prior: float, revenue: float, revenue_prior: float) -> float | None:
    """J1-05: revenue growth divided by fixed-asset growth. Undefined unless BOTH grew (a shrinking
    asset base, or flat revenue, gives no meaningful ratio)."""
    g_item, g_rev = growth(item, item_prior), growth(revenue, revenue_prior)
    if g_item is None or g_rev is None or g_item <= 0 or g_rev <= 0:
        return None
    return g_rev / g_item


def assets_vs_expenses(ta: float, ca: float, ta_prior: float, ca_prior: float, exp: float, exp_prior: float) -> dict | None:
    """J1-08 (option B): growth of non-current assets (property, plant, equipment and soft assets =
    total assets minus current assets) divided by growth of total expenses."""
    return growth_ratio(ta - ca, ta_prior - ca_prior, exp, exp_prior)


def excess_over_revenue_level(item: float, item_prior: float, revenue: float, revenue_prior: float) -> float | None:
    """How much the item exceeds what it would be had it grown in line with revenue."""
    scale = _div(revenue, revenue_prior)
    if scale is None:
        return None
    return max(0.0, item - item_prior * scale)


# --- J1-07 ------------------------------------------------------------------

def other_income_share(other_income: float, pbt: float) -> float | None:
    """other_income / PBT. Undefined (None) when PBT is zero or negative."""
    if pbt <= 0:
        return None
    return other_income / pbt


# --- J1-09 ------------------------------------------------------------------

def restatement_change_pct(old: float, new: float) -> float | None:
    """(new - old) / abs(old), in percent. None when old is zero."""
    r = _div(new - old, abs(old))
    return None if r is None else r * 100.0


# --- J1-06: the eight Beneish components (Build Plan 7.3) --------------------
# Each takes a dict of this year (t) / last year (t-1) inputs and returns the
# component or None. Missing inputs are detected by the caller.

def dsri(v: dict) -> float | None:
    a = _div(v["receivables"], v["revenue"])
    b = _div(v["receivables_prior"], v["revenue_prior"])
    return None if a is None or b is None else _div(a, b)


def gmi(v: dict) -> float | None:
    # gross margin = (revenue - cost) / revenue ; GMI = margin(t-1) / margin(t)
    m_now = _div(v["revenue"] - v["cost"], v["revenue"])
    m_prior = _div(v["revenue_prior"] - v["cost_prior"], v["revenue_prior"])
    return None if m_now is None or m_prior is None else _div(m_prior, m_now)


def aqi(v: dict) -> float | None:
    a = _div(v["current_assets"] + v["ppe"], v["total_assets"])
    b = _div(v["current_assets_prior"] + v["ppe_prior"], v["total_assets_prior"])
    if a is None or b is None:
        return None
    return _div(1.0 - a, 1.0 - b)


def sgi(v: dict) -> float | None:
    return _div(v["revenue"], v["revenue_prior"])


def depi(v: dict) -> float | None:
    rate_now = _div(v["depreciation"], v["depreciation"] + v["ppe"])
    rate_prior = _div(v["depreciation_prior"], v["depreciation_prior"] + v["ppe_prior"])
    return None if rate_now is None or rate_prior is None else _div(rate_prior, rate_now)


def sgai(v: dict) -> float | None:
    a = _div(v["sga"], v["revenue"])
    b = _div(v["sga_prior"], v["revenue_prior"])
    return None if a is None or b is None else _div(a, b)


def lvgi(v: dict) -> float | None:
    a = _div(v["current_liabilities"] + v["long_term_debt"], v["total_assets"])
    b = _div(v["current_liabilities_prior"] + v["long_term_debt_prior"], v["total_assets_prior"])
    return None if a is None or b is None else _div(a, b)


def tata(v: dict) -> float | None:
    """(change in current assets - change in cash - change in current liabilities
    excluding current debt - depreciation) / total assets."""
    d_ca = v["current_assets"] - v["current_assets_prior"]
    d_cash = v["cash"] - v["cash_prior"]
    cl_ex_debt = v["current_liabilities"] - v["current_borrowings"]
    cl_ex_debt_prior = v["current_liabilities_prior"] - v["current_borrowings_prior"]
    d_cl = cl_ex_debt - cl_ex_debt_prior
    return _div(d_ca - d_cash - d_cl - v["depreciation"], v["total_assets"])


# component name -> (function, {formula key -> standard field, "_prior" suffix = year t-1})
BENEISH = {
    "DSRI": (dsri, {"receivables": "trade_receivables", "revenue": "revenue_from_operations"}),
    "GMI": (gmi, {"revenue": "revenue_from_operations", "cost": "cost_of_materials_or_goods"}),
    "AQI": (aqi, {"current_assets": "current_assets", "ppe": "property_plant_equipment", "total_assets": "total_assets"}),
    "SGI": (sgi, {"revenue": "revenue_from_operations"}),
    "DEPI": (depi, {"depreciation": "depreciation_amortisation", "ppe": "property_plant_equipment"}),
    "SGAI": (sgai, {"sga": "selling_and_admin_expenses", "revenue": "revenue_from_operations"}),
    "LVGI": (lvgi, {"current_liabilities": "current_liabilities", "long_term_debt": "long_term_borrowings",
                    "total_assets": "total_assets"}),
    "TATA": (tata, {"current_assets": "current_assets", "cash": "cash_and_equivalents",
                    "current_liabilities": "current_liabilities", "current_borrowings": "current_borrowings",
                    "depreciation": "depreciation_amortisation", "total_assets": "total_assets"}),
}
# TATA uses depreciation and total assets only for year t, not t-1.
_NO_PRIOR = {("TATA", "depreciation"), ("TATA", "total_assets")}


def beneish_required_inputs(component: str, fy_has_prior: bool = True) -> list[tuple[str, str, bool]]:
    """[(formula key, standard field, is_prior_year)] needed for one component."""
    _, fields = BENEISH[component]
    out = []
    for key, std in fields.items():
        out.append((key, std, False))
        if (component, key) not in _NO_PRIOR:
            out.append((key + "_prior", std, True))
    return out


# --- J1-16 distress score (Altman Z'' for emerging markets) ----------------------------------------------------
# Z'' = 3.25 + 6.56*X1 + 3.26*X2 + 6.72*X3 + 1.05*X4   (Altman 2000, non-manufacturers and emerging markets;
# the constant 3.25 is part of the published emerging-market model, so it lives here with the coefficients.)
#   X1 = (current assets - current liabilities) / total assets
#   X2 = retained earnings / total assets   <- we use "Other equity" (reserves and surplus, which include retained
#                                              earnings) as the stand-in, because retained earnings is not on the balance sheet
#   X3 = EBIT / total assets                <- EBIT = profit before tax + finance costs
#   X4 = book value of equity / total liabilities
ALTMAN_EM_CONSTANT = 3.25
ALTMAN_COEFFICIENTS = (6.56, 3.26, 6.72, 1.05)


def altman_z2(current_assets: float, current_liabilities: float, total_assets: float, other_equity: float,
              pbt: float, finance_cost: float, total_equity: float, total_liabilities: float) -> dict | None:
    """Returns {"x1".."x4", "z"}; None when total assets or total liabilities is zero."""
    if total_assets == 0 or total_liabilities == 0:
        return None
    x1 = (current_assets - current_liabilities) / total_assets
    x2 = other_equity / total_assets
    x3 = (pbt + finance_cost) / total_assets
    x4 = total_equity / total_liabilities
    c1, c2, c3, c4 = ALTMAN_COEFFICIENTS
    return {"x1": x1, "x2": x2, "x3": x3, "x4": x4,
            "z": ALTMAN_EM_CONSTANT + c1 * x1 + c2 * x2 + c3 * x3 + c4 * x4}


def altman_z(v: dict) -> float | None:
    res = altman_z2(v["current_assets"], v["current_liabilities"], v["total_assets"], v["other_equity"],
                    v["pbt"], v["finance_cost"], v["total_equity"], v["total_liabilities"])
    return None if res is None else res["z"]


# --- J1-17 digit pattern (Benford's Law) ---------------------------------------------------------------------------
import math as _math

BENFORD_EXPECTED = [_math.log10(1 + 1 / d) for d in range(1, 10)]


def benford_mad(counts: list[int]) -> float | None:
    """Mean absolute deviation between the observed first-digit shares and Benford's expected shares (Nigrini).
    None when there are no numbers."""
    n = sum(counts)
    if n == 0 or len(counts) != 9:
        return None
    return sum(abs(c / n - p) for c, p in zip(counts, BENFORD_EXPECTED)) / 9.0
