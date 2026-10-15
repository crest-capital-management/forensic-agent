"""Per-case access: who may open which case (review/access.py)."""
import pytest
from sqlalchemy import select

from crest_forensic.db.models import AppUser, ConfigVersion, Escalation, Flag, Run, TypologyMatch
from crest_forensic.review import access, service as svc
from crest_forensic.tests.test_review_api import client, company, session  # noqa: F401  (fixtures: one shared in-memory database for the API client)


@pytest.fixture()
def users(session):
    svc.ensure_default_users(session)
    return {u.username: u for u in session.execute(select(AppUser)).scalars()}


def _case(session, users, company, portfolio=False, by="analyst1"):
    return svc.create_case(session, users[by], company.company_id, ["FY2026"], "routine screen", is_portfolio_company=portfolio)


def _flag(session, company):
    cfg = ConfigVersion(version=1, content={}, content_hash="h")
    session.add(cfg)
    session.flush()
    run = Run(company_id=company.company_id, basis="consolidated", years=["FY2026"], config_version_id=cfg.id, config_approved=True,
              code_version="t", run_signature="s", manifest={})
    session.add(run)
    session.flush()
    f = Flag(run_id=run.id, check_id="J1-03", check_version=1, financial_year="FY2026", what_observed="o", location={}, technique="t",
             severity="high", severity_rule_id="R", materiality={"label": "material"}, evidence_confidence="high", figures={},
             citation={"inputs": [{"x": 1}]}, content_hash="c")
    session.add(f)
    session.flush()
    return f


def test_the_creator_and_the_forensic_lead_see_the_case_others_do_not(session, users, company):
    case = _case(session, users, company)
    assert access.can_access(session, users["analyst1"], case) and access.can_access(session, users["lead1"], case)
    for other in ("adviser1", "partner1", "owner1"):
        assert not access.can_access(session, users[other], case)
    with pytest.raises(svc.RuleError) as e:
        access.ensure_access(session, users["owner1"], case.id)
    assert e.value.status == 404 and "not found" in str(e.value).lower()           # the same answer as for a case that does not exist


def test_lists_show_only_the_cases_a_user_may_open(session, users, company):
    mine, theirs = _case(session, users, company), _case(session, users, company, by="lead1")
    ids = lambda u: {c["id"] for c in svc.list_cases(session, users[u])}   # noqa: E731
    assert ids("analyst1") == {mine.id} and ids("lead1") == {mine.id, theirs.id} and ids("owner1") == set()
    home = {r["company_id"]: r for r in svc.home(session, users["owner1"])}
    assert home[company.company_id]["cases"] == 0 and home[company.company_id]["latest_case_id"] is None


def test_adding_and_removing_members_and_who_may_do_it(session, users, company):
    case = _case(session, users, company)
    with pytest.raises(svc.RuleError) as e:                                         # a member who is not the creator or the lead cannot add
        access.add_member(session, users["owner1"], case.id, "adviser1")
    assert e.value.status == 404                                                    # owner1 cannot even see the case
    out = access.add_member(session, users["analyst1"], case.id, "owner1")
    assert {m["username"] for m in out["members"]} == {"analyst1", "owner1"}
    assert access.can_access(session, users["owner1"], case)
    with pytest.raises(svc.RuleError):                                              # now owner1 sees it but still may not manage it
        access.add_member(session, users["owner1"], case.id, "adviser1")
    with pytest.raises(svc.RuleError):
        access.add_member(session, users["analyst1"], case.id, "owner1")            # already has access
    with pytest.raises(svc.RuleError):
        access.add_member(session, users["analyst1"], case.id, "lead1")             # the lead already sees every case
    with pytest.raises(svc.RuleError):
        access.remove_member(session, users["lead1"], case.id, "analyst1")          # the creator cannot be removed
    access.remove_member(session, users["lead1"], case.id, "owner1")
    assert not access.can_access(session, users["owner1"], case)
    row = session.execute(select(access.CaseMember).where(access.CaseMember.username == "owner1")).scalars().one()
    assert row.removed_by == "lead1" and row.removed_at is not None                 # the record of the access is kept


def test_an_adviser_sees_a_portfolio_case_only_once_a_flag_is_escalated(session, users, company):
    f = _flag(session, company)
    plain, portfolio = _case(session, users, company), _case(session, users, company, portfolio=True)
    assert not access.can_access(session, users["adviser1"], portfolio)
    svc.review_flag(session, users["analyst1"], portfolio.id, f.id, "accept", "real")
    svc.request_escalation(session, users["analyst1"], portfolio.id, f.id, "please approve")
    assert access.can_access(session, users["adviser1"], portfolio) and not access.can_access(session, users["adviser1"], plain)


def test_a_partner_sees_a_case_only_when_a_match_needs_their_review(session, users, company):
    case = _case(session, users, company)
    assert not access.can_access(session, users["partner1"], case)
    session.add(TypologyMatch(case_id=case.id, batch=1, scheme_id="FSF-01", scheme_name="s", class_label="c", coverage=0.5, present=[], missing=[],
                              against=[], innocent_explanations=[], evidence_to_confirm=[], citations={}, named_individual=True,
                              input_hash="h", created_by="analyst1", partner_status="pending"))
    session.flush()
    assert access.can_access(session, users["partner1"], case)


def test_http_routes_are_guarded_for_cases_memos_matches_and_escalations(client, session, company):
    svc.ensure_default_users(session)
    users = {u.username: u for u in session.execute(select(AppUser)).scalars()}
    session.commit()
    case = _case(session, users, company)
    session.commit()
    own, other = {"X-User": "analyst1"}, {"X-User": "owner1"}
    for path in (f"/api/cases/{case.id}", f"/api/cases/{case.id}/status", f"/api/cases/{case.id}/typology", f"/api/cases/{case.id}/memos",
                 f"/api/cases/{case.id}/chats", f"/api/cases/{case.id}/access"):
        assert client.get(path, headers=own).status_code == 200, path
        assert client.get(path, headers=other).status_code == 404, path
    assert client.post(f"/api/cases/{case.id}/typology/run", headers=other).status_code == 404
    assert client.get("/api/memos/999999", headers=other).status_code == 404                  # unknown ids answer the same
    assert client.get("/api/cases", headers=other).json() == []
    added = client.post(f"/api/cases/{case.id}/access", headers=own, json={"username": "owner1"})
    assert added.status_code == 200 and client.get(f"/api/cases/{case.id}", headers=other).status_code == 200
    assert client.post(f"/api/cases/{case.id}/access", headers=other, json={"username": "adviser1"}).status_code == 403
    assert client.post(f"/api/cases/{case.id}/access/remove", headers=own, json={"username": "owner1"}).status_code == 200
    assert client.get(f"/api/cases/{case.id}", headers=other).status_code == 404
