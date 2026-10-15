import pytest
from sqlalchemy import select

from crest_forensic.db.models import CheckResultRow, Company, Flag, GuardrailEvent
from crest_forensic.guardrails.config_gate import ConfigNotApproved, unapproved_values
from crest_forensic.screen import load_check_config
from crest_forensic.tests.helpers import make_snapshot, screen, seed

Y = ["FY2025"]


def flags_of(session, run, check_id=None):
    stmt = select(Flag).where(Flag.run_id == run.id)
    if check_id:
        stmt = stmt.where(Flag.check_id == check_id)
    return session.execute(stmt.order_by(Flag.check_id, Flag.financial_year)).scalars().all()


def result_of(session, run, check_id):
    return session.execute(select(CheckResultRow).where(
        CheckResultRow.run_id == run.id, CheckResultRow.check_id == check_id)).scalar_one()


def seed_pat_cfo(session, company, snap, pat, cfo, revenue=1000, fy="FY2025"):
    seed(session, company, snap, "profit_after_tax", {fy: pat})
    seed(session, company, snap, "cash_flow_from_operations", {fy: cfo})
    seed(session, company, snap, "revenue_from_operations", {fy: revenue})


# --- J1-01 -------------------------------------------------------------------

def test_j1_01_high_flag_with_full_citation(session, company, tmp_path):
    snap = make_snapshot(session, company)
    seed_pat_cfo(session, company, snap, pat=100, cfo=50)
    run = screen(session, company, tmp_path, Y)

    (flag,) = flags_of(session, run, "J1-01")
    assert flag.severity == "high" and flag.severity_rule_id == "SEV-J1-01"
    assert flag.figures["metric_value"] == pytest.approx(0.5)
    assert flag.materiality["label"] == "material"          # 50 is 5% of revenue 1000
    assert flag.evidence_confidence == "medium"             # one provider, no estimate
    names = {i["name"] for i in flag.citation["inputs"]}
    assert {"pat", "cfo"} <= names
    assert all(i["line_item_id"] and i["snapshot_id"] and i["snapshot_fetched_at"] for i in flag.citation["inputs"])
    assert flag.citation["config_status"] == "APPROVED"
    assert "innocent explanations" in flag.citation["note"]


def test_j1_01_medium_uses_the_spec_limit(session, company, tmp_path):
    snap = make_snapshot(session, company)
    seed_pat_cfo(session, company, snap, pat=100, cfo=75)   # 25% gap: above spec 20%, below proposed 40%
    (flag,) = flags_of(session, screen(session, company, tmp_path, Y), "J1-01")
    assert flag.severity == "medium"
    assert flag.figures["thresholds_applied"]["medium"] == {"value": 0.2, "source": "spec"}
    assert flag.figures["thresholds_applied"]["high"]["source"] == "proposal"


def test_j1_01_below_limit_computes_but_does_not_flag(session, company, tmp_path):
    snap = make_snapshot(session, company)
    seed_pat_cfo(session, company, snap, pat=100, cfo=85)
    run = screen(session, company, tmp_path, Y)
    assert flags_of(session, run, "J1-01") == []
    assert result_of(session, run, "J1-01").detail["observations"] == 1


def test_derived_cfo_gives_low_evidence_confidence_even_at_high_severity(session, company, tmp_path):
    snap = make_snapshot(session, company)
    seed(session, company, snap, "profit_after_tax", {"FY2025": 100})
    seed(session, company, snap, "cash_flow_from_operations", {"FY2025": 50}, derivation="indirect_method_v1")
    (flag,) = flags_of(session, screen(session, company, tmp_path, Y), "J1-01")
    assert flag.severity == "high"
    assert flag.evidence_confidence == "low"
    assert any(i["derived"] for i in flag.citation["inputs"])


def test_inputs_from_two_providers_cap_confidence_at_low(session, company, tmp_path):
    seed(session, company, make_snapshot(session, company, "rapidapi_moneycontrol"), "profit_after_tax", {"FY2025": 100})
    seed(session, company, make_snapshot(session, company, "yfinance"), "cash_flow_from_operations", {"FY2025": 50})
    (flag,) = flags_of(session, screen(session, company, tmp_path, Y), "J1-01")
    assert flag.evidence_confidence == "low"


def test_every_input_confirmed_by_two_providers_gives_high_confidence(session, company, tmp_path):
    for provider in ("rapidapi_moneycontrol", "yfinance"):
        snap = make_snapshot(session, company, provider)
        seed_pat_cfo(session, company, snap, pat=100, cfo=50)
    (flag,) = flags_of(session, screen(session, company, tmp_path, Y), "J1-01")
    assert flag.evidence_confidence == "high"


