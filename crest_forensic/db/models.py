"""SQLAlchemy models for the Phase 1 data foundation.

Design constraints (see Build Plan sections 5, 6 and the Developer Review
sections 5-6): snapshots and line_items are append-only. Nothing in this
module updates or deletes a snapshot or line_item row — new data always
means a new row.
"""
from __future__ import annotations

import datetime as dt

from sqlalchemy import (
    JSON,
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Index,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


def _utcnow() -> dt.datetime:
    return dt.datetime.now(dt.timezone.utc)


class Company(Base):
    __tablename__ = "companies"

    company_id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(255))
    isin: Mapped[str | None] = mapped_column(String(20), nullable=True)
    nse_symbol: Mapped[str | None] = mapped_column(String(50), nullable=True)
    bse_code: Mapped[str | None] = mapped_column(String(20), nullable=True)
    sc_id: Mapped[str | None] = mapped_column(String(50), nullable=True, index=True)
    sector: Mapped[str | None] = mapped_column(String(255), nullable=True)
    is_financial_company: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    # SUPPORTED / SUPPORTED_WITH_LIMITATIONS / INSUFFICIENT_DATA / UNSUPPORTED_ENTITY_TYPE
    supported_status: Mapped[str | None] = mapped_column(String(40), nullable=True)

    __table_args__ = (Index("ix_companies_nse_symbol", "nse_symbol"),)


class Snapshot(Base):
    """One immutable fetch. Never updated, never deleted."""

    __tablename__ = "snapshots"

    snapshot_id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    company_id: Mapped[int] = mapped_column(ForeignKey("companies.company_id"))
    source_provider: Mapped[str] = mapped_column(String(50))  # "rapidapi_moneycontrol"
    source_endpoint: Mapped[str] = mapped_column(String(255))
    request_params: Mapped[dict] = mapped_column(JSON)
    fetched_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)
    raw_payload: Mapped[dict] = mapped_column(JSON)
    payload_hash: Mapped[str] = mapped_column(String(64), index=True)  # sha256 hex
    provisional: Mapped[bool] = mapped_column(Boolean, default=True)


class LineItem(Base):
    """One normalized financial figure, traced back to its snapshot."""

    __tablename__ = "line_items"

    value_id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    company_id: Mapped[int] = mapped_column(ForeignKey("companies.company_id"))
    snapshot_id: Mapped[int] = mapped_column(ForeignKey("snapshots.snapshot_id"))
    standard_field: Mapped[str] = mapped_column(String(100), index=True)
    raw_value: Mapped[str] = mapped_column(String(100))  # keep the untouched source string
    normalized_value: Mapped[float | None] = mapped_column(Float, nullable=True)
    unit: Mapped[str | None] = mapped_column(String(20), nullable=True)
    currency: Mapped[str] = mapped_column(String(10), default="INR")
    financial_year: Mapped[str | None] = mapped_column(String(10), nullable=True)  # "FY2025"
    period_end_date: Mapped[dt.date | None] = mapped_column(nullable=True)
    period_type: Mapped[str] = mapped_column(String(20))  # annual / quarterly
    basis: Mapped[str] = mapped_column(String(20))  # standalone / consolidated / UNKNOWN
    semantics: Mapped[str] = mapped_column(String(10))  # flow / stock
    statement_type: Mapped[str] = mapped_column(String(20))  # income / balance_sheet / cash_flow / notes
    source_field_name: Mapped[str] = mapped_column(String(150))
    source_ref: Mapped[str | None] = mapped_column(String(255), nullable=True)  # json-path in raw_payload
    mapping_version: Mapped[int] = mapped_column(default=1)
    retrieved_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)
    # None = directly sourced from the provider. Otherwise, e.g.
    # "indirect_method_v1" — this value was computed from OTHER line items,
    # not read from the source, and must never be presented as if sourced.
    derivation_method: Mapped[str | None] = mapped_column(String(50), nullable=True)

    __table_args__ = (
        Index(
            "ix_line_items_lookup",
            "company_id",
            "standard_field",
            "financial_year",
            "basis",
        ),
    )


