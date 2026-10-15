import pytest

from crest_forensic.db.models import AppUser, ConfigVersion, Flag, Run
from crest_forensic.review import service as svc


@pytest.fixture()
def users(session):
    svc.ensure_default_users(session)
    from sqlalchemy import select
    return {u.role: u for u in session.execute(select(AppUser)).scalars()}


@pytest.fixture()
def flags(session, company):
    cfg = ConfigVersion(version=1, content={}, content_hash="h")
    session.add(cfg)
    session.flush()
    run = Run(company_id=company.company_id, basis="consolidated", years=["FY2025", "FY2026"],
              config_version_id=cfg.id, config_approved=False, code_version="t", run_signature="s", manifest={})
    session.add(run)
    session.flush()
    rows = []
    for i, (sev, mat) in enumerate([("low", "not_assessed"), ("high", "material"), ("medium", "not_assessed"),
                                    ("high", "not_material")]):
        f = Flag(run_id=run.id, check_id=f"J1-0{i}", check_version=1, financial_year="FY2026", what_observed="obs",
                 location={}, technique="t", severity=sev, severity_rule_id="R", materiality={"label": mat},
                 evidence_confidence="high", figures={}, citation={"inputs": [{"x": 1}]}, content_hash=f"c{i}")
        session.add(f)
        rows.append(f)
    session.flush()
    return rows


def _case(session, users, company, portfolio=False):
    return svc.create_case(session, users["analyst"], company.company_id, ["FY2026"], "routine screen",
                           is_portfolio_company=portfolio)


def test_case_page_ranks_flags_by_severity_then_materiality(session, users, company, flags):
    case = _case(session, users, company)
    order = [(f["severity"], f["materiality"]) for f in svc.case_page(session, case.id)["flags"]]
    assert order == [("high", "material"), ("high", "not_material"), ("medium", "not_assessed"), ("low", "not_assessed")]


def test_case_needs_a_reason_and_a_year(session, users, company):
    with pytest.raises(svc.RuleError):
        svc.create_case(session, users["analyst"], company.company_id, ["FY2026"], "  ")
    with pytest.raises(svc.RuleError):
        svc.create_case(session, users["analyst"], company.company_id, [], "why")


def test_a_review_needs_a_reason_and_a_valid_decision(session, users, company, flags):
    case = _case(session, users, company)
    with pytest.raises(svc.RuleError):
        svc.review_flag(session, users["analyst"], case.id, flags[0].id, "accept", " ")
    with pytest.raises(svc.RuleError):
        svc.review_flag(session, users["analyst"], case.id, flags[0].id, "maybe", "because")


def test_changing_your_mind_adds_a_row_and_the_latest_decision_wins(session, users, company, flags):
    case = _case(session, users, company)
    svc.review_flag(session, users["analyst"], case.id, flags[1].id, "accept", "looks real")
    svc.review_flag(session, users["analyst"], case.id, flags[1].id, "reject", "explained in note 12")
    detail = svc.flag_detail(session, case.id, flags[1].id)
    assert detail["review"]["decision"] == "reject" and len(detail["history"]) == 2


def test_roles_are_enforced(session, users, company, flags):
    case = _case(session, users, company)
    with pytest.raises(svc.RuleError) as e:
        svc.review_flag(session, users["adviser"], case.id, flags[0].id, "accept", "x")
    assert e.value.status == 403
    with pytest.raises(svc.RuleError):
        svc.create_case(session, users["partner"], company.company_id, ["FY2026"], "x")


def test_only_an_accepted_flag_can_be_escalated(session, users, company, flags):
    case = _case(session, users, company)
    with pytest.raises(svc.RuleError):
        svc.request_escalation(session, users["analyst"], case.id, flags[1].id, "note")
    svc.review_flag(session, users["analyst"], case.id, flags[1].id, "reject", "no")
    with pytest.raises(svc.RuleError):
        svc.request_escalation(session, users["analyst"], case.id, flags[1].id, "note")


def test_portfolio_escalation_waits_for_the_adviser_and_an_analyst_cannot_approve(session, users, company, flags):
    case = _case(session, users, company, portfolio=True)
    svc.review_flag(session, users["analyst"], case.id, flags[1].id, "accept", "real")
    state = svc.request_escalation(session, users["analyst"], case.id, flags[1].id, "needs client call")
    assert state["state"] == "awaiting_adviser"
    with pytest.raises(svc.RuleError) as e:
        svc.approve_escalation(session, users["analyst"], state["id"])
    assert e.value.status == 403
    assert svc.approve_escalation(session, users["adviser"], state["id"])["state"] == "escalated"


