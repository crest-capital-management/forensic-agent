import datetime as dt

from sqlalchemy import select

from crest_forensic.db.models import DataQualityEvent, LineItem, Snapshot
from crest_forensic.ingestion.derive import METHOD_INDIRECT_V1, derive_cfo_indirect


def _snapshot(session, company):
    snap = Snapshot(
        company_id=company.company_id,
        source_provider="rapidapi_moneycontrol",
        source_endpoint="/stocks/financials/balance-sheet",
        request_params={},
        fetched_at=dt.datetime.now(dt.timezone.utc),
        raw_payload={},
        payload_hash="x",
        provisional=True,
    )
    session.add(snap)
    session.flush()
    return snap


def _add(session, company, snap, field, year, value, semantics="stock", basis="standalone"):
    session.add(
        LineItem(
            company_id=company.company_id,
            snapshot_id=snap.snapshot_id,
            standard_field=field,
            raw_value=str(value),
            normalized_value=value,
            unit="INR_absolute",
            currency="INR",
            financial_year=year,
            period_type="annual",
            basis=basis,
            semantics=semantics,
            statement_type="balance_sheet",
            source_field_name="test",
            mapping_version=1,
        )
    )


def _seed_two_years(session, company, snap, *, pat, dep, recv, inv, cl, basis="standalone"):
    """pat/dep/recv/inv/cl are each a (FY2025_value, FY2026_value) tuple."""
    for i, year in enumerate(("FY2025", "FY2026")):
        _add(session, company, snap, "profit_after_tax", year, pat[i], semantics="flow", basis=basis)
        _add(session, company, snap, "depreciation_amortisation", year, dep[i], semantics="flow", basis=basis)
        _add(session, company, snap, "trade_receivables", year, recv[i], basis=basis)
        _add(session, company, snap, "inventories", year, inv[i], basis=basis)
        _add(session, company, snap, "current_liabilities", year, cl[i], basis=basis)
    session.flush()


def test_derives_cfo_using_standard_indirect_formula(session, company):
    snap = _snapshot(session, company)
    _seed_two_years(
        session, company, snap,
        pat=(100.0, 120.0),
        dep=(10.0, 12.0),
        recv=(50.0, 70.0),   # +20 (uses cash)
        inv=(30.0, 25.0),    # -5 (releases cash)
        cl=(40.0, 55.0),     # +15 (uses less cash / releases cash)
    )

    created = derive_cfo_indirect(session, company.company_id, "standalone")

    # Only FY2026 is derivable (FY2025 has no prior year FY2024 in the data).
    assert len(created) == 1
    li = created[0]
    assert li.standard_field == "cash_flow_from_operations"
    assert li.financial_year == "FY2026"
    assert li.derivation_method == METHOD_INDIRECT_V1
    # PAT120 + Dep12 - ΔRecv(20) - ΔInv(-5) + ΔCL(15) = 120+12-20+5+15 = 132
    assert li.normalized_value == 132.0
    assert li.raw_value.startswith("derived=")


def test_derived_row_is_logged_never_silent(session, company):
    snap = _snapshot(session, company)
    _seed_two_years(
        session, company, snap,
        pat=(100.0, 120.0), dep=(10.0, 12.0),
        recv=(50.0, 70.0), inv=(30.0, 25.0), cl=(40.0, 55.0),
    )
    derive_cfo_indirect(session, company.company_id, "standalone")

    events = session.execute(
        select(DataQualityEvent).where(DataQualityEvent.company_id == company.company_id)
    ).scalars().all()
    assert any(e.issue_type == "DERIVED_VALUE" for e in events)


def test_missing_prior_year_input_is_skipped_and_logged(session, company):
    snap = _snapshot(session, company)
    # Only one year of data at all — no prior year exists for anything.
    _add(session, company, snap, "profit_after_tax", "FY2026", 120.0, semantics="flow")
    _add(session, company, snap, "depreciation_amortisation", "FY2026", 12.0, semantics="flow")
    _add(session, company, snap, "trade_receivables", "FY2026", 70.0)
    _add(session, company, snap, "inventories", "FY2026", 25.0)
    _add(session, company, snap, "current_liabilities", "FY2026", 55.0)
    session.flush()

    created = derive_cfo_indirect(session, company.company_id, "standalone")
    assert created == []

    events = session.execute(
        select(DataQualityEvent).where(DataQualityEvent.company_id == company.company_id)
    ).scalars().all()
    assert any(e.issue_type == "DERIVATION_SKIPPED" for e in events)


def test_missing_single_field_skips_only_that_year(session, company):
    snap = _snapshot(session, company)
    _seed_two_years(
        session, company, snap,
        pat=(100.0, 120.0), dep=(10.0, 12.0),
        recv=(50.0, 70.0), inv=(30.0, 25.0), cl=(40.0, 55.0),
    )
    # Delete FY2025's inventories row so FY2026's derivation (which needs
    # FY2025 as the prior year) can't be computed.
    row = session.execute(
        select(LineItem).where(
            LineItem.standard_field == "inventories", LineItem.financial_year == "FY2025"
        )
    ).scalar_one()
    session.delete(row)
    session.flush()

    created = derive_cfo_indirect(session, company.company_id, "standalone")
    assert created == []


def test_standalone_and_consolidated_derived_independently(session, company):
    snap = _snapshot(session, company)
    _seed_two_years(
        session, company, snap,
        pat=(100.0, 120.0), dep=(10.0, 12.0),
        recv=(50.0, 70.0), inv=(30.0, 25.0), cl=(40.0, 55.0),
        basis="standalone",
    )
    _seed_two_years(
        session, company, snap,
        pat=(200.0, 240.0), dep=(20.0, 24.0),
        recv=(100.0, 140.0), inv=(60.0, 50.0), cl=(80.0, 110.0),
        basis="consolidated",
    )

    standalone = derive_cfo_indirect(session, company.company_id, "standalone")
    consolidated = derive_cfo_indirect(session, company.company_id, "consolidated")

    assert standalone[0].normalized_value == 132.0
    assert consolidated[0].normalized_value == 264.0  # exactly double the standalone inputs