def test_source_conflict_stops_the_check_instead_of_picking_a_side(session, company, tmp_path):
    seed(session, company, make_snapshot(session, company, "rapidapi_moneycontrol"), "profit_after_tax", {"FY2025": 100})
    seed(session, company, make_snapshot(session, company, "yfinance"), "profit_after_tax", {"FY2025": 140})
    seed(session, company, make_snapshot(session, company, "yfinance"), "cash_flow_from_operations", {"FY2025": 50})
    run = screen(session, company, tmp_path, Y)

    assert flags_of(session, run, "J1-01") == []
    res = result_of(session, run, "J1-01")
    assert res.status == "NOT_ENOUGH_DATA"
    assert res.detail["skipped"][0]["reason"] == "SOURCE_CONFLICT"


def test_missing_data_says_not_enough_data_never_guesses(session, company, tmp_path):
    seed(session, company, make_snapshot(session, company), "profit_after_tax", {"FY2025": 100})  # no CFO at all
    run = screen(session, company, tmp_path, Y)
    res = result_of(session, run, "J1-01")
    assert res.status == "NOT_ENOUGH_DATA" and flags_of(session, run) == []
    assert "cash_flow_from_operations" in res.detail["skipped"][0]["detail"]


def test_zero_profit_is_not_computable_not_a_crash(session, company, tmp_path):
    snap = make_snapshot(session, company)
    seed_pat_cfo(session, company, snap, pat=0, cfo=50)
    res = result_of(session, screen(session, company, tmp_path, Y), "J1-01")
    assert res.detail["skipped"][0]["reason"] == "NOT_COMPUTABLE"


# --- J1-02 -------------------------------------------------------------------

@pytest.mark.parametrize("cfo,expected", [(100, None), (0, "medium"), (-100, "high")])
def test_j1_02_accruals_severity(session, company, tmp_path, cfo, expected):
    snap = make_snapshot(session, company)
    seed(session, company, snap, "profit_after_tax", {"FY2025": 120})
    seed(session, company, snap, "cash_flow_from_operations", {"FY2025": cfo})
    seed(session, company, snap, "total_assets", {"FY2024": 800, "FY2025": 1000})
    flags = flags_of(session, screen(session, company, tmp_path, Y), "J1-02")
    assert [f.severity for f in flags] == ([expected] if expected else [])


def test_j1_02_needs_prior_year_total_assets(session, company, tmp_path):
    snap = make_snapshot(session, company)
    seed(session, company, snap, "profit_after_tax", {"FY2025": 120})
    seed(session, company, snap, "cash_flow_from_operations", {"FY2025": 0})
    seed(session, company, snap, "total_assets", {"FY2025": 1000})   # FY2024 missing
    res = result_of(session, screen(session, company, tmp_path, Y), "J1-02")
    assert res.status == "NOT_ENOUGH_DATA" and "total_assets@FY2024" in res.detail["skipped"][0]["detail"]


# --- J1-03 / J1-04 / J1-05 -----------------------------------------------------

def test_j1_03_receivables_outgrowing_revenue(session, company, tmp_path):
    snap = make_snapshot(session, company)
    seed(session, company, snap, "trade_receivables", {"FY2024": 100, "FY2025": 130})
    seed(session, company, snap, "revenue_from_operations", {"FY2024": 1000, "FY2025": 1100})
    (flag,) = flags_of(session, screen(session, company, tmp_path, Y), "J1-03")
    assert flag.severity == "high"
    assert flag.figures["growth_ratio"] == pytest.approx(3.0)


def test_j1_03_in_line_with_revenue_is_not_flagged(session, company, tmp_path):
    snap = make_snapshot(session, company)
    seed(session, company, snap, "trade_receivables", {"FY2024": 100, "FY2025": 110})
    seed(session, company, snap, "revenue_from_operations", {"FY2024": 1000, "FY2025": 1100})
    assert flags_of(session, screen(session, company, tmp_path, Y), "J1-03") == []


def test_j1_03_receivables_up_while_revenue_falls_uses_fixed_severity(session, company, tmp_path):
    snap = make_snapshot(session, company)
    seed(session, company, snap, "trade_receivables", {"FY2024": 100, "FY2025": 130})
    seed(session, company, snap, "revenue_from_operations", {"FY2024": 1000, "FY2025": 900})
    (flag,) = flags_of(session, screen(session, company, tmp_path, Y), "J1-03")
    assert flag.severity == "medium" and flag.figures["metric_value"] is None
    assert "did not grow" in flag.what_observed


