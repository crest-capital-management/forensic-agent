"""Run a text task: call the extractor, record the call, validate every finding in code.

A finding only becomes usable (validation_status PASSED) if the exact quote is
found, word for word, on the page the model cited, and that page is one of the
pages that was actually sent. Anything else is stored as FAILED with the reason
and never reaches a flag (Build Plan section 10.1: "Code confirms the quote
exists. If it does not, the flag is dropped").
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field

from sqlalchemy import select
from sqlalchemy.orm import Session

from crest_forensic.db.models import Document, DocumentVersion, LlmCall, TextFinding
from crest_forensic.documents.quotes import MIN_QUOTE_CHARS, find_quote_page, quote_in_page
from crest_forensic.text.pages import select_pages
from crest_forensic.text.tasks import PROMPT_VERSION, TASKS, TextTask, prompt_sha256

MAX_QUOTE_CHARS = 600
PASSED, FAILED = "PASSED", "FAILED"
_ALLOWED_KEYS = {"finding_type", "exact_quote", "page", "confidence"}


@dataclass
class TaskRun:
    check_id: str
    basis: str
    status: str                      # OK / NO_PAGES
    reused: bool = False
    llm_call_id: int | None = None
    pages_sent: list[int] = field(default_factory=list)
    findings: list[TextFinding] = field(default_factory=list)


def validate_finding(raw: object, task: TextTask, pages: dict[int, str]) -> tuple[str, str]:
    """Returns (PASSED|FAILED, reason). Trusts nothing about `raw`."""
    if not isinstance(raw, dict):
        return FAILED, "finding is not an object"
    extra = set(raw) - _ALLOWED_KEYS
    if extra:
        return FAILED, f"unexpected fields: {sorted(extra)}"
    ftype, quote, page, confidence = (raw.get(k) for k in ("finding_type", "exact_quote", "page", "confidence"))
    if ftype not in task.finding_types:
        return FAILED, f"finding_type {ftype!r} is not allowed for {task.check_id}"
    if confidence not in ("high", "medium", "low"):
        return FAILED, f"confidence {confidence!r} is not allowed"
    if not isinstance(quote, str) or not (MIN_QUOTE_CHARS <= len(quote.strip()) <= MAX_QUOTE_CHARS):
        return FAILED, f"quote must be {MIN_QUOTE_CHARS}-{MAX_QUOTE_CHARS} characters"
    if isinstance(page, bool) or not isinstance(page, int) or page not in pages:
        return FAILED, f"page {page!r} is not one of the pages that were sent"
    if quote_in_page(quote, pages[page]):
        return PASSED, ""
    elsewhere = find_quote_page(quote, pages)
    if elsewhere is not None:
        return FAILED, f"quote is on page {elsewhere}, not the cited page {page} (wrong location)"
    return FAILED, "quote not found verbatim on any page that was sent"


def _request_sha(model: str, task: TextTask, basis: str, fy: str, pages: dict[int, str]) -> str:
    return hashlib.sha256(json.dumps({
        "model": model, "prompt": prompt_sha256(), "task": task.check_id, "basis": basis, "fy": fy,
        "pages": {str(n): hashlib.sha256(t.encode("utf-8")).hexdigest() for n, t in sorted(pages.items())},
    }, sort_keys=True).encode("utf-8")).hexdigest()


def run_text_task(
    session: Session, company_id: int, version: DocumentVersion, check_id: str, basis: str, extractor,
    force: bool = False,
) -> TaskRun:
    task = TASKS[check_id]
    fy = session.get(Document, version.document_id).fiscal_year
    pages = select_pages(session, version, task, basis)
    if not pages:
        return TaskRun(check_id, basis, "NO_PAGES")

    task_key = f"{check_id}:{basis}"
    request_sha = _request_sha(extractor.model_label, task, basis, fy, pages)
    existing = session.execute(select(LlmCall).where(
        LlmCall.request_sha256 == request_sha, LlmCall.task == task_key,
        LlmCall.document_version_id == version.id)).scalars().first()
    if existing and not force:
        found = session.execute(select(TextFinding).where(TextFinding.llm_call_id == existing.id)
                                .order_by(TextFinding.id)).scalars().all()
        return TaskRun(check_id, basis, "OK", True, existing.id, sorted(pages), list(found))

    raw = extractor.extract(task, basis, fy, pages)
    call = LlmCall(
        document_version_id=version.id, task=task_key, model=raw.model, prompt_version=PROMPT_VERSION,
        prompt_sha256=prompt_sha256(), pages=sorted(pages), request_sha256=request_sha, response=raw.response,
        input_tokens=raw.input_tokens, output_tokens=raw.output_tokens,
    )
    session.add(call)
    session.flush()

    findings_raw = raw.response.get("findings") if isinstance(raw.response, dict) else None
    stored: list[TextFinding] = []
    seen: set[tuple] = set()
    if not isinstance(findings_raw, list):
        findings_raw = [{"_malformed": True}]
    for item in findings_raw:
        status, detail = validate_finding(item, task, pages)
        if status == PASSED:
            key = (item["finding_type"], " ".join(item["exact_quote"].split()))
            if key in seen:
                status, detail = FAILED, "duplicate of an earlier finding"
            seen.add(key)
        row = TextFinding(
            llm_call_id=call.id, document_version_id=version.id, company_id=company_id, check_id=check_id,
            financial_year=fy, basis=basis,
            finding_type=str(item.get("finding_type", "malformed")) if isinstance(item, dict) else "malformed",
            quote=str(item.get("exact_quote", "")) if isinstance(item, dict) else "",
            page_number=item.get("page") if isinstance(item, dict) and isinstance(item.get("page"), int) else None,
            payload={"confidence": item.get("confidence") if isinstance(item, dict) else None, "raw": item},
            validation_status=status, validation_detail=detail,
        )
        session.add(row)
        stored.append(row)
    session.flush()
    return TaskRun(check_id, basis, "OK", False, call.id, sorted(pages), stored)
