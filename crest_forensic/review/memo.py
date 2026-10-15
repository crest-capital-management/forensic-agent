"""Job 4: the research assessment memo (draft for a named human to edit and sign).

Version 1 uses NO AI model. Every sentence is filled from saved data with fixed wording: the case, the flags a reviewer accepted,
their figures and citations, and the reviewers' own decisions. The same wording rules as the agent apply: banned words are never
written (the text is withheld and a notice says so), every finding carries sources, an edited finding may not contain a number
that its sources do not contain, and the DRAFT line stays on until the owner signs.

Rules (from Job Spec 4 and MEMO_TEMPLATE_PROPOSAL.md):
  - only ACCEPTED flags enter. For a portfolio company the flag must also be escalated with the adviser's approval
    (REQUIRE_ADVISER_FOR_PORTFOLIO, suggested default, for the forensic lead to confirm);
  - every generate and every edit is a NEW saved version; nothing is edited in place;
  - if a flag decision, the scope or the limits' approval change, the memo is "out of date" and must be regenerated and reviewed;
  - the named owner (role memo_owner or forensic_lead) signs; signing locks the memo; nothing is sent from the tool.
"""
from __future__ import annotations

import copy
import datetime as dt
import hashlib
import json
import re
import secrets

from sqlalchemy import select
from sqlalchemy.orm import Session

from crest_forensic.agent.tools import Toolbox
from crest_forensic.db.models import AppUser, Case, Company, Flag, Memo, MemoVersion
from crest_forensic.guardrails.language import LEADS_NOT_PROOF, PUBLIC_DATA_LIMIT, banned_terms_in
from crest_forensic.review import memo_library as lib
from crest_forensic.review import service as svc
from crest_forensic.review.service import RuleError, require

DRAFT_LINE = "DRAFT - for human review"
# Annex D, standard text adopted 2026-10-14 (the forensic lead left the choice to the developer). The owner may replace it when editing a memo.
# Titles of the ICAI standards and the five-year retention are from public sources; paragraph numbers are not given.
ANNEX_D_DEFAULT = (
    "Documentation discipline follows the ICAI Forensic Accounting and Investigation Standards as firm practice: FAIS 110 (nature of the engagement), "
    "FAIS 120 (understanding the risk) and FAIS 130 (laws and regulations). This memo is a research assessment built on public filings. "
    "Record keeping: the sources behind each finding (annex B), the run and limits used (annex A), every version of this memo with its change log (annex C) "
    "and the reviewers' decisions are kept in the tool and are not edited after the fact. Under the SEBI (Research Analysts) Regulations, 2014 (Regulation 25) "
    "and, where it applies, the SEBI (Investment Advisers) Regulations, 2013 (Regulation 19), research records are kept for at least five years, on paper or "
    "electronically with digital signatures where a signature is needed, and for longer where a dispute or review is pending. The memo owner confirms which "
    "regime applies to this document before it leaves the firm."
)
REQUIRE_ADVISER_FOR_PORTFOLIO = True
OWNER_ROLES = ("memo_owner", "forensic_lead")
WITHHELD = "[text withheld: it contains wording this tool does not use. See the case record.]"
SOURCE_RULE = "annual report first, then the free finance data, then the paid API; a difference of more than 0.1% is shown as a conflict"
_NUM = re.compile(r"\d[\d,]*\.?\d*")


# ---------------------------------------------------------------------------------------------------------------------------
# helpers

def _clean(text: str | None, notices: list[str], where: str) -> str:
    text = (text or "").strip()
    bad = banned_terms_in(text)
    if bad:
        notices.append(f"{where}: text withheld because it used wording this tool does not use. Read the original in the case record.")
        return WITHHELD
    return text


def _numbers(text: str) -> set[str]:
    return {m.group(0).replace(",", "").rstrip(".") for m in _NUM.finditer(text or "")}


def _all_strings(node) -> list[str]:
    if isinstance(node, str):
        return [node]
    if isinstance(node, dict):
        return [s for v in node.values() for s in _all_strings(v)]
    if isinstance(node, list):
        return [s for v in node for s in _all_strings(v)]
    return []


def _display(session: Session, username: str | None) -> str:
    if not username:
        return ""
    u = session.execute(select(AppUser).where(AppUser.username == username)).scalars().first()
    return u.display_name if u else username


