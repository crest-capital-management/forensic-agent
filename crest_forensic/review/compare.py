"""Compare two screen runs (Build Plan 11.1 screen 5): what changed, and what could explain it.

Two runs are only comparable if they are for the same company and the same basis.
A flag is "the same flag" in both runs when its check, year, finding type, page and
quote match. Same flag + same content hash = unchanged. Same flag + different hash =
changed, and we list exactly which figures, severity or inputs moved. A flag in only
one run is new or gone. Causes are shown as POSSIBLE causes, taken from what differed
between the runs, never asserted.
"""
from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from crest_forensic import config_store as store
from crest_forensic.db.models import Company, ConfigVersion, Flag, Review, Run, CheckResultRow
from crest_forensic.review.service import RuleError
from crest_forensic.text.priority import _rank, source_priority


def _run(session: Session, run_id: int) -> Run:
    run = session.get(Run, run_id)
    if run is None:
        raise RuleError(f"Run {run_id} not found.", 404)
    return run


def list_runs(session: Session, company_id: int | None = None) -> list[dict]:
    stmt = select(Run).order_by(Run.id.desc())
    if company_id:
        stmt = stmt.where(Run.company_id == company_id)
    out = []
    for r in session.execute(stmt).scalars():
        cfg = session.get(ConfigVersion, r.config_version_id)
        out.append({"id": r.id, "company_id": r.company_id, "company": session.get(Company, r.company_id).name,
                    "basis": r.basis, "years": r.years, "started_at": r.started_at.isoformat(),
                    "flags_created": r.flags_created, "config_approved": r.config_approved,
                    "config_version_id": r.config_version_id, "config_version": cfg.version if cfg else None,
                    "code_version": r.code_version[:8]})
    return out


def _key(f: Flag, occurrence: dict) -> tuple:
    fig = f.figures or {}
    base = (f.check_id, f.financial_year, str(fig.get("finding_type") or ""), str(fig.get("page") or ""),
            " ".join(str(fig.get("quote") or "").split())[:80])
    n = occurrence.get(base, 0)
    occurrence[base] = n + 1
    return base + (n,)


def _flags_by_key(session: Session, run_id: int) -> dict[tuple, Flag]:
    flags = session.execute(select(Flag).where(Flag.run_id == run_id)
                            .order_by(Flag.check_id, Flag.financial_year, Flag.content_hash)).scalars().all()
    occ: dict = {}
    return {_key(f, occ): f for f in flags}


def _inputs(f: Flag) -> dict[tuple, dict]:
    out = {}
    for i in (f.citation or {}).get("inputs") or []:
        out[(i.get("field"), i.get("fy"), i.get("name"))] = i
    return out


def _numbers(d: dict) -> dict:
    return {k: v for k, v in (d or {}).items() if isinstance(v, (int, float)) and not isinstance(v, bool)}


def _flag_summary(f: Flag) -> dict:
    return {"flag_id": f.id, "check_id": f.check_id, "financial_year": f.financial_year,
            "what_observed": f.what_observed, "severity": f.severity,
            "materiality": (f.materiality or {}).get("label"), "evidence_confidence": f.evidence_confidence}


def _decision(session: Session, flag_id: int) -> dict | None:
    r = session.execute(select(Review).where(Review.flag_id == flag_id).order_by(Review.id.desc())).scalars().first()
    return None if r is None else {"decision": r.decision, "reviewer": r.reviewer, "reason": r.reason}


