import datetime as dt

from crest_forensic.checks.filing_dates import days_late, due_days, run_j1_13
from crest_forensic.db.models import Company
from crest_forensic.guardrails.validate import validate_observation
from crest_forensic.ingestion.exchange_files import NSE_RESULTS
from crest_forensic.ingestion.fetch_and_snapshot import save_snapshot
from crest_forensic.connectors.base import RawSourceResponse
from crest_forensic.screen import load_check_config

CFG = load_check_config()["checks"]["J1-13"]


def _row(period_end, received, basis="standalone", **extra):
    return {"period_end": period_end, "basis": basis, "received_at": received, "xbrl_url": "x", **extra}


def _save(session, company_id, rows):
    resp = RawSourceResponse(provider=NSE_RESULTS, endpoint="file:t.csv", request_params={}, status_code=200,
                             payload={"rows": rows}, fetched_at=dt.datetime.now(dt.timezone.utc))
    return save_snapshot(session, company_id, resp)


def test_due_days_and_days_late():
    assert due_days(dt.date(2026, 6, 30), CFG) == 45 and due_days(dt.date(2026, 3, 31), CFG) == 60
    # 45 days after 30 Sep is 14 Nov; filed 15 Nov at 00:30 India time = one day late
    assert days_late(dt.date(2026, 9, 30), "2026-11-15T00:30:00+05:30", 45) == 1
    assert days_late(dt.date(2026, 9, 30), "2026-10-08T22:07:30+05:30", 45) == -37


def test_on_time_filing_is_shown_without_a_flag(session):
    co = Company(name="T")
    session.add(co)
    session.flush()
    _save(session, co.company_id, [_row("2026-09-30", "2026-10-08T22:07:30+05:30")])
    res = run_j1_13(session, co.company_id, "standalone", ["FY2027"], CFG)
    (o,) = res.observations
    assert o.severity is None and o.metric_value == -37.0


def test_late_filing_gets_proposal_severity_and_passes_the_guardrail(session):
    co = Company(name="T")
    session.add(co)
    session.flush()
    _save(session, co.company_id, [_row("2026-09-30", "2026-11-20T10:00:00+05:30"),
                                   _row("2026-06-30", "2026-10-30T10:00:00+05:30")])
    res = run_j1_13(session, co.company_id, "standalone", ["FY2027"], CFG)
    sev = {o.figures["period_end"]: o.severity for o in res.observations}
    assert sev == {"2026-06-30": "high", "2026-09-30": "medium"}   # 77 and 6 days after due
    assert all(validate_observation(session, o, co.company_id, "standalone") == [] for o in res.observations)


def test_tampered_figure_is_caught_and_revised_rows_and_other_basis_are_ignored(session):
    co = Company(name="T")
    session.add(co)
    session.flush()
    _save(session, co.company_id, [_row("2026-09-30", "2026-11-20T10:00:00+05:30"),
                                   _row("2026-09-30", "2026-12-30T10:00:00+05:30", submission_type="Revised"),
                                   _row("2026-09-30", "2026-10-01T10:00:00+05:30", basis="consolidated")])
    (o,) = run_j1_13(session, co.company_id, "standalone", ["FY2027"], CFG).observations
    assert o.figures["received_at"].startswith("2026-11-20")
    object.__setattr__(o, "metric_value", 1.0)
    assert any(g == "recalculation" for g, _ in validate_observation(session, o, co.company_id, "standalone"))


def test_config_without_due_days_needs_definition(session):
    co = Company(name="T")
    session.add(co)
    session.flush()
    res = run_j1_13(session, co.company_id, "standalone", ["FY2027"], {"rule_id": "SEV-J1-13", "thresholds": {}})
    assert res.status == "NEEDS_DEFINITION" and not res.observations
