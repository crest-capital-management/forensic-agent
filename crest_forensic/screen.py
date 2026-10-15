"""Run a Job 1 number screen and create flags — deterministically.

Flow (Developer Review 4.2):
    saved evidence -> calculation -> observation -> guardrails -> formal flag

Only this module writes flags, and only after every guardrail passes. Claude
has no part in it (Build Plan rule 6; Developer Review 3.1).
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

import yaml
from sqlalchemy import select
from sqlalchemy.orm import Session

from crest_forensic.checks.base import InputStore, evidence_confidence
from crest_forensic.checks.registry import REGISTRY
from crest_forensic.checks.text import CHECK_SECTION, run_text_checks
from crest_forensic.config_store import active_config
from crest_forensic.db.models import (
    CheckResultRow, Company, ConfigVersion, Document, DocumentVersion, Flag, GuardrailEvent, LlmCall, Run,
    Snapshot, TextFinding,
)
from crest_forensic.guardrails.config_gate import ensure_config_runnable, unapproved_values
from crest_forensic.guardrails.language import LEADS_NOT_PROOF, PUBLIC_DATA_LIMIT
from crest_forensic.guardrails.validate import validate_observation
from crest_forensic.ingestion.resolve import load_policy
from crest_forensic.ingestion.supported_status import UNSUPPORTED_ENTITY_TYPE

DEFAULT_CONFIG_PATH = Path(__file__).resolve().parent / "config" / "check_config.yaml"
_PKG = Path(__file__).resolve().parent

_STATEMENT_OF = {
    "profit_after_tax": "Statement of Profit and Loss", "profit_before_tax": "Statement of Profit and Loss",
    "revenue_from_operations": "Statement of Profit and Loss", "other_income": "Statement of Profit and Loss",
    "tax_expense": "Statement of Profit and Loss", "depreciation_amortisation": "Statement of Profit and Loss",
    "cost_of_materials_or_goods": "Statement of Profit and Loss", "selling_and_admin_expenses": "Statement of Profit and Loss",
    "cash_flow_from_operations": "Cash Flow Statement",
}


def _sha(obj) -> str:
    return hashlib.sha256(json.dumps(obj, sort_keys=True, default=str).encode("utf-8")).hexdigest()


def code_version() -> str:
    """Hash of the source that decides results, so a run records exactly which code made it."""
    files = sorted(
        [*(_PKG / "checks").glob("*.py"), *(_PKG / "guardrails").glob("*.py"), _PKG / "screen.py",
         _PKG / "ingestion" / "resolve.py", _PKG / "ingestion" / "derive.py"]
    )
    h = hashlib.sha256()
    for f in files:
        h.update(f.name.encode())
        h.update(f.read_bytes())
    return h.hexdigest()[:16]


def load_check_config(path: str | Path = DEFAULT_CONFIG_PATH) -> dict:
    with open(path, "r", encoding="utf-8") as fh:
        return yaml.safe_load(fh)


def save_config_version(session: Session, config: dict) -> ConfigVersion:
    content_hash = _sha(config)
    existing = session.execute(
        select(ConfigVersion).where(ConfigVersion.content_hash == content_hash)
    ).scalars().first()
    if existing:
        return existing
    approval = config.get("approval") or {}
    row = ConfigVersion(
        version=config["version"], content=config, content_hash=content_hash, owner=config.get("owner"),
        approved_by=approval.get("approved_by"), approved_at=approval.get("approved_at"),
    )
    session.add(row)
    session.flush()
    return row


def years_between(first: str, last: str) -> list[str]:
    a, b = int(first[2:]), int(last[2:])
    return [f"FY{y}" for y in range(a, b + 1)]


def _flag_content_hash(obs, basis: str) -> str:
    return _sha({
        "check": obs.check_id, "fy": obs.fy, "basis": basis, "severity": obs.severity,
        "metric": None if obs.metric_value is None else round(obs.metric_value, 9),
        "inputs": sorted((i.standard_field, i.fy, i.line_item_id, round(i.value, 6)) for i in obs.inputs),
        "evidence": sorted((e["fy"], e["document_sha256"], e["page"], e.get("quote", "")) for e in obs.evidence),
        "finding_type": obs.metric_name if obs.evidence else None,
        **({"filing_period": obs.figures["period_end"]} if obs.formula_id.startswith(("filing:", "shareholding:", "market:", "fees:", "relparty:", "peers:")) else {}),
    })


def _text_evidence_confidence(obs) -> str:
    """The quote is code-verified, so the passage is real. Confidence only drops if the
    model itself was unsure how to classify it."""
    conf = obs.figures.get("model_confidence")
    return {"low": "low", "medium": "medium"}.get(conf, "high")


def run_screen(
    session: Session, company_id: int, basis: str, years: list[str],
    *, allow_draft_config: bool = False, config_path: str | Path = DEFAULT_CONFIG_PATH,
) -> Run:
    company = session.get(Company, company_id)
    if company.supported_status == UNSUPPORTED_ENTITY_TYPE:
        raise ValueError(f"{company.name} is an unsupported entity type; no screen is run.")

    # No file named: use the live config (the newest version saved in the app, else the YAML file).
    config = active_config(session) if Path(config_path) == DEFAULT_CONFIG_PATH else load_check_config(config_path)
    approved = ensure_config_runnable(config, allow_draft_config)  # raises if not allowed
    cfg_row = save_config_version(session, config)
    policy = load_policy()

    store = InputStore(session, company_id, basis, policy)
    results, drafts = [], []
    for check_id, fn in REGISTRY:
        result = fn(store, years, config["checks"][check_id])
        results.append(result)
        drafts += [o for o in result.observations if o.severity is not None]
    for result in run_text_checks(session, company_id, basis, years, config["checks"]):
        results.append(result)
        drafts += [o for o in result.observations if o.severity is not None]

    # Guardrails: every would-be flag is validated; failures are dropped and logged.
    passed, dropped = [], []
    for obs in drafts:
        failures = validate_observation(session, obs, company_id, basis)
        (dropped if failures else passed).append((obs, failures))

    snapshot_ids = sorted(session.execute(
        select(Snapshot.snapshot_id).where(Snapshot.company_id == company_id)).scalars().all())
    from crest_forensic.ingestion.mapping import DEFAULT_MAPPING_PATH, load_field_mapping
    from crest_forensic.ingestion.yahoo import YAHOO_MAPPING_PATH
    manifest = {
        "snapshot_ids": snapshot_ids, "config_version_id": cfg_row.id, "config_hash": cfg_row.content_hash,
        "code_version": code_version(), "source_policy_version": policy["version"],
        "field_mapping_versions": {
            "rapidapi_moneycontrol": load_field_mapping(DEFAULT_MAPPING_PATH).mapping_version,
            "yfinance": load_field_mapping(YAHOO_MAPPING_PATH).mapping_version},
        "check_versions": {r.check_id: r.check_version for r in results},
        "documents": [
            {"version_id": v.id, "fiscal_year": d.fiscal_year, "sha256": v.file_sha256}
            for d, v in session.execute(
                select(Document, DocumentVersion).join(DocumentVersion, DocumentVersion.document_id == Document.id)
                .where(Document.company_id == company_id).order_by(DocumentVersion.id)).all()],
        "text_extractions": [
            {"call_id": c.id, "task": c.task, "model": c.model, "prompt_sha256": c.prompt_sha256}
            for c in session.execute(select(LlmCall).join(
                DocumentVersion, DocumentVersion.id == LlmCall.document_version_id).join(
                Document, Document.id == DocumentVersion.document_id).where(
                Document.company_id == company_id).order_by(LlmCall.id)).scalars()],
        "config_approved": approved,
        "unapproved_limit_count": len(unapproved_values(config)),
        "supported_status": company.supported_status,
    }
    signature = _sha({"company": company_id, "basis": basis, "years": years, "manifest": manifest})

    run = Run(
        company_id=company_id, basis=basis, years=years, config_version_id=cfg_row.id, config_approved=approved,
        code_version=manifest["code_version"], run_signature=signature, manifest=manifest,
        flags_created=len(passed), flags_dropped=len(dropped),
    )
    session.add(run)
    session.flush()

    for r in results:
        session.add(CheckResultRow(
            run_id=run.id, check_id=r.check_id, check_version=r.check_version, status=r.status,
            detail={
                "observations": len(r.observations),
                "metrics": [{"fy": o.fy, "metric": o.metric_name, "value": o.metric_value, "severity": o.severity}
                            for o in r.observations],
                "skipped": [{"fy": s.fy, "reason": s.reason, "detail": s.detail} for s in r.skipped],
                "notes": r.notes},
        ))

    for obs, failures in dropped:
        for guardrail, detail in failures:
            session.add(GuardrailEvent(run_id=run.id, check_id=obs.check_id, financial_year=obs.fy,
                                       guardrail=guardrail, detail=detail))

    for obs, _ in passed:
        if obs.formula_id.startswith("digits:"):
            ev = obs.evidence[0]
            pages = sorted({p for span in ev["sections"].values() for p in span})
            session.add(Flag(
                run_id=run.id, check_id=obs.check_id, check_version=run.manifest["check_versions"][obs.check_id],
                financial_year=obs.fy, what_observed=obs.what_observed,
                location={"documents": [ev["file_name"]], "sections": ev["sections"], "pages": [pages[0], pages[-1]],
                          "financial_years": [obs.fy], "basis": basis},
                technique=obs.technique, severity=obs.severity, severity_rule_id=obs.severity_rule_id,
                materiality=obs.materiality, evidence_confidence="low",   # a weak signal by nature
                figures={**obs.figures, "metric": obs.metric_name, "metric_value": obs.metric_value,
                         "thresholds_applied": obs.thresholds_applied},
                citation={
                    "company": company.name, "basis": basis, "evidence": obs.evidence,
                    "config_version_id": cfg_row.id,
                    "config_status": "APPROVED" if approved else "DRAFT_UNAPPROVED",
                    "note": f"{LEADS_NOT_PROOF} {PUBLIC_DATA_LIMIT}"},
                content_hash=_flag_content_hash(obs, basis),
            ))
            continue
        if obs.formula_id.startswith("peers:"):
            session.add(Flag(
                run_id=run.id, check_id=obs.check_id, check_version=run.manifest["check_versions"][obs.check_id],
                financial_year=obs.fy, what_observed=obs.what_observed,
                location={"statements": ["Statement of profit and loss"], "line_items": sorted({i.standard_field for i in obs.inputs}),
                          "peers": [p["name"] for p in obs.figures["peers"]], "financial_years": [obs.fy], "basis": basis},
                technique=obs.technique, severity=obs.severity, severity_rule_id=obs.severity_rule_id,
                materiality=obs.materiality, evidence_confidence="low",      # peer figures are unofficial and provisional
                figures={**obs.figures, "metric_value": obs.metric_value, "thresholds_applied": obs.thresholds_applied},
                citation={
                    "company": company.name, "basis": basis, "inputs": [i.ref() for i in obs.inputs],
                    "peers": [{"snapshot_id": p["snapshot_id"], "name": p["name"], "rate_pct": round(p["rate"] * 100, 2)} for p in obs.figures["peers"]],
                    "config_version_id": cfg_row.id,
                    "config_status": "APPROVED" if approved else "DRAFT_UNAPPROVED",
                    "note": f"{LEADS_NOT_PROOF} {PUBLIC_DATA_LIMIT}"},
                content_hash=_flag_content_hash(obs, basis),
            ))
            continue
        if obs.formula_id.startswith("relparty:"):
            session.add(Flag(
                run_id=run.id, check_id=obs.check_id, check_version=run.manifest["check_versions"][obs.check_id],
                financial_year=obs.fy, what_observed=obs.what_observed,
                location={"statements": ["Notes: transactions with related parties"], "line_items": sorted({i.standard_field for i in obs.inputs}),
                          "pages": [obs.figures["page"]], "financial_years": [obs.fy], "basis": basis},
                technique=obs.technique, severity=obs.severity, severity_rule_id=obs.severity_rule_id,
                materiality=obs.materiality, evidence_confidence="high",     # printed in the audited report's notes
                figures={**obs.figures, "metric_value": obs.metric_value, "thresholds_applied": obs.thresholds_applied},
                citation={
                    "company": company.name, "basis": basis, "inputs": [i.ref() for i in obs.inputs],
                    "related_parties": [{"snapshot_id": obs.figures["snapshot_id"], "fy": obs.fy, "page": obs.figures["page"],
                                         "report_fy": obs.figures["report_fy"]}],
                    "config_version_id": cfg_row.id,
                    "config_status": "APPROVED" if approved else "DRAFT_UNAPPROVED",
                    "note": f"{LEADS_NOT_PROOF} {PUBLIC_DATA_LIMIT}"},
                content_hash=_flag_content_hash(obs, basis),
            ))
            continue
        if obs.formula_id.startswith("fees:"):
            session.add(Flag(
                run_id=run.id, check_id=obs.check_id, check_version=run.manifest["check_versions"][obs.check_id],
                financial_year=obs.fy, what_observed=obs.what_observed,
                location={"auditor_fees": [f"Auditor's remuneration note, standalone notes, annual reports {obs.figures['report_fys'][0]} and {obs.figures['report_fys'][1]}"],
                          "pages": obs.figures["pages"], "financial_years": [obs.fy, obs.figures["prior_fy"]], "basis": basis},
                technique=obs.technique, severity=obs.severity, severity_rule_id=obs.severity_rule_id,
                materiality=obs.materiality, evidence_confidence="medium",   # printed in whole crores
                figures={**obs.figures, "metric_value": obs.metric_value, "thresholds_applied": obs.thresholds_applied},
                citation={
                    "company": company.name, "basis": basis,
                    "auditor_fees": [{"snapshot_id": i, "fy": y, "page": pg} for i, y, pg in
                                     zip(obs.figures["snapshot_ids"], (obs.fy, obs.figures["prior_fy"]), obs.figures["pages"])],
                    "config_version_id": cfg_row.id,
                    "config_status": "APPROVED" if approved else "DRAFT_UNAPPROVED",
                    "note": f"{LEADS_NOT_PROOF} {PUBLIC_DATA_LIMIT}"},
                content_hash=_flag_content_hash(obs, basis),
            ))
            continue
        if obs.formula_id.startswith("market:"):
            session.add(Flag(
                run_id=run.id, check_id=obs.check_id, check_version=run.manifest["check_versions"][obs.check_id],
                financial_year=obs.fy, what_observed=obs.what_observed,
                location={"prices": [f"{obs.figures['stock_ticker']} and Nifty 50 daily prices around the {obs.figures['quarter']} results"],
                          "financial_years": [obs.fy], "basis": basis},
                technique=obs.technique, severity=obs.severity, severity_rule_id=obs.severity_rule_id,
                materiality=obs.materiality, evidence_confidence="low",   # unofficial price source, statistical signal
                figures={**obs.figures, "metric_value": obs.metric_value, "thresholds_applied": obs.thresholds_applied},
                citation={
                    "company": company.name, "basis": basis,
                    "prices": [{"stock_snapshot_id": obs.figures["stock_snapshot_id"], "index_snapshot_id": obs.figures["index_snapshot_id"],
                                "results_snapshot_id": obs.figures["results_snapshot_id"], "reaction_day": obs.figures["reaction_day"],
                                "source": obs.figures["price_source"]}],
                    "config_version_id": cfg_row.id,
                    "config_status": "APPROVED" if approved else "DRAFT_UNAPPROVED",
                    "note": f"{LEADS_NOT_PROOF} {PUBLIC_DATA_LIMIT}"},
                content_hash=_flag_content_hash(obs, basis),
            ))
            continue
        if obs.formula_id.startswith("shareholding:"):
            session.add(Flag(
                run_id=run.id, check_id=obs.check_id, check_version=run.manifest["check_versions"][obs.check_id],
                financial_year=obs.fy, what_observed=obs.what_observed,
                location={"shareholding": [(f"{obs.figures['quarter']} and {obs.figures['prior_quarter']} shareholding patterns, exchange filings"
                                            if obs.figures.get("prior_quarter") else f"{obs.figures['quarter']} shareholding pattern, exchange filing")],
                          "financial_years": [obs.fy], "basis": basis},
                technique=obs.technique, severity=obs.severity, severity_rule_id=obs.severity_rule_id,
                materiality=obs.materiality, evidence_confidence="medium",   # exchange filings saved by hand
                figures={**obs.figures, "metric": obs.metric_name, "metric_value": obs.metric_value,
                         "thresholds_applied": obs.thresholds_applied},
                citation={
                    "company": company.name, "basis": basis,
                    "shareholding": [{"shareholding_id": i, "snapshot_id": s} for i, s in
                                     zip(obs.figures["shareholding_ids"], obs.figures["snapshot_ids"])],
                    "config_version_id": cfg_row.id,
                    "config_status": "APPROVED" if approved else "DRAFT_UNAPPROVED",
                    "note": f"{LEADS_NOT_PROOF} {PUBLIC_DATA_LIMIT}"},
                content_hash=_flag_content_hash(obs, basis),
            ))
            continue
        if obs.formula_id.startswith("filing:"):
            session.add(Flag(
                run_id=run.id, check_id=obs.check_id, check_version=run.manifest["check_versions"][obs.check_id],
                financial_year=obs.fy, what_observed=obs.what_observed,
                location={"filings": [f"{obs.figures['quarter']} {basis} results, exchange record"],
                          "financial_years": [obs.fy], "basis": basis},
                technique=obs.technique, severity=obs.severity, severity_rule_id=obs.severity_rule_id,
                materiality=obs.materiality, evidence_confidence="medium",   # hand-downloaded exchange file
                figures={**obs.figures, "metric": obs.metric_name, "metric_value": obs.metric_value,
                         "thresholds_applied": obs.thresholds_applied},
                citation={
                    "company": company.name, "basis": basis,
                    "filings": [{"snapshot_id": obs.figures["snapshot_id"], "period_end": obs.figures["period_end"],
                                 "received_at": obs.figures["received_at"], "xbrl_url": obs.figures["xbrl_url"]}],
                    "config_version_id": cfg_row.id,
                    "config_status": "APPROVED" if approved else "DRAFT_UNAPPROVED",
                    "note": f"{LEADS_NOT_PROOF} {PUBLIC_DATA_LIMIT}"},
                content_hash=_flag_content_hash(obs, basis),
            ))
            continue
        if obs.evidence:
            section = CHECK_SECTION[obs.check_id].format(basis=basis)
            session.add(Flag(
                run_id=run.id, check_id=obs.check_id, check_version=run.manifest["check_versions"][obs.check_id],
                financial_year=obs.fy, what_observed=obs.what_observed,
                location={"documents": sorted({e["file_name"] for e in obs.evidence}),
                          "section": section, "pages": sorted({e["page"] for e in obs.evidence}),
                          "printed_pages": sorted({str(e["printed_page"]) for e in obs.evidence if e["printed_page"]}),
                          "financial_years": sorted({e["fy"] for e in obs.evidence}), "basis": basis},
                technique=obs.technique, severity=obs.severity, severity_rule_id=obs.severity_rule_id,
                materiality=obs.materiality, evidence_confidence=_text_evidence_confidence(obs),
                figures={**obs.figures, "metric": obs.metric_name, "thresholds_applied": obs.thresholds_applied},
                citation={
                    "company": company.name, "basis": basis, "evidence": obs.evidence,
                    "config_version_id": cfg_row.id,
                    "config_status": "APPROVED" if approved else "DRAFT_UNAPPROVED",
                    "note": f"{LEADS_NOT_PROOF} {PUBLIC_DATA_LIMIT}"},
                content_hash=_flag_content_hash(obs, basis),
            ))
            continue
        fields = sorted({i.standard_field for i in obs.inputs})
        years_used = sorted({i.fy for i in obs.inputs})
        session.add(Flag(
            run_id=run.id, check_id=obs.check_id, check_version=run.manifest["check_versions"][obs.check_id],
            financial_year=obs.fy, what_observed=obs.what_observed,
            location={"statements": sorted({_STATEMENT_OF.get(f, "Balance Sheet") for f in fields}),
                      "line_items": fields, "financial_years": years_used, "basis": basis},
            technique=obs.technique, severity=obs.severity, severity_rule_id=obs.severity_rule_id,
            materiality=obs.materiality, evidence_confidence=evidence_confidence(obs.inputs),
            figures={**obs.figures, "metric": obs.metric_name, "metric_value": obs.metric_value,
                     "thresholds_applied": obs.thresholds_applied},
            citation={
                "company": company.name, "basis": basis, "inputs": [i.ref() for i in obs.inputs],
                "config_version_id": cfg_row.id,
                "config_status": "APPROVED" if approved else "DRAFT_UNAPPROVED",
                "note": f"{LEADS_NOT_PROOF} {PUBLIC_DATA_LIMIT}"},
            content_hash=_flag_content_hash(obs, basis),
        ))
    session.flush()
    return run
