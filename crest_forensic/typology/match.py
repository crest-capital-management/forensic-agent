"""Job 3: match the flags a reviewer accepted, and the public-record items people have added, against the scheme library.

Rules (Job Spec 3, Build Plan section 12):
- only flags a reviewer ACCEPTED count (a flag labelled not material never counts); public-record items count by their tags;
- a scheme is ranked by COVERAGE of its whole pattern (present indicators / all indicators), and only with at least min_present present;
- missing indicators are listed, facts that cut against a scheme are kept (checks that ran and raised nothing), innocent explanations and
  the evidence that would confirm or refute it are always shown, with what is NOT available in the public domain marked;
- every match is a hypothesis, carries references (a scheme without references is refused), and a match that involves a named individual
  (a public-record item marked so) needs a partner's review as well as the forensic lead's;
- the tool's own wording never uses the words the banned-language guard blocks; nothing here says that a wrong was done or by whom.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

import yaml
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from crest_forensic.db.models import (
    AppUser, Case, CheckResultRow, Flag, PublicRecordItem, TypologyMatch,
)
from crest_forensic.guardrails.language import banned_terms_in
from crest_forensic.review import service as svc
from crest_forensic.review.service import RuleError, require

SCHEMES_PATH = Path(__file__).resolve().parent / "schemes.yaml"
KINDS = ("enforcement_order", "tribunal", "announcement", "news", "filing_analysis", "other")
HYPOTHESIS = "Hypothesis for planning the next step. It is not a finding and does not say that anything wrong was done."


def load_schemes(path: Path = SCHEMES_PATH) -> dict:
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def record_tags(library: dict | None = None) -> list[str]:
    library = library or load_schemes()
    return sorted({i["record_tag"] for s in library["schemes"] for i in s["indicators"] if i.get("record_tag")})


# ---------------------------------------------------------------------------------------------------------------------------
# inputs

def counted_flags(session: Session, case: Case) -> tuple[list[dict], dict]:
    """Accepted, material flags in the case years from the newest run of each basis, plus what was left out and why."""
    rows, left = [], {"unreviewed": 0, "rejected": 0, "not_material": 0}
    computed: dict[str, int] = {}
    for run in svc._latest_runs(session, case.company_id):
        for res in session.execute(select(CheckResultRow).where(CheckResultRow.run_id == run.id)).scalars():
            n = (res.detail or {}).get("observations") or 0
            if n and res.status in ("COMPLETED", "METRIC_ONLY"):
                computed[res.check_id] = computed.get(res.check_id, 0) + n
        for flag in session.execute(select(Flag).where(Flag.run_id == run.id)).scalars():
            if flag.financial_year not in case.years:
                continue
            review, _carried = svc.effective_review(session, flag, run)
            if review is None:
                left["unreviewed"] += 1
            elif review.decision != "accept":
                left["rejected"] += 1
            elif (flag.materiality or {}).get("label") == "not_material":
                left["not_material"] += 1
            else:
                rows.append({"flag_id": flag.id, "check_id": flag.check_id, "fy": flag.financial_year, "basis": run.basis,
                             "severity": flag.severity, "what": flag.what_observed})
    return rows, {"left_out": left, "computed": computed}


def record_items(session: Session, company_id: int) -> list[PublicRecordItem]:
    return session.execute(select(PublicRecordItem).where(PublicRecordItem.company_id == company_id)
                           .order_by(PublicRecordItem.id)).scalars().all()


# ---------------------------------------------------------------------------------------------------------------------------
# scoring

def score(library: dict, flags: list[dict], computed: dict[str, int], items: list[PublicRecordItem]) -> list[dict]:
    """One result per scheme, ranked schemes first (highest coverage, then more present indicators)."""
    min_present = library["scoring"]["min_present"]
    out = []
    for s in library["schemes"]:
        present, missing, against = [], [], []
        for ind in s["indicators"]:
            if ind.get("tool_check"):
                hits = [f for f in flags if f["check_id"] == ind["tool_check"]]
                if hits:
                    present.append({"indicator": ind["text"], "source": "flag", "check_id": ind["tool_check"],
                                    "flag_ids": [h["flag_id"] for h in hits],
                                    "detail": "; ".join(sorted({f"{h['fy']} ({h['basis']})" for h in hits})),
                                    "what": hits[0]["what"]})
                elif computed.get(ind["tool_check"]):
                    missing.append({"indicator": ind["text"], "why": f"{ind['tool_check']} ran and no accepted flag was raised"})
                    against.append(f"{ind['tool_check']} was computed for {computed[ind['tool_check']]} period(s) and no accepted flag came out: {ind['text'].lower()} is not seen.")
                else:
                    missing.append({"indicator": ind["text"], "why": f"{ind['tool_check']} has no usable result for this case"})
            else:
                hits = [i for i in items if ind["record_tag"] in (i.tags or [])]
                if hits:
                    present.append({"indicator": ind["text"], "source": "public_record", "record_item_ids": [h.id for h in hits],
                                    "detail": "; ".join(f"{h.title} ({h.source_name}{', ' + h.published_on if h.published_on else ''})" for h in hits),
                                    "what": hits[0].summary})
                else:
                    missing.append({"indicator": ind["text"], "why": "no public-record item with this tag has been added"})
        coverage = round(len(present) / len(s["indicators"]), 4)
        named = any(i.names_individual for p in present if p["source"] == "public_record" for i in items if i.id in p["record_item_ids"])
        out.append({"scheme": s, "present": present, "missing": missing, "against": against + list(s["contradicting"]),
                    "coverage": coverage, "ranked": len(present) >= min_present, "named_individual": named})
    out.sort(key=lambda r: (not r["ranked"], -r["coverage"], -len(r["present"]), r["scheme"]["id"]))
    return out


def _text_of(result: dict) -> list[str]:
    s = result["scheme"]
    texts = [s["scheme_name"], s["plain_pattern"], s["class_label"]]
    texts += [p["indicator"] + " " + p["detail"] for p in result["present"]]
    texts += [m["indicator"] + " " + m["why"] for m in result["missing"]]
    texts += result["against"] + s["innocent_explanations"] + [e["text"] for e in s["evidence_to_confirm"]]
    return texts


def check_result(result: dict) -> None:
    """Refuse a match that has no references on both sides, or that uses banned wording in the tool's own text."""
    s = result["scheme"]
    cites = s.get("citations") or {}
    if not cites.get("acfe") or not cites.get("fais"):
        raise RuleError(f"{s['id']}: a match needs both an ACFE and a FAIS reference; none is stored for this scheme.")
    # present[].what is a flag's own text or a person's summary of a public record: those passed their own checks when saved
    bad = banned_terms_in(*[t for t in _text_of(result)])
    if bad:
        raise RuleError(f"{s['id']}: wording this tool does not use was found ({', '.join(bad)}).")


