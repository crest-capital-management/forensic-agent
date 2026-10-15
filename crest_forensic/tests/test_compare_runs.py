import pytest

from crest_forensic.db.models import AppUser, Case, Company, ConfigVersion, Flag, Review, Run
from crest_forensic.review import compare as cmp
from crest_forensic.review import service as svc


@pytest.fixture()
def cfg(session):
    row = ConfigVersion(version=1, content={"checks": {"J1-03": {"thresholds": {"high": {"value": 2.0, "source": "proposal"}}}}},
                        content_hash="h1")
    session.add(row)
    session.flush()
    return row


def make_run(session, company, cfg, basis="consolidated", code="code1", snaps=(1, 2), docs="aaa"):
    run = Run(company_id=company.company_id, basis=basis, years=["FY2025", "FY2026"], config_version_id=cfg.id,
              config_approved=False, code_version=code, run_signature=f"s{code}{snaps}{docs}{basis}",
              manifest={"snapshot_ids": list(snaps), "documents": [{"version_id": 1, "fiscal_year": "FY2026", "sha256": docs * 21}],
                        "source_policy_version": 3, "field_mapping_versions": {}})
    session.add(run)
    session.flush()
    return run


def make_flag(session, run, check="J1-03", fy="FY2026", sev="high", metric=3.2, receivables=677e9, h=None, page=None):
    fig = {"metric_value": metric, "growth_ratio": metric}
    if page:
        fig.update({"finding_type": "caro", "page": page, "quote": f"quote p{page}"})
    f = Flag(run_id=run.id, check_id=check, check_version=1, financial_year=fy, what_observed="obs", location={},
             technique="t", severity=sev, severity_rule_id="R", materiality={"label": "material"},
             evidence_confidence="high", figures=fig,
             citation={"inputs": [{"field": "trade_receivables", "fy": fy, "name": "item", "value": receivables,
                                   "provider": "annual_report_pdf", "snapshot_id": 1, "resolution": "AGREE"}]},
             content_hash=h or f"{check}{fy}{sev}{metric}{receivables}{page}")
    session.add(f)
    session.flush()
    return f


def test_identical_runs_report_no_differences(session, company, cfg):
    a, b = make_run(session, company, cfg), make_run(session, company, cfg, code="code1")
    make_flag(session, a)
    make_flag(session, b)
    r = cmp.compare(session, a.id, b.id)
    assert (len(r["new"]), len(r["gone"]), len(r["changed"]), len(r["unchanged"])) == (0, 0, 0, 1)
    assert "exactly the same flags" in r["headline"] and r["possible_causes"] == []


def test_new_gone_changed_and_unchanged_are_told_apart(session, company, cfg):
    a, b = make_run(session, company, cfg), make_run(session, company, cfg, code="code2", snaps=(1, 2, 3))
    make_flag(session, a, check="J1-03", fy="FY2025", sev="medium", metric=1.7)          # unchanged
    make_flag(session, b, check="J1-03", fy="FY2025", sev="medium", metric=1.7)
    make_flag(session, a, check="J1-04", sev="high", metric=8.0)                          # changed (restated input)
    make_flag(session, b, check="J1-04", sev="medium", metric=1.6, receivables=650e9)
    make_flag(session, a, check="J1-07")                                                  # gone
    make_flag(session, b, check="J1-11", page=164)                                        # new
    r = cmp.compare(session, a.id, b.id)
    assert (len(r["new"]), len(r["gone"]), len(r["changed"]), len(r["unchanged"])) == (1, 1, 1, 1)
    assert r["new"][0]["check_id"] == "J1-11" and r["gone"][0]["check_id"] == "J1-07"
    whats = {c["what"] for c in r["changed"][0]["changes"]}
    assert {"severity", "figure: metric value", "input: trade_receivables FY2026"} <= whats
    assert "Saved data differs (a restatement, a new source or a corrected value)" in r["possible_causes"]
    assert "The calculation code differs" in r["possible_causes"]
    snap = next(d for d in r["differences"] if d["item"].startswith("Saved data"))
    assert snap["detail"] == {"added": [3], "removed": []}