def _flag_changes(a: Flag, b: Flag) -> list[dict]:
    changes = []
    for label, va, vb in (("severity", a.severity, b.severity),
                          ("materiality", (a.materiality or {}).get("label"), (b.materiality or {}).get("label")),
                          ("evidence confidence", a.evidence_confidence, b.evidence_confidence),
                          ("what was observed", a.what_observed, b.what_observed)):
        if va != vb:
            changes.append({"what": label, "before": va, "after": vb})
    na, nb = _numbers(a.figures), _numbers(b.figures)
    for k in sorted(set(na) | set(nb)):
        if na.get(k) != nb.get(k):
            changes.append({"what": f"figure: {k.replace('_', ' ')}", "before": na.get(k), "after": nb.get(k)})
    ia, ib = _inputs(a), _inputs(b)
    record_only: list[str] = []
    for k in sorted(set(ia) | set(ib), key=lambda t: tuple(str(x) for x in t)):
        x, y = ia.get(k), ib.get(k)
        name = f"input: {k[0]} {k[1]}"
        if x is None or y is None:
            changes.append({"what": name, "before": None if x is None else x.get("value"),
                            "after": None if y is None else y.get("value")})
        elif x.get("value") != y.get("value"):
            changes.append({"what": name, "before": x.get("value"), "after": y.get("value"),
                            "detail": f"source {x.get('provider')} snapshot {x.get('snapshot_id')} → "
                                      f"{y.get('provider')} snapshot {y.get('snapshot_id')}"})
        elif x.get("provider") != y.get("provider") or x.get("resolution") != y.get("resolution"):
            changes.append({"what": name + " (same value, different source)",
                            "before": f"{x.get('provider')} / {x.get('resolution')}",
                            "after": f"{y.get('provider')} / {y.get('resolution')}"})
        elif (x.get("snapshot_id"), x.get("line_item_id")) != (y.get("snapshot_id"), y.get("line_item_id")):
            record_only.append(f"{k[0]} {k[1]}")
    if record_only:
        changes.append({"what": "same figures, re-saved records", "before": None, "after": None,
                        "detail": f"{len(record_only)} inputs have identical values but point to newly saved line-item "
                                  f"records (this happens after a reprocess): {', '.join(sorted(set(record_only)))}"})
    ea = {(e.get("fy"), e.get("page"), e.get("quote")): e for e in (a.citation or {}).get("evidence") or []}
    eb = {(e.get("fy"), e.get("page"), e.get("quote")): e for e in (b.citation or {}).get("evidence") or []}
    for k in set(ea) - set(eb):
        changes.append({"what": f"quoted passage p{k[1]} {k[0]}", "before": "present", "after": "missing"})
    for k in set(eb) - set(ea):
        changes.append({"what": f"quoted passage p{k[1]} {k[0]}", "before": "missing", "after": "present"})
    for k in set(ea) & set(eb):
        if ea[k].get("document_sha256") != eb[k].get("document_sha256"):
            changes.append({"what": f"quoted passage p{k[1]} {k[0]} (document file)",
                            "before": str(ea[k].get("document_sha256"))[:12], "after": str(eb[k].get("document_sha256"))[:12]})
    if not changes:
        changes.append({"what": "internal fingerprint only", "before": None, "after": None,
                        "detail": "No figure, limit-based result or quote differs; only an internal record reference changed."})
    return changes


def _doc_shas(run: Run) -> dict:
    return {d["fiscal_year"]: d["sha256"] for d in (run.manifest or {}).get("documents", [])}


def _text_models(run: Run) -> dict:
    """The model whose findings counted for each task: the highest-priority one among the calls the run listed
    (the manifest lists every call that existed, including cross-checks that were not counted)."""
    priority = source_priority()
    best: dict[str, str] = {}
    for t in (run.manifest or {}).get("text_extractions", []):
        cur = best.get(t["task"])
        if cur is None or _rank(t["model"], priority) < _rank(cur, priority):
            best[t["task"]] = t["model"]
    return best


def _differences(session: Session, a: Run, b: Run) -> list[dict]:
    ma, mb = a.manifest or {}, b.manifest or {}
    rows = []

    def add(item, va, vb, detail=None):
        rows.append({"item": item, "a": va, "b": vb, "same": va == vb, "detail": detail})

    add("Years screened", ", ".join(a.years), ", ".join(b.years))
    add("Code version", a.code_version[:8], b.code_version[:8])
    ca, cb = session.get(ConfigVersion, a.config_version_id), session.get(ConfigVersion, b.config_version_id)
    cfg_changes = store.diff(ca.content, cb.content) if ca and cb and ca.id != cb.id else []
    add("Limits and severity rules (config)", f"v{ca.version}" + (" approved" if a.config_approved else " DRAFT"),
        f"v{cb.version}" + (" approved" if b.config_approved else " DRAFT"),
        cfg_changes or None)
    add("Source precedence policy", ma.get("source_policy_version"), mb.get("source_policy_version"))
    add("Field mapping versions", str(ma.get("field_mapping_versions")), str(mb.get("field_mapping_versions")))
    sa, sb = set(ma.get("snapshot_ids", [])), set(mb.get("snapshot_ids", []))
    add("Saved data snapshots used", f"{len(sa)}", f"{len(sb)}",
        {"added": sorted(sb - sa), "removed": sorted(sa - sb)} if sa != sb else None)
    da, db_ = _doc_shas(a), _doc_shas(b)
    for fy in sorted(set(da) | set(db_)):
        add(f"Annual report {fy} (file fingerprint)", (da.get(fy) or "none")[:12], (db_.get(fy) or "none")[:12])
    ta, tb = _text_models(a), _text_models(b)
    for task in sorted(set(ta) | set(tb)):
        if ta.get(task) != tb.get(task):
            add(f"Text reading for {task}", (ta.get(task) or "none")[:40], (tb.get(task) or "none")[:40])
    return rows


