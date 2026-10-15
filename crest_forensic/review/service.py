"""Review-app rules, enforced in code (Build Plan 11.2). The web layer only calls these.

- Reviews are append-only; a flag's review status is its latest review.
- A reason is required for every accept or reject.
- Escalation needs an accepted flag; on a portfolio company it also needs the adviser's approval.
- Only the roles named in PERMISSIONS can do each thing; an analyst can never approve an escalation.
"""
from __future__ import annotations

import datetime as dt

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from crest_forensic.db.models import (
    CaseEvent,
    ROLES, AppUser, Case, Company, Escalation, Flag, GuardrailEvent, Review, Run, WatchlistItem,
)

PERMISSIONS: dict[str, set[str]] = {
    "create_case": {"analyst", "forensic_lead"},
    "review_flag": {"analyst", "forensic_lead"},
    "request_escalation": {"analyst", "forensic_lead"},
    "approve_escalation": {"adviser"},
    "edit_config": {"forensic_lead"},      # limits and severity rules belong to the forensic lead
    "approve_config": {"forensic_lead"},
    "ask_agent": {"analyst", "forensic_lead"},
    "close_case": {"analyst", "forensic_lead"},
    "create_memo": {"analyst", "forensic_lead", "memo_owner"},   # Job 4: draft a research memo from accepted flags
    "run_typology": {"analyst", "forensic_lead"},          # Job 3: match accepted flags to the scheme library
    "review_typology": {"forensic_lead"},                  # the lead reviews every match
    "partner_review": {"partner"},                         # a match that names an individual
    "add_public_record": {"analyst", "forensic_lead"},
    "manage_users": {"forensic_lead"},      # create users, reset passwords, switch accounts off
    "view": set(ROLES),
}
SEVERITY_ORDER = {"high": 0, "medium": 1, "low": 2}
MATERIALITY_ORDER = {"material": 0, "not_assessed": 1, "not_material": 2}


class RuleError(Exception):
    """A rule was broken; `status` is the HTTP code the web layer should answer with."""

    def __init__(self, message: str, status: int = 400) -> None:
        super().__init__(message)
        self.status = status


def require(user: AppUser, action: str) -> None:
    if user.role not in PERMISSIONS[action]:
        raise RuleError(f"Role '{user.role}' is not allowed to {action.replace('_', ' ')}.", 403)


def _case(session: Session, case_id: int) -> Case:
    case = session.get(Case, case_id)
    if case is None:
        raise RuleError("Case not found.", 404)
    return case


def closure(session: Session, case: Case) -> dict | None:
    """The newest closing event, if the case is closed now."""
    ev = session.execute(select(CaseEvent).where(CaseEvent.case_id == case.id).order_by(CaseEvent.id.desc())).scalars().first()
    if case.status != "closed" or ev is None or ev.action != "closed":
        return None
    return {"by": ev.by, "reason": ev.reason, "at": ev.at.isoformat()}


def case_status(session: Session, case_id: int) -> dict:
    case = _case(session, case_id)
    return {"status": case.status, "closure": closure(session, case)}


def ensure_open(case: Case) -> None:
    if case.status == "closed":
        raise RuleError("This case is closed. Reopen it to continue.", 409)


def close_case(session: Session, user: AppUser, case_id: int, reason: str) -> dict:
    require(user, "close_case")
    case = _case(session, case_id)
    if case.status == "closed":
        raise RuleError("This case is already closed.")
    if not (reason or "").strip():
        raise RuleError("A reason for closing the case is required.")
    session.add(CaseEvent(case_id=case.id, action="closed", by=user.username, reason=reason.strip()))
    case.status = "closed"
    session.flush()
    return {"status": "closed", "closure": closure(session, case)}


def reopen_case(session: Session, user: AppUser, case_id: int, reason: str) -> dict:
    require(user, "close_case")
    case = _case(session, case_id)
    if case.status != "closed":
        raise RuleError("This case is not closed.")
    if not (reason or "").strip():
        raise RuleError("A reason for reopening the case is required.")
    session.add(CaseEvent(case_id=case.id, action="reopened", by=user.username, reason=reason.strip()))
    case.status = "open"
    session.flush()
    return {"status": "open", "closure": None}


def create_case(session: Session, user: AppUser, company_id: int, years: list[str], reason: str,
                exposure_note: str | None = None, is_portfolio_company: bool = False, name: str | None = None) -> Case:
    require(user, "create_case")
    if session.get(Company, company_id) is None:
        raise RuleError("Company not found.", 404)
    if not reason.strip():
        raise RuleError("A reason for opening the case is required.")
    if not years:
        raise RuleError("Choose at least one financial year.")
    name = " ".join((name or "").split())[:120] or None          # one line, at most 120 characters, optional
    case = Case(company_id=company_id, years=years, reason=reason.strip(), exposure_note=exposure_note,
                is_portfolio_company=is_portfolio_company, created_by=user.username, name=name)
    session.add(case)
    session.flush()
    from crest_forensic.review import access
    access.add_member_row(session, case.id, user.username, user.username)      # the person who opens a case is its first member
    session.flush()
    return case


