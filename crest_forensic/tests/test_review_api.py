import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from crest_forensic.db.models import Base, Company
from crest_forensic.review import api
from crest_forensic.tests.test_review_service import flags  # noqa: F401  (fixture reused)


@pytest.fixture()
def session():
    # one shared connection, so the web layer (another thread) sees the same in-memory database
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    with sessionmaker(bind=engine, expire_on_commit=False)() as sess:
        yield sess


@pytest.fixture()
def company(session):
    c = Company(name="Test Co", sc_id="TESTCO", sector="IT Services")
    session.add(c)
    session.flush()
    return c


@pytest.fixture()
def client(session, company, monkeypatch):
    monkeypatch.setenv("CREST_DEV_HEADER_AUTH", "1")      # these tests identify users by header; real running ignores it
    engine = session.get_bind()
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    monkeypatch.setattr(api, "get_session", lambda: factory())
    return TestClient(api.app)


def test_unknown_user_is_refused(client):
    assert client.get("/api/cases", headers={"X-User": "nobody"}).status_code == 401


def test_full_review_flow_over_http_and_role_refusals(client, session, company, flags):
    session.commit()
    h = {"X-User": "analyst1"}
    r = client.post("/api/cases", headers=h, json={"company_id": company.company_id, "years": ["FY2026"],
                                                   "reason": "screen", "is_portfolio_company": True})
    assert r.status_code == 200
    cid = r.json()["id"]
    page = client.get(f"/api/cases/{cid}", headers=h).json()
    top = page["flags"][0]
    assert top["severity"] == "high"
    assert client.post(f"/api/cases/{cid}/flags/{top['id']}/review", headers=h,
                       json={"decision": "accept", "reason": ""}).status_code == 400
    assert client.post(f"/api/cases/{cid}/flags/{top['id']}/review", headers=h,
                       json={"decision": "accept", "reason": "real"}).status_code == 200
    esc = client.post(f"/api/cases/{cid}/flags/{top['id']}/escalate", headers=h, json={"note": "call client"}).json()
    assert esc["state"] == "awaiting_adviser"
    assert client.post(f"/api/escalations/{esc['id']}/approve", headers=h).status_code == 403
    ok = client.post(f"/api/escalations/{esc['id']}/approve", headers={"X-User": "adviser1"})
    assert ok.json()["state"] == "escalated"
    assert client.get("/api/dashboard", headers=h).json()["accepted"] == 1


def test_config_editing_is_lead_only_over_http(client):
    body = {"changes": [{"path": "checks.J1-03.thresholds.high.value", "value": 2.5}], "reason": "peer data"}
    assert client.post("/api/config/edit", headers={"X-User": "analyst1"}, json=body).status_code == 403
    assert client.get("/api/config", headers={"X-User": "analyst1"}).status_code == 200   # anyone can view
    assert client.post("/api/config/edit", headers={"X-User": "lead1"}, json=body).status_code == 200
    page = client.get("/api/config", headers={"X-User": "analyst1"}).json()
    assert page["live"]["from"] == "database" and not page["live"]["approved"]
    assert client.post("/api/config/approve", headers={"X-User": "lead1"}, json={"reason": "x"}).status_code == 400


def test_ask_the_agent_over_http(client, session, company, flags, monkeypatch):
    from crest_forensic.agent.models import AgentTurn, ScriptedAgentModel
    session.commit()
    cid = client.post("/api/cases", headers={"X-User": "analyst1"},
                      json={"company_id": company.company_id, "years": ["FY2026"], "reason": "r"}).json()["id"]
    top = client.get(f"/api/cases/{cid}", headers={"X-User": "analyst1"}).json()["flags"][0]
    monkeypatch.setattr(api, "model_factory", lambda: ScriptedAgentModel([
        AgentTurn(tool_calls=[{"id": "c", "name": "list_flags", "args": {}}]),
        AgentTurn(text=f"The top flag is {top['check_id']} [flag:{top['id']}].")]))
    r = client.post(f"/api/cases/{cid}/ask", headers={"X-User": "analyst1"}, json={"question": "What is the top flag?"})
    assert r.status_code == 200 and r.json()["status"] == "answered" and r.json()["sources"][0]["ref"] == f"flag:{top['id']}"
    assert len(client.get(f"/api/cases/{cid}/ask", headers={"X-User": "analyst1"}).json()) == 1
    assert client.post(f"/api/cases/{cid}/ask", headers={"X-User": "partner1"}, json={"question": "hi"}).status_code == 404      # not a member: the case is not visible to a partner
    # a leading question never builds or calls a model
    monkeypatch.setattr(api, "model_factory", lambda: (_ for _ in ()).throw(AssertionError("model must not be built")))
    r = client.post(f"/api/cases/{cid}/ask", headers={"X-User": "analyst1"}, json={"question": "Was this fraud?"})
    assert r.status_code == 200 and r.json()["status"] == "refused"
    assert client.post(f"/api/cases/{cid}/ask", headers={"X-User": "analyst1"}, json={"question": "  "}).status_code == 400


def test_matrix_endpoint(client, session, company, flags):
    session.commit()
    h = {"X-User": "analyst1"}
    r = client.get(f"/api/companies/{company.company_id}/matrix?basis=standalone", headers=h)
    assert r.status_code == 200 and [x["key"] for x in r.json()["rows"]] == ["beneish", "altman", "benford", "sloan"]
    assert client.get(f"/api/companies/{company.company_id}/matrix?basis=weekly", headers=h).status_code == 400
    assert client.get("/api/companies/999/matrix", headers=h).status_code == 404
