import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import sessionmaker

from crest_forensic.db.models import AppUser, AuthSession
from crest_forensic.review import api, auth
from crest_forensic.review import service as svc
from crest_forensic.tests.test_review_api import company, session  # noqa: F401  (fixtures reused)

PW = "correct horse battery"          # a throwaway password used only inside these tests


@pytest.fixture(autouse=True)
def _reset_locks():
    auth._fails.clear()


@pytest.fixture()
def client(session, company, monkeypatch):
    monkeypatch.delenv("CREST_DEV_HEADER_AUTH", raising=False)       # real running: the header is NOT trusted
    factory = sessionmaker(bind=session.get_bind(), expire_on_commit=False)
    monkeypatch.setattr(api, "get_session", lambda: factory())
    c = TestClient(api.app)
    with factory() as s:
        svc.ensure_default_users(s)
        for name in ("analyst1", "lead1"):
            u = s.execute(select(AppUser).where(AppUser.username == name)).scalars().one()
            u.password_hash = auth.hash_password(PW)
        s.commit()
    return c


def login(c, user="analyst1", pw=PW):
    return c.post("/api/auth/login", json={"username": user, "password": pw})


def test_passwords_are_hashed_with_a_salt_and_verified():
    h1, h2 = auth.hash_password(PW), auth.hash_password(PW)
    assert PW not in h1 and h1 != h2 and h1.startswith("scrypt$")
    assert auth.verify_password(PW, h1) and not auth.verify_password(PW + "x", h1)
    assert not auth.verify_password(PW, None) and not auth.verify_password(PW, "garbage")


def test_nobody_gets_in_without_signing_in_and_the_x_user_header_is_ignored(client):
    assert client.get("/api/me").status_code == 401
    assert client.get("/api/cases", headers={"X-User": "analyst1"}).status_code == 401      # the old way no longer works


def test_login_sets_an_http_only_cookie_and_me_works_then_logout_ends_it(client):
    r = login(client)
    assert r.status_code == 200 and r.json()["role"] == "analyst"
    cookie = r.headers["set-cookie"].lower()
    assert "crest_session=" in cookie and "httponly" in cookie and "samesite=lax" in cookie
    assert client.get("/api/me").json()["username"] == "analyst1"
    assert client.post("/api/auth/logout").status_code == 200
    assert client.get("/api/me").status_code == 401


def test_wrong_password_and_unknown_user_get_the_same_answer(client):
    a, b = login(client, pw="wrong password here"), login(client, user="nobody")
    assert a.status_code == b.status_code == 401 and a.json() == b.json()
    assert login(client, user="adviser1").status_code == 401        # a user with no password cannot sign in yet


def test_five_wrong_passwords_lock_the_username_for_a_while(client):
    for _ in range(auth.MAX_FAILS):
        assert login(client, pw="wrong password here").status_code == 401
    r = login(client)                                              # even the right password is refused now
    assert r.status_code == 429 and "Too many" in r.json()["detail"]


def test_the_database_keeps_only_a_hash_of_the_session_token(client, session):
    r = login(client)
    token = client.cookies.get("crest_session")
    row = session.execute(select(AuthSession)).scalars().one()
    assert token and token != row.token_hash and len(row.token_hash) == 64


def test_an_expired_or_revoked_session_is_refused(client, session):
    login(client)
    row = session.execute(select(AuthSession)).scalars().one()
    import datetime as dt
    row.expires_at = dt.datetime.now(dt.timezone.utc) - dt.timedelta(minutes=1)
    session.commit()
    assert client.get("/api/me").status_code == 401


def test_a_switched_off_account_cannot_sign_in_or_keep_a_session(client, session):
    login(client)
    lead = TestClient(api.app)
    assert login(lead, "lead1").status_code == 200
    assert lead.post("/api/users/analyst1/active", json={"active": False}).status_code == 200
    assert client.get("/api/me").status_code == 401               # the analyst's open session ended with it
    assert login(client).status_code == 401
    assert lead.post("/api/users/lead1/active", json={"active": False}).status_code == 400   # not your own account


def test_changing_your_own_password_needs_the_current_one_and_signs_out_other_devices(client):
    other = TestClient(api.app)
    login(client)
    login(other)
    new = "a brand new passphrase"
    assert client.post("/api/auth/password", json={"current": "nope nope nope", "new": new}).status_code == 403
    assert client.post("/api/auth/password", json={"current": PW, "new": "short"}).status_code == 400
    assert client.post("/api/auth/password", json={"current": PW, "new": new}).status_code == 200
    assert client.get("/api/me").status_code == 200                # this device stays signed in
    assert other.get("/api/me").status_code == 401                 # the other one does not
    assert login(TestClient(api.app), pw=new).status_code == 200 and login(TestClient(api.app)).status_code == 401


