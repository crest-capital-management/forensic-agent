from crest_forensic.checks.auditor_fees import change_pct, rounding_range, run_j2_03
from crest_forensic.checks.base import InputStore
from crest_forensic.db.models import Company, Snapshot
from crest_forensic.documents.auditor_fees import ENDPOINT, PROVIDER
from crest_forensic.guardrails.validate import validate_observation
from crest_forensic.screen import load_check_config

CFG = load_check_config()["checks"]["J2-03"]


def _fees(audit, other=2):
    return dict(audit_fee_cr=audit, tax_matters_cr=1, other_services_cr=other, reimbursement_cr=0)


def _setup(session, by_year):
    co = Company(name="T")
    session.add(co)
    session.flush()
    session.add(Snapshot(company_id=co.company_id, source_provider=PROVIDER, source_endpoint=ENDPOINT, request_params={}, payload_hash="h",
                         raw_payload={"report_fy": "FY2026", "page": 300, "document_version_id": 1, "years": by_year}))
    session.flush()
    return co


def test_config_limit_comes_from_the_spec():
    assert CFG["thresholds"]["medium"] == {"value": 30.0, "source": "spec"}


def test_change_and_rounding_range():
    assert change_pct(13, 10) == 30.0
    lo, hi = rounding_range(13, 10)
    assert lo < 30.0 < hi


def test_jump_above_30_percent_flags_and_exactly_30_does_not(session):
    co = _setup(session, {"FY2024": _fees(10), "FY2025": _fees(13), "FY2026": _fees(20)})
    res = run_j2_03(InputStore(session, co.company_id, "consolidated"), ["FY2025", "FY2026"], CFG)
    by = {(o.fy, o.figures["metric"]): o for o in res.observations}
    assert by[("FY2025", "audit")].metric_value == 30.0 and by[("FY2025", "audit")].severity is None
    assert by[("FY2026", "audit")].severity == "medium" and round(by[("FY2026", "audit")].metric_value, 1) == 53.8
    assert "whole crores" in by[("FY2026", "audit")].what_observed
    assert all(validate_observation(session, o, co.company_id, "consolidated") == [] for o in res.observations)


def test_a_fall_is_not_a_jump_tampering_is_caught_and_standalone_is_not_applicable(session):
    co = _setup(session, {"FY2025": _fees(20), "FY2026": _fees(10)})
    res = run_j2_03(InputStore(session, co.company_id, "consolidated"), ["FY2026"], CFG)
    assert all(o.severity is None for o in res.observations) and res.observations[0].metric_value < 0
    o = res.observations[0]
    object.__setattr__(o, "metric_value", 99.0)
    assert any(g == "recalculation" for g, _ in validate_observation(session, o, co.company_id, "consolidated"))
    assert run_j2_03(InputStore(session, co.company_id, "standalone"), ["FY2026"], CFG).status == "NOT_APPLICABLE"
    assert run_j2_03(InputStore(session, co.company_id, "consolidated"), ["FY2024"], CFG).status == "NOT_ENOUGH_DATA"