def _symbol(company: Company) -> str:
    raw = company.nse_symbol or company.sc_id or "CO"
    return re.sub(r"[^A-Za-z0-9]", "", raw).upper() or "CO"


# ---------------------------------------------------------------------------------------------------------------------------
# which flags may enter

def select_flags(session: Session, case: Case) -> tuple[list[dict], list[dict]]:
    """(flags that enter the memo, accepted flags left out and why)."""
    page = svc.case_page(session, case.id)
    included, left_out = [], []
    for f in page["flags"]:
        if not f["review"] or f["review"]["decision"] != "accept":
            continue
        esc = f["escalation"]
        if case.is_portfolio_company and REQUIRE_ADVISER_FOR_PORTFOLIO and not (esc and esc["state"] == "escalated"):
            left_out.append({"flag_id": f["id"], "check_id": f["check_id"], "financial_year": f["financial_year"],
                             "reason": "accepted, but a portfolio company flag needs an escalation approved by the adviser first"})
            continue
        included.append(f)
    return included, left_out


def scheme_hypotheses(session: Session, case: Case) -> dict:
    """Annex E (Job 3): scheme matches the forensic lead accepted (and a partner too, when a named individual is involved).
    Each one is a hypothesis for planning the next step. The references are kept apart because they carry the names of the
    published sources, which are not the tool's own wording."""
    from crest_forensic.typology import match as typ

    rows = []
    for m in typ.latest_batch(session, case.id):
        if not typ.usable_for_work_product(m):
            continue
        rows.append({
            "match_id": m.id, "scheme_id": m.scheme_id, "scheme_name": m.scheme_name, "class_label": m.class_label,
            "coverage_pct": round(m.coverage * 100),
            "present": [{"indicator": p["indicator"], "detail": p["detail"]} for p in m.present],
            "missing": [x["indicator"] for x in m.missing], "against": list(m.against),
            "innocent": list(m.innocent_explanations), "evidence": [{"text": e["text"], "public": e["public"]} for e in m.evidence_to_confirm],
            "lead": _display(session, m.reviewed_by), "partner": _display(session, m.partner_by) if m.partner_by else None,
            "citations_verified": bool(m.citations_verified), "label": "hypothesis",
        })
    refs = {m.scheme_id: [f"{c['title']}: {c['locator']}" for c in (m.citations["acfe"] + m.citations["fais"])]
            for m in typ.latest_batch(session, case.id) if typ.usable_for_work_product(m)}
    return {"matches": rows, "references": refs,
            "line": ("Scheme matches are hypotheses for planning the next step. They are not findings and do not say that anything wrong was done."
                     if rows else "No scheme match has been accepted by the forensic lead for this case.")}


def fingerprint(session: Session, case: Case, included: list[dict], scope_note: str) -> str:
    items = []
    for f in included:
        flag = session.get(Flag, f["id"])
        r = f["review"]
        items.append([f["id"], flag.content_hash, r["decision"], r["reviewer"], r["reason"], r["decided_at"],
                      (f["escalation"] or {}).get("state"), f["draft_config"]])
    hyp = scheme_hypotheses(session, case)
    items.append(["schemes", sorted((m["match_id"], m["lead"], m["partner"]) for m in hyp["matches"])])
    blob = json.dumps({"flags": items, "years": case.years, "reason": case.reason, "scope": scope_note,
                       "library": lib.LIBRARY_APPROVED, "portfolio": case.is_portfolio_company}, sort_keys=True, default=str)
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()


# ---------------------------------------------------------------------------------------------------------------------------
# building the content

def _limit_line(detail: dict) -> str:
    th = (detail.get("figures") or {}).get("thresholds_applied") or {}
    parts = [f"{lvl} {th[lvl]['value']}" for lvl in ("high", "medium", "low")
             if isinstance(th.get(lvl), dict) and th[lvl].get("value") is not None]
    base = (f"Check {detail['check_id']}, limit applied: {', '.join(parts)}." if parts
            else f"Check {detail['check_id']}, severity set by rule {detail['severity_rule_id']}.")
    return base + (" These limits have NOT been approved by the forensic lead (draft)." if detail["draft_config"] else " Limits approved by the forensic lead.")


