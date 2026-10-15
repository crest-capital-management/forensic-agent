import datetime as dt
import math

import pytest
from sqlalchemy import select

from crest_forensic import config_store
from crest_forensic.checks import formulas
from crest_forensic.checks.base import Observation
from crest_forensic.db.models import (
    CheckResultRow, ConfigVersion, Document, DocumentVersion, Flag, GuardrailEvent, TextExtract,
)
from crest_forensic.documents import digits
from crest_forensic.guardrails.validate import validate_observation
from crest_forensic.tests.helpers import make_snapshot, screen, seed

Y = ["FY2026"]

# A healthy company by hand: X1 0.2, X2 0.2, X3 0.1, X4 0.6667 -> Z'' = 3.25 + 1.312 + 0.652 + 0.672 + 0.7 = 6.586
HEALTHY = dict(current_assets=500, current_liabilities=300, total_assets=1000, other_equity=200,
               profit_before_tax=90, finance_cost=10, total_equity=400, total_liabilities=600)
# Weak: little liquidity, deficits in reserves, thin return, heavy debt
WEAK = dict(current_assets=300, current_liabilities=500, total_assets=1000, other_equity=-300,
            profit_before_tax=-50, finance_cost=40, total_equity=100, total_liabilities=900)


def seed_company(session, company, values, fy="FY2026"):
    snap = make_snapshot(session, company)
    for field, v in values.items():
        seed(session, company, snap, field, {fy: v})
    return snap


def result_of(session, run, check_id):
    return session.execute(select(CheckResultRow).where(
        CheckResultRow.run_id == run.id, CheckResultRow.check_id == check_id)).scalar_one()


def flags_of(session, run, check_id):
    return session.execute(select(Flag).where(Flag.run_id == run.id, Flag.check_id == check_id)).scalars().all()


# ---- Altman Z'' ---------------------------------------------------------------------------------------------

def test_the_formula_matches_a_hand_calculation():
    r = formulas.altman_z2(500, 300, 1000, 200, 90, 10, 400, 600)
    assert [round(r[k], 4) for k in ("x1", "x2", "x3", "x4")] == [0.2, 0.2, 0.1, 0.6667]
    assert round(r["z"], 3) == 6.586


def test_zero_assets_or_liabilities_cannot_be_scored():
    assert formulas.altman_z2(1, 1, 0, 1, 1, 1, 1, 1) is None
    assert formulas.altman_z2(1, 1, 1, 1, 1, 1, 1, 0) is None


def test_a_healthy_company_is_scored_but_not_flagged(session, company, tmp_path):
    seed_company(session, company, HEALTHY)
    run = screen(session, company, tmp_path, Y)
    row = result_of(session, run, "J1-16")
    assert row.status == "COMPLETED"
    (m,) = row.detail["metrics"]
    assert round(m["value"], 3) == 6.586 and m["severity"] is None
    assert flags_of(session, run, "J1-16") == []


def test_a_weak_company_is_flagged_with_review_wording_and_a_full_citation(session, company, tmp_path):
    seed_company(session, company, WEAK)
    run = screen(session, company, tmp_path, Y)
    (flag,) = flags_of(session, run, "J1-16")
    assert flag.severity == "high" and flag.figures["zone"] == "below"
    assert "closer look" in flag.what_observed and "below 4.15" in flag.what_observed
    for word in ("bankrupt", "fraud", "fail", "insolven", "default"):
        assert word not in flag.what_observed.lower()
    assert {i["field"] for i in flag.citation["inputs"]} == {
        "current_assets", "current_liabilities", "total_assets", "other_equity", "profit_before_tax",
        "finance_cost", "total_equity", "total_liabilities"}
    assert "Other equity" in flag.what_observed          # the stand-in is always stated


def test_missing_other_equity_means_not_enough_data_never_a_guess(session, company, tmp_path):
    seed_company(session, company, {k: v for k, v in HEALTHY.items() if k != "other_equity"})
    run = screen(session, company, tmp_path, Y)
    row = result_of(session, run, "J1-16")
    assert row.status == "NOT_ENOUGH_DATA" and "other_equity" in row.detail["skipped"][0]["detail"]