def test_a_changed_limit_is_listed_setting_by_setting(session, company, cfg):
    cfg2 = ConfigVersion(version=2, content={"checks": {"J1-03": {"thresholds": {"high": {"value": 2.5, "source": "lead"}}}}},
                         content_hash="h2")
    session.add(cfg2)
    session.flush()
    a, b = make_run(session, company, cfg), make_run(session, company, cfg2)
    make_flag(session, a, sev="high")
    make_flag(session, b, sev="medium", h="other")
    r = cmp.compare(session, a.id, b.id)
    limits = next(d for d in r["differences"] if d["item"].startswith("Limits"))
    assert limits["same"] is False and limits["detail"][0]["old_value"] == 2.0 and limits["detail"][0]["new_value"] == 2.5
    assert "The limits or severity rules differ" in r["possible_causes"]


def test_an_earlier_decision_on_a_matching_flag_is_shown_not_copied(session, company, cfg):
    svc.ensure_default_users(session)
    analyst = session.query(AppUser).filter_by(username="analyst1").one()
    case = svc.create_case(session, analyst, company.company_id, ["FY2026"], "x")
    a, b = make_run(session, company, cfg), make_run(session, company, cfg, code="code2")
    fa = make_flag(session, a)
    make_flag(session, b)
    svc.review_flag(session, analyst, case.id, fa.id, "accept", "real")
    r = cmp.compare(session, a.id, b.id)
    assert r["unchanged"][0]["decision_in_a"]["decision"] == "accept"
    assert session.query(Review).count() == 1       # nothing was copied onto the new run's flag


def test_runs_of_different_basis_or_company_cannot_be_compared(session, company, cfg):
    a, b = make_run(session, company, cfg, basis="consolidated"), make_run(session, company, cfg, basis="standalone")
    with pytest.raises(svc.RuleError):
        cmp.compare(session, a.id, b.id)
    with pytest.raises(svc.RuleError):
        cmp.compare(session, a.id, a.id)
    with pytest.raises(svc.RuleError) as e:
        cmp.compare(session, a.id, 999)
    assert e.value.status == 404
    other = Company(name="Other", sc_id="OTH")
    session.add(other)
    session.flush()
    c = make_run(session, other, cfg, basis="consolidated")
    with pytest.raises(svc.RuleError):
        cmp.compare(session, a.id, c.id)


def test_two_flags_with_the_same_key_are_matched_in_order(session, company, cfg):
    a, b = make_run(session, company, cfg), make_run(session, company, cfg, code="c2")
    for run in (a, b):
        make_flag(session, run, check="J1-14", page=311, h="x1")
        make_flag(session, run, check="J1-14", page=311, h="x2")
    r = cmp.compare(session, a.id, b.id)
    assert (len(r["unchanged"]), len(r["new"]), len(r["gone"])) == (2, 0, 0)


def test_check_status_changes_are_listed(session, company, cfg):
    from crest_forensic.db.models import CheckResultRow
    a, b = make_run(session, company, cfg), make_run(session, company, cfg, code="c2")
    session.add_all([CheckResultRow(run_id=a.id, check_id="J1-10", check_version=1, status="NOT_ENOUGH_DATA", detail={}),
                     CheckResultRow(run_id=b.id, check_id="J1-10", check_version=1, status="COMPLETED", detail={})])
    session.flush()
    assert cmp.compare(session, a.id, b.id)["check_status_changes"] == [
        {"check_id": "J1-10", "a": "NOT_ENOUGH_DATA", "b": "COMPLETED"}]


def test_text_reading_shows_the_main_source_not_a_cross_check(session, company, cfg):
    a, b = make_run(session, company, cfg), make_run(session, company, cfg, code="c2")
    calls = [{"call_id": 1, "task": "J1-10:consolidated", "model": "claude-code-session (manual)"},
             {"call_id": 2, "task": "J1-10:consolidated", "model": "gemini-3.6-flash"}]   # gemini listed last
    a.manifest = {**a.manifest, "text_extractions": calls}
    b.manifest = {**b.manifest, "text_extractions": calls}
    r = cmp.compare(session, a.id, b.id)
    assert not any(d["item"].startswith("Text reading") and not d["same"] for d in r["differences"])
