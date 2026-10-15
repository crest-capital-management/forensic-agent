import pytest

from crest_forensic.checks import formulas
from crest_forensic.review import matrix as mtx
from crest_forensic.review import service as svc
from crest_forensic.tests.helpers import make_snapshot, seed
from crest_forensic.tests.test_altman_benford import HEALTHY, WEAK, benford_texts, make_report


def put(session, company, values, fy="FY2026"):
    snap = make_snapshot(session, company)
    values = {"revenue_from_operations": 1000, **values}      # the matrix takes its years from the revenue data
    for field, v in values.items():
        seed(session, company, snap, field, {fy: v})


def row(data, key):
    return next(r for r in data["rows"] if r["key"] == key)


def test_the_four_measures_are_laid_out_side_by_side_per_year(session, company):
    put(session, company, HEALTHY)
    d = mtx.build_matrix(session, company.company_id, "standalone")
    assert [r["key"] for r in d["rows"]] == ["beneish", "altman", "benford", "sloan"]
    assert d["basis"] == "standalone" and d["company"]["name"] == "Test Co"


def test_an_altman_cell_equals_the_check_and_gets_a_badge_from_the_live_limits(session, company):
    put(session, company, HEALTHY)
    cell = row(mtx.build_matrix(session, company.company_id, "standalone"), "altman")["cells"]["FY2026"]
    assert cell["display"] == "6.59" and cell["badge"] == "normal" and cell["zone"] == "above"
    assert "Other equity" in cell["what"] and cell["providers"]


def test_a_weak_company_is_marked_review_first_and_counted_in_the_summary(session, company):
    put(session, company, WEAK)
    d = mtx.build_matrix(session, company.company_id, "standalone")
    assert row(d, "altman")["cells"]["FY2026"]["badge"] == "review"
    assert d["summary"]["FY2026"]["review"] == 1 and d["summary"]["FY2026"]["no_data"] == 2


def test_the_combined_m_score_is_not_shown_and_the_parts_are(session, company):
    put(session, company, {"revenue_from_operations": 1000, "trade_receivables": 200, "current_assets": 500,
                           "property_plant_equipment": 300, "total_assets": 1000, "depreciation_amortisation": 50})
    snap = make_snapshot(session, company, minutes=5)
    for field in ("revenue_from_operations", "trade_receivables", "current_assets", "property_plant_equipment",
                  "total_assets", "depreciation_amortisation"):
        seed(session, company, snap, field, {"FY2025": 900})
    ben = row(mtx.build_matrix(session, company.company_id, "standalone"), "beneish")
    assert "not shown" in ben["message"] and "forensic lead" in ben["message"]
    assert all(c["badge"] is None for c in ben["cells"].values())          # no verdict on the parts
    assert [p["key"] for p in ben["parts"]] == list(mtx.BEN_PARTS)
    assert ben["parts"][0]["cells"]["FY2026"]["display"] != "not enough data"   # DSRI is computable here


def test_missing_data_is_not_enough_data_never_a_guess(session, company):
    put(session, company, {k: v for k, v in HEALTHY.items() if k != "other_equity"})
    cell = row(mtx.build_matrix(session, company.company_id, "standalone"), "altman")["cells"]["FY2026"]
    assert cell["display"] == "not enough data" and cell["badge"] is None and cell["value"] is None
    assert "other_equity" in cell["what"]


def test_years_stop_at_the_newest_annual_report_and_are_capped_at_ten(session, company):
    snap = make_snapshot(session, company)
    for y in range(2012, 2028):
        seed(session, company, snap, "revenue_from_operations", {f"FY{y}": 1000 + y})
    make_report(session, company, ["Revenue 2,67,021"], fy="FY2026")
    d = mtx.build_matrix(session, company.company_id, "standalone")
    assert d["years"][-1] == "FY2026" and len(d["years"]) == 10 and d["years"][0] == "FY2017"


def test_benford_cells_get_badges_from_the_bands(session, company):
    make_report(session, company, benford_texts(formulas.BENFORD_EXPECTED, total=1500))
    seed(session, company, make_snapshot(session, company), "revenue_from_operations", {"FY2026": 1000})
    cell = row(mtx.build_matrix(session, company.company_id, "standalone"), "benford")["cells"]["FY2026"]
    assert cell["badge"] == "normal" and cell["band"] in ("close", "acceptable") and cell["numbers_counted"] >= 1000


def test_skewed_digits_are_marked_review_first(session, company):
    make_report(session, company, benford_texts([0.02] * 8 + [0.84], total=1500))
    seed(session, company, make_snapshot(session, company), "revenue_from_operations", {"FY2026": 1000})
    cell = row(mtx.build_matrix(session, company.company_id, "standalone"), "benford")["cells"]["FY2026"]
    assert cell["badge"] == "review" and cell["band"] == "nonconforming"