def test_the_lead_can_move_the_zone_limits_but_not_invert_them(session):
    from crest_forensic.review import config_service as cfg
    from crest_forensic.review import service as svc
    svc.ensure_default_users(session)
    from crest_forensic.db.models import AppUser
    lead = session.execute(select(AppUser).where(AppUser.username == "lead1")).scalars().first()
    cfg.edit(session, lead, [{"path": "checks.J1-16.zones.stress_below.value", "value": 3.0}], "tighter")
    with pytest.raises(svc.RuleError):
        cfg.edit(session, lead, [{"path": "checks.J1-16.zones.stress_below.value", "value": 9.0}], "bad")


# ---- Benford: the method ------------------------------------------------------------------------------------

def test_a_perfect_benford_set_scores_zero_and_a_skewed_one_scores_high():
    perfect = [round(1000 * p) for p in formulas.BENFORD_EXPECTED]
    assert formulas.benford_mad(perfect) < 0.0005
    assert formulas.benford_mad([0, 0, 0, 0, 0, 0, 0, 0, 1000]) > 0.1
    assert formulas.benford_mad([0] * 9) is None


def test_amounts_are_found_but_years_short_numbers_and_dates_are_not():
    text = "Revenue 2,67,021 and 1,06,878 FY 2026 2025 note 12 5.2% on 31/03/2026 at 10:30 and 362 plus 12,345.67 and 007"
    assert digits.amount_tokens(text) == ["2,67,021", "1,06,878", "362", "12,345"]
    assert digits.leading_digits(text) == [2, 1, 3, 1]


def make_report(session, company, texts, fy="FY2026", sections=None, sha="b" * 64):
    doc = Document(company_id=company.company_id, doc_type="annual_report", fiscal_year=fy, title=f"AR {fy}")
    session.add(doc)
    session.flush()
    n = len(texts)
    version = DocumentVersion(
        document_id=doc.id, file_name=f"ar_{fy}.pdf", file_sha256=sha, page_count=n, extractor="test",
        sections=sections or {"standalone_notes": {"first": 1, "last": n}},
        created_at=dt.datetime(2026, 10, 1, tzinfo=dt.timezone.utc))
    session.add(version)
    session.flush()
    for i, t in enumerate(texts, start=1):
        session.add(TextExtract(document_version_id=version.id, page_number=i, printed_page=str(i + 100), text=t, text_sha256="x"))
    session.flush()
    return version


def benford_texts(shares, total=1200):
    """Pages of DISTINCT amounts whose leading digits follow the given shares."""
    nums, k = [], 100
    for d, share in zip(range(1, 10), shares):
        for _ in range(round(total * share)):
            nums.append(f"{d}{k % 90 + 10}{k // 90 + 10}")      # e.g. 1xxxx, all different
            k += 1
    chunks = [nums[i:i + 100] for i in range(0, len(nums), 100)]
    return [" ".join(c) for c in chunks]


def test_the_same_figure_printed_many_times_is_counted_once():
    text = "100 100 100 100 100 100 250 250 360"
    assert sorted(set(digits.amount_tokens(text))) == ["100", "250", "360"]


# ---- Benford: the check -------------------------------------------------------------------------------------------

def shrink_min_numbers(cfg):
    cfg["checks"]["J1-17"]["min_numbers"]["value"] = 300


def test_benford_shaped_numbers_are_scored_but_not_flagged(session, company, tmp_path):
    make_report(session, company, benford_texts(formulas.BENFORD_EXPECTED))
    run = screen(session, company, tmp_path, Y, mutate=shrink_min_numbers)
    (m,) = result_of(session, run, "J1-17").detail["metrics"]
    assert m["value"] < 0.006 and m["severity"] is None
    assert flags_of(session, run, "J1-17") == []


