import datetime as dt

from sqlalchemy import select

from crest_forensic.db.models import DataQualityEvent, LineItem, Snapshot
from crest_forensic.ingestion.mapping import FieldMapping, FieldMappingConfig
from crest_forensic.ingestion.normalize import (
    financial_year_from_year_month,
    normalize_snapshot,
    parse_numeric,
)


def _make_snapshot(session, company, payload) -> Snapshot:
    snap = Snapshot(
        company_id=company.company_id,
        source_provider="rapidapi_moneycontrol",
        source_endpoint="/stocks/financials/balance-sheet",
        request_params={"sc_id": "TESTCO", "type": "standalone"},
        fetched_at=dt.datetime.now(dt.timezone.utc),
        raw_payload=payload,
        payload_hash="deadbeef",
        provisional=True,
    )
    session.add(snap)
    session.flush()
    return snap


def _period(year, month, items: dict[str, str]) -> dict:
    return {
        "type": "MAN",
        "year": year,
        "month": month,
        "item": [{"name": k, "value": v, "head_flag": 0} for k, v in items.items()],
    }


def _payload(*periods) -> dict:
    return {"status": "success", "meta": {}, "data": list(periods)}


# --- parse_numeric / financial_year_from_year_month unit tests -------------

def test_parse_numeric_handles_commas_dashes_and_types():
    assert parse_numeric("1,234.50") == 1234.5
    assert parse_numeric(1234) == 1234.0
    assert parse_numeric("--") is None  # this provider's "not disclosed" marker
    assert parse_numeric("") is None
    assert parse_numeric(None) is None


def test_financial_year_from_year_month_confident_patterns():
    # March year-end => same-numbered FY (FY2026 ends March 2026)
    assert financial_year_from_year_month("2026", "March") == ("FY2026", True)
    # A quarter ending in June belongs to the FY that STARTS that April
    assert financial_year_from_year_month("2026", "June") == ("FY2027", True)
    assert financial_year_from_year_month("2025", "December") == ("FY2026", True)


def test_financial_year_from_year_month_unrecognized_is_not_confident():
    label, confident = financial_year_from_year_month("2025", "Blorp")
    assert confident is False
    assert label == "2025-Blorp"  # raw, not guessed


# --- normalize_snapshot: real period/item shape -----------------------------

def test_missing_field_logs_event_never_defaults(session, company):
    payload = _payload(_period("2026", "March", {"Net Sales": "1000"}))
    snapshot = _make_snapshot(session, company, payload)
    mapping = FieldMappingConfig(
        mapping_version=2,
        fields=[
            FieldMapping(
                standard_field="profit_after_tax",
                statement_type="income",
                semantics="flow",
                source_endpoint="balance_sheet",
                item_name_contains="Reported Net Profit",  # not present in payload
                unit_multiplier=1.0,
            )
        ],
    )
    created = normalize_snapshot(session, snapshot, mapping, "standalone", "balance_sheet")

    assert created == []
    events = session.execute(
        select(DataQualityEvent).where(DataQualityEvent.snapshot_id == snapshot.snapshot_id)
    ).scalars().all()
    assert any(e.issue_type == "MISSING_FIELD" for e in events)


def test_unit_conversion_applies_multiplier(session, company):
    payload = _payload(
        _period("2026", "March", {"Net Sales": "1000"}),
        _period("2025", "March", {"Net Sales": "900"}),
    )
    snapshot = _make_snapshot(session, company, payload)
    mapping = FieldMappingConfig(
        mapping_version=2,
        fields=[
            FieldMapping(
                standard_field="revenue_from_operations",
                statement_type="income",
                semantics="flow",
                source_endpoint="balance_sheet",
                item_name_contains="Net Sales",
                unit_multiplier=1e7,  # 1 crore = 1e7
            )
        ],
    )
    created = normalize_snapshot(session, snapshot, mapping, "standalone", "balance_sheet")

    by_year = {li.financial_year: li for li in created}
    assert by_year["FY2026"].normalized_value == 1000 * 1e7
    assert by_year["FY2026"].unit == "INR_absolute"
    assert by_year["FY2025"].normalized_value == 900 * 1e7


def test_unconfirmed_unit_multiplier_leaves_normalized_value_unset_and_logs_event(session, company):
    payload = _payload(_period("2026", "March", {"Net Sales": "1000"}))
    snapshot = _make_snapshot(session, company, payload)
    mapping = FieldMappingConfig(
        mapping_version=2,
        fields=[
            FieldMapping(
                standard_field="revenue_from_operations",
                statement_type="income",
                semantics="flow",
                source_endpoint="balance_sheet",
                item_name_contains="Net Sales",
                unit_multiplier=None,  # unit not confirmed yet
            )
        ],
    )
    created = normalize_snapshot(session, snapshot, mapping, "standalone", "balance_sheet")

    assert created[0].normalized_value is None
    assert created[0].raw_value == "1000"
    events = session.execute(
        select(DataQualityEvent).where(DataQualityEvent.snapshot_id == snapshot.snapshot_id)
    ).scalars().all()
    assert any(e.issue_type == "UNIT_MISMATCH" for e in events)


def test_negative_revenue_logs_event(session, company):
    payload = _payload(_period("2026", "March", {"Net Sales": "-50"}))
    snapshot = _make_snapshot(session, company, payload)
    mapping = FieldMappingConfig(
        mapping_version=2,
        fields=[
            FieldMapping(
                standard_field="revenue_from_operations",
                statement_type="income",
                semantics="flow",
                source_endpoint="balance_sheet",
                item_name_contains="Net Sales",
                unit_multiplier=1.0,
            )
        ],
    )
    normalize_snapshot(session, snapshot, mapping, "standalone", "balance_sheet")
    events = session.execute(
        select(DataQualityEvent).where(DataQualityEvent.snapshot_id == snapshot.snapshot_id)
    ).scalars().all()
    assert any(e.issue_type == "NEGATIVE_REVENUE" for e in events)