def _finding(session: Session, case: Case, tb: Toolbox, f: dict, notices: list[str]) -> dict:
    detail = svc.flag_detail(session, case.id, f["id"])
    got = tb.t_get_flag(f["id"])
    refs = [got["ref"]] + [e["ref"] for e in got["evidence"]] + [i["ref"] for i in got["inputs"]]
    sources = []
    for ref in dict.fromkeys(refs):
        meta = tb.refs[ref]
        sources.append({"ref": ref, "label": meta["label"], "quote": meta.get("quote"), "page": meta.get("page"),
                        "printed_page": meta.get("printed_page")})
    r = f["review"]
    where = f"Finding {f['check_id']} {f['financial_year']}"
    return {
        "flag_id": f["id"], "check_id": f["check_id"], "financial_year": f["financial_year"], "basis": f["basis"],
        "severity": f["severity"], "materiality": f["materiality"], "evidence_confidence": f["evidence_confidence"],
        "text": _clean(f["what_observed"], notices, where),
        "limit_line": _limit_line(detail),
        "reviewer": {"by": r["reviewer"], "by_name": _display(session, r["reviewer"]), "at": r["decided_at"],
                     "reason": _clean(r["reason"], notices, where + " reviewer reason"),
                     "carried_from_earlier_run": bool(r.get("carried_from"))},
        "sources": sources, "standing_line": LEADS_NOT_PROOF,
    }


def build_content(session: Session, case: Case, owner: str, scope_note: str, reference: str = "") -> tuple[dict, str, list[dict]]:
    """The whole memo as data. Returns (content, input fingerprint, accepted flags left out)."""
    company = session.get(Company, case.company_id)
    included, left_out = select_flags(session, case)
    if not included:
        raise RuleError("No flags are ready for a memo yet: a memo uses only accepted flags"
                        + (" that the adviser has approved for escalation." if case.is_portfolio_company and left_out else "."))
    notices: list[str] = []
    tb = Toolbox(session, case)
    findings = [_finding(session, case, tb, f, notices) for f in included]
    check_ids = [f["check_id"] for f in findings]
    symbol = company.nse_symbol or company.sc_id or ""
    runs = svc._latest_runs(session, case.company_id)
    seen = [i.get("snapshot_fetched_at") for f in included
            for i in (svc.flag_detail(session, case.id, f["id"]).get("citation") or {}).get("inputs") or [] if i.get("snapshot_fetched_at")]
    as_of = (max(seen)[:10] if seen else max(r.started_at for r in runs).date().isoformat()) if (seen or runs) else ""
    approved = all(r.config_approved for r in runs) if runs else False
    scope_note = (scope_note or "").strip()
    reason = _clean(case.reason, notices, "Case reason")
    years = sorted(case.years)
    scope = [f"Assessment of {company.name} ({symbol}) for {', '.join(years)}. The case was opened for this reason: {reason}"]
    if scope_note:
        scope.append("Reviewer's scope decisions: " + _clean(scope_note, notices, "Scope note"))
    scope.append("This memo draws only on public filings saved in the tool and on decisions recorded by named reviewers. "
                 "It is not an audit, and it reaches no conclusion.")
    bg = [f"{company.name}, symbol {symbol or 'not saved'}"
          + (f", ISIN {company.isin}" if company.isin else "") + (f", sector {company.sector}" if company.sector else "") + "."]
    bg.append("CREST portfolio company: yes." if case.is_portfolio_company else "CREST portfolio company: no.")
    bg.append(f"Trigger for the review: {reason}")
    content = {
        "header": {
            "reference": reference, "company": company.name, "symbol": symbol, "company_id": company.company_id,
            "case_id": case.id, "years": years, "bases": sorted({f["basis"] for f in findings}),
            "owner": owner, "data_as_of": as_of, "limits_approved": approved,
            "limits_line": "Limits approved by the forensic lead." if approved else "DRAFT: the limits behind these findings have not been approved by the forensic lead.",
            "draft_line": DRAFT_LINE, "version_no": 0,
        },
        "scope": scope,
        "background": bg,
        "findings": findings,
        "open_questions": lib.questions_for(check_ids),
        "next_steps": lib.steps_for(check_ids),
        "ownership": {"owner": owner, "note": "A named human reviews, edits and signs this memo. Until signature it is a working draft and stays internal."},
        "annex_a": {
            "checks": [{"check_id": c, "name": lib.NAMES.get(c, c)} for c in sorted(set(check_ids))],
            "runs": [{"run_id": r.id, "basis": r.basis, "years": r.years, "config_approved": r.config_approved, "code_version": r.code_version}
                     for r in runs if r.basis in {f["basis"] for f in findings}],
            "source_rule": SOURCE_RULE,
            "library_line": ("Wording of the open questions and next steps has been approved by the forensic lead." if lib.LIBRARY_APPROVED
                             else "Wording of the open questions and next steps is a draft that the forensic lead has not approved."),
        },
        "annex_b": [s for f in findings for s in f["sources"]],
        "annex_d": {"text": ANNEX_D_DEFAULT, "supplied": True},
        "annex_e": scheme_hypotheses(session, case),
        "standing": [LEADS_NOT_PROOF, PUBLIC_DATA_LIMIT],
        "notices": notices,
    }
    return content, fingerprint(session, case, included, scope_note), left_out


