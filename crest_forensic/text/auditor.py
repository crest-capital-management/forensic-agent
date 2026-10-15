"""Auditor identity for J1-12, read by a fixed pattern (no model needed).

Finds the firm name and ICAI firm registration number in the auditor's report
signature block. The quote stops at the registration number so the signing
partner (an individual) is never part of the evidence.
"""
from __future__ import annotations

import re

from sqlalchemy import select
from sqlalchemy.orm import Session

from crest_forensic.db.models import Document, DocumentVersion, LlmCall, TextFinding
from crest_forensic.documents.ingest import load_pages
from crest_forensic.documents.quotes import normalize, quote_in_page
from crest_forensic.text.run import FAILED, PASSED

DETERMINISTIC_MODEL = "deterministic:auditor-signature-regex-v1"
FINDING_TYPE = "auditor_identity"

_SIGNATURE = re.compile(
    r"For (?P<name>[A-Z][^|]{2,60}?) Chartered Accountants Firm's Registration No\.? ?:? ?"
    r"(?P<reg>[0-9A-Z]+(?:/[A-Z]-?[0-9]+)?)")


def read_auditor_identity(pages: dict[int, str]) -> dict | None:
    for number in sorted(pages):
        m = _SIGNATURE.search(normalize(pages[number]))
        if m:
            return {"page": number, "quote": m.group(0), "firm_name": m.group("name").strip(),
                    "registration_no": m.group("reg")}
    return None


def run_auditor_identity(session: Session, company_id: int, version: DocumentVersion, basis: str) -> TextFinding | None:
    span = (version.sections or {}).get(f"{basis}_auditors_report_full")
    if not span:
        return None
    request_sha = f"auditor-{version.id}-{basis}"
    existing = session.execute(select(LlmCall).where(LlmCall.request_sha256 == request_sha)).scalars().first()
    if existing:
        return session.execute(select(TextFinding).where(TextFinding.llm_call_id == existing.id)).scalars().first()

    pages = load_pages(session, version.id, span["first"], span["last"])
    found = read_auditor_identity(pages)
    fy = session.get(Document, version.document_id).fiscal_year

    call = LlmCall(
        document_version_id=version.id, task=f"J1-12:{basis}", model=DETERMINISTIC_MODEL,
        prompt_version="n/a", prompt_sha256="n/a", pages=sorted(pages), request_sha256=request_sha,
        response={"found": found},
    )
    session.add(call)
    session.flush()
    if not found:
        return None

    verified = quote_in_page(found["quote"], pages[found["page"]])
    row = TextFinding(
        llm_call_id=call.id, document_version_id=version.id, company_id=company_id, check_id="J1-12",
        financial_year=fy, basis=basis, finding_type=FINDING_TYPE, quote=found["quote"], page_number=found["page"],
        payload={"firm_name": found["firm_name"], "registration_no": found["registration_no"]},
        validation_status=PASSED if verified else FAILED,
        validation_detail="" if verified else "quote not found on its own page",
    )
    session.add(row)
    session.flush()
    return row
