import datetime as dt

from sqlalchemy import select

from crest_forensic.connectors.base import RawSourceResponse
from crest_forensic.db.models import DataQualityEvent, Snapshot
from crest_forensic.ingestion.fetch_and_snapshot import compute_payload_hash, save_snapshot


def _response(payload=None, parse_error=None, raw_text=None, status_code=200):
    return RawSourceResponse(
        provider="rapidapi_moneycontrol",
        endpoint="/stocks/financials/income",
        request_params={"sc_id": "TCS", "type": "standalone"},
        status_code=status_code,
        payload=payload or {},
        fetched_at=dt.datetime.now(dt.timezone.utc),
        raw_text=raw_text,
        parse_error=parse_error,
    )


def test_fetching_twice_creates_two_snapshot_rows(session, company):
    save_snapshot(session, company.company_id, _response({"data": {"a": 1}}))
    save_snapshot(session, company.company_id, _response({"data": {"a": 1}}))
    session.commit()

    rows = session.execute(select(Snapshot).where(Snapshot.company_id == company.company_id)).scalars().all()
    assert len(rows) == 2
    assert rows[0].snapshot_id != rows[1].snapshot_id


def test_identical_payloads_give_identical_hash():
    payload = {"data": {"revenue": 100, "year": "FY2025"}}
    assert compute_payload_hash(payload) == compute_payload_hash(dict(payload))


def test_changed_payload_gives_different_hash():
    h1 = compute_payload_hash({"data": {"revenue": 100}})
    h2 = compute_payload_hash({"data": {"revenue": 101}})
    assert h1 != h2


def test_raw_payload_saved_even_when_parsing_fails(session, company):
    snapshot = save_snapshot(
        session,
        company.company_id,
        _response(parse_error="JSONDecodeError: bad token", raw_text="<html>not json</html>", status_code=502),
    )
    session.commit()

    assert snapshot.raw_payload["_raw_text"] == "<html>not json</html>"
    assert snapshot.raw_payload["_parse_error"].startswith("JSONDecodeError")

    events = session.execute(
        select(DataQualityEvent).where(DataQualityEvent.snapshot_id == snapshot.snapshot_id)
    ).scalars().all()
    assert len(events) == 1
    assert events[0].issue_type == "PARSE_ERROR"
    assert events[0].severity == "error"


def test_no_code_path_updates_a_snapshot(session, company):
    """Sanity check that Snapshot has no update helper — inserts only."""
    snapshot = save_snapshot(session, company.company_id, _response({"data": {"a": 1}}))
    session.commit()
    original_hash = snapshot.payload_hash

    # The only way to "change" a snapshot in this codebase is to insert a new one.
    save_snapshot(session, company.company_id, _response({"data": {"a": 2}}))
    session.commit()

    refreshed = session.get(Snapshot, snapshot.snapshot_id)
    assert refreshed.payload_hash == original_hash