def _check_status(session: Session, a: Run, b: Run) -> list[dict]:
    def load(run):
        return {r.check_id: r for r in session.execute(select(CheckResultRow).where(CheckResultRow.run_id == run.id)).scalars()}
    ra, rb = load(a), load(b)
    out = []
    for cid in sorted(set(ra) | set(rb)):
        sa, sb = (ra[cid].status if cid in ra else None), (rb[cid].status if cid in rb else None)
        if sa != sb:
            out.append({"check_id": cid, "a": sa, "b": sb})
    return out


def compare(session: Session, a_id: int, b_id: int) -> dict:
    if a_id == b_id:
        raise RuleError("Choose two different runs.")
    a, b = _run(session, a_id), _run(session, b_id)
    if a.company_id != b.company_id or a.basis != b.basis:
        raise RuleError("Only runs for the same company and the same basis (consolidated or standalone) can be compared.")
    fa, fb = _flags_by_key(session, a.id), _flags_by_key(session, b.id)
    new, gone, changed, unchanged = [], [], [], []
    for k in sorted(set(fa) | set(fb), key=lambda t: tuple(str(x) for x in t)):
        x, y = fa.get(k), fb.get(k)
        if x is None:
            new.append({**_flag_summary(y)})
        elif y is None:
            gone.append({**_flag_summary(x), "decision": _decision(session, x.id)})
        elif x.content_hash == y.content_hash:
            unchanged.append({**_flag_summary(y), "decision_in_a": _decision(session, x.id)})
        else:
            changed.append({**_flag_summary(y), "flag_id_a": x.id, "changes": _flag_changes(x, y),
                            "decision_in_a": _decision(session, x.id)})
    diffs = _differences(session, a, b)
    differing = [d["item"] for d in diffs if not d["same"]]
    headline = (f"Run {a.id} → run {b.id} ({a.basis}): {len(new)} new, {len(gone)} gone, {len(changed)} changed, "
                f"{len(unchanged)} unchanged flags.")
    if not (new or gone or changed):
        headline += " The two runs found exactly the same flags."
    possible = []
    if any(not d["same"] and d["item"].startswith("Saved data") for d in diffs):
        possible.append("Saved data differs (a restatement, a new source or a corrected value)")
    if any(not d["same"] and d["item"].startswith("Annual report") for d in diffs):
        possible.append("A different annual report file was used")
    if any(not d["same"] and d["item"].startswith("Limits") for d in diffs):
        possible.append("The limits or severity rules differ")
    if any(not d["same"] and d["item"].startswith("Text reading") for d in diffs):
        possible.append("A different model or reading produced the text findings")
    if any(not d["same"] and d["item"] == "Code version" for d in diffs):
        possible.append("The calculation code differs")
    return {
        "company": session.get(Company, a.company_id).name, "basis": a.basis,
        "run_a": next(r for r in list_runs(session, a.company_id) if r["id"] == a.id),
        "run_b": next(r for r in list_runs(session, b.company_id) if r["id"] == b.id),
        "headline": headline, "differences": diffs, "what_differs": differing,
        "possible_causes": possible if (new or gone or changed) else [],
        "new": new, "gone": gone, "changed": changed, "unchanged": unchanged,
        "check_status_changes": _check_status(session, a, b),
        "note": "Possible causes come from what differed between the two runs. They are hints for a reviewer, not findings.",
    }