class Shareholding(Base):
    __tablename__ = "shareholding"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    company_id: Mapped[int] = mapped_column(ForeignKey("companies.company_id"))
    snapshot_id: Mapped[int] = mapped_column(ForeignKey("snapshots.snapshot_id"))
    quarter: Mapped[str] = mapped_column(String(20))  # e.g. "Q1FY2026"
    promoter_pct: Mapped[float | None] = mapped_column(Float, nullable=True)
    pledged_pct: Mapped[float | None] = mapped_column(Float, nullable=True)
    fii_pct: Mapped[float | None] = mapped_column(Float, nullable=True)
    dii_pct: Mapped[float | None] = mapped_column(Float, nullable=True)
    retrieved_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)


class DataQualityEvent(Base):
    __tablename__ = "data_quality_events"

    event_id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    snapshot_id: Mapped[int | None] = mapped_column(ForeignKey("snapshots.snapshot_id"), nullable=True)
    company_id: Mapped[int | None] = mapped_column(ForeignKey("companies.company_id"), nullable=True)
    field_name: Mapped[str | None] = mapped_column(String(100), nullable=True)
    issue_type: Mapped[str] = mapped_column(String(50))
    severity: Mapped[str] = mapped_column(String(10))  # info / warning / error
    note: Mapped[str] = mapped_column(Text)
    created_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)


# ---------------------------------------------------------------------------
# Phase 2: config versions, runs, check results, flags, guardrail events.
# Build Plan section 6: rows in runs / flags / check_results are never edited
# or deleted — a re-run or a new decision always inserts new rows.
# ---------------------------------------------------------------------------


class ConfigVersion(Base):
    """One saved copy of the check config (limits + severity rules)."""

    __tablename__ = "config_versions"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    version: Mapped[int] = mapped_column()
    content: Mapped[dict] = mapped_column(JSON)
    content_hash: Mapped[str] = mapped_column(String(64), index=True)
    owner: Mapped[str | None] = mapped_column(String(100), nullable=True)
    approved_by: Mapped[str | None] = mapped_column(String(100), nullable=True)
    approved_at: Mapped[str | None] = mapped_column(String(40), nullable=True)
    created_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)
    # Phase 4: versions made in the config editor. `origin` is "file" (copied from the YAML by a run)
    # or "editor" (created by the forensic lead in the app); the newest editor version is the live config.
    origin: Mapped[str] = mapped_column(String(10), default="file")
    created_by: Mapped[str | None] = mapped_column(String(60), nullable=True)
    note: Mapped[str | None] = mapped_column(Text, nullable=True)
    parent_id: Mapped[int | None] = mapped_column(ForeignKey("config_versions.id"), nullable=True)


class Run(Base):
    __tablename__ = "runs"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    company_id: Mapped[int] = mapped_column(ForeignKey("companies.company_id"))
    basis: Mapped[str] = mapped_column(String(20))
    years: Mapped[list] = mapped_column(JSON)
    config_version_id: Mapped[int] = mapped_column(ForeignKey("config_versions.id"))
    config_approved: Mapped[bool] = mapped_column(Boolean)
    code_version: Mapped[str] = mapped_column(String(64))
    run_signature: Mapped[str] = mapped_column(String(64), index=True)
    manifest: Mapped[dict] = mapped_column(JSON)
    flags_created: Mapped[int] = mapped_column(default=0)
    flags_dropped: Mapped[int] = mapped_column(default=0)
    started_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)


class CheckResultRow(Base):
    __tablename__ = "check_results"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    run_id: Mapped[int] = mapped_column(ForeignKey("runs.id"), index=True)
    check_id: Mapped[str] = mapped_column(String(20))
    check_version: Mapped[int] = mapped_column()
    # COMPLETED / NOT_ENOUGH_DATA / METRIC_ONLY / NEEDS_DEFINITION
    status: Mapped[str] = mapped_column(String(30))
    detail: Mapped[dict] = mapped_column(JSON)