# ---------------------------------------------------------------------------------------------------------------------------
# checks on a whole memo

def validate(content: dict) -> None:
    scan = dict(content)
    annex_e = dict(scan.get("annex_e") or {})
    annex_e.pop("references", None)               # names of published sources: not the tool's own wording
    scan["annex_e"] = annex_e
    bad = banned_terms_in(*[s for s in _all_strings(scan) if s != WITHHELD])
    if bad:
        raise RuleError("The memo contains wording this tool does not use: " + ", ".join(bad) + ". Rephrase it as what the filing shows.")
    if content.get("header", {}).get("draft_line") != DRAFT_LINE:
        raise RuleError("The DRAFT marker cannot be removed.")
    if not content.get("findings"):
        raise RuleError("A memo needs at least one finding.")
    for f in content["findings"]:
        if not any(not str(s.get("ref", "")).startswith("flag:") for s in f.get("sources") or []):
            raise RuleError(f"Finding {f.get('check_id')} {f.get('financial_year')} has no saved figure or filing page behind it. "
                            "Every claim needs a citation to a public source.")
        if not (f.get("text") or "").strip():
            raise RuleError(f"Finding {f.get('check_id')} {f.get('financial_year')} has no text.")
    if not any((s or "").strip() for s in content.get("scope", [])):
        raise RuleError("The scope section cannot be empty.")


def _apply_changes(old: dict, changes: dict) -> dict:
    """Only these parts may be edited by a person. Sources, figures, decisions and the DRAFT marker stay as generated."""
    new = copy.deepcopy(old)
    unknown = set(changes) - {"scope", "background", "findings", "open_questions", "next_steps", "annex_d"}
    if unknown:
        raise RuleError("These parts of the memo cannot be edited: " + ", ".join(sorted(unknown)) + ".")
    for key in ("scope", "background"):
        if key in changes:
            lines = [str(x).strip() for x in changes[key] if str(x).strip()]
            if not lines:
                raise RuleError(f"The {key} section cannot be empty.")
            new[key] = lines
    if "findings" in changes:
        by_id = {str(f["flag_id"]): f for f in new["findings"]}
        for fid, text in changes["findings"].items():
            f = by_id.get(str(fid))
            if f is None:
                raise RuleError(f"Flag {fid} is not in this memo.")
            allowed = _numbers(" ".join([f["text"], f["limit_line"]] + [s["label"] + " " + (s.get("quote") or "") for s in f["sources"]]))
            extra = sorted(n for n in _numbers(text) if n not in allowed)
            if extra:
                raise RuleError(f"The text for flag {fid} contains a number its sources do not contain: {', '.join(extra)}. "
                                "Every figure must come from the cited sources.")
            f["text"] = str(text).strip()
    if "open_questions" in changes:
        qs = []
        for q in changes["open_questions"]:
            if not str(q.get("text", "")).strip():
                continue
            if q.get("public_data") not in ("yes", "partly", "no"):
                raise RuleError("Each open question must say whether public data can close it: yes, partly or no.")
            qs.append({"text": str(q["text"]).strip(), "public_data": q["public_data"], "how": str(q.get("how", "")).strip(),
                       "check_id": q.get("check_id")})
        new["open_questions"] = qs
    if "next_steps" in changes:
        ns = changes["next_steps"]
        new["next_steps"] = {k: [str(x).strip() for x in ns.get(k, []) if str(x).strip()] for k in ("public", "engagement")}
    if "annex_d" in changes:
        text = str(changes["annex_d"]).strip()
        new["annex_d"] = {"text": text, "supplied": bool(text)}
    return new


