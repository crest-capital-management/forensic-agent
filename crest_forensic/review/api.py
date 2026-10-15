"""Thin web layer over review/service.py. Run:  python -m crest_forensic.review.api

No rules live here. Who is calling comes from the X-User header: a development
stand-in with placeholder users (analyst1, lead1, adviser1, partner1, owner1).
Real sign-in must replace it before anyone outside development uses the app.
"""
from __future__ import annotations

import os

from fastapi import Depends, FastAPI, Header, HTTPException, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from sqlalchemy import select

from crest_forensic.db.models import AppUser, Company
from crest_forensic.db.session import get_session
from crest_forensic.text.extractors import load_llm_config
from crest_forensic.agent import loop as agent_loop
from crest_forensic.agent.models import make_model
from crest_forensic.review import auth
from crest_forensic.review import compare as cmp
from crest_forensic.review import matrix as mtx
from crest_forensic.review import memo as memo_mod
from crest_forensic.review import memo_export
from crest_forensic.review import memo_pdf
from crest_forensic.review import narrative as nar
from crest_forensic.review import config_service as cfg
from crest_forensic.review import access
from crest_forensic.review import service as svc
from crest_forensic.typology import match as typ

app = FastAPI(title="CREST Forensic Review API", docs_url=None, redoc_url=None, openapi_url=None)   # no public route map
app.add_middleware(CORSMiddleware, allow_origins=["http://localhost:3000", "http://127.0.0.1:3000"],
                   allow_methods=["*"], allow_headers=["*"])


def db():
    session = get_session()
    try:
        svc.ensure_default_users(session)
        session.commit()
        yield session
    finally:
        session.close()


COOKIE = "crest_session"


def current_user(request: Request, x_user: str | None = Header(default=None), session=Depends(db)) -> AppUser:
    """Who is asking: the signed-in cookie session. The old X-User header is accepted ONLY when CREST_DEV_HEADER_AUTH=1
    (automated tests); in normal running it is ignored, so nobody can claim to be someone else."""
    user = auth.user_for_token(session, request.cookies.get(COOKIE))
    if user is None and x_user and os.environ.get("CREST_DEV_HEADER_AUTH") == "1":
        user = session.execute(select(AppUser).where(AppUser.username == x_user)).scalars().first()
    if user is None:
        raise HTTPException(401, "Sign in required.")
    return user


def _run(session, fn, *args, **kwargs):
    try:
        out = fn(session, *args, **kwargs)
        session.commit()
        return out
    except svc.RuleError as exc:
        session.rollback()
        raise HTTPException(exc.status, str(exc))


class NewCase(BaseModel):
    company_id: int
    years: list[str]
    reason: str
    exposure_note: str | None = None
    is_portfolio_company: bool = False
    name: str | None = None


class ReviewIn(BaseModel):
    decision: str
    reason: str


class EscalateIn(BaseModel):
    note: str


@app.get("/api/me")
def me(session=Depends(db), user: AppUser = Depends(current_user)):
    return {"username": user.username, "display_name": user.display_name, "role": user.role,
            "password_set_at": user.password_set_at.isoformat() if user.password_set_at else None,
            "signed_in_devices": auth.active_session_count(session, user)}


class Methodology(BaseModel):
    text: str


@app.get("/api/me/methodology")
def my_methodology(session=Depends(db), user: AppUser = Depends(current_user)):
    return _run(session, nar.get_methodology, user)


@app.put("/api/me/methodology")
def save_my_methodology(body: Methodology, session=Depends(db), user: AppUser = Depends(current_user)):
    return _run(session, nar.save_methodology, user, body.text)


class LoginIn(BaseModel):
    username: str
    password: str


@app.post("/api/auth/login")
def login(body: LoginIn, request: Request, response: Response, session=Depends(db)):
    try:
        token, user = auth.login(session, body.username, body.password, ip=request.client.host if request.client else None)
        session.commit()
    except svc.RuleError as exc:
        session.rollback()
        raise HTTPException(exc.status, str(exc))
    response.set_cookie(COOKIE, token, httponly=True, samesite="lax", max_age=auth.SESSION_HOURS * 3600, path="/",
                        secure=request.url.scheme == "https" or os.environ.get("CREST_COOKIE_SECURE") == "1")   # behind an HTTPS proxy the API itself sees http
    return {"username": user.username, "display_name": user.display_name, "role": user.role}