class Flag(Base):
    __tablename__ = "flags"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    run_id: Mapped[int] = mapped_column(ForeignKey("runs.id"), index=True)
    check_id: Mapped[str] = mapped_column(String(20))
    check_version: Mapped[int] = mapped_column()
    financial_year: Mapped[str] = mapped_column(String(10))
    what_observed: Mapped[str] = mapped_column(Text)
    location: Mapped[dict] = mapped_column(JSON)
    technique: Mapped[str] = mapped_column(String(200))
    severity: Mapped[str] = mapped_column(String(10))  # high / medium / low
    severity_rule_id: Mapped[str] = mapped_column(String(30))
    materiality: Mapped[dict] = mapped_column(JSON)
    evidence_confidence: Mapped[str] = mapped_column(String(10))  # high / medium / low
    figures: Mapped[dict] = mapped_column(JSON)
    citation: Mapped[dict] = mapped_column(JSON)
    status: Mapped[str] = mapped_column(String(20), default="OPEN")
    content_hash: Mapped[str] = mapped_column(String(64), index=True)
    created_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)


class GuardrailEvent(Base):
    """A flag that failed a guardrail and was dropped (never shown as a flag)."""

    __tablename__ = "guardrail_events"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    run_id: Mapped[int] = mapped_column(ForeignKey("runs.id"), index=True)
    check_id: Mapped[str] = mapped_column(String(20))
    financial_year: Mapped[str | None] = mapped_column(String(10), nullable=True)
    guardrail: Mapped[str] = mapped_column(String(40))
    detail: Mapped[str] = mapped_column(Text)
    created_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)


# ---------------------------------------------------------------------------
# Phase 3: documents (annual reports), page text, LLM calls, text findings.
# ---------------------------------------------------------------------------


class Document(Base):
    """A logical source document, e.g. TCS annual report for FY2026."""

    __tablename__ = "documents"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    company_id: Mapped[int] = mapped_column(ForeignKey("companies.company_id"))
    doc_type: Mapped[str] = mapped_column(String(30))  # annual_report
    fiscal_year: Mapped[str] = mapped_column(String(10))  # FY2026 = the year the report covers
    title: Mapped[str] = mapped_column(String(255))
    created_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)


class DocumentVersion(Base):
    """One immutable copy of a document, identified by the SHA-256 of the file."""

    __tablename__ = "document_versions"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    document_id: Mapped[int] = mapped_column(ForeignKey("documents.id"), index=True)
    file_name: Mapped[str] = mapped_column(String(255))
    file_sha256: Mapped[str] = mapped_column(String(64), index=True)
    page_count: Mapped[int] = mapped_column()
    extractor: Mapped[str] = mapped_column(String(60))
    # Page ranges found by heading detection, e.g. {"standalone_auditors_report": {"first": 240, "last": 252}}
    sections: Mapped[dict] = mapped_column(JSON)
    created_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)


class TextExtract(Base):
    """The text of one PDF page, exactly as extracted."""

    __tablename__ = "text_extracts"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    document_version_id: Mapped[int] = mapped_column(ForeignKey("document_versions.id"), index=True)
    page_number: Mapped[int] = mapped_column()  # PDF page index, 1-based
    printed_page: Mapped[str | None] = mapped_column(String(10), nullable=True)
    text: Mapped[str] = mapped_column(Text)
    text_sha256: Mapped[str] = mapped_column(String(64))

    __table_args__ = (Index("ix_text_extracts_doc_page", "document_version_id", "page_number"),)


