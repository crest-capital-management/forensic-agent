import datetime as dt

import pandas as pd
from sqlalchemy import select

from crest_forensic.connectors.yfinance_connector import frame_to_payload
from crest_forensic.db.models import DataQualityEvent, LineItem, Snapshot
from crest_forensic.ingestion.yahoo import infer_basis, load_yahoo_mapping, normalize_yahoo_batch


def _snap(session, company, provider, endpoint, payload=None):
    snap = Snapshot(
        company_id=company.company_id,
        source_provider=provider,
        source_endpoint=endpoint,
        request_params={},
        fetched_at=dt.datetime.now(dt.timezone.utc),
        raw_payload=payload or {},
        payload_hash="x",
        provisional=True,
    )
    session.add(snap)
    session.flush()
    return snap


def _seed_moneycontrol_revenue(session, company, standalone, consolidated):
    """standalone/consolidated: {fy: absolute INR}"""
    snap = _snap(session, company, "rapidapi_moneycontrol", "/stocks/financials/cash-flow")
    for basis, values in (("standalone", standalone), ("consolidated", consolidated)):
        for fy, v in values.items():
            session.add(LineItem(
                company_id=company.company_id, snapshot_id=snap.snapshot_id,
                standard_field="revenue_from_operations", raw_value=str(v), normalized_value=v,
                unit="INR_absolute", currency="INR", financial_year=fy, period_type="annual",
                basis=basis, semantics="flow", statement_type="income",
                source_field_name="t", mapping_version=1,
            ))
    session.flush()


def _yahoo_payload(statement, periods, currency="INR"):
    """periods: {(year, month): {line name: value}}"""
    return {
        "status": "success",
        "meta": {"source": "yfinance", "currency": currency, "statement": statement},
        "data": [
            {"type": "YF", "year": y, "month": m,
             "item": [{"name": n, "value": v, "head_flag": 0} for n, v in items.items()]}
            for (y, m), items in periods.items()
        ],
    }


STANDALONE = {"FY2025": 214_853e7, "FY2026": 220_938e7}
CONSOLIDATED = {"FY2025": 255_324e7, "FY2026": 267_021e7}
YAHOO_REVENUE = {("2025", "March"): {"Total Revenue": 255_324e7}, ("2026", "March"): {"Total Revenue": 267_021e7}}


def test_frame_to_payload_keeps_numbers_and_marks_nan_as_not_disclosed():
    frame = pd.DataFrame(
        {pd.Timestamp("2026-03-31"): [520.0, float("nan")], pd.Timestamp("2025-03-31"): [489.0, 5.0]},
        index=["Operating Cash Flow", "Free Cash Flow"],
    )
    payload = frame_to_payload(frame, "TCS.NS", "cash_flow", "INR")

    assert payload["meta"]["currency"] == "INR"
    assert payload["meta"]["basis"] == "not stated by source"
    first = payload["data"][0]
    assert (first["year"], first["month"]) == ("2026", "March")
    values = {i["name"]: i["value"] for i in first["item"]}
    assert values["Operating Cash Flow"] == 520.0
    assert values["Free Cash Flow"] == "--"


def test_basis_inferred_as_consolidated_when_revenue_matches_consolidated_only(session, company):
    _seed_moneycontrol_revenue(session, company, STANDALONE, CONSOLIDATED)
    income = _snap(session, company, "yfinance", "yfinance:income", _yahoo_payload("income", YAHOO_REVENUE))
    basis, _ = infer_basis(session, company.company_id, income)
    assert basis == "consolidated"


def test_basis_unknown_when_revenue_matches_neither(session, company):
    _seed_moneycontrol_revenue(session, company, STANDALONE, CONSOLIDATED)
    off = {("2025", "March"): {"Total Revenue": 1.0e12}, ("2026", "March"): {"Total Revenue": 1.1e12}}
    income = _snap(session, company, "yfinance", "yfinance:income", _yahoo_payload("income", off))
    basis, _ = infer_basis(session, company.company_id, income)
    assert basis == "UNKNOWN"


def test_basis_unknown_with_too_little_overlap_to_be_sure(session, company):
    _seed_moneycontrol_revenue(session, company, {"FY2026": 220_938e7}, {"FY2026": 267_021e7})
    one_year = {("2026", "March"): {"Total Revenue": 267_021e7}}
    income = _snap(session, company, "yfinance", "yfinance:income", _yahoo_payload("income", one_year))
    basis, _ = infer_basis(session, company.company_id, income)
    assert basis == "UNKNOWN"


def test_normalize_batch_stores_real_cfo_with_inferred_basis_and_no_unit_rescale(session, company):
    _seed_moneycontrol_revenue(session, company, STANDALONE, CONSOLIDATED)
    income = _snap(session, company, "yfinance", "yfinance:income", _yahoo_payload("income", YAHOO_REVENUE))
    cashflow = _snap(session, company, "yfinance", "yfinance:cash_flow", _yahoo_payload(
        "cash_flow", {("2026", "March"): {"Operating Cash Flow": 520_940e7}}))

    basis, created = normalize_yahoo_batch(session, company.company_id, [income, cashflow], load_yahoo_mapping())

    assert basis == "consolidated"
    cfo = next(li for li in created if li.standard_field == "cash_flow_from_operations")
    assert cfo.financial_year == "FY2026"
    assert cfo.basis == "consolidated"
    assert cfo.normalized_value == 520_940e7  # Yahoo is already absolute INR
    assert cfo.derivation_method is None  # sourced, not derived


def test_non_inr_snapshot_is_not_normalized_and_is_logged(session, company):
    _seed_moneycontrol_revenue(session, company, STANDALONE, CONSOLIDATED)
    usd = _snap(session, company, "yfinance", "yfinance:cash_flow", _yahoo_payload(
        "cash_flow", {("2026", "March"): {"Operating Cash Flow": 62.0}}, currency="USD"))

    _, created = normalize_yahoo_batch(session, company.company_id, [usd], load_yahoo_mapping())

    assert created == []
    events = session.execute(select(DataQualityEvent).where(
        DataQualityEvent.snapshot_id == usd.snapshot_id)).scalars().all()
    assert any(e.issue_type == "UNIT_MISMATCH" for e in events)


def test_unknown_basis_is_stored_as_unknown_never_guessed(session, company):
    # No MoneyControl data at all to compare against.
    cashflow = _snap(session, company, "yfinance", "yfinance:cash_flow", _yahoo_payload(
        "cash_flow", {("2026", "March"): {"Operating Cash Flow": 520_940e7}}))

    basis, created = normalize_yahoo_batch(session, company.company_id, [cashflow], load_yahoo_mapping())

    assert basis == "UNKNOWN"
    assert created[0].basis == "UNKNOWN"
