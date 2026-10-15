"""Choose which saved pages are sent to the model for a task. Deterministic; no model."""
from __future__ import annotations

import re

from sqlalchemy.orm import Session

from crest_forensic.db.models import DocumentVersion
from crest_forensic.documents.ingest import load_pages
from crest_forensic.documents.quotes import normalize
from crest_forensic.text.tasks import TextTask


def select_pages(session: Session, version: DocumentVersion, task: TextTask, basis: str) -> dict[int, str]:
    sel = task.selector
    sections = version.sections or {}

    if "section" in sel:
        span = sections.get(sel["section"].format(basis=basis))
        return load_pages(session, version.id, span["first"], span["last"]) if span else {}

    span = sections.get(sel["notes_section"].format(basis=basis))
    if not span:
        return {}
    notes = load_pages(session, version.id, span["first"], span["last"])

    if "heading_regex" in sel:
        rx, head = re.compile(sel["heading_regex"], re.I), sel.get("heading_chars", 700)
        matched = [n for n, t in notes.items() if rx.search(normalize(t)[:head])]
    else:
        rx = re.compile(sel["regex"], re.I)
        matched = [n for n, t in notes.items() if rx.search(normalize(t))]

    chosen: set[int] = set()
    for n in matched:
        chosen.update(m for m in range(n, n + sel.get("pages_after", 0) + 1) if m in notes)
    ordered = sorted(chosen)[: sel.get("max_pages", 8)]
    return {n: notes[n] for n in ordered}