# ---------------------------------------------------------------------------------------------------------------------------
# lifecycle

def _memo(session: Session, memo_id: int) -> Memo:
    memo = session.get(Memo, memo_id)
    if memo is None:
        raise RuleError("Memo not found.", 404)
    return memo


def _versions(session: Session, memo_id: int) -> list[MemoVersion]:
    return list(session.execute(select(MemoVersion).where(MemoVersion.memo_id == memo_id).order_by(MemoVersion.version_no)).scalars())


def _save_version(session: Session, memo: Memo, user: AppUser, kind: str, content: dict, fp: str, note: str) -> MemoVersion:
    n = len(_versions(session, memo.id)) + 1
    content = copy.deepcopy(content)
    content["header"]["version_no"] = n
    content["header"]["reference"] = memo.reference
    row = MemoVersion(memo_id=memo.id, version_no=n, kind=kind, created_by=user.username, content=content, input_hash=fp, change_note=note)
    session.add(row)
    session.flush()
    return row


def _can_edit(user: AppUser, memo: Memo) -> bool:
    return user.username == memo.owner or user.role == "forensic_lead"


def _require_unlocked(memo: Memo) -> None:
    if memo.signed_version_id is not None:
        raise RuleError("This memo is signed and locked. Start a new memo to change it.", 409)


def create_memo(session: Session, user: AppUser, case_id: int, owner: str, scope_note: str = "") -> dict:
    require(user, "create_memo")
    case = svc._case(session, case_id)
    owner_user = session.execute(select(AppUser).where(AppUser.username == owner)).scalars().first()
    if owner_user is None or not owner_user.active or owner_user.role not in OWNER_ROLES:
        raise RuleError("The memo owner must be an active person with the memo owner or forensic lead role.")
    content, fp, _ = build_content(session, case, _display(session, owner), scope_note)
    validate(content)
    memo = Memo(case_id=case.id, reference=f"pending-{secrets.token_hex(6)}", owner=owner, scope_note=(scope_note or "").strip(),
                created_by=user.username)
    session.add(memo)
    session.flush()
    company = session.get(Company, case.company_id)
    memo.reference = f"CREST-{_symbol(company)}-{dt.date.today().year}-{memo.id:03d}"
    from crest_forensic.review import access
    access.add_member_row(session, case.id, owner, user.username)       # the memo's owner must be able to open the case
    _save_version(session, memo, user, "generated", content, fp, "First draft generated from the accepted flags.")
    return get_memo(session, user, memo.id)


def regenerate(session: Session, user: AppUser, memo_id: int, note: str = "") -> dict:
    memo = _memo(session, memo_id)
    if not _can_edit(user, memo):
        raise RuleError("Only the memo owner or the forensic lead can regenerate this memo.", 403)
    _require_unlocked(memo)
    case = svc._case(session, memo.case_id)
    content, fp, _ = build_content(session, case, _display(session, memo.owner), memo.scope_note)
    validate(content)
    _save_version(session, memo, user, "generated", content, fp, (note or "").strip() or "Regenerated from the current accepted flags.")
    return get_memo(session, user, memo.id)


def edit_memo(session: Session, user: AppUser, memo_id: int, changes: dict, note: str) -> dict:
    memo = _memo(session, memo_id)
    if not _can_edit(user, memo):
        raise RuleError("Only the memo owner or the forensic lead can edit this memo.", 403)
    _require_unlocked(memo)
    if not (note or "").strip():
        raise RuleError("Say what you changed: every edit is logged with a short note.")
    latest = _versions(session, memo.id)[-1]
    new = _apply_changes(latest.content, changes or {})
    validate(new)
    _save_version(session, memo, user, "edited", new, latest.input_hash, note.strip())
    return get_memo(session, user, memo.id)