def test_not_disclosed_marker_is_treated_as_missing_not_zero(session, company):
    payload = _payload(_period("2026", "March", {"Net Sales": "--"}))
    snapshot = _make_snapshot(session, company, payload)
    mapping = FieldMappingConfig(
        mapping_version=2,
        fields=[
            FieldMapping(
                standard_field="revenue_from_operations",
                statement_type="income",
                semantics="flow",
                source_endpoint="balance_sheet",
                item_name_contains="Net Sales",
                unit_multiplier=1.0,
            )
        ],
    )
    created = normalize_snapshot(session, snapshot, mapping, "standalone", "balance_sheet")
    assert created[0].normalized_value is None
    events = session.execute(
        select(DataQualityEvent).where(DataQualityEvent.snapshot_id == snapshot.snapshot_id)
    ).scalars().all()
    assert any(e.issue_type == "MISSING_FIELD" and "not numeric" in e.note for e in events)


def test_standalone_and_consolidated_never_merged(session, company):
    mapping = FieldMappingConfig(
        mapping_version=2,
        fields=[
            FieldMapping(
                standard_field="revenue_from_operations",
                statement_type="income",
                semantics="flow",
                source_endpoint="balance_sheet",
                item_name_contains="Net Sales",
                unit_multiplier=1.0,
            )
        ],
    )
    standalone_snap = _make_snapshot(session, company, _payload(_period("2026", "March", {"Net Sales": "1000"})))
    consolidated_snap = _make_snapshot(session, company, _payload(_period("2026", "March", {"Net Sales": "1500"})))

    normalize_snapshot(session, standalone_snap, mapping, "standalone", "balance_sheet")
    normalize_snapshot(session, consolidated_snap, mapping, "consolidated", "balance_sheet")
    session.flush()

    rows = session.execute(
        select(LineItem).where(LineItem.company_id == company.company_id)
    ).scalars().all()
    by_basis = {r.basis: r.normalized_value for r in rows}
    assert by_basis["standalone"] == 1000.0
    assert by_basis["consolidated"] == 1500.0


def test_unrecognized_basis_is_logged_not_guessed(session, company):
    payload = _payload(_period("2026", "March", {"Net Sales": "1000"}))
    snapshot = _make_snapshot(session, company, payload)
    mapping = FieldMappingConfig(
        mapping_version=2,
        fields=[
            FieldMapping(
                standard_field="revenue_from_operations",
                statement_type="income",
                semantics="flow",
                source_endpoint="balance_sheet",
                item_name_contains="Net Sales",
                unit_multiplier=1.0,
            )
        ],
    )
    created = normalize_snapshot(session, snapshot, mapping, "weird_basis", "balance_sheet")
    assert created[0].basis == "UNKNOWN"
    events = session.execute(
        select(DataQualityEvent).where(DataQualityEvent.snapshot_id == snapshot.snapshot_id)
    ).scalars().all()
    assert any(e.issue_type == "BASIS_UNKNOWN" for e in events)


def test_unmapped_field_logs_field_not_available(session, company):
    payload = _payload(_period("2026", "March", {"Net Sales": "1000"}))
    snapshot = _make_snapshot(session, company, payload)
    mapping = FieldMappingConfig(
        mapping_version=2,
        fields=[
            FieldMapping(
                standard_field="auditor_fees",
                statement_type="notes",
                semantics="flow",
                source_endpoint="balance_sheet",
                item_name_contains=None,  # not yet / not available
            )
        ],
    )
    created = normalize_snapshot(session, snapshot, mapping, "standalone", "balance_sheet")
    assert created == []
    events = session.execute(
        select(DataQualityEvent).where(DataQualityEvent.snapshot_id == snapshot.snapshot_id)
    ).scalars().all()
    assert any(e.issue_type == "FIELD_NOT_AVAILABLE_FROM_SOURCE" for e in events)


def test_mapping_entries_for_other_endpoints_are_ignored(session, company):
    """A field mapped only for source_endpoint='income' must not fire when
    normalizing a 'balance_sheet' snapshot, and vice versa."""
    payload = _payload(_period("2026", "March", {"Net Sales": "1000"}))
    snapshot = _make_snapshot(session, company, payload)
    mapping = FieldMappingConfig(
        mapping_version=2,
        fields=[
            FieldMapping(
                standard_field="revenue_from_operations",
                statement_type="income",
                semantics="flow",
                source_endpoint="income",  # different endpoint than what we normalize below
                item_name_contains="Net Sales/Income from operations",
                unit_multiplier=1.0,
            )
        ],
    )
    created = normalize_snapshot(session, snapshot, mapping, "standalone", "balance_sheet")
    assert created == []


def test_mapping_limited_to_standalone_is_skipped_for_consolidated(session, company):
    payload = _payload(_period("2026", "March", {"Reported Net Profit": "1000"}))
    mapping = FieldMappingConfig(
        mapping_version=2,
        fields=[FieldMapping(
            standard_field="profit_after_tax", statement_type="income", semantics="flow",
            source_endpoint="cash_flow", item_name_contains="Reported Net Profit",
            unit_multiplier=1.0, bases=["standalone"],
        )],
    )
    standalone = normalize_snapshot(session, _make_snapshot(session, company, payload), mapping, "standalone", "cash_flow")
    consolidated = normalize_snapshot(session, _make_snapshot(session, company, payload), mapping, "consolidated", "cash_flow")
    assert len(standalone) == 1
    assert consolidated == []
