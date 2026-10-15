import datetime as dt

from sqlalchemy import select

from crest_forensic.checks.base import InputStore
from crest_forensic.checks.ratio_breaks import change, run_j2_05, severity_of
from crest_forensic.checks.related_party import run_j2_06, share_pct
from crest_forensic.connectors.base import RawSourceResponse
from crest_forensic.db.models import Flag
from crest_forensic.documents.related_party import ENDPOINT, PROVIDER, parse_page
from crest_forensic.guardrails.validate import validate_observation
from crest_forensic.ingestion.fetch_and_snapshot import save_snapshot
from crest_forensic.screen import load_check_config
from crest_forensic.tests.helpers import make_snapshot, screen, seed

CFG5 = load_check_config()["checks"]["J2-05"]
CFG6 = load_check_config()["checks"]["J2-06"]


# ---- J2-05 ratio breaks ----------------------------------------------------------------------------------------------

def test_change_and_severity_rules():
    assert change("pct", 0.20, 0.10) == 10.0                    # percentage points
    assert change("days", 130.0, 100.0) == 30.0                 # percent of last year's value
    assert change("days", 5.0, 0.0) is None
    assert severity_of(5.0, 5.0, 3.0) is None and severity_of(5.1, 5.0, 3.0) == "medium" and severity_of(-15.1, 5.0, 3.0) == "high"
    assert {CFG5[k]["source"] for k in ("pct_points_limit", "relative_limit_pct", "high_multiple")} == {"proposal"}


def _seed_margin(session, company, pat_prior, pat):
    snap = make_snapshot(session, company)
    seed(session, company, snap, "revenue_from_operations", {"FY2023": 1000, "FY2024": 1000, "FY2025": 1000})
    seed(session, company, snap, "profit_after_tax", {"FY2024": pat_prior, "FY2025": pat})
    return snap


def test_a_margin_move_beyond_the_limit_is_flagged_and_passes_the_guardrail(session, company):
    _seed_margin(session, company, 200, 100)                         # net margin 20% -> 10%: -10 percentage points
    res = run_j2_05(InputStore(session, company.company_id, "standalone"), ["FY2025"], CFG5)
    by = {o.figures["ratio"]: o for o in res.observations}
    assert by["pat_margin"].metric_value == -10.0 and by["pat_margin"].severity == "medium"
    assert all(validate_observation(session, o, company.company_id, "standalone") == [] for o in res.observations)
    object.__setattr__(by["pat_margin"], "metric_value", -1.0)
    assert any(g == "recalculation" for g, _ in validate_observation(session, by["pat_margin"], company.company_id, "standalone"))


def test_a_small_move_is_shown_but_not_flagged_and_missing_years_are_skipped(session, company):
    _seed_margin(session, company, 200, 180)                         # -2 percentage points
    res = run_j2_05(InputStore(session, company.company_id, "standalone"), ["FY2025", "FY2026"], CFG5)
    o = next(o for o in res.observations if o.figures["ratio"] == "pat_margin")
    assert o.severity is None and o.metric_value == -2.0
    assert any(s.fy == "FY2026" for s in res.skipped)


def test_without_limits_the_check_needs_a_definition(session, company):
    assert run_j2_05(InputStore(session, company.company_id, "standalone"), ["FY2025"], {"rule_id": "x"}).status == "NEEDS_DEFINITION"


def test_flag_is_created_in_a_screen_with_its_inputs(session, company, tmp_path):
    _seed_margin(session, company, 200, 100)
    run = screen(session, company, tmp_path, ["FY2025"])
    flags = session.execute(select(Flag).where(Flag.run_id == run.id, Flag.check_id == "J2-05")).scalars().all()
    assert [f.severity for f in flags] == ["medium"] and flags[0].citation["inputs"]


# ---- J2-06 related-party concentration ---------------------------------------------------------------------------------

PAGE = """Notes forming part of Standalone Financial Statements
(H crore)
Year ended March 31, 2026
Tata Sons
Private
Limited
Subsidiaries
Total
Revenue from operations
78
31,189
1,354
4,887
-
37,508
Interest income
-
3
83
Purchases of goods and services (including
reimbursements)
2
19,654
831
231
-
20,718
"""


def test_the_related_party_table_is_read_from_the_page_text():
    rows = {r["label_key"]: r for r in parse_page(PAGE)}
    assert rows["revenue_cr"]["total"] == 37508 and rows["revenue_cr"]["year"] == 2026
    assert rows["purchases_cr"]["total"] == 20718                       # a wrapped label is handled
    assert parse_page(PAGE.replace("Tata Sons", "Segment")) == []        # only tables headed by the holding company
    assert share_pct(37508, 220938 * 1e7) == round(37508 / 220938 * 100, 6)


def _save_rp(session, company, basis="standalone", rev=37508, pur=20718):
    save_snapshot(session, company.company_id, RawSourceResponse(
        provider=PROVIDER, endpoint=ENDPOINT, request_params={}, status_code=200, fetched_at=dt.datetime.now(dt.timezone.utc),
        payload={"document_version_id": 1, "file_name": "x.pdf", "file_sha256": "h", "report_fy": "FY2025", "basis": basis, "unit": "INR crore",
                 "years": {"FY2025": {"revenue_cr": rev, "purchases_cr": pur}}, "pages": {"FY2025": 311}}))
    session.flush()


def test_concentration_levels_use_the_proposal_limits_and_pass_the_guardrail(session, company):
    snap = make_snapshot(session, company)
    seed(session, company, snap, "revenue_from_operations", {"FY2025": 100e7})              # INR 100 crore
    seed(session, company, snap, "total_expenses", {"FY2025": 80e7})
    _save_rp(session, company, rev=60, pur=20)                                              # 60% of revenue, 25% of expenses
    res = run_j2_06(InputStore(session, company.company_id, "standalone"), ["FY2025"], CFG6)
    by = {o.figures["measure"]: o for o in res.observations}
    assert by["revenue"].severity == "high" and by["purchases"].severity is None             # exactly 25% is not above the limit
    assert all(validate_observation(session, o, company.company_id, "standalone") == [] for o in res.observations)
    object.__setattr__(by["revenue"], "metric_value", 10.0)
    assert any(g == "recalculation" for g, _ in validate_observation(session, by["revenue"], company.company_id, "standalone"))


def test_other_basis_and_missing_data_are_not_mixed_in(session, company):
    snap = make_snapshot(session, company)
    seed(session, company, snap, "revenue_from_operations", {"FY2025": 100e7}, basis="consolidated")
    seed(session, company, snap, "total_expenses", {"FY2025": 80e7}, basis="consolidated")
    _save_rp(session, company, basis="standalone", rev=60, pur=20)
    res = run_j2_06(InputStore(session, company.company_id, "consolidated"), ["FY2025"], CFG6)
    assert not res.observations and res.status == "NOT_ENOUGH_DATA"