def sign_memo(session: Session, user: AppUser, memo_id: int) -> dict:
    memo = _memo(session, memo_id)
    if user.username != memo.owner:
        raise RuleError("Only the named owner of the memo can sign it.", 403)
    _require_unlocked(memo)
    latest = _versions(session, memo.id)[-1]
    case = svc._case(session, memo.case_id)
    included, _ = select_flags(session, case)
    if fingerprint(session, case, included, memo.scope_note) != latest.input_hash:
        raise RuleError("The flags or decisions changed since this draft was made. Regenerate it and review it before signing.", 409)
    validate(latest.content)
    memo.signed_version_id, memo.signed_by, memo.signed_at = latest.id, user.username, dt.datetime.now(dt.timezone.utc)
    session.flush()
    return get_memo(session, user, memo.id)


# ---------------------------------------------------------------------------------------------------------------------------
# reading

def get_memo(session: Session, user: AppUser, memo_id: int, version_no: int | None = None) -> dict:
    memo = _memo(session, memo_id)
    versions = _versions(session, memo.id)
    shown = next((v for v in versions if v.version_no == version_no), versions[-1]) if version_no else versions[-1]
    case = svc._case(session, memo.case_id)
    included, left_out = select_flags(session, case)
    out_of_date = fingerprint(session, case, included, memo.scope_note) != versions[-1].input_hash
    signed = memo.signed_version_id is not None
    return {
        "id": memo.id, "case_id": memo.case_id, "reference": memo.reference, "owner": memo.owner,
        "owner_name": _display(session, memo.owner), "created_by": memo.created_by, "created_at": memo.created_at.isoformat(),
        "scope_note": memo.scope_note, "status": "signed" if signed else "draft",
        "banner": (f"Signed by {_display(session, memo.signed_by)} on {memo.signed_at.date().isoformat()}" if signed else DRAFT_LINE),
        "signed_by": memo.signed_by, "signed_at": memo.signed_at.isoformat() if memo.signed_at else None,
        "signed_version_no": next((v.version_no for v in versions if v.id == memo.signed_version_id), None),
        "out_of_date": out_of_date and not signed, "left_out": left_out,
        "shown_version_no": shown.version_no, "latest_version_no": versions[-1].version_no, "content": shown.content,
        "versions": [{"version_no": v.version_no, "kind": v.kind, "created_by": v.created_by, "created_by_name": _display(session, v.created_by),
                      "created_at": v.created_at.isoformat(), "change_note": v.change_note} for v in versions],
        "can_edit": (not signed) and _can_edit(user, memo), "can_sign": (not signed) and user.username == memo.owner,
    }


def list_memos(session: Session, case_id: int) -> list[dict]:
    svc._case(session, case_id)
    out = []
    for m in session.execute(select(Memo).where(Memo.case_id == case_id).order_by(Memo.id.desc())).scalars():
        vs = _versions(session, m.id)
        out.append({"id": m.id, "reference": m.reference, "owner": m.owner, "owner_name": _display(session, m.owner),
                    "status": "signed" if m.signed_version_id is not None else "draft", "versions": len(vs),
                    "updated_at": vs[-1].created_at.isoformat(), "created_at": m.created_at.isoformat()})
    return out


def list_all(session: Session, user: AppUser | None = None) -> list[dict]:
    """Every memo of the cases the user may open, newest first (for the Memos page)."""
    from crest_forensic.review import access

    allowed = None if user is None else access.accessible_case_ids(session, user)
    out = []
    for m in session.execute(select(Memo).order_by(Memo.id.desc())).scalars():
        if allowed is not None and m.case_id not in allowed:
            continue
        case = session.get(Case, m.case_id)
        company = session.get(Company, case.company_id) if case else None
        vs = _versions(session, m.id)
        out.append({"id": m.id, "reference": m.reference, "case_id": m.case_id, "company": company.name if company else "",
                    "owner": m.owner, "owner_name": _display(session, m.owner),
                    "status": "signed" if m.signed_version_id is not None else "draft", "versions": len(vs),
                    "created_at": m.created_at.isoformat(), "updated_at": vs[-1].created_at.isoformat()})
    return out


def owner_choices(session: Session) -> list[dict]:
    return [{"username": u.username, "display_name": u.display_name, "role": u.role}
            for u in session.execute(select(AppUser).where(AppUser.active.is_(True), AppUser.role.in_(OWNER_ROLES)).order_by(AppUser.id)).scalars()]
