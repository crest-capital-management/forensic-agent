"""Ingest an annual-report PDF: hash it, store every page's text, find its sections."""
from __future__ import annotations

import hashlib
import re
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from crest_forensic.db.models import Document, DocumentVersion, TextExtract
from crest_forensic.documents.sections import locate_sections

EXTRACTOR = "pymupdf"


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def _printed_page(text: str) -> str | None:
    """The page number printed in the page header, e.g. 'Integrated Annual Report 2025-26 | 196'."""
    for line in [ln.strip() for ln in text.splitlines() if ln.strip()][:8]:
        if re.fullmatch(r"\d{1,3}", line):
            return line
    return None


def read_pdf_pages(path: Path) -> dict[int, str]:
    import pymupdf

    with pymupdf.open(path) as doc:
        return {i + 1: page.get_text() for i, page in enumerate(doc)}


def ingest_document(
    session: Session, company_id: int, path: str | Path, doc_type: str, fiscal_year: str, title: str | None = None,
) -> tuple[DocumentVersion, bool]:
    """Returns (version, created). The same file (same SHA-256) is never stored twice."""
    path = Path(path)
    digest = sha256_file(path)

    existing = session.execute(
        select(DocumentVersion).join(Document, Document.id == DocumentVersion.document_id)
        .where(Document.company_id == company_id, DocumentVersion.file_sha256 == digest)
    ).scalars().first()
    if existing:
        # The file and its page text never change, but the section finder may have improved:
        # re-derive the sections from the STORED pages (no PDF needed).
        stored = load_pages(session, existing.id, 1, existing.page_count)
        refreshed = locate_sections(stored)
        if refreshed != existing.sections:
            existing.sections = refreshed
        return existing, False

    pages = read_pdf_pages(path)
    document = session.execute(
        select(Document).where(Document.company_id == company_id, Document.doc_type == doc_type,
                               Document.fiscal_year == fiscal_year)
    ).scalars().first()
    if document is None:
        document = Document(company_id=company_id, doc_type=doc_type, fiscal_year=fiscal_year,
                            title=title or f"{doc_type} {fiscal_year}")
        session.add(document)
        session.flush()

    version = DocumentVersion(
        document_id=document.id, file_name=path.name, file_sha256=digest, page_count=len(pages),
        extractor=EXTRACTOR, sections=locate_sections(pages),
    )
    session.add(version)
    session.flush()

    for number, text in pages.items():
        session.add(TextExtract(
            document_version_id=version.id, page_number=number, printed_page=_printed_page(text),
            text=text, text_sha256=hashlib.sha256(text.encode("utf-8")).hexdigest(),
        ))
    session.flush()
    return version, True


def load_pages(session: Session, document_version_id: int, first: int, last: int) -> dict[int, str]:
    rows = session.execute(
        select(TextExtract).where(
            TextExtract.document_version_id == document_version_id,
            TextExtract.page_number >= first, TextExtract.page_number <= last)
        .order_by(TextExtract.page_number)
    ).scalars().all()
    return {r.page_number: r.text for r in rows}