# ---------------------------------------------------------------------------------------------------------------------------
# running and reviewing

def _input_hash(library: dict, flags: list[dict], items: list[PublicRecordItem]) -> str:
    blob = json.dumps({"v": library["version"], "min": library["scoring"]["min_present"], "flags": sorted(f["flag_id"] for f in flags),
                       "items": sorted((i.id, tuple(sorted(i.tags or [])), i.names_individual) for i in items)}, sort_keys=True)
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()


def _match_row(m: TypologyMatch) -> dict:
    return {
        "id": m.id, "batch": m.batch, "scheme_id": m.scheme_id, "scheme_name": m.scheme_name, "class_label": m.class_label,
        "coverage": m.coverage, "present": m.present, "missing": m.missing, "against": m.against,
        "innocent_explanations": m.innocent_explanations, "evidence_to_confirm": m.evidence_to_confirm, "citations": m.citations,
        "named_individual": m.named_individual, "label": "hypothesis", "notice": HYPOTHESIS,
        "created_by": m.created_by, "created_at": m.created_at.isoformat(),
        "review": {"status": m.review_status, "by": m.reviewed_by, "note": m.review_note,
                   "at": None if m.reviewed_at is None else m.reviewed_at.isoformat()},
        "partner": {"status": m.partner_status, "by": m.partner_by, "note": m.partner_note,
                    "at": None if m.partner_at is None else m.partner_at.isoformat()},
    }


