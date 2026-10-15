"""Find the sections of an annual report (no model involved).

Auditor's-report parts are found by their headings. Financial statements are
found by what they contain (e.g. "TOTAL ASSETS" with "TOTAL EQUITY AND
LIABILITIES"), because the statement titles are not always present in the PDF
text layer. Basis follows document order: statements after the consolidated
auditor's report and before the standalone one are consolidated.

The result is stored on the document version so every later quote can be
checked to lie inside the section it was supposed to come from.
"""
from __future__ import annotations

import re

from crest_forensic.documents.quotes import normalize

# Headings that occur once, as a heading. Matched anywhere on the page.
_REPORT_HEADINGS = {
    "consolidated_auditors_report": r"Report on the Audit of the Consolidated Financial Statements",
    "consolidated_annexure_a": r"Annexure A to the Independent Auditor's Report on the [Cc]onsolidated",
    "consolidated_annexure_b": r"Annexure B to the Independent Auditor's Report on the [Cc]onsolidated",
    "standalone_auditors_report": r"Report on the Audit of the Standalone Financial Statements",
    "standalone_annexure_a": r"Annexure A to the Independent Auditor's Report on the [Ss]tandalone",
    "standalone_annexure_b": r"Annexure B to the Independent Auditor's Report on the [Ss]tandalone",
}

# Statement name -> phrases that must ALL be on the page.
_STATEMENT_SIGNATURES = {
    "balance_sheet": ["TOTAL ASSETS", "TOTAL EQUITY AND LIABILITIES"],
    "profit_and_loss": ["TOTAL INCOME", "PROFIT BEFORE TAX", "Earnings per equity share"],
    "cash_flow": ["CASH FLOWS FROM OPERATING ACTIVITIES"],
}
_STATEMENT_PAGES = {"balance_sheet": 1, "profit_and_loss": 1, "cash_flow": 2}

FULL_REPORT_PARTS = {
    "consolidated_auditors_report_full": [
        "consolidated_auditors_report", "consolidated_annexure_a", "consolidated_annexure_b"],
    "standalone_auditors_report_full": [
        "standalone_auditors_report", "standalone_annexure_a", "standalone_annexure_b"],
}


def _first_page(pages: dict[int, str], test, after: int = 0, before: int | None = None) -> int | None:
    for n in sorted(pages):
        if n > after and (before is None or n < before) and test(pages[n]):
            return n
    return None


def locate_sections(pages: dict[int, str]) -> dict[str, dict[str, int]]:
    norm = {n: normalize(t) for n, t in pages.items()}
    last_page = max(pages) if pages else 0

    starts: dict[str, int] = {}
    for key, pattern in _REPORT_HEADINGS.items():
        rx = re.compile(pattern)
        page = _first_page(norm, rx.search)
        if page is not None:
            starts[key] = page

    cons_start = starts.get("consolidated_auditors_report")
    stand_start = starts.get("standalone_auditors_report")
    bounds = {  # (statements must come after, and before)
        "consolidated": (cons_start or 0, stand_start),
        "standalone": (stand_start or 0, None),
    }
    statement_starts: dict[str, int] = {}
    for basis, (after, before) in bounds.items():
        if basis == "standalone" and stand_start is None:
            continue
        for name, phrases in _STATEMENT_SIGNATURES.items():
            page = _first_page(norm, lambda t, ph=phrases: all(p in t for p in ph), after, before)
            if page is not None:
                statement_starts[f"{basis}_{name}"] = page

    sections: dict[str, dict[str, int]] = {}

    # Auditor's-report parts run up to the next part, or to the balance sheet for the last one.
    for basis in ("consolidated", "standalone"):
        parts = sorted(
            [(k, p) for k, p in starts.items() if k.startswith(basis)], key=lambda kv: kv[1])
        end_marker = statement_starts.get(f"{basis}_balance_sheet", last_page + 1)
        for i, (key, first) in enumerate(parts):
            nxt = parts[i + 1][1] if i + 1 < len(parts) else end_marker
            sections[key] = {"first": first, "last": max(first, nxt - 1)}

    for key, first in statement_starts.items():
        name = key.split("_", 1)[1]
        sections[key] = {"first": first, "last": min(last_page, first + _STATEMENT_PAGES[name] - 1)}

    # Notes to the financial statements: after the last statement of each basis.
    cons_cf = sections.get("consolidated_cash_flow")
    if cons_cf:
        notes_end = (stand_start - 1) if stand_start else last_page
        if notes_end > cons_cf["last"]:
            sections["consolidated_notes"] = {"first": cons_cf["last"] + 1, "last": notes_end}
    stand_cf = sections.get("standalone_cash_flow")
    if stand_cf and last_page > stand_cf["last"]:
        sections["standalone_notes"] = {"first": stand_cf["last"] + 1, "last": last_page}

    for full, parts in FULL_REPORT_PARTS.items():
        present = [sections[p] for p in parts if p in sections]
        if present:
            sections[full] = {"first": min(s["first"] for s in present), "last": max(s["last"] for s in present)}
    return sections