@app.post("/api/auth/logout")
def logout(request: Request, response: Response, session=Depends(db)):
    auth.logout(session, request.cookies.get(COOKIE))
    session.commit()
    response.delete_cookie(COOKIE, path="/")
    return {"ok": True}


@app.post("/api/auth/logout-all")
def logout_all(response: Response, session=Depends(db), user: AppUser = Depends(current_user)):
    ended = auth.logout_everywhere(session, user)
    session.commit()
    response.delete_cookie(COOKIE, path="/")
    return {"ended": ended}


class PasswordChange(BaseModel):
    current: str
    new: str


@app.post("/api/auth/password")
def change_password(body: PasswordChange, request: Request, session=Depends(db), user: AppUser = Depends(current_user)):
    return _run(session, lambda s: auth.change_own_password(s, user, body.current, body.new, request.cookies.get(COOKIE))) or {"ok": True}


class NewUser(BaseModel):
    username: str
    display_name: str
    role: str
    password: str


class PasswordReset(BaseModel):
    new: str


class ActiveIn(BaseModel):
    active: bool


@app.get("/api/users")
def users(session=Depends(db), user: AppUser = Depends(current_user)):
    return _run(session, auth.admin_list, user)


@app.get("/api/auth/events")
def auth_events(limit: int = 100, session=Depends(db), user: AppUser = Depends(current_user)):
    return _run(session, auth.recent_events, user, limit)


@app.post("/api/users")
def new_user(body: NewUser, session=Depends(db), user: AppUser = Depends(current_user)):
    created = _run(session, auth.create_user, user, body.username, body.display_name, body.role, body.password)
    return {"username": created.username}


@app.post("/api/users/{username}/password")
def reset_password(username: str, body: PasswordReset, session=Depends(db), user: AppUser = Depends(current_user)):
    return _run(session, lambda s: auth.set_password_for(s, user, username, body.new)) or {"ok": True}


@app.post("/api/users/{username}/active")
def user_active(username: str, body: ActiveIn, session=Depends(db), user: AppUser = Depends(current_user)):
    out = _run(session, auth.set_active, user, username, body.active)
    return {"username": out.username, "active": out.active}


def access_guard(request: Request, session=Depends(db)) -> None:
    """Runs for EVERY route. When the URL names a case, a memo, a scheme match or an escalation, the signed-in user must be allowed to open
    that case (review/access.py); otherwise the answer is 404, the same as for a case that does not exist."""
    pp = request.path_params
    for kind in ("case_id", "memo_id", "match_id", "escalation_id"):
        if kind in pp:
            user = current_user(request, request.headers.get("x-user"), session)
            cid = access.case_id_of(session, kind, int(pp[kind]))
            if cid is None:
                raise HTTPException(404, "Not found.")
            try:
                access.ensure_access(session, user, cid)
            except svc.RuleError as exc:
                raise HTTPException(exc.status, str(exc))
            return


app.router.dependencies.append(Depends(access_guard))     # added before any route, so every route below is covered


class WatchIn(BaseModel):
    company_id: int
    watch: bool


@app.get("/api/home")
def home(session=Depends(db), user: AppUser = Depends(current_user)):
    return svc.home(session, user)


@app.post("/api/watchlist")
def watchlist(body: WatchIn, session=Depends(db), user: AppUser = Depends(current_user)):
    return _run(session, svc.set_watchlist, user, body.company_id, body.watch)


@app.get("/api/companies")
def companies(session=Depends(db), user: AppUser = Depends(current_user)):
    return [{"company_id": c.company_id, "name": c.name, "sc_id": c.sc_id}
            for c in session.execute(select(Company).order_by(Company.name)).scalars()]


@app.get("/api/cases")
def cases(session=Depends(db), user: AppUser = Depends(current_user)):
    return svc.list_cases(session, user)


