"""Unit tests with small made-up inputs and hand-calculated answers (Build Plan section 14)."""
import math

from crest_forensic.checks import formulas as f


def test_profit_cash_gap():
    assert math.isclose(f.profit_cash_gap(100, 70), 0.30)
    assert math.isclose(f.profit_cash_gap(100, 130), 0.30)  # above profit counts too
    assert math.isclose(f.profit_cash_gap(-100, -50), 0.50)  # uses abs(PAT)
    assert f.profit_cash_gap(0, 10) is None  # zero denominator is "cannot compute", never 0


def test_accruals_ratio_uses_average_total_assets():
    assert math.isclose(f.accruals_ratio(120, 100, 1000, 800), 20 / 900)
    assert math.isclose(f.accruals_ratio(100, 120, 1000, 800), -20 / 900)  # sign kept
    assert f.accruals_ratio(1, 1, 0, 0) is None


def test_growth_ratio():
    r = f.growth_ratio(120, 100, 1100, 1000)
    assert math.isclose(r["item_growth"], 0.20) and math.isclose(r["revenue_growth"], 0.10)
    assert math.isclose(r["ratio"], 2.0)


def test_growth_ratio_undefined_when_revenue_not_growing():
    r = f.growth_ratio(120, 100, 900, 1000)
    assert r["ratio"] is None and r["item_growth"] > 0
    assert f.growth_ratio(120, 100, 1000, 1000)["ratio"] is None  # exactly flat


def test_growth_ratio_none_when_prior_is_zero():
    assert f.growth_ratio(5, 0, 1100, 1000) is None
    assert f.growth_ratio(5, 4, 1100, 0) is None


def test_excess_over_revenue_level():
    assert math.isclose(f.excess_over_revenue_level(120, 100, 1100, 1000), 10.0)
    assert f.excess_over_revenue_level(105, 100, 1100, 1000) == 0.0  # grew less than revenue


def test_other_income_share():
    assert math.isclose(f.other_income_share(30, 100), 0.30)
    assert f.other_income_share(30, 0) is None
    assert f.other_income_share(30, -10) is None


def test_restatement_change_pct():
    assert math.isclose(f.restatement_change_pct(1000, 950), -5.0)
    assert f.restatement_change_pct(0, 5) is None


# --- Beneish components, each checked against a hand calculation -------------

def test_beneish_dsri_sgi():
    v = {"receivables": 150, "revenue": 1000, "receivables_prior": 100, "revenue_prior": 1000}
    assert math.isclose(f.dsri(v), 1.5)
    assert math.isclose(f.sgi({"revenue": 1100, "revenue_prior": 1000}), 1.1)


def test_beneish_gmi():
    v = {"revenue": 1000, "cost": 600, "revenue_prior": 1000, "cost_prior": 500}
    assert math.isclose(f.gmi(v), 0.5 / 0.4)  # margin(t-1) / margin(t)


def test_beneish_aqi():
    v = {"current_assets": 300, "ppe": 200, "total_assets": 1000,
         "current_assets_prior": 200, "ppe_prior": 200, "total_assets_prior": 1000}
    assert math.isclose(f.aqi(v), 0.5 / 0.6)


def test_beneish_depi():
    v = {"depreciation": 50, "ppe": 450, "depreciation_prior": 40, "ppe_prior": 460}
    assert math.isclose(f.depi(v), 0.08 / 0.10)


def test_beneish_sgai_lvgi():
    assert math.isclose(f.sgai({"sga": 100, "revenue": 1000, "sga_prior": 80, "revenue_prior": 1000}), 1.25)
    v = {"current_liabilities": 300, "long_term_debt": 100, "total_assets": 1000,
         "current_liabilities_prior": 250, "long_term_debt_prior": 100, "total_assets_prior": 1000}
    assert math.isclose(f.lvgi(v), 0.40 / 0.35)


def test_beneish_tata():
    v = {"current_assets": 300, "current_assets_prior": 250, "cash": 60, "cash_prior": 50,
         "current_liabilities": 300, "current_borrowings": 50,
         "current_liabilities_prior": 250, "current_borrowings_prior": 40,
         "depreciation": 50, "total_assets": 1000}
    # dCA 50 - dCash 10 - dCL(ex debt: 250 - 210 = 40) - dep 50 = -50 ; / 1000
    assert math.isclose(f.tata(v), -0.05)


def test_beneish_zero_denominators_return_none():
    assert f.sgai({"sga": 0, "revenue": 1000, "sga_prior": 0, "revenue_prior": 1000}) is None
    assert f.dsri({"receivables": 1, "revenue": 0, "receivables_prior": 1, "revenue_prior": 1}) is None