class LlmCall(Base):
    """Every model call: what was asked, with which pinned model and prompt, and what came back."""

    __tablename__ = "llm_calls"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    document_version_id: Mapped[int | None] = mapped_column(ForeignKey("document_versions.id"), nullable=True)
    task: Mapped[str] = mapped_column(String(40))  # e.g. J1-10:standalone
    model: Mapped[str] = mapped_column(String(80))
    prompt_version: Mapped[str] = mapped_column(String(40))
    prompt_sha256: Mapped[str] = mapped_column(String(64))
    pages: Mapped[list] = mapped_column(JSON)  # PDF pages that were sent
    request_sha256: Mapped[str] = mapped_column(String(64), index=True)
    response: Mapped[dict] = mapped_column(JSON)
    input_tokens: Mapped[int | None] = mapped_column(nullable=True)
    output_tokens: Mapped[int | None] = mapped_column(nullable=True)
    created_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)


class TextFinding(Base):
    """A candidate finding proposed by the model. UNTRUSTED until validation passes."""

    __tablename__ = "text_findings"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    llm_call_id: Mapped[int] = mapped_column(ForeignKey("llm_calls.id"), index=True)
    document_version_id: Mapped[int] = mapped_column(ForeignKey("document_versions.id"), index=True)
    company_id: Mapped[int] = mapped_column(ForeignKey("companies.company_id"))
    check_id: Mapped[str] = mapped_column(String(20))
    financial_year: Mapped[str] = mapped_column(String(10))
    basis: Mapped[str | None] = mapped_column(String(20), nullable=True)
    finding_type: Mapped[str] = mapped_column(String(60))
    quote: Mapped[str] = mapped_column(Text)
    page_number: Mapped[int | None] = mapped_column(nullable=True)
    payload: Mapped[dict] = mapped_column(JSON)
    validation_status: Mapped[str] = mapped_column(String(10))  # PASSED / FAILED
    validation_detail: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)


# ---------------------------------------------------------------------------
# Phase 4: review app. Cases, people, reviews, escalations.
# Flags (above) are never edited; a reviewer's decision is a NEW row in `reviews`,
# and a flag's review status is whatever its latest review says.
# ---------------------------------------------------------------------------

ROLES = ("analyst", "forensic_lead", "adviser", "partner", "memo_owner")


class AppUser(Base):
    __tablename__ = "app_users"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    username: Mapped[str] = mapped_column(String(60), unique=True)
    display_name: Mapped[str] = mapped_column(String(120))
    role: Mapped[str] = mapped_column(String(20))  # one of ROLES
    password_hash: Mapped[str | None] = mapped_column(String(300), nullable=True)   # salted scrypt; None = cannot sign in yet
    password_set_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    active: Mapped[bool] = mapped_column(Boolean, default=True, server_default="1")


class AuthSession(Base):
    """A signed-in browser. Only the SHA-256 of the cookie token is kept."""

    __tablename__ = "auth_sessions"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    token_hash: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    username: Mapped[str] = mapped_column(String(60), index=True)
    created_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)
    expires_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True))
    revoked: Mapped[bool] = mapped_column(Boolean, default=False)


class AuthEvent(Base):
    """Append-only log of sign-ins and account changes. Never holds a password or a token."""

    __tablename__ = "auth_events"
    __table_args__ = {"sqlite_autoincrement": True}

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    created_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), default=_utcnow, index=True)
    event: Mapped[str] = mapped_column(String(30), index=True)
    username: Mapped[str] = mapped_column(String(60), index=True)     # the account concerned (as typed, for failed sign-ins)
    actor: Mapped[str | None] = mapped_column(String(60), nullable=True)   # who did it, when someone else did
    ip: Mapped[str | None] = mapped_column(String(45), nullable=True)
    detail: Mapped[str] = mapped_column(String(200), default="")


class Case(Base):
    __tablename__ = "cases"
    __table_args__ = {"sqlite_autoincrement": True}   # an id is never handed out twice, even after a delete

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    company_id: Mapped[int] = mapped_column(ForeignKey("companies.company_id"), index=True)
    years: Mapped[list] = mapped_column(JSON)
    reason: Mapped[str] = mapped_column(Text)
    exposure_note: Mapped[str | None] = mapped_column(Text, nullable=True)
    is_portfolio_company: Mapped[bool] = mapped_column(Boolean, default=False)
    name: Mapped[str | None] = mapped_column(String(120), nullable=True)      # optional free-text name given by whoever opens the case
    status: Mapped[str] = mapped_column(String(20), default="open")  # open / in_review / escalated / closed
    created_by: Mapped[str] = mapped_column(String(60))
    created_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)


