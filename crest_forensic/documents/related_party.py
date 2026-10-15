"""Related-party totals: read the 'Transactions with related parties' table of an annual report (no model).

For each basis the notes print a table by category of related party (the holding company, subsidiaries, group companies, others) with a
Total column, one table per year (the report year and the year before). This reads the Total of two rows, in INR crore:
  - "Revenue from operations" (revenue earned from related parties);
  - "Purchases of goods and services" (purchases from related parties).
Each report is saved as one snapshot per basis that cites the document, page and values. A year printed in two reports is taken from the
report of that year. Only tables that are headed by the holding company's name are read, so segment and geography tables are never mixed in.
"""
from __future__ import annotations

import datetime as dt
import re

from sqlalchemy import select
from sqlalchemy.orm import Session

from crest_forensic.connectors.base import RawSourceResponse
from crest_forensic.db.models import Document, DocumentVersion, Snapshot, TextExtract
from crest_forensic.ingestion.fetch_and_snapshot import compute_payload_hash, save_snapshot

PROVIDER = "annual_report_pdf"
ENDPOINT = "related_party_totals"
BASES = ("standalone", "consolidated")
ROWS = {"Revenue from operations": "revenue_cr", "Purchases of goods and services": "purchases_cr"}
_NUM = re.compile(r"-?[\d,]+|-")
_YEAR = re.compile(r"March 31, (\d{4})")


def _to_int(tok: str) -> int:
    return 0 if tok.strip() == "-" else int(tok.replace(",", ""))


def parse_page(text: str) -> list[dict]:
    """Every related-party table row of interest on one page: [{'label_key', 'fy_year', 'total', 'numbers'}]."""
    lines = [ln.strip() for ln in text.splitlines()]
    out = []
    for i, ln in enumerate(lines):
        key = next((v for k, v in ROWS.items() if ln.startswith(k)), None)
        if key is None:
            continue
        j = i + 1
        while j < len(lines) and not _NUM.fullmatch(lines[j]) and j - i < 4:      # a wrapped label
            j += 1
        nums = []
        while j < len(lines) and _NUM.fullmatch(lines[j]):
            nums.append(lines[j])
            j += 1
        if len(nums) < 4:
            continue                                                               # not a table with categories and a total
        before = lines[max(0, i - 60):i]
        if not any("Tata Sons" in b for b in before):
            continue
        years = [m for b in before for m in _YEAR.findall(b)]
        if not years:
            continue
        out.append({"label_key": key, "year": int(years[-1]), "total": _to_int(nums[-1]), "numbers": [_to_int(n) for n in nums]})
    return out


def read_version(session: Session, version: DocumentVersion, basis: str) -> dict | None:
    sec = (version.sections or {}).get(f"{basis}_notes")
    if not sec:
        return None
    years: dict[str, dict] = {}
    pages: dict[str, int] = {}
    for te in session.execute(select(TextExtract).where(
            TextExtract.document_version_id == version.id, TextExtract.page_number >= sec["first"],
            TextExtract.page_number <= sec["last"]).order_by(TextExtract.page_number)).scalars():
        for r in parse_page(te.text):
            fy = f"FY{r['year']}"
            if r["label_key"] not in years.setdefault(fy, {}):
                years[fy][r["label_key"]] = r["total"]
                pages[fy] = te.page_number
    years = {fy: v for fy, v in years.items() if set(v) == set(ROWS.values())}
    return {"years": years, "pages": {fy: pages[fy] for fy in years}} if years else None


def ingest_related_party(session: Session, company_id: int) -> list[str]:
    msgs = []
    q = (select(Document, DocumentVersion).join(DocumentVersion, DocumentVersion.document_id == Document.id)
         .where(Document.company_id == company_id, Document.doc_type == "annual_report").order_by(DocumentVersion.id))
    for doc, version in session.execute(q).all():
        for basis in BASES:
            got = read_version(session, version, basis)
            if got is None:
                msgs.append(f"{doc.fiscal_year} {basis}: no related-party table found")
                continue
            payload = {"document_version_id": version.id, "file_name": version.file_name, "file_sha256": version.file_sha256,
                       "report_fy": doc.fiscal_year, "basis": basis, "unit": "INR crore", **got}
            h = compute_payload_hash(payload)
            if session.query(Snapshot).filter_by(company_id=company_id, source_provider=PROVIDER, source_endpoint=ENDPOINT, payload_hash=h).first():
                msgs.append(f"{doc.fiscal_year} {basis}: already saved")
                continue
            snap = save_snapshot(session, company_id, RawSourceResponse(
                provider=PROVIDER, endpoint=ENDPOINT, request_params={"document_version_id": version.id, "basis": basis},
                status_code=200, payload=payload, fetched_at=dt.datetime.now(dt.timezone.utc)))
            msgs.append(f"{doc.fiscal_year} {basis}: {', '.join(sorted(got['years']))} (snapshot {snap.snapshot_id})")
    return msgs


def load_related_party(session: Session, company_id: int, basis: str) -> tuple[dict[str, dict], list[str]]:
    """{FY: {'revenue_cr', 'purchases_cr', 'report_fy', 'page', 'snapshot_id'}} plus notes on years whose two printed tables differ."""
    best: dict[str, dict] = {}
    seen: dict[str, list[tuple[str, dict]]] = {}
    q = session.query(Snapshot).filter_by(company_id=company_id, source_provider=PROVIDER, source_endpoint=ENDPOINT).order_by(Snapshot.snapshot_id)
    for snap in q:
        p = snap.raw_payload
        if p.get("basis") != basis:
            continue
        for fy, vals in p["years"].items():
            seen.setdefault(fy, []).append((p["report_fy"], vals))
            if fy not in best or p["report_fy"] == fy:
                best[fy] = {**vals, "report_fy": p["report_fy"], "page": p["pages"][fy], "snapshot_id": snap.snapshot_id}
    notes = [f"{fy}: the related-party totals differ between reports ({', '.join(r for r, _ in v)}); the report of that year is used."
             for fy, v in sorted(seen.items()) if len({tuple(sorted(x.items())) for _, x in v}) > 1]
    return best, notes
