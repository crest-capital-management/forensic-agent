import pytest
from sqlalchemy import select

from crest_forensic.agent import loop
from crest_forensic.agent.models import ScriptedAgentModel
from crest_forensic.db.models import AppUser, CaseEvent
from crest_forensic.review import service as svc
from crest_forensic.tests.test_agent import case, users  # noqa: F401  (fixtures reused)
from crest_forensic.tests.test_review_service import flags  # noqa: F401


def test_closing_needs_a_reason_and_is_recorded_then_reopening_restores_it(session, users, case):
    with pytest.raises(svc.RuleError, match="reason"):
        svc.close_case(session, users["analyst"], case.id, "  ")
    out = svc.close_case(session, users["analyst"], case.id, "Review finished; nothing to escalate.")
    assert out["status"] == "closed" and out["closure"]["by"] == users["analyst"].username
    assert svc.case_page(session, case.id)["case"]["closure"]["reason"].startswith("Review finished")
    assert next(c for c in svc.list_cases(session) if c["id"] == case.id)["status"] == "closed"
    with pytest.raises(svc.RuleError, match="already closed"):
        svc.close_case(session, users["analyst"], case.id, "again")
    assert svc.reopen_case(session, users["analyst"], case.id, "New filing arrived.")["status"] == "open"
    assert svc.case_page(session, case.id)["case"]["closure"] is None
    assert [e.action for e in session.execute(select(CaseEvent)).scalars()] == ["closed", "reopened"]   # history is kept


def test_a_closed_case_cannot_be_reviewed_escalated_or_asked_about(session, users, case):
    page = svc.case_page(session, case.id)
    flag_id = page["flags"][0]["id"]
    svc.close_case(session, users["analyst"], case.id, "Done.")
    with pytest.raises(svc.RuleError, match="closed"):
        svc.review_flag(session, users["analyst"], case.id, flag_id, "accept", "x")
    with pytest.raises(svc.RuleError, match="closed"):
        svc.request_escalation(session, users["analyst"], case.id, flag_id, "x")
    with pytest.raises(svc.RuleError, match="closed"):
        loop.ask(session, users["analyst"], case.id, "Which flags are severe?", ScriptedAgentModel([]))
    svc.reopen_case(session, users["analyst"], case.id, "Back.")
    assert svc.review_flag(session, users["analyst"], case.id, flag_id, "accept", "ok").decision == "accept"


def test_only_analyst_and_forensic_lead_can_close_or_reopen(session, users, case):
    for role in ("adviser", "partner", "memo_owner"):
        with pytest.raises(svc.RuleError, match="not allowed"):
            svc.close_case(session, users[role], case.id, "x")
    svc.close_case(session, users["forensic_lead"], case.id, "Done.")
    with pytest.raises(svc.RuleError, match="not allowed"):
        svc.reopen_case(session, users["adviser"], case.id, "x")


def test_the_status_endpoint_reports_a_closure_for_the_chat_to_use(session, users, case):
    assert svc.case_status(session, case.id) == {"status": "open", "closure": None}
    svc.close_case(session, users["analyst"], case.id, "Done.")
    out = svc.case_status(session, case.id)
    assert out["status"] == "closed" and out["closure"]["reason"] == "Done."


def test_a_deleted_case_id_is_never_handed_out_again(session, users, flags, company):  # noqa: F811
    first = svc.create_case(session, users["analyst"], company.company_id, ["FY2026"], "one")
    session.delete(first)
    session.flush()
    second = svc.create_case(session, users["analyst"], company.company_id, ["FY2026"], "two")
    assert second.id > first.id


# ---- decisions carried over after a re-run -----------------------------------------------------------------

def _rerun_copy(session, flag_row):
    """Simulate a re-run: a new run with a copy of one flag (same content hash) and one changed copy."""
    from crest_forensic.db.models import Flag, Run
    old = session.get(Flag, flag_row["id"])
    old_run = session.get(Run, old.run_id)
    new_run = Run(**{c.name: getattr(old_run, c.name) for c in Run.__table__.columns if c.name not in ("id",)})
    session.add(new_run)
    session.flush()

    def clone(**over):
        data = {c.name: getattr(old, c.name) for c in Flag.__table__.columns if c.name not in ("id",)}
        data.update(run_id=new_run.id, **over)
        f = Flag(**data)
        session.add(f)
        session.flush()
        return f
    return new_run, clone


def test_an_identical_flag_in_a_later_run_shows_the_earlier_decision_as_carried_over(session, users, case, flags):  # noqa: F811
    first = svc.case_page(session, case.id)["flags"][0]
    svc.review_flag(session, users["analyst"], case.id, first["id"], "accept", "Worth a look.")
    _, clone = _rerun_copy(session, first)
    same = clone()
    changed = clone(content_hash="different-" + session.get(type(same), first["id"]).content_hash[:20])
    from crest_forensic.review import service
    run_same = session.get(service.Run, same.run_id)
    review, carried = service.effective_review(session, same, run_same)
    assert review is not None and review.decision == "accept" and carried.id == first["id"]
    row = service._flag_row(session, session.get(service.Case, case.id), same, run_same)
    assert row["review"]["carried_from"] == {"flag_id": first["id"], "run_id": carried.run_id}
    # a flag whose figures changed (different hash) is NOT carried over
    assert service.effective_review(session, changed, session.get(service.Run, changed.run_id)) == (None, None)
    # a fresh decision on the new flag replaces the carried one
    svc.review_flag(session, users["analyst"], case.id, same.id, "reject", "Explained by a restatement.")
    review, carried = service.effective_review(session, same, run_same)
    assert review.decision == "reject" and carried is None


def test_a_carried_acceptance_can_be_escalated_once_and_an_earlier_escalation_is_carried_too(session, users, case, flags):  # noqa: F811
    from crest_forensic.review import service
    first = svc.case_page(session, case.id)["flags"][0]
    svc.review_flag(session, users["analyst"], case.id, first["id"], "accept", "Worth a look.")
    svc.request_escalation(session, users["analyst"], case.id, first["id"], "Please look.")
    _, clone = _rerun_copy(session, first)
    same = clone()
    row = service._flag_row(session, session.get(service.Case, case.id), same, session.get(service.Run, same.run_id))
    assert row["escalation"] is not None                              # the earlier escalation shows on the identical flag
    with pytest.raises(svc.RuleError, match="already has an escalation"):
        svc.request_escalation(session, users["analyst"], case.id, same.id, "again")