class CaseEvent(Base):
    """Closing and reopening a case. Append-only: the case's current state is its newest event."""

    __tablename__ = "case_events"
    __table_args__ = {"sqlite_autoincrement": True}   # an id is never handed out twice, even after a delete

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    case_id: Mapped[int] = mapped_column(ForeignKey("cases.id"), index=True)
    action: Mapped[str] = mapped_column(String(10))          # closed / reopened
    by: Mapped[str] = mapped_column(String(60))
    reason: Mapped[str] = mapped_column(Text)
    at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)


class Review(Base):
    """One reviewer decision on one flag. Append-only: changing your mind adds a row."""

    __tablename__ = "reviews"
    __table_args__ = {"sqlite_autoincrement": True}   # an id is never handed out twice, even after a delete

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    flag_id: Mapped[int] = mapped_column(ForeignKey("flags.id"), index=True)
    case_id: Mapped[int] = mapped_column(ForeignKey("cases.id"), index=True)
    reviewer: Mapped[str] = mapped_column(String(60))
    decision: Mapped[str] = mapped_column(String(10))  # accept / reject
    reason: Mapped[str] = mapped_column(Text)
    decided_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)


class Escalation(Base):
    __tablename__ = "escalations"
    __table_args__ = {"sqlite_autoincrement": True}   # an id is never handed out twice, even after a delete

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    flag_id: Mapped[int] = mapped_column(ForeignKey("flags.id"), index=True)
    case_id: Mapped[int] = mapped_column(ForeignKey("cases.id"), index=True)
    requested_by: Mapped[str] = mapped_column(String(60))
    note: Mapped[str] = mapped_column(Text)
    requested_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)
    adviser_approval_by: Mapped[str | None] = mapped_column(String(60), nullable=True)
    approved_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class Memo(Base):
    """A research assessment memo for one case (Job 4). Its text lives in append-only MemoVersion rows."""

    __tablename__ = "memos"
    __table_args__ = {"sqlite_autoincrement": True}   # an id is never handed out twice

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    case_id: Mapped[int] = mapped_column(ForeignKey("cases.id"), index=True)
    reference: Mapped[str] = mapped_column(String(80), unique=True)
    owner: Mapped[str] = mapped_column(String(60))               # the named human who edits and signs
    scope_note: Mapped[str] = mapped_column(Text, default="")
    created_by: Mapped[str] = mapped_column(String(60))
    created_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)
    signed_version_id: Mapped[int | None] = mapped_column(nullable=True)     # set when signed; the memo is then locked
    signed_by: Mapped[str | None] = mapped_column(String(60), nullable=True)
    signed_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class MemoVersion(Base):
    """One saved draft of a memo. Never edited: a regenerate or a human edit adds a new row."""

    __tablename__ = "memo_versions"
    __table_args__ = {"sqlite_autoincrement": True}

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    memo_id: Mapped[int] = mapped_column(ForeignKey("memos.id"), index=True)
    version_no: Mapped[int] = mapped_column()
    kind: Mapped[str] = mapped_column(String(12))                # generated / edited
    created_by: Mapped[str] = mapped_column(String(60))
    created_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)
    content: Mapped[dict] = mapped_column(JSON)
    input_hash: Mapped[str] = mapped_column(String(64))          # fingerprint of the flags and decisions it was built from
    change_note: Mapped[str] = mapped_column(Text, default="")


class AgentSession(Base):
    """One chat about a case. A case can have many; the messages inside are the audit log and are never edited."""

    __tablename__ = "agent_sessions"
    __table_args__ = {"sqlite_autoincrement": True}   # an id is never handed out twice, even after a delete

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    case_id: Mapped[int] = mapped_column(ForeignKey("cases.id"), index=True)
    created_by: Mapped[str] = mapped_column(String(60))
    title: Mapped[str] = mapped_column(String(120), default="New chat")   # the first question, shortened
    created_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)


