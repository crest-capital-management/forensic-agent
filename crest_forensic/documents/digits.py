"""Leading-digit counts of the amounts printed in an annual report's financial statements and notes (J1-17).

Deterministic, no model. Each distinct amount is counted once. Which numbers count: amounts of three or more digits, written with Indian or
international comma grouping or plain, e.g. 1,06,878 and 362 and 12,345.67. Left out: numbers starting with 0, numbers of one or two digits
(note numbers, percentages, counts), calendar years, and numbers that are part of a date or a reference (touching
"/", ":" or "-"). Printed page numbers are not removed; they are a tiny share of the numbers.

The section names come from the document's saved section map, so the same pages are read each time.
"""
from __future__ import annotations

import re

from sqlalchemy import select
from sqlalchemy.orm import Session

from crest_forensic.db.models import DocumentVersion, TextExtract

SECTIONS = ("{basis}_balance_sheet", "{basis}_profit_and_loss", "{basis}_cash_flow", "{basis}_notes")

_AMOUNT = re.compile(r"(?<![\d,.\-/:])(\d{1,3}(?:,\d{2,3})+|\d{3,})(?:\.\d+)?(?![\d,]|[/:\-]\d)")
_YEAR = re.compile(r"(?:19|20)\d{2}$")


def amount_tokens(text: str) -> list[str]:
    """The amounts in a page of text, as printed (years and short numbers already removed)."""
    out = []
    for m in _AMOUNT.finditer(text):
        token = m.group(1)
        if token.startswith("0") or ("," not in token and _YEAR.match(token)):
            continue                      # leading zeros are codes, not amounts; calendar years are not amounts
        out.append(token)
    return out


def leading_digit(token: str) -> int | None:
    first = token.lstrip("0")[:1]
    return int(first) if first.isdigit() and first != "0" else None


def leading_digits(text: str) -> list[int]:
    return [d for d in (leading_digit(t) for t in amount_tokens(text)) if d is not None]


def sections_for(version: DocumentVersion, basis: str) -> dict[str, tuple[int, int]]:
    spans = version.sections or {}
    found = {}
    for pattern in SECTIONS:
        name = pattern.format(basis=basis)
        if name in spans:
            found[name] = (spans[name]["first"], spans[name]["last"])
    return found


def count_digits(session: Session, version: DocumentVersion, basis: str) -> dict:
    """{"counts": [9 ints for digits 1..9], "n": int, "sections": {name: (first, last)}}.

    Each DISTINCT amount is counted once. Benford's Law describes a set of different amounts; the same figure
    printed again (a comparative column, a repeated table, "100" per cent in a holdings table) would otherwise
    swamp the pattern."""
    spans = sections_for(version, basis)
    distinct: set[str] = set()
    for first, last in spans.values():
        pages = session.execute(select(TextExtract.text).where(
            TextExtract.document_version_id == version.id,
            TextExtract.page_number >= first, TextExtract.page_number <= last)).scalars().all()
        for text in pages:
            distinct.update(amount_tokens(text))
    counts = [0] * 9
    for token in distinct:
        d = leading_digit(token)
        if d is not None:
            counts[d - 1] += 1
    return {"counts": counts, "n": sum(counts), "sections": spans}