def test_only_the_forensic_lead_manages_users(client):
    login(client)                                                  # an analyst
    assert client.get("/api/users").status_code == 403
    assert client.post("/api/users", json={"username": "x1", "display_name": "X", "role": "analyst", "password": PW}).status_code == 403
    lead = TestClient(api.app)
    login(lead, "lead1")
    listing = lead.get("/api/users").json()
    assert {u["username"] for u in listing} >= {"analyst1", "lead1"} and "password_hash" not in str(listing)
    assert lead.post("/api/users", json={"username": "New.User", "display_name": "New User", "role": "analyst", "password": PW}).status_code == 200
    assert lead.post("/api/users", json={"username": "new.user", "display_name": "Again", "role": "analyst", "password": PW}).status_code == 400
    assert lead.post("/api/users", json={"username": "bad name", "display_name": "B", "role": "analyst", "password": PW}).status_code == 400
    assert lead.post("/api/users", json={"username": "r1", "display_name": "R", "role": "boss", "password": PW}).status_code == 400
    assert login(TestClient(api.app), "new.user").status_code == 200
    assert lead.post("/api/users/analyst1/password", json={"new": "reset by the lead"}).status_code == 200
    assert client.get("/api/me").status_code == 401                # the reset ended the analyst's session
    assert login(TestClient(api.app), pw="reset by the lead").status_code == 200


def test_password_rules():
    with pytest.raises(svc.RuleError):
        auth.check_new_password("short", "analyst1")
    with pytest.raises(svc.RuleError):
        auth.check_new_password("analyst1analyst1".replace("analyst1analyst1", "ANALYST1   "), "analyst1")
    auth.check_new_password("a long enough one", "analyst1")


def test_me_reports_the_profile_and_sign_out_everywhere_ends_every_device(client):
    other = TestClient(api.app)
    login(client)
    login(other)
    me = client.get("/api/me").json()
    assert me["username"] == "analyst1" and me["signed_in_devices"] == 2 and "password_hash" not in me
    assert client.post("/api/auth/logout-all").json()["ended"] == 2
    assert client.get("/api/me").status_code == 401 and other.get("/api/me").status_code == 401


OPEN_ROUTES = {("POST", "/api/auth/login"), ("POST", "/api/auth/logout")}


def test_every_route_needs_a_session_except_login_and_logout(client):
    """A new route that forgets its sign-in check fails this test."""
    from fastapi.routing import APIRoute
    checked = 0
    for route in api.app.routes:
        if not isinstance(route, APIRoute):
            continue
        path = route.path.replace("{username}", "analyst1")
        for part in ("case_id", "flag_id", "company_id", "escalation_id"):
            path = path.replace("{" + part + "}", "1")
        for method in route.methods - {"HEAD", "OPTIONS"}:
            if (method, route.path) in OPEN_ROUTES:
                continue
            r = client.request(method, path, json={})
            assert r.status_code == 401, f"{method} {route.path} answered {r.status_code} without a session"
            checked += 1
    assert checked >= 30


def test_the_api_publishes_no_docs_or_schema(client):
    for path in ("/docs", "/redoc", "/openapi.json"):
        assert client.get(path).status_code == 404


# ---- audit log -------------------------------------------------------------------------------------------------------

def _events(session):
    from crest_forensic.db.models import AuthEvent
    session.expire_all()
    return [(e.event, e.username, e.actor, e.detail) for e in session.execute(select(AuthEvent).order_by(AuthEvent.id)).scalars()]


def test_sign_ins_wrong_passwords_lock_and_sign_out_are_logged_without_secrets(client, session):
    login(client, pw="wrong password here")
    login(client, user="nobody")
    login(client)
    client.post("/api/auth/logout")
    kinds = [e[0] for e in _events(session)]
    assert kinds == ["login_failed", "login_failed", "login_ok", "logout"]
    assert _events(session)[0][3] == "wrong password" and _events(session)[1][3] == "unknown user"
    assert "wrong password here" not in str(_events(session)) and PW not in str(_events(session))
    for _ in range(auth.MAX_FAILS):
        login(client, pw="wrong password here")
    login(client)
    assert _events(session)[-1][0] == "login_locked"


def test_account_changes_are_logged_with_who_did_them(client, session):
    login(client, "lead1")
    client.post("/api/users", json={"username": "new1", "display_name": "New One", "role": "analyst", "password": "another long pass"})
    client.post("/api/users/new1/password", json={"new": "yet another long pass"})
    client.post("/api/users/new1/active", json={"active": False})
    client.post("/api/auth/password", json={"current": PW, "new": "my brand new password"})
    log = _events(session)
    assert ("user_created", "new1", "lead1", "role analyst") in log
    assert ("password_reset", "new1", "lead1", "") in log
    assert ("user_switched_off", "new1", "lead1", "") in log
    assert ("password_changed", "lead1", None, "") in log


def test_only_the_forensic_lead_can_read_the_audit_log(client):
    login(client, "analyst1")
    assert client.get("/api/auth/events").status_code == 403
    client.post("/api/auth/logout")
    login(client, "lead1")
    rows = client.get("/api/auth/events").json()
    assert rows and rows[0]["event"] == "login_ok" and rows[0]["username"] == "lead1"