def test_j1_03_conflicting_receivables_sources_are_not_silently_resolved(session, company, tmp_path):
    for provider, recv in (("rapidapi_moneycontrol", 130), ("yfinance", 100)):
        snap = make_snapshot(session, company, provider)
        seed(session, company, snap, "trade_receivables", {"FY2024": 100, "FY2025": recv})
        seed(session, company, snap, "revenue_from_operations", {"FY2024": 1000, "FY2025": 1100})
    run = screen(session, company, tmp_path, Y)
    assert flags_of(session, run, "J1-03") == []
    assert result_of(session, run, "J1-03").detail["skipped"][0]["reason"] == "SOURCE_CONFLICT"


def test_j1_04_zero_prior_inventory_is_not_computable(session, company, tmp_path):
    snap = make_snapshot(session, company)
    seed(session, company, snap, "inventories", {"FY2024": 0, "FY2025": 30})
    seed(session, company, snap, "revenue_from_operations", {"FY2024": 1000, "FY2025": 1100})
    run = screen(session, company, tmp_path, Y)
    assert flags_of(session, run, "J1-04") == []
    assert result_of(session, run, "J1-04").detail["skipped"][0]["reason"] == "NOT_COMPUTABLE"


def _no_j1_05_limits(cfg):
    cfg["checks"]["J1-05"]["thresholds"] = {"high": {"value": None, "source": "needs_lead"}, "medium": {"value": None, "source": "needs_lead"}}


def test_j1_05_reports_the_metric_but_never_flags_without_limits(session, company, tmp_path):
    snap = make_snapshot(session, company)
    seed(session, company, snap, "property_plant_equipment", {"FY2024": 100, "FY2025": 110})
    seed(session, company, snap, "revenue_from_operations", {"FY2024": 1000, "FY2025": 2000})
    run = screen(session, company, tmp_path, Y, mutate=_no_j1_05_limits)
    res = result_of(session, run, "J1-05")
    assert res.status == "METRIC_ONLY" and res.detail["observations"] == 1
    assert flags_of(session, run, "J1-05") == []


def test_j1_05_is_revenue_growth_over_fixed_asset_growth_and_flags_with_limits(session, company, tmp_path):
    snap = make_snapshot(session, company)
    seed(session, company, snap, "property_plant_equipment", {"FY2024": 100, "FY2025": 110})       # +10%
    seed(session, company, snap, "revenue_from_operations", {"FY2024": 1000, "FY2025": 1400})      # +40%: ratio 4.0
    run = screen(session, company, tmp_path, Y)
    (flag,) = flags_of(session, run, "J1-05")
    assert flag.severity == "high" and "4.00x" in flag.what_observed


def test_j1_05_ratio_is_undefined_when_fixed_assets_shrink_and_never_flags(session, company, tmp_path):
    snap = make_snapshot(session, company)
    seed(session, company, snap, "property_plant_equipment", {"FY2024": 100, "FY2025": 90})
    seed(session, company, snap, "revenue_from_operations", {"FY2024": 1000, "FY2025": 1400})
    run = screen(session, company, tmp_path, Y)
    assert flags_of(session, run, "J1-05") == []
    assert "undefined" in result_of(session, run, "J1-05").detail["metrics"][0].__str__() or result_of(session, run, "J1-05").detail["observations"] == 1


# --- J1-06 / J1-07 / J1-08 ----------------------------------------------------

def test_j1_06_shows_components_individually_with_no_severity_and_lists_unavailable(session, company, tmp_path):
    snap = make_snapshot(session, company)
    seed(session, company, snap, "trade_receivables", {"FY2024": 100, "FY2025": 150})
    seed(session, company, snap, "revenue_from_operations", {"FY2024": 1000, "FY2025": 1000})
    run = screen(session, company, tmp_path, Y)
    res = result_of(session, run, "J1-06")
    metrics = {m["metric"]: m["value"] for m in res.detail["metrics"]}
    assert metrics["DSRI"] == pytest.approx(1.5) and metrics["SGI"] == pytest.approx(1.0)
    assert all(m["severity"] is None for m in res.detail["metrics"])
    unavailable = " ".join(s["detail"] for s in res.detail["skipped"])
    assert "GMI" in unavailable and "LVGI" in unavailable
    assert any("M-score" in n for n in res.detail["notes"])
    assert flags_of(session, run, "J1-06") == []