def latest_decision(session: Session, flag_id: int) -> Review | None:
    return session.execute(select(Review).where(Review.flag_id == flag_id)
                           .order_by(Review.id.desc())).scalars().first()


def effective_review(session: Session, flag: Flag, run: Run) -> tuple[Review | None, Flag | None]:
    """A flag's own latest decision. If it has none, the decision on an IDENTICAL flag from an earlier run of the same
    company and basis (same check, year and content hash: same figures, evidence and severity), shown as carried over.
    A flag whose figures changed in any way has a different hash, so it is NOT carried over and needs a fresh look."""
    own = latest_decision(session, flag.id)
    if own is not None:
        return own, None
    row = session.execute(
        select(Review, Flag).join(Flag, Flag.id == Review.flag_id).join(Run, Run.id == Flag.run_id)
        .where(Flag.content_hash == flag.content_hash, Flag.id < flag.id, Flag.check_id == flag.check_id,
               Flag.financial_year == flag.financial_year, Run.company_id == run.company_id, Run.basis == run.basis)
        .order_by(Review.id.desc()).limit(1)).first()
    return (row[0], row[1]) if row else (None, None)


def escalation_for(session: Session, case: Case, flag: Flag, carried: Flag | None) -> dict | None:
    """The flag's own escalation, or the one on the identical earlier flag its decision was carried over from."""
    own = escalation_state(session, case, flag.id)
    if own is None and carried is not None:
        return escalation_state(session, case, carried.id)
    return own


def escalation_state(session: Session, case: Case, flag_id: int) -> dict | None:
    esc = session.execute(select(Escalation).where(Escalation.flag_id == flag_id, Escalation.case_id == case.id)
                          .order_by(Escalation.id.desc())).scalars().first()
    if esc is None:
        return None
    needs_adviser = case.is_portfolio_company
    approved = esc.adviser_approval_by is not None
    return {"id": esc.id, "requested_by": esc.requested_by, "note": esc.note, "needs_adviser": needs_adviser,
            "adviser_approval_by": esc.adviser_approval_by,
            "state": "escalated" if (approved or not needs_adviser) else "awaiting_adviser"}


def _latest_runs(session: Session, company_id: int) -> list[Run]:
    """The newest run for each basis (consolidated / standalone). Older runs are kept but not shown here."""
    runs = session.execute(select(Run).where(Run.company_id == company_id).order_by(Run.id.desc())).scalars().all()
    seen, out = set(), []
    for r in runs:
        if r.basis not in seen:
            seen.add(r.basis)
            out.append(r)
    return out


def _flag_row(session: Session, case: Case, flag: Flag, run: Run) -> dict:
    review, carried = effective_review(session, flag, run)
    return {
        "id": flag.id, "run_id": flag.run_id, "basis": run.basis, "check_id": flag.check_id,
        "financial_year": flag.financial_year, "what_observed": flag.what_observed, "technique": flag.technique,
        "severity": flag.severity, "severity_rule_id": flag.severity_rule_id,
        "materiality": (flag.materiality or {}).get("label"), "evidence_confidence": flag.evidence_confidence,
        "draft_config": not run.config_approved,
        "review": None if review is None else {"decision": review.decision, "reviewer": review.reviewer,
                                               "reason": review.reason, "decided_at": review.decided_at.isoformat(),
                                               "carried_from": None if carried is None else {"flag_id": carried.id, "run_id": carried.run_id}},
        "escalation": escalation_for(session, case, flag, carried),
    }


def duplicate_of(session: Session, case: Case) -> int | None:
    """The id of the earliest EARLIER case on the same company with the same set of years, else None (shown as a "duplicate" label)."""
    for other in session.execute(select(Case).where(Case.company_id == case.company_id, Case.id < case.id).order_by(Case.id)).scalars():
        if set(other.years or []) == set(case.years or []):
            return other.id
    return None


