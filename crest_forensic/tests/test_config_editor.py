import pytest
from sqlalchemy import select

from crest_forensic import config_store as store
from crest_forensic.db.models import AppUser, ConfigVersion
from crest_forensic.guardrails.config_gate import ConfigNotApproved
from crest_forensic.review import config_service as cfg
from crest_forensic.review import service as svc
from crest_forensic.screen import run_screen
from crest_forensic.tests.helpers import make_snapshot, seed

HIGH = "checks.J1-03.thresholds.high.value"
MED = "checks.J1-03.thresholds.medium.value"


@pytest.fixture()
def users(session):
    svc.ensure_default_users(session)
    return {u.role: u for u in session.execute(select(AppUser)).scalars()}


def test_nothing_is_live_until_the_lead_saves_a_change(session):
    assert store.live_version(session) is None
    assert cfg.overview(session)["live"]["from"] == "file"


def test_an_edit_makes_a_new_version_sets_source_lead_and_keeps_the_old_one(session, users):
    cfg.edit(session, users["forensic_lead"], [{"path": HIGH, "value": 2.5}], "peer data suggests 2.5")
    row = store.live_version(session)
    node = row.content["checks"]["J1-03"]["thresholds"]["high"]
    assert (node["value"], node["source"]) == (2.5, "lead")
    assert row.created_by == "lead1" and row.note == "peer data suggests 2.5"
    cfg.edit(session, users["forensic_lead"], [{"path": MED, "value": 1.2}], "second change")
    assert len(session.execute(select(ConfigVersion).where(ConfigVersion.origin == "editor")).scalars().all()) == 2


def test_reason_is_required_and_bad_values_are_refused(session, users):
    lead = users["forensic_lead"]
    for changes, reason in [([{"path": HIGH, "value": 3}], " "), ([{"path": HIGH, "value": -1}], "x"),
                            ([{"path": HIGH, "value": "abc"}], "x"),
                            ([{"path": "checks.J1-10.finding_severity.key_audit_matter.value", "value": "critical"}], "x"),
                            ([{"path": "checks.J1-03.metric", "value": 1}], "x"),
                            ([{"path": "checks.NOPE.thresholds.high.value", "value": 1}], "x"),
                            ([{"path": HIGH, "value": 1.0}], "x")]:   # high below medium (1.5)
        with pytest.raises(svc.RuleError):
            cfg.edit(session, lead, changes, reason)
    assert store.live_version(session) is None   # nothing was saved


def test_only_the_forensic_lead_can_edit_confirm_or_approve(session, users):
    for role in ("analyst", "adviser", "partner", "memo_owner"):
        for call in (lambda u: cfg.edit(session, u, [{"path": HIGH, "value": 3}], "x"),
                     lambda u: cfg.confirm(session, u, "x"), lambda u: cfg.approve(session, u, "x")):
            with pytest.raises(svc.RuleError) as e:
                call(users[role])
            assert e.value.status == 403


def test_severity_can_be_set_and_cleared(session, users):
    path = "checks.J1-10.finding_severity.key_audit_matter.value"
    cfg.edit(session, users["forensic_lead"], [{"path": path, "value": "low"}], "show KAMs as low")
    assert store.live_version(session).content["checks"]["J1-10"]["finding_severity"]["key_audit_matter"]["value"] == "low"
    cfg.edit(session, users["forensic_lead"], [{"path": path, "value": None}], "never a flag")
    assert store.live_version(session).content["checks"]["J1-10"]["finding_severity"]["key_audit_matter"]["value"] is None


def test_approval_is_refused_while_proposals_remain_and_works_after_confirming(session, users):
    lead = users["forensic_lead"]
    with pytest.raises(svc.RuleError):
        cfg.approve(session, lead, "x")              # no editor version yet
    cfg.edit(session, lead, [{"path": HIGH, "value": 2.5}], "tweak")
    with pytest.raises(svc.RuleError) as e:
        cfg.approve(session, lead, "ready")
    assert "unconfirmed" in str(e.value)
    cfg.confirm(session, lead, "reviewed each against peer data")
    assert cfg.overview(session)["summary"]["unconfirmed_proposals"] == 0
    cfg.approve(session, lead, "approved for the pilot")
    live = cfg.overview(session)["live"]
    assert live["approved"] and live["approved_by"] == "lead1"
    with pytest.raises(svc.RuleError):
        cfg.approve(session, lead, "again")          # already approved


def test_any_change_after_approval_clears_the_approval(session, users):
    lead = users["forensic_lead"]
    cfg.edit(session, lead, [{"path": HIGH, "value": 2.5}], "tweak")
    cfg.confirm(session, lead, "ok")
    cfg.approve(session, lead, "ok")
    cfg.edit(session, lead, [{"path": MED, "value": 1.3}], "late tweak")
    live = cfg.overview(session)["live"]
    assert not live["approved"] and live["approved_by"] is None


def test_history_shows_what_changed(session, users):
    cfg.edit(session, users["forensic_lead"], [{"path": HIGH, "value": 2.5}], "tweak")
    (v,) = cfg.overview(session)["versions"]
    (ch,) = v["changes"]
    assert (ch["path"], ch["old_value"], ch["new_value"], ch["new_source"]) == (
        "checks.J1-03.thresholds.high", 2.0, 2.5, "lead")


def _tcs_like(session, company):
    snap = make_snapshot(session, company)
    seed(session, company, snap, "revenue_from_operations", {"FY2025": 100e7, "FY2026": 101e7})
    seed(session, company, snap, "trade_receivables", {"FY2025": 20e7, "FY2026": 30e7})


def test_a_screen_uses_the_live_config_and_is_stamped_draft_until_it_is_approved(session, company, users):
    _tcs_like(session, company)
    lead = users["forensic_lead"]
    with pytest.raises(ConfigNotApproved):                    # file config is unapproved
        run_screen(session, company.company_id, "standalone", ["FY2025", "FY2026"])
    cfg.edit(session, lead, [{"path": HIGH, "value": 2.5}], "tweak")
    cfg.confirm(session, lead, "ok")
    with pytest.raises(ConfigNotApproved):                    # edited but not approved
        run_screen(session, company.company_id, "standalone", ["FY2025", "FY2026"])
    cfg.approve(session, lead, "ok")
    run = run_screen(session, company.company_id, "standalone", ["FY2025", "FY2026"])
    assert run.config_approved is True
    assert session.get(ConfigVersion, run.config_version_id).approved_by == "lead1"
