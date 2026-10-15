import datetime as dt
from pathlib import Path

import pytest

from crest_forensic.db.models import LineItem, Snapshot
from crest_forensic.ingestion.golden import (
    compare_to_golden, evaluate_golden, format_mismatch_table, load_golden,
)

_REAL_GOLDEN_PATH = Path(__file__).parent / "golden" / "tcs_golden.yaml"


def _snapshot(session, company):
    snap = Snapshot(
        company_id=company.company_id,
        source_provider="rapidapi_moneycontrol",
        source_endpoint="/stocks/financials/income",
        request_params={},
        fetched_at=dt.datetime.now(dt.timezone.utc),
        raw_payload={},
        payload_hash="x",
        provisional=True,
    )
    session.add(snap)
    session.flush()
    return snap


def _add(session, company, snap, field, year, normalized_value, basis="standalone"):
    session.add(
        LineItem(
            company_id=company.company_id,
            snapshot_id=snap.snapshot_id,
            standard_field=field,
            raw_value=str(normalized_value),
            normalized_value=normalized_value,
            unit="INR_absolute",
            currency="INR",
            financial_year=year,
            period_type="annual",
            basis=basis,
            semantics="flow",
            statement_type="income",
            source_field_name="test",
            mapping_version=1,
        )
    )


def test_mechanism_reports_every_mismatch_not_just_the_first(session, company):
    """Synthetic fixture data only — NOT real TCS figures. Exercises the
    comparison/reporting mechanism itself."""
    snap = _snapshot(session, company)
    _add(session, company, snap, "revenue_from_operations", "FY2025", 1000 * 1e7)  # matches
    _add(session, company, snap, "profit_after_tax", "FY2025", 50 * 1e7)  # will mismatch
    session.flush()

    golden = {
        "years": {
            "FY2025": {
                "revenue_from_operations": {"value": 1000, "unit": "INR crore", "page": 1},
                "profit_after_tax": {"value": 999, "unit": "INR crore", "page": 2},  # deliberately wrong
                "cash_flow_from_operations": {"value": 10, "unit": "INR crore", "page": 3},  # missing entirely
            }
        }
    }

    mismatches = compare_to_golden(session, company.company_id, golden, basis="standalone")

    fields_with_issues = {m["field"] for m in mismatches}
    assert "profit_after_tax" in fields_with_issues
    assert "cash_flow_from_operations" in fields_with_issues
    assert "revenue_from_operations" not in fields_with_issues
    # sanity: the report renders as a readable table, not just a bool
    table = format_mismatch_table(mismatches)
    assert "profit_after_tax" in table


def test_matching_values_produce_no_mismatches(session, company):
    snap = _snapshot(session, company)
    _add(session, company, snap, "revenue_from_operations", "FY2025", 1000 * 1e7)
    session.flush()

    golden = {"years": {"FY2025": {"revenue_from_operations": {"value": 1000, "unit": "INR crore"}}}}
    assert compare_to_golden(session, company.company_id, golden) == []


# --- per-provider comparison ---------------------------------------------------

def _provider_snapshot(session, company, provider):
    snap = Snapshot(
        company_id=company.company_id, source_provider=provider, source_endpoint="x", request_params={},
        fetched_at=dt.datetime.now(dt.timezone.utc), raw_payload={}, payload_hash=provider, provisional=True)
    session.add(snap)
    session.flush()
    return snap


def test_comparison_is_per_provider_so_it_says_which_source_is_right(session, company):
    good = _provider_snapshot(session, company, "yfinance")
    bad = _provider_snapshot(session, company, "rapidapi_moneycontrol")
    _add(session, company, good, "total_assets", "FY2026", 182372 * 1e7, basis="consolidated")
    _add(session, company, bad, "total_assets", "FY2026", 108478 * 1e7, basis="consolidated")
    session.flush()

    golden = {"unit": "INR crore", "statements": {"consolidated": {"FY2026": {"total_assets": {"value": 182372}}}}}
    by_provider = {p: evaluate_golden(session, company.company_id, golden, "consolidated", p)[0]["status"]
                   for p in ("yfinance", "rapidapi_moneycontrol")}
    assert by_provider == {"yfinance": "MATCH", "rapidapi_moneycontrol": "MISMATCH"}


def test_a_source_with_no_value_is_reported_missing_not_mismatched(session, company):
    golden = {"unit": "INR crore", "statements": {"standalone": {"FY2026": {"total_assets": {"value": 149268}}}}}
    (row,) = evaluate_golden(session, company.company_id, golden, "standalone", "yfinance")
    assert row["status"] == "MISSING"


def test_derived_estimates_are_never_compared_as_if_they_were_sourced(session, company):
    snap = _provider_snapshot(session, company, "rapidapi_moneycontrol")
    session.add(LineItem(
        company_id=company.company_id, snapshot_id=snap.snapshot_id, standard_field="cash_flow_from_operations",
        raw_value="x", normalized_value=1.0, unit="INR_absolute", currency="INR", financial_year="FY2026",
        period_type="annual", basis="standalone", semantics="flow", statement_type="cash_flow",
        source_field_name="d", mapping_version=1, derivation_method="indirect_method_v1"))
    session.flush()
    golden = {"unit": "INR crore", "statements": {"standalone": {"FY2026": {"cash_flow_from_operations": {"value": 45597}}}}}
    (row,) = evaluate_golden(session, company.company_id, golden, "standalone")
    assert row["status"] == "MISSING"


# --- the answer key itself (guards against transcription errors) ------------------

@pytest.fixture(scope="module")
def tcs_golden():
    return load_golden(_REAL_GOLDEN_PATH)


def _entries(golden):
    for basis, years in golden["statements"].items():
        for year, fields in years.items():
            yield basis, year, {f: e["value"] for f, e in fields.items()}


def test_golden_profit_before_tax_less_tax_equals_profit(tcs_golden):
    """Printed identity: PBT - total tax expense = profit for the year."""
    checked = 0
    for basis, year, v in _entries(tcs_golden):
        assert v["profit_before_tax"] - v["tax_expense"] == v["profit_after_tax"], (basis, year)
        checked += 1
    assert checked == 4  # consolidated + standalone, FY2026 + FY2025


def test_golden_balance_sheet_sanity(tcs_golden):
    for basis, year, v in _entries(tcs_golden):
        assert v["trade_receivables"] > v["trade_receivables_billed"] > 0, (basis, year)
        assert v["inventories"] < v["current_assets"] < v["total_assets"], (basis, year)
        assert v["current_liabilities"] < v["total_assets"] - v["total_equity"] + 1, (basis, year)


def test_golden_covers_both_bases_and_years_with_the_same_fields(tcs_golden):
    shapes = {(b, y): set(f) for b, y, f in ((b, y, v) for b, y, v in _entries(tcs_golden))}
    assert {b for b, _ in shapes} == {"consolidated", "standalone"}
    assert {y for _, y in shapes} == {"FY2026", "FY2025"}
    assert len({frozenset(s) for s in shapes.values()}) == 1


def test_golden_pages_agree_with_the_users_own_notes(tcs_golden):
    """Notes.xlsx: consolidated revenue p168, receivables p167, cash flow p173 (FY2025-26 report)."""
    pages = tcs_golden["pages"]
    assert pages["consolidated_profit_and_loss"]["pdf"] == 168
    assert pages["consolidated_balance_sheet"]["pdf"] == 167
    assert pages["consolidated_cash_flow"]["pdf"] == 173