def case_page(session: Session, case_id: int) -> dict:
    case = _case(session, case_id)
    company = session.get(Company, case.company_id)
    runs = _latest_runs(session, case.company_id)
    flags = []
    for run in runs:
        for f in session.execute(select(Flag).where(Flag.run_id == run.id)).scalars():
            if f.financial_year in case.years:
                flags.append(_flag_row(session, case, f, run))
    flags.sort(key=lambda r: (SEVERITY_ORDER.get(r["severity"], 9), MATERIALITY_ORDER.get(r["materiality"], 9),
                              r["check_id"], r["financial_year"]))
    notes = []
    for run in runs:
        for g in session.execute(select(GuardrailEvent).where(GuardrailEvent.run_id == run.id)).scalars():
            notes.append({"run_id": run.id, "check_id": g.check_id, "financial_year": g.financial_year,
                          "guardrail": g.guardrail, "detail": g.detail})
    return {
        "case": {"id": case.id, "name": case.name, "company": company.name, "company_id": company.company_id, "years": case.years,
                 "reason": case.reason, "exposure_note": case.exposure_note,
                 "is_portfolio_company": case.is_portfolio_company, "status": case.status,
                 "created_by": case.created_by, "created_at": case.created_at.isoformat(),
                 "closure": closure(session, case), "duplicate_of": duplicate_of(session, case)},
        "runs": [{"id": r.id, "basis": r.basis, "years": r.years, "started_at": r.started_at.isoformat(),
                  "config_approved": r.config_approved, "flags_created": r.flags_created,
                  "flags_dropped": r.flags_dropped, "code_version": r.code_version} for r in runs],
        "flags": flags,
        "data_quality_notes": notes,
        "counts": {"total": len(flags), "unreviewed": sum(1 for f in flags if f["review"] is None),
                   "accepted": sum(1 for f in flags if f["review"] and f["review"]["decision"] == "accept"),
                   "rejected": sum(1 for f in flags if f["review"] and f["review"]["decision"] == "reject")},
    }


def list_cases(session: Session, user: AppUser | None = None) -> list[dict]:
    """Newest first. With a user: only the cases that user may open (see review/access.py)."""
    from crest_forensic.review import access

    allowed = None if user is None else access.accessible_case_ids(session, user)
    out = []
    for case in session.execute(select(Case).order_by(Case.id.desc())).scalars():
        if allowed is not None and case.id not in allowed:
            continue
        page = case_page(session, case.id)
        escalated = any(f["escalation"] and f["escalation"]["state"] in ("escalated", "awaiting_adviser")
                        for f in page["flags"])
        reviewed = page["counts"]["total"] > page["counts"]["unreviewed"]
        status = "closed" if case.status == "closed" else "escalated" if escalated else ("in_review" if reviewed else case.status)
        out.append({**page["case"], "status": status, "counts": page["counts"]})
    return out


def flag_detail(session: Session, case_id: int, flag_id: int) -> dict:
    case = _case(session, case_id)
    flag = session.get(Flag, flag_id)
    run = session.get(Run, flag.run_id) if flag else None
    if flag is None or run.company_id != case.company_id:
        raise RuleError("Flag not found for this case.", 404)
    reviews = session.execute(select(Review).where(Review.flag_id == flag_id, Review.case_id == case_id)
                              .order_by(Review.id)).scalars().all()
    return {
        **_flag_row(session, case, flag, run),
        "location": flag.location, "materiality_detail": flag.materiality, "figures": flag.figures,
        "citation": flag.citation, "content_hash": flag.content_hash,
        "history": [{"decision": r.decision, "reviewer": r.reviewer, "reason": r.reason,
                     "decided_at": r.decided_at.isoformat()} for r in reviews],
        "disclaimer": "Statistical lead only: most anomalies have innocent explanations. "
                      "Public data cannot show the reason.",
    }


def review_flag(session: Session, user: AppUser, case_id: int, flag_id: int, decision: str, reason: str) -> Review:
    require(user, "review_flag")
    ensure_open(_case(session, case_id))
    flag_detail(session, case_id, flag_id)  # also checks the flag belongs to this case
    if decision not in ("accept", "reject"):
        raise RuleError("Decision must be 'accept' or 'reject'.")
    if not reason.strip():
        raise RuleError("A reason is required for every accept or reject.")
    row = Review(flag_id=flag_id, case_id=case_id, reviewer=user.username, decision=decision, reason=reason.strip())
    session.add(row)
    session.flush()
    return row


def request_escalation(session: Session, user: AppUser, case_id: int, flag_id: int, note: str) -> dict:
    require(user, "request_escalation")
    case = _case(session, case_id)
    ensure_open(case)
    flag_detail(session, case_id, flag_id)
    flag = session.get(Flag, flag_id)
    last, carried = effective_review(session, flag, session.get(Run, flag.run_id))
    if last is None or last.decision != "accept":
        raise RuleError("Only a flag that a reviewer has accepted can be escalated.")
    if not note.strip():
        raise RuleError("A note explaining the escalation is required.")
    if escalation_for(session, case, flag, carried):
        raise RuleError("This flag already has an escalation.")
    session.add(Escalation(flag_id=flag_id, case_id=case_id, requested_by=user.username, note=note.strip()))
    session.flush()
    return escalation_state(session, case, flag_id)


