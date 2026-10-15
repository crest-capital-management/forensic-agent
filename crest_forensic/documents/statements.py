"""Read figures straight from the printed financial statements of an annual report.

No model is involved: each configured label (config/statement_lines.yaml) is
found by exact match on its statement page and the numbers printed beside it
are parsed. The audited report is the highest-authority source we have, so
these values are stored as line items from provider "annual_report_pdf", each
citing a snapshot that records the document, section, page and printed label.
"""
from __future__ import annotations

import hashlib
import re
from pathlib import Path

import yaml
from sqlalchemy import select
from sqlalchemy.orm import Session

from crest_forensic.db.models import Document, DocumentVersion, LineItem, Snapshot
from crest_forensic.documents.ingest import load_pages
from crest_forensic.documents.quotes import normalize
from crest_forensic.ingestion.fetch_and_snapshot import compute_payload_hash
from crest_forensic.ingestion.quality import (
    MISSING_FIELD, SEVERITY_ERROR, SEVERITY_WARNING, UNIT_MISMATCH, log_quality_event,
)

PROVIDER = "annual_report_pdf"
CRORE = 1e7
DEFAULT_LINES_PATH = Path(__file__).resolve().parent.parent / "config" / "statement_lines.yaml"

_NOTE_RE = re.compile(r"\d{1,2}(\([a-z]+\))?$")
_NUM_RE = re.compile(r"\(?\d[\d,]*(\.\d+)?\)?$")
_DASHES = {"-", "–", "—"}
_CRORE_HEADER = re.compile(r"\(\s*\S{1,3}\s*crores?\s*\)")


def load_statement_lines(path: str | Path = DEFAULT_LINES_PATH) -> dict:
    with open(path, "r", encoding="utf-8") as fh:
        return yaml.safe_load(fh)


def _parse_value(token: str) -> int | float | None:
    token = token.strip()
    if token in _DASHES:
        return None  # printed as nil
    negative = token.startswith("(") and token.endswith(")")
    number = token.strip("()").replace(",", "")
    value = float(number) if "." in number else int(number)
    return -value if negative else value


def _row_values(lines: list[str], at: int) -> list[str] | None:
    """The two value tokens printed after the label on line `at` (a note column is dropped)."""
    tokens: list[str] = []
    for line in lines[at + 1: at + 6]:
        if _NOTE_RE.match(line) or _NUM_RE.match(line) or line in _DASHES:
            tokens.append(line)
        else:
            break
    if len(tokens) >= 3 and _NOTE_RE.match(tokens[0]):
        tokens = tokens[1:3]
    elif len(tokens) >= 2:
        tokens = tokens[:2]
    else:
        return None
    return tokens if len(tokens) == 2 else None


def find_row(pages: dict[int, str], label: str, occurrence: int = 0) -> dict | None:
    """Locate the nth printed row with this label across the section's pages."""
    target = normalize(label)
    seen = 0
    for number in sorted(pages):
        lines = [ln.strip() for ln in pages[number].splitlines() if ln.strip()]
        for i, line in enumerate(lines):
            if normalize(line) != target:
                continue
            tokens = _row_values(lines, i)
            if tokens is None:
                continue
            if seen == occurrence:
                return {"label": label, "page": number, "tokens": tokens}
            seen += 1
    return None


def _prior_fy(fy: str) -> str:
    return f"FY{int(fy[2:]) - 1}"


def _snapshot_for(session: Session, version: DocumentVersion, company_id: int, section: str, payload: dict) -> Snapshot:
    endpoint = f"pdf:{version.file_sha256[:12]}:{section}"
    existing = session.execute(
        select(Snapshot).where(Snapshot.company_id == company_id, Snapshot.source_provider == PROVIDER,
                               Snapshot.source_endpoint == endpoint)
    ).scalars().first()
    if existing:
        return existing  # immutable: re-extraction reuses it
    snap = Snapshot(
        company_id=company_id, source_provider=PROVIDER, source_endpoint=endpoint,
        request_params={"document_version_id": version.id, "section": section, "unit": "INR crore"},
        fetched_at=version.created_at, raw_payload=payload, payload_hash=compute_payload_hash(payload),
        provisional=False,
    )
    session.add(snap)
    session.flush()
    return snap