class AgentMessage(Base):
    """Every question put to the agent and what came back: an audit log, never edited."""

    __tablename__ = "agent_messages"
    __table_args__ = {"sqlite_autoincrement": True}   # an id is never handed out twice, even after a delete

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    case_id: Mapped[int] = mapped_column(ForeignKey("cases.id"), index=True)
    session_id: Mapped[int | None] = mapped_column(ForeignKey("agent_sessions.id"), index=True, nullable=True)
    asked_by: Mapped[str] = mapped_column(String(60))
    question: Mapped[str] = mapped_column(Text)
    answer: Mapped[str] = mapped_column(Text)
    # answered / refused (a leading question, no model call) / clarify (too short to answer, no model call) / blocked (a guardrail stopped the model's answer) / error
    status: Mapped[str] = mapped_column(String(10))
    model: Mapped[str | None] = mapped_column(String(80), nullable=True)
    tool_calls: Mapped[list] = mapped_column(JSON)
    sources: Mapped[list] = mapped_column(JSON)
    warnings: Mapped[list] = mapped_column(JSON)
    input_tokens: Mapped[int | None] = mapped_column(nullable=True)
    output_tokens: Mapped[int | None] = mapped_column(nullable=True)
    model_calls: Mapped[int] = mapped_column(default=0)   # requests made to the model: the free quota is counted in these
    created_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)


class MatrixNarrative(Base):
    """An AI reading of one company's multi-year matrix: stored, never edited (an audit log like the agent's answers)."""

    __tablename__ = "matrix_narratives"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    company_id: Mapped[int] = mapped_column(ForeignKey("companies.company_id"), index=True)
    basis: Mapped[str] = mapped_column(String(15))
    years: Mapped[list] = mapped_column(JSON)
    facts_hash: Mapped[str] = mapped_column(String(16))     # identifies the exact matrix the model was shown
    text: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(10))         # answered / blocked (a guardrail stopped it) / error
    model: Mapped[str | None] = mapped_column(String(80), nullable=True)
    warnings: Mapped[list] = mapped_column(JSON)
    sources: Mapped[list] = mapped_column(JSON)
    input_tokens: Mapped[int | None] = mapped_column(nullable=True)
    output_tokens: Mapped[int | None] = mapped_column(nullable=True)
    model_calls: Mapped[int] = mapped_column(default=0)
    methodology: Mapped[str | None] = mapped_column(Text, nullable=True)   # the writer's own notes that were sent with the matrix
    created_by: Mapped[str] = mapped_column(String(60))
    created_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)


class UserMethodology(Base):
    """One user's own written approach to reading a matrix. It steers emphasis in their narratives; it changes no number,
    label or approved limit."""

    __tablename__ = "user_methodologies"

    username: Mapped[str] = mapped_column(String(60), primary_key=True)
    text: Mapped[str] = mapped_column(Text)
    updated_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)


class WatchlistItem(Base):
    """A company a user keeps an eye on (the Home screen's Watchlist filter)."""

    __tablename__ = "watchlist_items"
    __table_args__ = (UniqueConstraint("username", "company_id", name="uq_watchlist_user_company"),)

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    username: Mapped[str] = mapped_column(String(60), index=True)
    company_id: Mapped[int] = mapped_column(ForeignKey("companies.company_id"))
    added_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)