def test_numbers_that_break_the_pattern_raise_a_low_confidence_lead_with_a_citation(session, company, tmp_path):
    skewed = [0.02, 0.02, 0.02, 0.02, 0.02, 0.02, 0.02, 0.02, 0.82]
    make_report(session, company, benford_texts(skewed))
    run = screen(session, company, tmp_path, Y, mutate=shrink_min_numbers)
    (flag,) = flags_of(session, run, "J1-17")
    assert flag.severity == "low" and flag.evidence_confidence == "low" and flag.figures["band"] == "nonconforming"
    assert "weak signal" in flag.what_observed and "outside the usual range" in flag.what_observed
    (ev,) = flag.citation["evidence"]
    assert ev["n"] == sum(ev["counts"]) and ev["document_sha256"] == "b" * 64 and ev["sections"] == {"standalone_notes": [1, 12]}
    assert flag.location["documents"] == ["ar_FY2026.pdf"]


def test_too_few_numbers_means_the_test_is_skipped(session, company, tmp_path):
    make_report(session, company, ["Revenue 2,67,021 and 1,06,878 and 362"])
    run = screen(session, company, tmp_path, Y)           # shipped limit: at least 1000 numbers
    row = result_of(session, run, "J1-17")
    assert row.status == "NOT_ENOUGH_DATA" and "needs at least 1,000" in row.detail["skipped"][0]["detail"]


def test_no_annual_report_means_not_enough_data(session, company, tmp_path):
    run = screen(session, company, tmp_path, Y)
    assert "no annual report is saved" in result_of(session, run, "J1-17").detail["skipped"][0]["detail"]


def test_the_guardrail_recounts_the_document_and_drops_a_tampered_flag(session, company, tmp_path):
    version = make_report(session, company, benford_texts([0.02] * 8 + [0.84]))
    run = screen(session, company, tmp_path, Y, mutate=shrink_min_numbers)
    (flag,) = flags_of(session, run, "J1-17")
    ev = dict(flag.citation["evidence"][0])
    good = Observation(check_id="J1-17", fy="FY2026", metric_name="m", metric_value=ev["mad"], severity="low",
                       severity_rule_id="R", formula_id="digits:standalone", technique="t", what_observed="plain wording",
                       inputs=[], thresholds_applied={}, materiality={}, figures={}, evidence=[ev])
    assert validate_observation(session, good, company.company_id, "standalone") == []
    bad_counts = dict(ev, counts=[ev["counts"][0] + 5] + ev["counts"][1:])
    bad = Observation(**{**good.__dict__, "evidence": [bad_counts]})
    assert validate_observation(session, bad, company.company_id, "standalone")[0][0] == "recalculation"
    wrong_score = Observation(**{**good.__dict__, "metric_value": 0.0001})
    assert validate_observation(session, wrong_score, company.company_id, "standalone")[0][0] == "recalculation"
    wrong_doc = Observation(**{**good.__dict__, "evidence": [dict(ev, document_sha256="f" * 64)]})
    assert validate_observation(session, wrong_doc, company.company_id, "standalone")[0][0] == "citation"
    banned = Observation(**{**good.__dict__, "what_observed": "this looks like fraud"})
    assert validate_observation(session, banned, company.company_id, "standalone")[0][0] == "banned_language"


# ---- config -----------------------------------------------------------------------------------------------------

def test_a_saved_live_config_that_predates_the_new_checks_gains_them_and_loses_its_approval(session):
    old = config_store.load_file_config()
    del old["checks"]["J1-16"], old["checks"]["J1-17"]
    old["approval"] = {"approved_by": "lead1", "approved_at": "2026-10-01"}
    session.add(ConfigVersion(version=7, content=old, content_hash="old", origin="editor", created_by="lead1"))
    session.flush()
    live = config_store.active_config(session)
    assert "J1-16" in live["checks"] and "J1-17" in live["checks"]
    assert live["approval"] == {"approved_by": None, "approved_at": None}
    assert "checks.J1-17.min_numbers" in config_store.unconfirmed(live)