def test_j1_07_other_income_share(session, company, tmp_path):
    snap = make_snapshot(session, company)
    seed(session, company, snap, "other_income", {"FY2024": 100, "FY2025": 600})
    seed(session, company, snap, "profit_before_tax", {"FY2025": 1000})
    (flag,) = flags_of(session, screen(session, company, tmp_path, Y), "J1-07")
    assert flag.severity == "high" and flag.figures["other_income_yoy_pct"] == pytest.approx(500.0)


def test_j1_07_negative_pbt_is_not_computable(session, company, tmp_path):
    snap = make_snapshot(session, company)
    seed(session, company, snap, "other_income", {"FY2025": 60})
    seed(session, company, snap, "profit_before_tax", {"FY2025": -10})
    run = screen(session, company, tmp_path, Y)
    assert flags_of(session, run, "J1-07") == []
    assert result_of(session, run, "J1-07").detail["skipped"][0]["reason"] == "NOT_COMPUTABLE"


def test_j1_08_flags_non_current_assets_growing_faster_than_expenses(session, company, tmp_path):
    snap = make_snapshot(session, company)
    seed(session, company, snap, "total_assets", {"FY2024": 1000, "FY2025": 1300})
    seed(session, company, snap, "current_assets", {"FY2024": 600, "FY2025": 650})                  # non-current 400 -> 650: +62.5%
    seed(session, company, snap, "total_expenses", {"FY2024": 800, "FY2025": 840})                  # +5%: ratio 12.5
    seed(session, company, snap, "revenue_from_operations", {"FY2024": 1000, "FY2025": 1000})
    run = screen(session, company, tmp_path, Y)
    (flag,) = flags_of(session, run, "J1-08")
    assert flag.severity == "high" and "ratio 12.50x" in flag.what_observed
    assert flag.figures["non_current_assets_growth_pct"] == 62.5


def test_j1_08_without_inputs_says_not_enough_data(session, company, tmp_path):
    res = result_of(session, screen(session, company, tmp_path, Y), "J1-08")
    assert res.status == "NOT_ENOUGH_DATA"


def test_j1_07_year_on_year_jump_limit_raises_a_flag_only_once_the_lead_sets_it(session, company, tmp_path):
    snap = make_snapshot(session, company)
    seed(session, company, snap, "other_income", {"FY2024": 10, "FY2025": 30})          # +200%, share of PBT only 6%
    seed(session, company, snap, "profit_before_tax", {"FY2024": 500, "FY2025": 500})
    seed(session, company, snap, "revenue_from_operations", {"FY2024": 1000, "FY2025": 1000})
    assert flags_of(session, screen(session, company, tmp_path, Y), "J1-07") == []

    def set_limit(cfg):
        cfg["checks"]["J1-07"]["yoy_jump_threshold"] = {"value": 100, "source": "lead"}
    (flag,) = flags_of(session, screen(session, company, tmp_path, Y, mutate=set_limit), "J1-07")
    assert flag.severity == "medium" and "above the limit of 100%" in flag.what_observed


# --- J1-09 restatement test -----------------------------------------------------

def test_restatement_shows_the_difference_between_two_snapshots(session, company, tmp_path):
    old = make_snapshot(session, company, minutes=0)
    new = make_snapshot(session, company, minutes=30)
    seed(session, company, old, "revenue_from_operations", {"FY2025": 1000})
    seed(session, company, new, "revenue_from_operations", {"FY2025": 950})
    (flag,) = flags_of(session, screen(session, company, tmp_path, Y), "J1-09")
    assert flag.figures["change_pct"] == pytest.approx(-5.0)
    ins = {i["name"]: i for i in flag.citation["inputs"]}
    assert ins["old"]["snapshot_id"] == old.snapshot_id and ins["new"]["snapshot_id"] == new.snapshot_id
    assert ins["old"]["value"] == 1000 and ins["new"]["value"] == 950


def test_unchanged_figure_across_snapshots_is_not_a_restatement(session, company, tmp_path):
    for minutes in (0, 30):
        seed(session, company, make_snapshot(session, company, minutes=minutes), "revenue_from_operations", {"FY2025": 1000})
    assert flags_of(session, screen(session, company, tmp_path, Y), "J1-09") == []


def test_single_snapshot_cannot_show_a_restatement(session, company, tmp_path):
    seed(session, company, make_snapshot(session, company), "revenue_from_operations", {"FY2025": 1000})
    assert result_of(session, screen(session, company, tmp_path, Y), "J1-09").status == "NOT_ENOUGH_DATA"


