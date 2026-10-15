"""Auditor fees: read the 'Auditor's remuneration' note of an annual report (no model).

TCS prints one small table in the standalone notes: the statutory audit fee, taxation matters, other
services and reimbursement, for the report year and the year before, in INR crore (whole crores, so
small changes are not visible). Each report is saved as one snapshot that cites the document, page and
table values. A year printed in two reports (as the year itself and as a comparative) is kept from the
report of that year; a difference between the two is reported, never silently replaced.
"""
from __future__ import annotations

import datetime as dt
import re
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from crest_forensic.connectors.base import RawSourceResponse
from crest_forensic.db.models import Document, DocumentVersion, Snapshot, TextExtract
from crest_forensic.documents.ingest import sha256_file
from crest_forensic.ingestion.fetch_and_snapshot import compute_payload_hash, save_snapshot

PROVIDER = "annual_report_pdf"
ENDPOINT = "auditor_fees"
ROWS = {"Auditor": "audit_fee_cr", "For taxation matters": "tax_matters_cr",
        "For other services": "other_services_cr", "For reimbursement of expenses": "reimbursement_cr"}
_MARKER = re.compile(r"Auditor.{1,3}s\s+remuneration\s+consists")


def _find_page(session: Session, version_id: int) -> int | None:
    for te in session.execute(select(TextExtract).where(TextExtract.document_version_id == version_id)
                              .order_by(TextExtract.page_number)).scalars():
        if _MARKER.search(te.text) and te.page_number > 100:   # notes, not the contents list
            return te.page_number
    return None


def parse_fee_table(rows: list[list[str]]) -> dict[str, dict[str, int]]:
    """rows: the table as cells. Header cells read like 'Year ended\\nMarch 31, 2026'."""
    years = []
    for cell in rows[0][1:]:
        m = re.search(r"March\s+31,\s*(\d{4})", cell or "")
        if not m:
            raise ValueError(f"cannot read the year from the header cell {cell!r}")
        years.append(f"FY{m.group(1)}")
    out: dict[str, dict[str, int]] = {fy: {} for fy in years}
    for r in rows[1:]:
        key = ROWS.get((r[0] or "").strip())
        if key:
            for fy, cell in zip(years, r[1:]):
                out[fy][key] = int(str(cell).replace(",", "").strip())
    for fy, vals in out.items():
        if set(vals) != set(ROWS.values()):
            raise ValueError(f"{fy}: expected the four fee lines, found {sorted(vals)}")
    return out


def parse_fee_text(text: str) -> dict[str, dict[str, int]]:
    """Fallback when the PDF table cannot be found: the page text lists the header years, then each
    label followed by its two numbers (report year first)."""
    m = _MARKER.search(text)
    lines = [ln.strip() for ln in text[m.end():].splitlines() if ln.strip()]
    years = []
    for ln in lines[:12]:
        y = re.fullmatch(r"March\s+31,\s*(\d{4})", ln)
        if y:
            years.append(f"FY{y.group(1)}")
    if len(years) != 2:
        raise ValueError("cannot read the two fee years from the page text")
    rows: list[list[str]] = [[""] + [f"March 31, {y[2:]}" for y in years]]
    for label in ROWS:
        i = lines.index(label)
        rows.append([label, lines[i + 1], lines[i + 2]])
    return parse_fee_table(rows)


def read_fee_table(pdf_path: Path, page_number: int) -> list[list[str]]:
    import pymupdf

    with pymupdf.open(pdf_path) as doc:
        for tb in doc[page_number - 1].find_tables().tables:
            rows = tb.extract()
            if any((r[0] or "").strip() == "For taxation matters" for r in rows):
                return rows
    raise ValueError(f"no auditor fee table found on page {page_number}")


def ingest_auditor_fees(session: Session, company_id: int, pdf_path: str | Path) -> str:
    pdf_path = Path(pdf_path)
    digest = sha256_file(pdf_path)
    version = session.execute(
        select(DocumentVersion).join(Document, Document.id == DocumentVersion.document_id)
        .where(Document.company_id == company_id, DocumentVersion.file_sha256 == digest)).scalars().first()
    if version is None:
        raise ValueError("this PDF has not been ingested yet (run ingest-document first)")
    document = session.get(Document, version.document_id)
    page = _find_page(session, version.id)
    if page is None:
        raise ValueError("no 'Auditor's remuneration' note found in the saved pages")
    try:
        years = parse_fee_table(read_fee_table(pdf_path, page))
    except ValueError:
        text = session.execute(select(TextExtract.text).where(
            TextExtract.document_version_id == version.id, TextExtract.page_number == page)).scalar_one()
        years = parse_fee_text(text)
    payload = {"document_version_id": version.id, "file_name": version.file_name, "file_sha256": digest,
               "report_fy": document.fiscal_year, "page": page, "basis": "standalone", "unit": "INR crore",
               "years": years}
    h = compute_payload_hash(payload)
    old = session.query(Snapshot).filter_by(company_id=company_id, source_provider=PROVIDER,
                                            source_endpoint=ENDPOINT, payload_hash=h).first()
    if old:
        return f"{document.fiscal_year}: already saved (snapshot {old.snapshot_id})"
    snap = save_snapshot(session, company_id, RawSourceResponse(
        provider=PROVIDER, endpoint=ENDPOINT, request_params={"document_version_id": version.id},
        status_code=200, payload=payload, fetched_at=dt.datetime.now(dt.timezone.utc)))
    return f"{document.fiscal_year} report, page {page}: {', '.join(sorted(years))} (snapshot {snap.snapshot_id})"


def load_auditor_fees(session: Session, company_id: int) -> tuple[dict[str, dict], list[str]]:
    """{FY: {fee lines, 'report_fy', 'page', 'snapshot_id', 'document_version_id'}} plus notes on any
    year whose two printed values differ between reports."""
    best: dict[str, dict] = {}
    seen: dict[str, list[tuple[str, dict]]] = {}
    q = session.query(Snapshot).filter_by(company_id=company_id, source_provider=PROVIDER, source_endpoint=ENDPOINT)
    for snap in q.order_by(Snapshot.snapshot_id):
        p = snap.raw_payload
        for fy, vals in p["years"].items():
            seen.setdefault(fy, []).append((p["report_fy"], vals))
            if fy not in best or p["report_fy"] == fy:     # the report of the year itself wins
                best[fy] = {**vals, "report_fy": p["report_fy"], "page": p["page"],
                            "snapshot_id": snap.snapshot_id, "document_version_id": p["document_version_id"]}
    notes = []
    for fy, versions in sorted(seen.items()):
        if len({tuple(sorted(v.items())) for _, v in versions}) > 1:
            notes.append(f"{fy}: the fee table differs between reports ({', '.join(r for r, _ in versions)}); "
                         f"the report of that year is used.")
    return best, notes


def fee_changes(fees: dict[str, dict]) -> list[dict]:
    """Year-on-year change of the audit fee and of the total of all four lines, in percent."""
    out = []
    for fy in sorted(fees):
        prior = f"FY{int(fy[2:]) - 1}"
        if prior in fees:
            cur, old = fees[fy], fees[prior]
            tot = lambda d: sum(d[k] for k in ROWS.values())  # noqa: E731
            out.append({"fy": fy, "audit_fee_change_pct": round((cur["audit_fee_cr"] / old["audit_fee_cr"] - 1) * 100, 1),
                        "total_change_pct": round((tot(cur) / tot(old) - 1) * 100, 1),
                        "audit_fee_cr": cur["audit_fee_cr"], "total_cr": tot(cur)})
    return out
