"""Per-case access (who may open which case).

Rules (decided 2026-10-15; the forensic lead may change them):
  - The FORENSIC LEAD sees every case: the lead owns the limits, reviews every scheme match and signs off, so needs the whole picture.
  - Everyone else sees a case only if they are a MEMBER of it. The person who opens a case is its first member; a memo's owner is added
    when the memo is drafted; the forensic lead or the case's creator can add and remove members.
  - An ADVISER can also open a portfolio-company case that has an escalation (that is the adviser's job: approving it).
  - A PARTNER can also open a case that has a scheme match naming an individual (that is the partner's job: reviewing it).
  - Someone without access gets "Case not found", the same answer as for a case that does not exist: the tool does not reveal that a case exists.
  - Company-level public data (the company list, flag counts, the multi-year matrix, compare runs, the dashboard totals) is not case data
    and stays visible to every signed-in user. What is protected is the case itself: its reason and notes, flag decisions and reasons,
    escalations, chats with the agent, memos and scheme matches.
  - Removing a member keeps the record (removed_by, removed_at). The creator cannot be removed.
"""
from __future__ import annotations

import datetime as dt

from sqlalchemy import select
from sqlalchemy.orm import Session

from crest_forensic.db.models import AppUser, Case, CaseMember, Escalation, Memo, TypologyMatch
from crest_forensic.review.service import RuleError


def active_members(session: Session, case_id: int) -> list[CaseMember]:
    return session.execute(select(CaseMember).where(CaseMember.case_id == case_id, CaseMember.removed_at.is_(None))
                           .order_by(CaseMember.id)).scalars().all()


def is_member(session: Session, case_id: int, username: str) -> bool:
    return session.execute(select(CaseMember.id).where(
        CaseMember.case_id == case_id, CaseMember.username == username, CaseMember.removed_at.is_(None))).first() is not None


def can_access(session: Session, user: AppUser, case: Case) -> bool:
    if user.role == "forensic_lead" or is_member(session, case.id, user.username):
        return True
    if user.role == "adviser":
        return bool(case.is_portfolio_company) and session.execute(select(Escalation.id).where(Escalation.case_id == case.id)).first() is not None
    if user.role == "partner":
        return session.execute(select(TypologyMatch.id).where(
            TypologyMatch.case_id == case.id, TypologyMatch.partner_status != "not_needed")).first() is not None
    return False


def ensure_access(session: Session, user: AppUser, case_id: int) -> Case:
    case = session.get(Case, case_id)
    if case is None or not can_access(session, user, case):
        raise RuleError("Case not found.", 404)                    # the same answer whether it exists or not
    return case


def accessible_case_ids(session: Session, user: AppUser) -> set[int]:
    return {c.id for c in session.execute(select(Case)).scalars() if can_access(session, user, c)}


def add_member_row(session: Session, case_id: int, username: str, added_by: str) -> bool:
    """Add a member if not already one. Returns True if a row was added. No permission check: used by the app's own rules."""
    if is_member(session, case_id, username):
        return False
    session.add(CaseMember(case_id=case_id, username=username, added_by=added_by))
    session.flush()
    return True


def _may_manage(user: AppUser, case: Case) -> bool:
    return user.role == "forensic_lead" or user.username == case.created_by


def overview(session: Session, user: AppUser, case_id: int) -> dict:
    case = ensure_access(session, user, case_id)
    members = active_members(session, case_id)
    names = {u.username: u for u in session.execute(select(AppUser)).scalars()}
    can_manage = _may_manage(user, case)
    return {
        "case_id": case_id, "can_manage": can_manage,
        "members": [{"username": m.username, "display_name": names[m.username].display_name if m.username in names else m.username,
                     "role": names[m.username].role if m.username in names else None, "added_by": m.added_by,
                     "added_at": m.added_at.isoformat(), "is_creator": m.username == case.created_by} for m in members],
        "candidates": ([{"username": u.username, "display_name": u.display_name, "role": u.role}
                        for u in names.values() if u.active and u.role != "forensic_lead" and not any(m.username == u.username for m in members)]
                       if can_manage else []),
        "also_see": [
            "Forensic leads see every case.",
            "An adviser sees a portfolio-company case once a flag in it has been escalated.",
            "A partner sees a case that has a scheme match naming an individual.",
        ],
    }


def add_member(session: Session, user: AppUser, case_id: int, username: str) -> dict:
    case = ensure_access(session, user, case_id)
    if not _may_manage(user, case):
        raise RuleError("Only the forensic lead or the person who opened the case can change who has access.", 403)
    target = session.execute(select(AppUser).where(AppUser.username == username)).scalars().first()
    if target is None or not target.active:
        raise RuleError("That user does not exist or is switched off.", 404)
    if target.role == "forensic_lead":
        raise RuleError("Forensic leads already see every case.")
    if not add_member_row(session, case_id, username, user.username):
        raise RuleError("That person already has access.")
    return overview(session, user, case_id)


def remove_member(session: Session, user: AppUser, case_id: int, username: str) -> dict:
    case = ensure_access(session, user, case_id)
    if not _may_manage(user, case):
        raise RuleError("Only the forensic lead or the person who opened the case can change who has access.", 403)
    if username == case.created_by:
        raise RuleError("The person who opened the case cannot be removed from it.")
    row = session.execute(select(CaseMember).where(CaseMember.case_id == case_id, CaseMember.username == username,
                                                   CaseMember.removed_at.is_(None))).scalars().first()
    if row is None:
        raise RuleError("That person is not a member of this case.", 404)
    row.removed_by, row.removed_at = user.username, dt.datetime.now(dt.timezone.utc)
    session.flush()
    return overview(session, user, case_id)


def case_id_of(session: Session, kind: str, ident: int) -> int | None:
    """Resolve the case a memo, scheme match, escalation or flag-in-case URL points at."""
    if kind == "case_id":
        return ident
    model = {"memo_id": Memo, "match_id": TypologyMatch, "escalation_id": Escalation}.get(kind)
    row = session.get(model, ident) if model else None
    return None if row is None else row.case_id
