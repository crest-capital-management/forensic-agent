import datetime as dt

from crest_forensic.checks.base import InputStore
from crest_forensic.checks.shareholding import prior_quarter_end, run_j2_01, step_points
from crest_forensic.db.models import Company, Shareholding, Snapshot
from crest_forensic.guardrails.validate import validate_observation
from crest_forensic.screen import load_check_config

CFG = load_check_config()["checks"]["J2-01"]


def _setup(session, promoter_by_quarter):
    co = Company(name="T")
    session.add(co)
    session.flush()
    snap = Snapshot(company_id=co.company_id, source_provider="x", source_endpoint="x", request_params={},
                    raw_payload={}, payload_hash="h")
    session.add(snap)
    session.flush()
    for q, pct in promoter_by_quarter.items():
        session.add(Shareholding(company_id=co.company_id, snapshot_id=snap.snapshot_id, quarter=q, promoter_pct=pct))
    session.flush()
    return co


def test_config_limit_comes_from_the_spec():
    assert CFG["thresholds"]["medium"] == {"value": 2.0, "source": "spec"}


def test_prior_quarter_and_step():
    assert prior_quarter_end(dt.date(2026, 3, 31)) == dt.date(2025, 12, 31)
    assert prior_quarter_end(dt.date(2026, 6, 30)) == dt.date(2026, 3, 31)
    assert step_points(71.77, 72.41) == -0.64


def test_small_step_shown_big_step_flagged_and_validated(session):
    co = _setup(session, {"Q4FY2025": 72.0, "Q1FY2026": 71.5, "Q2FY2026": 68.9, "Q3FY2026": 68.9})
    res = run_j2_01(InputStore(session, co.company_id, "consolidated"), ["FY2026"], CFG)
    by_q = {o.figures["quarter"]: o for o in res.observations}
    assert by_q["Q1FY2026"].severity is None and by_q["Q1FY2026"].metric_value == -0.5
    assert by_q["Q2FY2026"].severity == "medium" and by_q["Q2FY2026"].metric_value == -2.6
    assert by_q["Q3FY2026"].severity is None
    assert validate_observation(session, by_q["Q2FY2026"], co.company_id, "consolidated") == []


def test_exactly_two_points_is_not_above_the_limit(session):
    co = _setup(session, {"Q4FY2025": 70.0, "Q1FY2026": 72.0})
    (o,) = run_j2_01(InputStore(session, co.company_id, "consolidated"), ["FY2026"], CFG).observations
    assert o.metric_value == 2.0 and o.severity is None


def test_standalone_run_is_not_applicable_and_tampering_is_caught(session):
    co = _setup(session, {"Q4FY2025": 72.0, "Q1FY2026": 68.0})
    res = run_j2_01(InputStore(session, co.company_id, "standalone"), ["FY2026"], CFG)
    assert res.status == "NOT_APPLICABLE" and not res.observations
    (o,) = run_j2_01(InputStore(session, co.company_id, "consolidated"), ["FY2026"], CFG).observations
    object.__setattr__(o, "metric_value", -1.0)
    assert any(g == "recalculation" for g, _ in validate_observation(session, o, co.company_id, "consolidated"))