def latest_batch(session: Session, case_id: int) -> list[TypologyMatch]:
    top = session.execute(select(func.max(TypologyMatch.batch)).where(TypologyMatch.case_id == case_id)).scalar()
    if top is None:
        return []
    return session.execute(select(TypologyMatch).where(TypologyMatch.case_id == case_id, TypologyMatch.batch == top)
                           .order_by(TypologyMatch.id)).scalars().all()


def overview(session: Session, case_id: int) -> dict:
    """What the screen shows: the saved matches of the newest batch, and a live preview of every scheme's coverage."""
    case = svc._case(session, case_id)
    library = load_schemes()
    flags, info = counted_flags(session, case)
    items = record_items(session, case.company_id)
    results = score(library, flags, info["computed"], items)
    saved = latest_batch(session, case_id)
    return {
        "case_id": case_id, "label": "hypotheses", "notice": HYPOTHESIS, "min_present": library["scoring"]["min_present"],
        "counted_flags": len(flags), "left_out": info["left_out"],
        "saved_batch": saved[0].batch if saved else None,
        "stale": bool(saved) and saved[0].input_hash != _input_hash(library, flags, items),
        "matches": [_match_row(m) for m in saved],
        "preview": [{"scheme_id": r["scheme"]["id"], "scheme_name": r["scheme"]["scheme_name"], "class_label": r["scheme"]["class_label"],
                     "present": len(r["present"]), "total": len(r["scheme"]["indicators"]), "coverage": r["coverage"],
                     "ranked": r["ranked"], "reachable_without_records": sum(1 for i in r["scheme"]["indicators"] if i.get("tool_check")) >= library["scoring"]["min_present"]}
                    for r in results],
        "records": [record_row(i) for i in items], "record_tags": record_tags(library),
    }


def run_matching(session: Session, user: AppUser, case_id: int) -> dict:
    require(user, "run_typology")
    case = svc._case(session, case_id)
    svc.ensure_open(case)
    library = load_schemes()
    flags, info = counted_flags(session, case)
    items = record_items(session, case.company_id)
    h = _input_hash(library, flags, items)
    saved = latest_batch(session, case_id)
    if saved and saved[0].input_hash == h:
        return {**overview(session, case_id), "unchanged": True}
    results = [r for r in score(library, flags, info["computed"], items) if r["ranked"]]
    for r in results:
        check_result(r)
    batch = (saved[0].batch + 1) if saved else 1
    for r in results:
        s = r["scheme"]
        session.add(TypologyMatch(
            case_id=case_id, batch=batch, scheme_id=s["id"], scheme_name=s["scheme_name"], class_label=s["class_label"],
            coverage=r["coverage"], present=r["present"], missing=r["missing"], against=r["against"],
            innocent_explanations=s["innocent_explanations"], evidence_to_confirm=s["evidence_to_confirm"],
            citations=s["citations"], named_individual=r["named_individual"], input_hash=h, created_by=user.username,
            partner_status="pending" if r["named_individual"] else "not_needed"))
    session.flush()
    out = overview(session, case_id)
    out["unchanged"] = False
    out["ranked_now"] = len(results)
    return out


def _match(session: Session, match_id: int) -> TypologyMatch:
    m = session.get(TypologyMatch, match_id)
    if m is None:
        raise RuleError("Match not found.", 404)
    return m