def test_non_portfolio_escalation_needs_no_adviser(session, users, company, flags):
    case = _case(session, users, company, portfolio=False)
    svc.review_flag(session, users["analyst"], case.id, flags[1].id, "accept", "real")
    assert svc.request_escalation(session, users["analyst"], case.id, flags[1].id, "n")["state"] == "escalated"


def test_a_flag_from_another_company_is_not_reachable_through_the_case(session, users, company, flags):
    from crest_forensic.db.models import Company
    other = Company(name="Other", sc_id="OTH")
    session.add(other)
    session.flush()
    case = svc.create_case(session, users["analyst"], other.company_id, ["FY2026"], "x")
    with pytest.raises(svc.RuleError) as e:
        svc.flag_detail(session, case.id, flags[0].id)
    assert e.value.status == 404


def test_dashboard_counts_latest_decisions(session, users, company, flags):
    case = _case(session, users, company)
    svc.review_flag(session, users["analyst"], case.id, flags[0].id, "accept", "a")
    svc.review_flag(session, users["analyst"], case.id, flags[1].id, "reject", "b")
    d = svc.dashboard(session)
    assert (d["accepted"], d["rejected"], d["acceptance_rate_pct"], d["flags_with_citation_pct"]) == (1, 1, 50.0, 100.0)


def test_seeding_users_twice_is_harmless(session):
    from sqlalchemy import select
    svc.ensure_default_users(session)
    svc.ensure_default_users(session)
    assert len(session.execute(select(AppUser)).scalars().all()) == 5


def test_home_lists_each_company_with_flag_counts_and_a_per_user_watchlist(session, users, company, flags):
    me, other = users["analyst"], users["forensic_lead"]
    (row,) = svc.home(session, me)
    assert row["name"] == "Test Co" and row["type"] == "Stock" and row["flags"] == {"high": 2, "medium": 1, "low": 1}
    assert row["flags_total"] == 4 and row["draft"] is True and row["cases"] == 0 and not row["in_watchlist"]
    svc.set_watchlist(session, me, company.company_id, True)
    svc.set_watchlist(session, me, company.company_id, True)               # twice is harmless
    assert svc.home(session, me)[0]["in_watchlist"] and not svc.home(session, other)[0]["in_watchlist"]
    svc.set_watchlist(session, me, company.company_id, False)
    assert not svc.home(session, me)[0]["in_watchlist"]
    with pytest.raises(svc.RuleError):
        svc.set_watchlist(session, me, 999, True)


def test_a_portfolio_case_marks_the_company_as_portfolio(session, users, company, flags):
    svc.create_case(session, users["analyst"], company.company_id, ["FY2026"], "x", is_portfolio_company=True)
    row = svc.home(session, users["analyst"])[0]
    assert row["is_portfolio"] and row["cases"] == 1 and row["latest_case_id"] is not None


def test_a_case_on_the_same_company_and_years_is_labelled_a_duplicate_of_the_earlier_one(session, users, company):
    first = svc.create_case(session, users["analyst"], company.company_id, ["FY2025", "FY2026"], "first look")
    same = svc.create_case(session, users["analyst"], company.company_id, ["FY2026", "FY2025"], "again")      # same years, other order
    other_years = svc.create_case(session, users["analyst"], company.company_id, ["FY2026"], "narrower")
    third = svc.create_case(session, users["analyst"], company.company_id, ["FY2025", "FY2026"], "and again")
    assert svc.case_page(session, first.id)["case"]["duplicate_of"] is None
    assert svc.case_page(session, same.id)["case"]["duplicate_of"] == first.id
    assert svc.case_page(session, other_years.id)["case"]["duplicate_of"] is None
    assert svc.case_page(session, third.id)["case"]["duplicate_of"] == first.id          # points at the earliest one
    assert [c["duplicate_of"] for c in svc.list_cases(session)][::-1] == [None, first.id, None, first.id]


def test_a_case_can_have_an_optional_one_line_name(session, users, company):
    plain = svc.create_case(session, users["analyst"], company.company_id, ["FY2026"], "why")
    named = svc.create_case(session, users["analyst"], company.company_id, ["FY2026"], "why",
                            name="  TCS   receivables\nreview  ")
    long = svc.create_case(session, users["analyst"], company.company_id, ["FY2026"], "why", name="x" * 300)
    blank = svc.create_case(session, users["analyst"], company.company_id, ["FY2026"], "why", name="   ")
    assert svc.case_page(session, plain.id)["case"]["name"] is None
    assert svc.case_page(session, named.id)["case"]["name"] == "TCS receivables review"      # spaces and line breaks tidied
    assert len(svc.case_page(session, long.id)["case"]["name"]) == 120
    assert svc.case_page(session, blank.id)["case"]["name"] is None
    assert [c["name"] for c in svc.list_cases(session)][::-1][1] == "TCS receivables review"