@app.post("/api/cases")
def new_case(body: NewCase, session=Depends(db), user: AppUser = Depends(current_user)):
    case = _run(session, svc.create_case, user, body.company_id, body.years, body.reason,
                body.exposure_note, body.is_portfolio_company, body.name)
    return {"id": case.id}


@app.get("/api/cases/{case_id}")
def case(case_id: int, session=Depends(db), user: AppUser = Depends(current_user)):
    return _run(session, svc.case_page, case_id)


class CaseReason(BaseModel):
    reason: str


class AccessIn(BaseModel):
    username: str


@app.get("/api/cases/{case_id}/access")
def case_access(case_id: int, session=Depends(db), user: AppUser = Depends(current_user)):
    return _run(session, access.overview, user, case_id)


@app.post("/api/cases/{case_id}/access")
def case_access_add(case_id: int, body: AccessIn, session=Depends(db), user: AppUser = Depends(current_user)):
    return _run(session, access.add_member, user, case_id, body.username)


@app.post("/api/cases/{case_id}/access/remove")
def case_access_remove(case_id: int, body: AccessIn, session=Depends(db), user: AppUser = Depends(current_user)):
    return _run(session, access.remove_member, user, case_id, body.username)


@app.get("/api/cases/{case_id}/status")
def case_status(case_id: int, session=Depends(db), user: AppUser = Depends(current_user)):
    return _run(session, svc.case_status, case_id)


@app.post("/api/cases/{case_id}/close")
def close_case(case_id: int, body: CaseReason, session=Depends(db), user: AppUser = Depends(current_user)):
    return _run(session, svc.close_case, user, case_id, body.reason)


@app.post("/api/cases/{case_id}/reopen")
def reopen_case(case_id: int, body: CaseReason, session=Depends(db), user: AppUser = Depends(current_user)):
    return _run(session, svc.reopen_case, user, case_id, body.reason)


@app.get("/api/cases/{case_id}/flags/{flag_id}")
def flag(case_id: int, flag_id: int, session=Depends(db), user: AppUser = Depends(current_user)):
    return _run(session, svc.flag_detail, case_id, flag_id)


@app.post("/api/cases/{case_id}/flags/{flag_id}/review")
def review(case_id: int, flag_id: int, body: ReviewIn, session=Depends(db), user: AppUser = Depends(current_user)):
    row = _run(session, svc.review_flag, user, case_id, flag_id, body.decision, body.reason)
    return {"id": row.id}


@app.post("/api/cases/{case_id}/flags/{flag_id}/escalate")
def escalate(case_id: int, flag_id: int, body: EscalateIn, session=Depends(db), user: AppUser = Depends(current_user)):
    return _run(session, svc.request_escalation, user, case_id, flag_id, body.note)


@app.post("/api/escalations/{escalation_id}/approve")
def approve(escalation_id: int, session=Depends(db), user: AppUser = Depends(current_user)):
    return _run(session, svc.approve_escalation, user, escalation_id)


class ConfigChange(BaseModel):
    path: str
    value: float | str | None = None


class ConfigEdit(BaseModel):
    changes: list[ConfigChange]
    reason: str


class Question(BaseModel):
    question: str
    session_id: int | None = None


def model_factory():
    """Overridden in tests. Claude if its key is set, else Gemini (development)."""
    return make_model(load_llm_config())


class Reason(BaseModel):
    reason: str


@app.get("/api/config")
def config_overview(session=Depends(db), user: AppUser = Depends(current_user)):
    return cfg.overview(session)


@app.post("/api/config/edit")
def config_edit(body: ConfigEdit, session=Depends(db), user: AppUser = Depends(current_user)):
    return _run(session, cfg.edit, user, [c.model_dump() for c in body.changes], body.reason)


@app.post("/api/config/confirm-proposals")
def config_confirm(body: Reason, session=Depends(db), user: AppUser = Depends(current_user)):
    return _run(session, cfg.confirm, user, body.reason)


@app.post("/api/config/approve")
def config_approve(body: Reason, session=Depends(db), user: AppUser = Depends(current_user)):
    return _run(session, cfg.approve, user, body.reason)


