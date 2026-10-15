"""Which model's text findings are the main set.

Several models can read the same pages (the recorded Claude Code reading, a live
Claude call, Gemini). Only ONE source feeds the screen and flags for each
check; the rest are cross-checks, shown but never counted. The order comes from
`text_source_priority` in config/llm.yaml: a model label that starts with an
earlier entry wins. A source with no usable call for a check is skipped.
"""
from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from crest_forensic.db.models import LlmCall
from crest_forensic.text.extractors import load_llm_config

DEFAULT_PRIORITY = ["claude-code-session", "claude", "gemini"]


def source_priority() -> list[str]:
    return load_llm_config().get("text_source_priority") or DEFAULT_PRIORITY


def _rank(model: str, priority: list[str]) -> int:
    for i, prefix in enumerate(priority):
        if model.startswith(prefix):
            return i
    return len(priority)


def primary_call(session: Session, document_version_id: int, task: str) -> LlmCall | None:
    """The latest call of the highest-priority model for this task, or None."""
    calls = session.execute(select(LlmCall).where(
        LlmCall.document_version_id == document_version_id, LlmCall.task == task)
        .order_by(LlmCall.id)).scalars().all()
    if not calls:
        return None
    priority = source_priority()
    best = min(_rank(c.model, priority) for c in calls)
    return [c for c in calls if _rank(c.model, priority) == best][-1]