def review_match(session: Session, user: AppUser, match_id: int, decision: str, note: str, citations_verified: bool) -> dict:
    """The forensic lead accepts or rejects a match. Accepting needs a reason and the lead's confirmation that the references were checked."""
    require(user, "review_typology")
    m = _match(session, match_id)
    if decision not in ("accepted", "rejected"):
        raise RuleError("Decision must be accepted or rejected.")
    if not (note or "").strip():
        raise RuleError("A reason is required.")
    if banned_terms_in(note):
        raise RuleError("The note uses wording this tool does not use.")
    if decision == "accepted" and not citations_verified:
        raise RuleError("Confirm that you have checked the ACFE and FAIS references before accepting a match.")
    latest = latest_batch(session, m.case_id)
    if not latest or latest[0].batch != m.batch:
        raise RuleError("This match belongs to an older run; run the matching again.", 409)
    m.review_status, m.reviewed_by, m.review_note = decision, user.username, note.strip()
    m.citations_verified = bool(citations_verified)
    m.reviewed_at = svc.dt.datetime.now(svc.dt.timezone.utc)
    session.flush()
    return _match_row(m)


def partner_review(session: Session, user: AppUser, match_id: int, decision: str, note: str) -> dict:
    require(user, "partner_review")
    m = _match(session, match_id)
    if m.partner_status == "not_needed":
        raise RuleError("This match names no individual, so no partner review is needed.")
    if decision not in ("accepted", "rejected"):
        raise RuleError("Decision must be accepted or rejected.")
    if not (note or "").strip() or banned_terms_in(note):
        raise RuleError("A reason is required and it must not use wording this tool does not use.")
    m.partner_status, m.partner_by, m.partner_note = decision, user.username, note.strip()
    m.partner_at = svc.dt.datetime.now(svc.dt.timezone.utc)
    session.flush()
    return _match_row(m)


def usable_for_work_product(m: TypologyMatch) -> bool:
    """Accepted by the lead, and by a partner too when the match involves a named individual."""
    return m.review_status == "accepted" and (m.partner_status in ("not_needed", "accepted"))


# ---------------------------------------------------------------------------------------------------------------------------
# public-record items

def record_row(i: PublicRecordItem) -> dict:
    return {"id": i.id, "kind": i.kind, "title": i.title, "source_name": i.source_name, "url": i.url, "published_on": i.published_on,
            "summary": i.summary, "tags": i.tags, "names_individual": i.names_individual, "added_by": i.added_by,
            "added_at": i.added_at.isoformat()}


def add_record(session: Session, user: AppUser, company_id: int, body: dict) -> dict:
    """A person adds one public-record fact with its source. Wording is checked; tags must be ones a scheme uses."""
    require(user, "add_public_record")
    from crest_forensic.db.models import Company
    if session.get(Company, company_id) is None:
        raise RuleError("Company not found.", 404)
    kind = (body.get("kind") or "").strip()
    title, source, summary = (body.get("title") or "").strip(), (body.get("source_name") or "").strip(), (body.get("summary") or "").strip()
    tags = [t for t in (body.get("tags") or [])]
    if kind not in KINDS:
        raise RuleError(f"Kind must be one of: {', '.join(KINDS)}.")
    if not (title and source and summary):
        raise RuleError("Title, source and a short summary are required.")
    if len(summary) > 600:
        raise RuleError("Keep the summary under 600 characters.")
    if not tags or any(t not in record_tags() for t in tags):
        raise RuleError("Choose at least one tag, from the list the schemes use.")
    bad = banned_terms_in(title, summary)
    if bad:
        raise RuleError(f"Please rephrase: the text uses wording this tool does not use ({', '.join(bad)}). Describe what the source says, not a conclusion.")
    item = PublicRecordItem(company_id=company_id, kind=kind, title=title, source_name=source, url=(body.get("url") or "").strip() or None,
                            published_on=(body.get("published_on") or "").strip() or None, summary=summary, tags=tags,
                            names_individual=bool(body.get("names_individual")), added_by=user.username)
    session.add(item)
    session.flush()
    return record_row(item)