@app.get("/api/cases/{case_id}/ask")
def ask_history(case_id: int, session_id: int | None = None, session=Depends(db), user: AppUser = Depends(current_user)):
    return _run(session, lambda s: agent_loop.history(s, case_id, session_id))


@app.get("/api/cases/{case_id}/chats")
def chat_list(case_id: int, session=Depends(db), user: AppUser = Depends(current_user)):
    return _run(session, lambda s: agent_loop.list_sessions(s, case_id))


@app.post("/api/cases/{case_id}/chats")
def chat_create(case_id: int, session=Depends(db), user: AppUser = Depends(current_user)):
    return _run(session, agent_loop.create_session, user, case_id)


@app.post("/api/cases/{case_id}/ask")
def ask_agent(case_id: int, body: Question, session=Depends(db), user: AppUser = Depends(current_user)):
    cfg = load_llm_config().get("agent", {})

    def go(s):
        svc.require(user, "ask_agent")          # check the role and the question before building a model
        if not body.question.strip():
            raise svc.RuleError("Type a question first.")
        if agent_loop.is_leading_question(body.question) or agent_loop.needs_fuller_question(body.question, True):
            model = None                         # refused or answered in code; no model needed, none called
        else:
            try:
                model = model_factory()
            except RuntimeError as exc:
                raise svc.RuleError(f"No model is configured for the agent: {exc}", 503)
        return agent_loop.ask(s, user, case_id, body.question, model, max_rounds=cfg.get("max_tool_rounds", 5),
                              daily_call_cap=cfg.get("max_model_calls_per_day"), session_id=body.session_id)
    return _run(session, go)


class MemoNew(BaseModel):
    owner: str
    scope_note: str = ""


class MemoEdit(BaseModel):
    changes: dict
    note: str


class MemoRegen(BaseModel):
    note: str = ""


@app.get("/api/memos")
def all_memos(session=Depends(db), user: AppUser = Depends(current_user)):
    return _run(session, lambda s: memo_mod.list_all(s, user))


@app.get("/api/memo-owners")
def memo_owners(session=Depends(db), user: AppUser = Depends(current_user)):
    return _run(session, lambda s: memo_mod.owner_choices(s))


@app.get("/api/cases/{case_id}/memos")
def case_memos(case_id: int, session=Depends(db), user: AppUser = Depends(current_user)):
    return _run(session, memo_mod.list_memos, case_id)


@app.post("/api/cases/{case_id}/memos")
def new_memo(case_id: int, body: MemoNew, session=Depends(db), user: AppUser = Depends(current_user)):
    return _run(session, memo_mod.create_memo, user, case_id, body.owner, body.scope_note)


@app.get("/api/memos/{memo_id}")
def get_memo(memo_id: int, version: int | None = None, session=Depends(db), user: AppUser = Depends(current_user)):
    return _run(session, memo_mod.get_memo, user, memo_id, version)


@app.post("/api/memos/{memo_id}/regenerate")
def regenerate_memo(memo_id: int, body: MemoRegen, session=Depends(db), user: AppUser = Depends(current_user)):
    return _run(session, memo_mod.regenerate, user, memo_id, body.note)


@app.put("/api/memos/{memo_id}")
def edit_memo(memo_id: int, body: MemoEdit, session=Depends(db), user: AppUser = Depends(current_user)):
    return _run(session, memo_mod.edit_memo, user, memo_id, body.changes, body.note)


@app.post("/api/memos/{memo_id}/sign")
def sign_memo(memo_id: int, session=Depends(db), user: AppUser = Depends(current_user)):
    return _run(session, memo_mod.sign_memo, user, memo_id)


@app.get("/api/memos/{memo_id}/export.docx")
def export_memo(memo_id: int, version: int | None = None, session=Depends(db), user: AppUser = Depends(current_user)):
    data = _run(session, lambda s: memo_export.build_docx(memo_mod.get_memo(s, user, memo_id, version)))
    return Response(content=data, media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                    headers={"Content-Disposition": f'attachment; filename="memo-{memo_id}.docx"', "Cache-Control": "no-store"})