def test_a_bank_or_an_unknown_basis_is_refused(session, company):
    with pytest.raises(svc.RuleError):
        mtx.build_matrix(session, company.company_id, "quarterly")
    company.supported_status = "UNSUPPORTED_ENTITY_TYPE"
    with pytest.raises(svc.RuleError):
        mtx.build_matrix(session, company.company_id, "standalone")
    with pytest.raises(svc.RuleError) as e:
        mtx.build_matrix(session, 999, "standalone")
    assert e.value.status == 404


def test_the_matrix_writes_nothing(session, company):
    from crest_forensic.db.models import Flag, Run
    put(session, company, WEAK)
    mtx.build_matrix(session, company.company_id, "standalone")
    assert session.query(Run).count() == 0 and session.query(Flag).count() == 0


def test_no_badge_wording_is_a_verdict():
    from crest_forensic.guardrails.language import banned_terms_in
    words = " ".join(mtx.BADGE_WORDS.values()) + " ".join(mtx.BEN_PARTS.values())
    assert banned_terms_in(words) == []


# ---- plain ratios (information only) ----------------------------------------------------------------------------------

def ratio(data, key):
    return next(r for r in data["ratios"] if r["key"] == key)


def _two_years(session, company):
    put(session, company, {"revenue_from_operations": 1100, "profit_after_tax": 110, "profit_before_tax": 150, "finance_cost": 10,
                           "tax_expense": 40, "trade_receivables": 220, "inventories": 55, "current_assets": 600,
                           "current_liabilities": 300, "cash_flow_from_operations": 121})
    snap = make_snapshot(session, company, minutes=5)
    for field, v in {"revenue_from_operations": 1000, "profit_after_tax": 100, "profit_before_tax": 140, "finance_cost": 10,
                     "tax_expense": 40, "trade_receivables": 150, "inventories": 50, "current_assets": 500,
                     "current_liabilities": 250, "cash_flow_from_operations": 90}.items():
        seed(session, company, snap, field, {"FY2025": v})


def test_ratios_use_the_stated_formulas_and_say_what_they_used(session, company):
    _two_years(session, company)
    d = mtx.build_matrix(session, company.company_id, "standalone")
    assert [r["key"] for r in d["ratios"]] == ["rev_growth", "pat_margin", "pbit_margin", "tax_rate", "recv_days", "inv_days",
                                                "current_ratio", "cash_conv"]
    c = lambda k: ratio(d, k)["cells"]["FY2026"]
    assert round(c("rev_growth")["value"], 4) == 0.1 and c("pat_margin")["display"] == "10.0%"
    assert c("pbit_margin")["display"] == "14.5%" and c("tax_rate")["display"] == "26.7%"
    assert c("recv_days")["display"] == "73 days" and c("inv_days")["display"] == "18 days"
    assert c("current_ratio")["display"] == "2.00x" and c("cash_conv")["display"] == "1.10x"
    assert "÷" in c("recv_days")["what"] and "Information only" in c("recv_days")["what"] and c("recv_days")["providers"]
    assert "Change from FY2025" in c("pat_margin")["what"]


def test_ratios_never_carry_a_label_and_do_not_touch_the_summary_or_the_narrative_facts(session, company):
    from crest_forensic.review import narrative as nar
    _two_years(session, company)
    d = mtx.build_matrix(session, company.company_id, "standalone")
    assert all(c["badge"] is None for r in d["ratios"] for c in r["cells"].values())
    assert [r["key"] for r in d["rows"]] == ["beneish", "altman", "benford", "sloan"]
    facts, lines = nar.build_facts(d)
    assert not any(ref.startswith(("cell:rev", "cell:pat", "cell:recv", "cell:tax", "cell:current", "cell:cash")) for ref in lines)


def test_ratios_say_not_enough_data_rather_than_guess(session, company):
    put(session, company, {"profit_after_tax": 100, "profit_before_tax": -5, "tax_expense": 2, "cash_flow_from_operations": 50})
    d = mtx.build_matrix(session, company.company_id, "standalone")
    assert ratio(d, "rev_growth")["cells"]["FY2026"]["value"] is None            # no prior year
    assert ratio(d, "tax_rate")["cells"]["FY2026"]["skipped"] == "NOT_COMPUTABLE"   # loss before tax: rate is meaningless
    assert ratio(d, "recv_days")["cells"]["FY2026"]["value"] is None             # receivables not saved
