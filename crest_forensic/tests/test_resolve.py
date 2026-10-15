import datetime as dt

from sqlalchemy import select

from crest_forensic.db.models import DataQualityEvent, LineItem, Snapshot
from crest_forensic.ingestion.derive import derive_cfo_indirect
from crest_forensic.ingestion.resolve import (
    AGREE,
    CONFLICT,
    DERIVED_ESTIMATE,
    NO_DATA,
    SINGLE_SOURCE,
    detect_source_conflicts,
    resolve_value,
)

POLICY = {"version": 1, "provider_order": ["rapidapi_moneycontrol", "yfinance"], "conflict_tolerance_pct": 0.5}


def _snap(session, company, provider):
    snap = Snapshot(
        company_id=company.company_id, source_provider=provider, source_endpoint="x",
        request_params={}, fetched_at=dt.datetime.now(dt.timezone.utc),
        raw_payload={}, payload_hash="x", provisional=True,
    )
    session.add(snap)
    session.flush()
    return snap


def _item(session, company, snap, field, fy, value, basis="consolidated", derivation=None):
    session.add(LineItem(
        company_id=company.company_id, snapshot_id=snap.snapshot_id, standard_field=field,
        raw_value=str(value), normalized_value=value, unit="INR_absolute", currency="INR",
        financial_year=fy, period_type="annual", basis=basis, semantics="flow",
        statement_type="income", source_field_name="t", mapping_version=1,
        derivation_method=derivation,
    ))
    session.flush()


def test_no_data(session, company):
    assert resolve_value(session, company.company_id, "total_assets", "FY2026", "consolidated", POLICY).status == NO_DATA


def test_single_source_is_used(session, company):
    s = _snap(session, company, "yfinance")
    _item(session, company, s, "cash_flow_from_operations", "FY2026", 520.0)
    r = resolve_value(session, company.company_id, "cash_flow_from_operations", "FY2026", "consolidated", POLICY)
    assert (r.status, r.value, r.provider) == (SINGLE_SOURCE, 520.0, "yfinance")


def test_sourced_value_beats_derived_estimate(session, company):
    mc = _snap(session, company, "rapidapi_moneycontrol")
    yf = _snap(session, company, "yfinance")
    _item(session, company, mc, "cash_flow_from_operations", "FY2026", 561.0, derivation="indirect_method_v1")
    _item(session, company, yf, "cash_flow_from_operations", "FY2026", 520.0)
    r = resolve_value(session, company.company_id, "cash_flow_from_operations", "FY2026", "consolidated", POLICY)
    assert (r.status, r.value) == (SINGLE_SOURCE, 520.0)


def test_derived_used_only_when_nothing_sourced(session, company):
    mc = _snap(session, company, "rapidapi_moneycontrol")
    _item(session, company, mc, "cash_flow_from_operations", "FY2026", 561.0, derivation="indirect_method_v1")
    r = resolve_value(session, company.company_id, "cash_flow_from_operations", "FY2026", "consolidated", POLICY)
    assert (r.status, r.value) == (DERIVED_ESTIMATE, 561.0)


def test_sources_within_tolerance_agree_and_use_precedence_order(session, company):
    mc = _snap(session, company, "rapidapi_moneycontrol")
    yf = _snap(session, company, "yfinance")
    _item(session, company, yf, "total_assets", "FY2026", 1000.0)
    _item(session, company, mc, "total_assets", "FY2026", 1002.0)  # 0.2% apart
    r = resolve_value(session, company.company_id, "total_assets", "FY2026", "consolidated", POLICY)
    assert (r.status, r.provider, r.value) == (AGREE, "rapidapi_moneycontrol", 1002.0)


def test_sources_beyond_tolerance_conflict_and_no_value_is_picked(session, company):
    mc = _snap(session, company, "rapidapi_moneycontrol")
    yf = _snap(session, company, "yfinance")
    _item(session, company, mc, "trade_receivables", "FY2026", 677.0)
    _item(session, company, yf, "trade_receivables", "FY2026", 590.0)
    r = resolve_value(session, company.company_id, "trade_receivables", "FY2026", "consolidated", POLICY)
    assert r.status == CONFLICT
    assert r.value is None
    assert r.candidates == {"rapidapi_moneycontrol": 677.0, "yfinance": 590.0}  # both preserved


def test_detect_conflicts_logs_event_and_is_idempotent(session, company):
    mc = _snap(session, company, "rapidapi_moneycontrol")
    yf = _snap(session, company, "yfinance")
    _item(session, company, mc, "trade_receivables", "FY2026", 677.0)
    _item(session, company, yf, "trade_receivables", "FY2026", 590.0)
    _item(session, company, mc, "total_assets", "FY2026", 1000.0)
    _item(session, company, yf, "total_assets", "FY2026", 1000.0)  # agrees -> no conflict

    for _ in range(2):  # running twice must not duplicate events
        conflicts = detect_source_conflicts(session, company.company_id, POLICY)
        session.flush()

    assert [c["field"] for c in conflicts] == ["trade_receivables"]
    events = session.execute(select(DataQualityEvent).where(
        DataQualityEvent.issue_type == "SOURCE_CONFLICT")).scalars().all()
    assert len(events) == 1


def test_derivation_ignores_other_providers_rows(session, company):
    """A Yahoo row for the same field/year must never leak into the MoneyControl-based estimate."""
    mc = _snap(session, company, "rapidapi_moneycontrol")
    yf = _snap(session, company, "yfinance")
    for fy, pat, dep, recv, inv, cl in (("FY2025", 100, 10, 50, 30, 40), ("FY2026", 120, 12, 70, 25, 55)):
        for f, v in (("profit_after_tax", pat), ("depreciation_amortisation", dep),
                     ("trade_receivables", recv), ("inventories", inv), ("current_liabilities", cl)):
            _item(session, company, mc, f, fy, float(v))
    _item(session, company, yf, "profit_after_tax", "FY2026", 999999.0)  # poison value

    created = derive_cfo_indirect(session, company.company_id, "consolidated")
    assert created[0].normalized_value == 132.0
