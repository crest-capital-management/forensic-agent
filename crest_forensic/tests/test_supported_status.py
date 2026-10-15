import datetime as dt

from crest_forensic.db.models import LineItem, Snapshot
from crest_forensic.ingestion.supported_status import (
    INSUFFICIENT_DATA,
    SUPPORTED,
    SUPPORTED_WITH_LIMITATIONS,
    UNSUPPORTED_ENTITY_TYPE,
    compute_supported_status,
)

_KEYWORDS = ["bank", "nbfc", "insurance"]

_REQUIRED = [
    "revenue_from_operations",
    "profit_after_tax",
    "cash_flow_from_operations",
    "trade_receivables",
    "total_assets",
]


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


def _add_line_item(session, company, snapshot, field, year, value=100.0):
    li = LineItem(
        company_id=company.company_id,
        snapshot_id=snapshot.snapshot_id,
        standard_field=field,
        raw_value=str(value),
        normalized_value=value,
        unit="INR_absolute",
        currency="INR",
        financial_year=year,
        period_type="annual",
        basis="standalone",
        semantics="flow",
        statement_type="income",
        source_field_name="test",
        mapping_version=1,
    )
    session.add(li)


def test_bank_sector_is_unsupported_regardless_of_data(session, company):
    company.sector = "Private Sector Bank"
    status = compute_supported_status(session, company.company_id, company.sector, _KEYWORDS)
    assert status == UNSUPPORTED_ENTITY_TYPE


def test_two_years_of_data_is_insufficient(session, company):
    snap = _snapshot(session, company)
    for field in _REQUIRED:
        _add_line_item(session, company, snap, field, "FY2024")
        _add_line_item(session, company, snap, field, "FY2025")
    session.flush()

    status = compute_supported_status(session, company.company_id, "IT Services", _KEYWORDS)
    assert status == INSUFFICIENT_DATA


def test_three_years_but_missing_required_field_is_limited(session, company):
    snap = _snapshot(session, company)
    for field in _REQUIRED[:-1]:  # leave out total_assets
        for year in ("FY2023", "FY2024", "FY2025"):
            _add_line_item(session, company, snap, field, year)
    session.flush()

    status = compute_supported_status(session, company.company_id, "IT Services", _KEYWORDS)
    assert status == SUPPORTED_WITH_LIMITATIONS


def test_three_years_all_required_fields_is_supported(session, company):
    snap = _snapshot(session, company)
    for field in _REQUIRED:
        for year in ("FY2023", "FY2024", "FY2025"):
            _add_line_item(session, company, snap, field, year)
    session.flush()

    status = compute_supported_status(session, company.company_id, "IT Services", _KEYWORDS)
    assert status == SUPPORTED