def test_difference_between_two_providers_is_not_a_restatement(session, company, tmp_path):
    seed(session, company, make_snapshot(session, company, "rapidapi_moneycontrol"), "revenue_from_operations", {"FY2025": 1000})
    seed(session, company, make_snapshot(session, company, "yfinance", minutes=30), "revenue_from_operations", {"FY2025": 950})
    assert flags_of(session, screen(session, company, tmp_path, Y), "J1-09") == []


# --- config gate -------------------------------------------------------------------

def test_run_refuses_unapproved_config(session, company, tmp_path):
    with pytest.raises(ConfigNotApproved):
        screen(session, company, tmp_path, Y, approved=False)


def test_draft_override_runs_but_stamps_every_flag_and_the_run(session, company, tmp_path):
    seed_pat_cfo(session, company, make_snapshot(session, company), pat=100, cfo=50)
    run = screen(session, company, tmp_path, Y, approved=False, allow_draft=True)
    assert run.config_approved is False and run.manifest["unapproved_limit_count"] > 0
    (flag,) = flags_of(session, run, "J1-01")
    assert flag.citation["config_status"] == "DRAFT_UNAPPROVED"


def test_shipped_config_is_unapproved_and_marks_the_spec_numbers(session):
    cfg = load_check_config()
    assert not cfg["approval"]["approved_by"] and not cfg["approval"]["approved_at"]
    assert cfg["checks"]["J1-01"]["thresholds"]["medium"] == {"value": 0.2, "source": "spec"}
    assert len(unapproved_values(cfg)) > 10
    # the plan gives no number for J1-05 / J1-08: whatever the file carries is a PROPOSAL (never "spec", never "lead") until the lead confirms it
    for cid in ("J1-05", "J1-08"):
        assert {t["source"] for t in cfg["checks"][cid]["thresholds"].values()} == {"proposal"}
    assert cfg["checks"]["J1-06"]["combined_score"]["value"] is None


def test_unsupported_entity_type_is_not_screened(session, company, tmp_path):
    company.supported_status = "UNSUPPORTED_ENTITY_TYPE"
    with pytest.raises(ValueError):
        screen(session, company, tmp_path, Y)


# --- repeat test ---------------------------------------------------------------------

def test_same_snapshot_same_config_gives_identical_flags(session, company, tmp_path):
    snap = make_snapshot(session, company)
    seed_pat_cfo(session, company, snap, pat=100, cfo=50)
    seed(session, company, snap, "trade_receivables", {"FY2024": 100, "FY2025": 130})
    seed(session, company, snap, "revenue_from_operations", {"FY2024": 1000})
    seed(session, company, snap, "other_income", {"FY2025": 600})
    seed(session, company, snap, "profit_before_tax", {"FY2025": 1000})

    run1 = screen(session, company, tmp_path, Y)
    run2 = screen(session, company, tmp_path, Y)

    assert run1.id != run2.id                       # a re-run adds a run, never edits the old one
    assert run1.run_signature == run2.run_signature
    h1 = sorted(f.content_hash for f in flags_of(session, run1))
    h2 = sorted(f.content_hash for f in flags_of(session, run2))
    assert h1 and h1 == h2
    assert len(flags_of(session, run1)) == run1.flags_created  # earlier run's flags untouched


def test_new_snapshot_changes_the_run_signature(session, company, tmp_path):
    snap = make_snapshot(session, company)
    seed_pat_cfo(session, company, snap, pat=100, cfo=50)
    run1 = screen(session, company, tmp_path, Y)
    make_snapshot(session, company, minutes=99)      # a newer fetch exists
    run2 = screen(session, company, tmp_path, Y)
    assert run1.run_signature != run2.run_signature


def test_no_guardrail_drops_on_clean_data(session, company, tmp_path):
    seed_pat_cfo(session, company, make_snapshot(session, company), pat=100, cfo=50)
    run = screen(session, company, tmp_path, Y)
    assert run.flags_dropped == 0
    assert session.execute(select(GuardrailEvent)).scalars().all() == []


def test_a_figure_confirmed_by_both_sources_does_not_make_a_single_source_check_look_mixed(session, company, tmp_path):
    """Revenue agrees across two providers; receivables come from one. One provider supports
    every input, so confidence is medium, not low."""
    for provider in ("rapidapi_moneycontrol", "yfinance"):
        seed(session, company, make_snapshot(session, company, provider), "revenue_from_operations",
             {"FY2024": 1000, "FY2025": 1100})
    seed(session, company, make_snapshot(session, company, "rapidapi_moneycontrol"), "trade_receivables",
         {"FY2024": 100, "FY2025": 130})
    (flag,) = flags_of(session, screen(session, company, tmp_path, Y), "J1-03")
    assert flag.evidence_confidence == "medium"
