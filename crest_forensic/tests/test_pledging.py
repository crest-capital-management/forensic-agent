from crest_forensic.checks.base import InputStore
from crest_forensic.checks.pledging import run_j2_04
from crest_forensic.db.models import Company, Shareholding, Snapshot
from crest_forensic.guardrails.validate import validate_observation
from crest_forensic.screen import load_check_config

CFG = load_check_config()["checks"]["J2-04"]


def _setup(session, pledged_by_quarter):
    co = Company(name="T")
    session.add(co)
    session.flush()
    snap = Snapshot(company_id=co.company_id, source_provider="x", source_endpoint="x", request_params={}, raw_payload={}, payload_hash="h")
    session.add(snap)
    session.flush()
    for q, pct in pledged_by_quarter.items():
        session.add(Shareholding(company_id=co.company_id, snapshot_id=snap.snapshot_id, quarter=q, promoter_pct=70.0, pledged_pct=pct))
    session.flush()
    return co


def test_levels_and_missing_pledge_figures(session):
    co = _setup(session, {"Q1FY2026": 0.0, "Q2FY2026": 6.0, "Q3FY2026": 25.0, "Q4FY2026": None})
    res = run_j2_04(InputStore(session, co.company_id, "consolidated"), ["FY2026"], CFG)
    sev = {o.figures["quarter"]: o.severity for o in res.observations}
    assert sev == {"Q1FY2026": None, "Q2FY2026": "medium", "Q3FY2026": "high"}      # Q4 has no figure: skipped, not assumed zero
    assert all(validate_observation(session, o, co.company_id, "consolidated") == [] for o in res.observations)


def test_limits_are_proposals_standalone_is_not_applicable_and_tampering_is_caught(session):
    assert {t["source"] for t in CFG["thresholds"].values()} == {"proposal"}
    co = _setup(session, {"Q1FY2026": 6.0})
    assert run_j2_04(InputStore(session, co.company_id, "standalone"), ["FY2026"], CFG).status == "NOT_APPLICABLE"
    (o,) = run_j2_04(InputStore(session, co.company_id, "consolidated"), ["FY2026"], CFG).observations
    object.__setattr__(o, "metric_value", 1.0)
    assert any(g == "recalculation" for g, _ in validate_observation(session, o, co.company_id, "consolidated"))