def extract_statement_lines(
    session: Session, version: DocumentVersion, company_id: int, lines_config: dict | None = None,
) -> list[LineItem]:
    cfg = lines_config or load_statement_lines()
    document = session.get(Document, version.document_id)
    fy_now, fy_prior = document.fiscal_year, _prior_fy(document.fiscal_year)
    created: list[LineItem] = []

    for basis in ("consolidated", "standalone"):
        for statement in ("profit_and_loss", "balance_sheet", "cash_flow"):
            section = f"{basis}_{statement}"
            span = (version.sections or {}).get(section)
            wanted = [ln for ln in cfg["lines"] if ln["statement"] == statement]
            if not span or not wanted:
                continue
            pages = load_pages(session, version.id, span["first"], span["last"])

            if not any(_CRORE_HEADER.search(normalize(t)) for t in pages.values()):
                log_quality_event(
                    session, company_id=company_id, issue_type=UNIT_MISMATCH, severity=SEVERITY_ERROR,
                    note=f"{section} (pages {span['first']}-{span['last']}): no '(... crore)' unit header; section not read.")
                continue

            rows: dict[str, dict] = {}
            for ln in wanted:
                parts = ln.get("sum_of") or [{"label": ln["label"], "occurrence": ln.get("occurrence", 0)}]
                found = [find_row(pages, p["label"], p.get("occurrence", 0)) for p in parts]
                if any(f is None for f in found):
                    log_quality_event(
                        session, company_id=company_id, field_name=ln["field"], issue_type=MISSING_FIELD,
                        severity=SEVERITY_WARNING,
                        note=f"{section}: printed row not found for {[p['label'] for p in parts]}.")
                    continue
                rows[ln["field"]] = {"parts": found, "line": ln}

            payload = {
                "document": document.title, "fiscal_year": document.fiscal_year, "section": section,
                "page_sha256": {str(n): hashlib.sha256(t.encode("utf-8")).hexdigest() for n, t in pages.items()},
                "rows": {f: [{"label": p["label"], "page": p["page"], "tokens": p["tokens"]} for p in r["parts"]]
                         for f, r in rows.items()},
            }
            if not rows:
                continue
            snap = _snapshot_for(session, version, company_id, section, payload)

            for field, r in rows.items():
                ln, parts = r["line"], r["parts"]
                for column, fy in ((0, fy_now), (1, fy_prior)):
                    values = [_parse_value(p["tokens"][column]) for p in parts]
                    if all(v is None for v in values):
                        continue
                    total = sum(v or 0 for v in values)
                    raw = "+".join(p["tokens"][column] for p in parts)
                    li = LineItem(
                        company_id=company_id, snapshot_id=snap.snapshot_id, standard_field=field,
                        raw_value=raw, normalized_value=float(total) * CRORE, unit="INR_absolute", currency="INR",
                        financial_year=fy, period_type="annual", basis=basis, semantics=ln["semantics"],
                        statement_type=ln["statement_type"],
                        source_field_name=" + ".join(p["label"] for p in parts),
                        source_ref=f"pdf:{section}:{'+'.join(p['label'] for p in parts)}",
                        mapping_version=cfg["version"],
                    )
                    session.add(li)
                    created.append(li)
    session.flush()
    return created


def extract_all_documents(session: Session, company_id: int) -> list[LineItem]:
    versions = session.execute(
        select(DocumentVersion).join(Document, Document.id == DocumentVersion.document_id)
        .where(Document.company_id == company_id).order_by(DocumentVersion.id)
    ).scalars().all()
    created: list[LineItem] = []
    for version in versions:
        created += extract_statement_lines(session, version, company_id)
    return created