@app.get("/api/memos/{memo_id}/export.pdf")
def export_memo_pdf(memo_id: int, version: int | None = None, session=Depends(db), user: AppUser = Depends(current_user)):
    data = _run(session, lambda s: memo_pdf.build_pdf(memo_mod.get_memo(s, user, memo_id, version)))
    return Response(content=data, media_type="application/pdf",
                    headers={"Content-Disposition": f'attachment; filename="memo-{memo_id}.pdf"', "Cache-Control": "no-store"})


@app.get("/api/companies/{company_id}/matrix")
def company_matrix(company_id: int, basis: str = "consolidated", session=Depends(db), user: AppUser = Depends(current_user)):
    return _run(session, mtx.build_matrix, company_id, basis)


class NarrativeRequest(BaseModel):
    basis: str = "consolidated"
    force: bool = False


@app.get("/api/companies/{company_id}/matrix/narrative")
def matrix_narrative(company_id: int, basis: str = "consolidated", session=Depends(db), user: AppUser = Depends(current_user)):
    return _run(session, nar.latest, company_id, basis, user)


@app.post("/api/companies/{company_id}/matrix/narrative")
def matrix_narrative_write(company_id: int, body: NarrativeRequest, session=Depends(db), user: AppUser = Depends(current_user)):
    cfg_agent = load_llm_config().get("agent", {})

    def go(s):
        svc.require(user, "ask_agent")
        try:
            model = model_factory()
        except RuntimeError as exc:
            raise svc.RuleError(f"No model is configured for the agent: {exc}", 503)
        return nar.generate(s, user, company_id, body.basis, model, force=body.force,
                            daily_call_cap=cfg_agent.get("max_model_calls_per_day"))
    return _run(session, go)


@app.get("/api/runs")
def runs(company_id: int | None = None, session=Depends(db), user: AppUser = Depends(current_user)):
    return cmp.list_runs(session, company_id)


@app.get("/api/compare")
def compare_runs(a: int, b: int, session=Depends(db), user: AppUser = Depends(current_user)):
    return _run(session, cmp.compare, a, b)


class TypologyReview(BaseModel):
    decision: str
    note: str
    citations_verified: bool = False


class PartnerReview(BaseModel):
    decision: str
    note: str


class PublicRecord(BaseModel):
    kind: str
    title: str
    source_name: str
    summary: str
    tags: list[str]
    url: str | None = None
    published_on: str | None = None
    names_individual: bool = False


@app.get("/api/cases/{case_id}/typology")
def case_typology(case_id: int, session=Depends(db), user: AppUser = Depends(current_user)):
    return _run(session, typ.overview, case_id)


@app.post("/api/cases/{case_id}/typology/run")
def run_typology(case_id: int, session=Depends(db), user: AppUser = Depends(current_user)):
    return _run(session, typ.run_matching, user, case_id)


@app.post("/api/typology/{match_id}/review")
def review_typology(match_id: int, body: TypologyReview, session=Depends(db), user: AppUser = Depends(current_user)):
    return _run(session, typ.review_match, user, match_id, body.decision, body.note, body.citations_verified)


@app.post("/api/typology/{match_id}/partner-review")
def partner_review_typology(match_id: int, body: PartnerReview, session=Depends(db), user: AppUser = Depends(current_user)):
    return _run(session, typ.partner_review, user, match_id, body.decision, body.note)


@app.get("/api/companies/{company_id}/public-records")
def list_public_records(company_id: int, session=Depends(db), user: AppUser = Depends(current_user)):
    return {"items": [typ.record_row(i) for i in typ.record_items(session, company_id)], "tags": typ.record_tags(), "kinds": list(typ.KINDS)}


@app.post("/api/companies/{company_id}/public-records")
def add_public_record(company_id: int, body: PublicRecord, session=Depends(db), user: AppUser = Depends(current_user)):
    return _run(session, typ.add_record, user, company_id, body.model_dump())


@app.get("/api/dashboard")
def dashboard(session=Depends(db), user: AppUser = Depends(current_user)):
    return svc.dashboard(session)


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="127.0.0.1", port=8000)