def approve_escalation(session: Session, user: AppUser, escalation_id: int) -> dict:
    require(user, "approve_escalation")
    esc = session.get(Escalation, escalation_id)
    if esc is None:
        raise RuleError("Escalation not found.", 404)
    case = _case(session, esc.case_id)
    if not case.is_portfolio_company:
        raise RuleError("Adviser approval is only needed for portfolio companies.")
    if esc.adviser_approval_by:
        raise RuleError("Already approved.")
    esc.adviser_approval_by = user.username
    esc.approved_at = dt.datetime.now(dt.timezone.utc)
    session.flush()
    return escalation_state(session, case, esc.flag_id)


def dashboard(session: Session) -> dict:
    """Screen 10, from real data: reviewer acceptance, citation completeness."""
    total_flags = 0
    cited = 0
    for f in session.execute(select(Flag)).scalars():
        total_flags += 1
        c = f.citation or {}
        if c.get("evidence") or c.get("inputs") or c.get("filings") or c.get("shareholding") or c.get("prices") or c.get("auditor_fees"):
            cited += 1
    latest: dict[int, str] = {}   # each flag's latest decision
    for r in session.execute(select(Review).order_by(Review.id)).scalars():
        latest[r.flag_id] = r.decision
    accepted = sum(1 for d in latest.values() if d == "accept")
    rejected = sum(1 for d in latest.values() if d == "reject")
    decided = accepted + rejected
    return {
        "flags_total": total_flags,
        "flags_with_citation_pct": round(100 * cited / total_flags, 1) if total_flags else None,
        "flags_decided": decided, "accepted": accepted, "rejected": rejected,
        "acceptance_rate_pct": round(100 * accepted / decided, 1) if decided else None,
        "false_alarm_rate_pct": round(100 * rejected / decided, 1) if decided else None,
        "note": "Rates use each flag's latest decision. Small numbers: treat as indicative only.",
    }


def ensure_default_users(session: Session) -> None:
    """Placeholder identities for development; real sign-in comes later."""
    defaults = [("analyst1", "Analyst (dev)", "analyst"), ("lead1", "Forensic lead (dev)", "forensic_lead"),
                ("adviser1", "Adviser (dev)", "adviser"), ("partner1", "Partner (dev)", "partner"),
                ("owner1", "Memo owner (dev)", "memo_owner")]
    for username, name, role in defaults:
        if session.execute(select(AppUser).where(AppUser.username == username)).scalars().first() is None:
            try:
                with session.begin_nested():   # two requests can seed at once; the loser just skips
                    session.add(AppUser(username=username, display_name=name, role=role))
            except IntegrityError:
                pass
    session.flush()


def home(session: Session, user: AppUser) -> list[dict]:
    """Home screen: one row per company, with its flag counts from the newest run of each basis."""
    from crest_forensic.review import access

    allowed = access.accessible_case_ids(session, user)
    watched = {w.company_id for w in session.execute(
        select(WatchlistItem).where(WatchlistItem.username == user.username)).scalars()}
    rows = []
    for c in session.execute(select(Company).order_by(Company.name)).scalars():
        runs = _latest_runs(session, c.company_id)
        counts = {"high": 0, "medium": 0, "low": 0}
        for run in runs:
            for f in session.execute(select(Flag).where(Flag.run_id == run.id)).scalars():
                counts[f.severity] = counts.get(f.severity, 0) + 1
        cases = [k for k in session.execute(select(Case).where(Case.company_id == c.company_id).order_by(Case.id.desc())).scalars().all()
                 if k.id in allowed]                                 # only the cases this user may open
        rows.append({
            "company_id": c.company_id, "type": "Stock", "symbol": c.nse_symbol or c.sc_id or "", "name": c.name,
            "sector": c.sector, "supported_status": c.supported_status,
            "flags": counts, "flags_total": sum(counts.values()),
            "last_screen": max((r.started_at for r in runs), default=None) and max(r.started_at for r in runs).isoformat(),
            "draft": any(not r.config_approved for r in runs),
            "cases": len(cases), "latest_case_id": cases[0].id if cases else None,
            "is_portfolio": any(k.is_portfolio_company for k in cases), "in_watchlist": c.company_id in watched,
        })
    return rows


def set_watchlist(session: Session, user: AppUser, company_id: int, watch: bool) -> dict:
    if session.get(Company, company_id) is None:
        raise RuleError("Company not found.", 404)
    existing = session.execute(select(WatchlistItem).where(
        WatchlistItem.username == user.username, WatchlistItem.company_id == company_id)).scalars().first()
    if watch and existing is None:
        session.add(WatchlistItem(username=user.username, company_id=company_id))
    elif not watch and existing is not None:
        session.delete(existing)
    session.flush()
    return {"company_id": company_id, "in_watchlist": watch}