class PublicRecordItem(Base):
    """One public-record fact about a company (an enforcement order, tribunal ruling, exchange announcement or credible news item)
    added by a named person. Append-only. Job 3 counts an item as a present indicator when its tags match a scheme indicator."""

    __tablename__ = "public_record_items"
    __table_args__ = {"sqlite_autoincrement": True}

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    company_id: Mapped[int] = mapped_column(ForeignKey("companies.company_id"), index=True)
    kind: Mapped[str] = mapped_column(String(30))        # enforcement_order / tribunal / announcement / news / filing_analysis / other
    title: Mapped[str] = mapped_column(String(255))
    source_name: Mapped[str] = mapped_column(String(120))
    url: Mapped[str | None] = mapped_column(String(500), nullable=True)
    published_on: Mapped[str | None] = mapped_column(String(10), nullable=True)     # ISO date
    summary: Mapped[str] = mapped_column(Text)
    tags: Mapped[list] = mapped_column(JSON)
    names_individual: Mapped[bool] = mapped_column(Boolean, default=False)           # needs partner review before a match is kept
    added_by: Mapped[str] = mapped_column(String(60))
    added_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)


class TypologyMatch(Base):
    """One ranked scheme match for a case (Job 3). A hypothesis, never a conclusion. Each run adds a new batch; old batches are kept."""

    __tablename__ = "typology_matches"
    __table_args__ = {"sqlite_autoincrement": True}

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    case_id: Mapped[int] = mapped_column(ForeignKey("cases.id"), index=True)
    batch: Mapped[int] = mapped_column(index=True)
    scheme_id: Mapped[str] = mapped_column(String(20))
    scheme_name: Mapped[str] = mapped_column(String(200))
    class_label: Mapped[str] = mapped_column(String(80))
    coverage: Mapped[float] = mapped_column(Float)
    present: Mapped[list] = mapped_column(JSON)
    missing: Mapped[list] = mapped_column(JSON)
    against: Mapped[list] = mapped_column(JSON)
    innocent_explanations: Mapped[list] = mapped_column(JSON)
    evidence_to_confirm: Mapped[list] = mapped_column(JSON)
    citations: Mapped[dict] = mapped_column(JSON)
    named_individual: Mapped[bool] = mapped_column(Boolean, default=False)
    input_hash: Mapped[str] = mapped_column(String(64))
    created_by: Mapped[str] = mapped_column(String(60))
    created_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)
    review_status: Mapped[str] = mapped_column(String(12), default="pending")          # pending / accepted / rejected (forensic lead)
    reviewed_by: Mapped[str | None] = mapped_column(String(60), nullable=True)
    reviewed_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    review_note: Mapped[str | None] = mapped_column(Text, nullable=True)
    citations_verified: Mapped[bool | None] = mapped_column(Boolean, nullable=True)      # the lead confirmed the references were checked
    partner_status: Mapped[str] = mapped_column(String(12), default="not_needed")      # not_needed / pending / accepted / rejected
    partner_by: Mapped[str | None] = mapped_column(String(60), nullable=True)
    partner_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    partner_note: Mapped[str | None] = mapped_column(Text, nullable=True)


class PeerLink(Base):
    """The forensic lead's peer set: company_id is compared with peer_company_id (Job 2 peer tests). Append-only; ended_at closes a link."""

    __tablename__ = "peer_links"
    __table_args__ = (UniqueConstraint("company_id", "peer_company_id", name="uq_peer_link"), {"sqlite_autoincrement": True})

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    company_id: Mapped[int] = mapped_column(ForeignKey("companies.company_id"), index=True)
    peer_company_id: Mapped[int] = mapped_column(ForeignKey("companies.company_id"), index=True)
    approved_by: Mapped[str] = mapped_column(String(120))
    approved_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)
    note: Mapped[str | None] = mapped_column(Text, nullable=True)


class CaseMember(Base):
    """Who may open a case besides the forensic lead (who sees every case). Append-only: removing someone sets removed_at, so the
    record of who had access and when is kept."""

    __tablename__ = "case_members"
    __table_args__ = {"sqlite_autoincrement": True}

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    case_id: Mapped[int] = mapped_column(ForeignKey("cases.id"), index=True)
    username: Mapped[str] = mapped_column(String(60), index=True)
    added_by: Mapped[str] = mapped_column(String(60))
    added_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)
    removed_by: Mapped[str | None] = mapped_column(String(60), nullable=True)
    removed_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
