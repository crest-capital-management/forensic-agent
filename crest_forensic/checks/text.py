"""J1-10 .. J1-15: checks built on verified passages of the annual report.

By the time a finding reaches here it has already passed code validation (the
exact quote is on the cited page). The wording of every observation is
generated below from the finding TYPE; the only model-supplied text that is
ever shown is the verified quote. Severity comes from the config, not the model.
"""
from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from crest_forensic.checks.base import (
    STATUS_COMPLETED, STATUS_NEEDS_SOURCE, STATUS_NOT_ENOUGH_DATA, CheckResult, Observation, Skip,
)
from crest_forensic.db.models import Document, DocumentVersion, LlmCall, TextExtract, TextFinding
from crest_forensic.text.priority import primary_call

# check -> the section of the document its pages must lie in (location check)
CHECK_SECTION = {
    "J1-10": "{basis}_auditors_report",
    "J1-11": "{basis}_annexure_a",
    "J1-12": "{basis}_auditors_report_full",
    "J1-14": "{basis}_notes",
    "J1-15": "{basis}_notes",
}

_TECHNIQUE = {
    "J1-10": "Auditor's opinion, emphasis-of-matter and key audit matters, read from the auditor's report",
    "J1-11": "Adverse or qualified answers in the CARO annexure to the auditor's report",
    "J1-12": "Auditor firm registration number compared between consecutive annual reports",
    "J1-14": "Related-party disclosures lacking stated pricing or terms (Ind AS 24 notes)",
    "J1-15": "Stated changes of accounting policy or estimate, read from the notes",
}

_WORDING = {
    "opinion_unmodified": "the auditor's report on the {basis} financial statements for {fy} expresses an unmodified opinion (page {page}).",
    "opinion_qualified": "the auditor's report on the {basis} financial statements for {fy} expresses a qualified opinion (page {page}).",
    "opinion_adverse": "the auditor's report on the {basis} financial statements for {fy} expresses an adverse opinion (page {page}).",
    "opinion_disclaimer": "the auditor's report on the {basis} financial statements for {fy} disclaims an opinion (page {page}).",
    "emphasis_of_matter_paragraph": "the auditor's report on the {basis} financial statements for {fy} contains an emphasis-of-matter paragraph (page {page}).",
    "material_uncertainty_going_concern": "the auditor's report on the {basis} financial statements for {fy} states that a material uncertainty related to going concern exists (page {page}).",
    "key_audit_matter": "the auditor's report on the {basis} financial statements for {fy} lists a key audit matter (page {page}).",
    "caro_adverse_or_qualified_answer": "the CARO annexure to the auditor's report on the {basis} financial statements for {fy} reports an unfavourable or qualified answer (page {page}).",
    "related_party_terms_not_stated": "the related-party notes to the {basis} financial statements for {fy} disclose a transaction or balance without stating its pricing, terms or basis (page {page}).",
    "change_in_accounting_policy": "the notes to the {basis} financial statements for {fy} state a change in accounting policy (page {page}).",
    "change_in_accounting_estimate": "the notes to the {basis} financial statements for {fy} state a change in an accounting estimate (page {page}).",
    "adoption_of_new_accounting_standard": "the notes to the {basis} financial statements for {fy} state that a new or amended accounting standard was applied (page {page}).",
}


def _sentence(text: str) -> str:
    return text[0].upper() + text[1:]


def _latest_versions(session: Session, company_id: int) -> dict[str, DocumentVersion]:
    """fiscal_year -> the latest saved version of that year's annual report."""
    rows = session.execute(
        select(Document, DocumentVersion).join(DocumentVersion, DocumentVersion.document_id == Document.id)
        .where(Document.company_id == company_id, Document.doc_type == "annual_report")
        .order_by(DocumentVersion.id)).all()
    return {doc.fiscal_year: ver for doc, ver in rows}


def _evidence_item(session: Session, finding: TextFinding, version: DocumentVersion, role: str = "finding") -> dict:
    page = session.execute(select(TextExtract).where(
        TextExtract.document_version_id == version.id, TextExtract.page_number == finding.page_number)).scalars().first()
    return {
        "role": role, "finding_id": finding.id, "document_version_id": version.id,
        "document_sha256": version.file_sha256, "file_name": version.file_name, "fy": finding.financial_year,
        "page": finding.page_number, "printed_page": page.printed_page if page else None, "quote": finding.quote,
        "finding_type": finding.finding_type,
    }


def _severity(cfg: dict, finding_type: str) -> str | None:
    return ((cfg.get("finding_severity") or {}).get(finding_type) or {}).get("value")


def _observation(check_id: str, cfg: dict, fy: str, finding_type: str, evidence: list[dict],
                 wording: str, figures: dict) -> Observation:
    return Observation(
        check_id=check_id, fy=fy, metric_name=finding_type, metric_value=None,
        severity=_severity(cfg, finding_type), severity_rule_id=cfg["rule_id"],
        formula_id=f"text:{check_id}", technique=_TECHNIQUE[check_id], what_observed=_sentence(wording),
        inputs=[], thresholds_applied={"finding_severity": cfg.get("finding_severity")},
        materiality={"label": "not_assessed", "basis": "text passage; no monetary amount"},
        figures=figures, evidence=evidence,
    )


def run_text_check(session: Session, company_id: int, basis: str, years: list[str], check_id: str, cfg: dict) -> CheckResult:
    versions = _latest_versions(session, company_id)
    obs, skipped = [], []
    for fy in years:
        version = versions.get(fy)
        if version is None:
            continue
        ran = primary_call(session, version.id, f"{check_id}:{basis}")   # main source only; others are cross-checks
        if ran is None:
            skipped.append(Skip(fy, "NOT_ENOUGH_DATA", f"text extraction for {check_id} ({basis}) has not been run on the {fy} annual report"))
            continue
        findings = session.execute(select(TextFinding).where(
            TextFinding.llm_call_id == ran.id, TextFinding.check_id == check_id,
            TextFinding.basis == basis, TextFinding.validation_status == "PASSED").order_by(TextFinding.id)).scalars().all()
        for f in findings:
            wording = _WORDING[f.finding_type].format(basis=basis, fy=fy, page=f.page_number)
            conf = (f.payload or {}).get("confidence")
            obs.append(_observation(
                check_id, cfg, fy, f.finding_type, [_evidence_item(session, f, version)], wording,
                {"finding_type": f.finding_type, "page": f.page_number, "model_confidence": conf, "quote": f.quote}))

    if check_id == "J1-10":  # an opinion type must be identified for every document read
        for fy in years:
            if versions.get(fy) and not any(o.fy == fy and o.metric_name.startswith("opinion_") for o in obs) \
                    and not any(s.fy == fy for s in skipped):
                skipped.append(Skip(fy, "NOT_ENOUGH_DATA", "no verified statement of the audit opinion type was identified"))

    status = STATUS_NOT_ENOUGH_DATA if not obs and skipped else STATUS_COMPLETED
    return CheckResult(check_id, cfg.get("check_version", 1), status, obs, skipped)


def run_j1_12(session: Session, company_id: int, basis: str, years: list[str], cfg: dict) -> CheckResult:
    versions = _latest_versions(session, company_id)
    identities: dict[str, tuple[TextFinding, DocumentVersion]] = {}
    for fy, version in versions.items():
        f = session.execute(select(TextFinding).where(
            TextFinding.document_version_id == version.id, TextFinding.check_id == "J1-12",
            TextFinding.basis == basis, TextFinding.validation_status == "PASSED")).scalars().first()
        if f:
            identities[fy] = (f, version)

    obs, skipped = [], []
    ordered = sorted(identities)
    for prev, cur in zip(ordered, ordered[1:]):
        if cur not in years:
            continue
        (f_prev, v_prev), (f_cur, v_cur) = identities[prev], identities[cur]
        changed = f_prev.payload["registration_no"] != f_cur.payload["registration_no"]
        ftype = "auditor_changed" if changed else "auditor_unchanged"
        wording = (
            f"the auditor named in the report on the {basis} financial statements for {cur} (firm registration no. "
            f"{f_cur.payload['registration_no']}) differs from the auditor named for {prev} (firm registration no. "
            f"{f_prev.payload['registration_no']})." if changed else
            f"the auditor named in the report on the {basis} financial statements for {cur} is the same firm as for {prev} "
            f"(firm registration no. {f_cur.payload['registration_no']}).")
        o = _observation("J1-12", cfg, cur, ftype,
                         [_evidence_item(session, f_prev, v_prev, "prior_year"), _evidence_item(session, f_cur, v_cur, "current_year")],
                         wording, {"finding_type": ftype, "prior_fy": prev, "current_fy": cur,
                                   "prior_registration_no": f_prev.payload["registration_no"],
                                   "current_registration_no": f_cur.payload["registration_no"]})
        obs.append(o)
    if not obs:
        skipped.append(Skip("*", "NOT_ENOUGH_DATA",
                            f"need the auditor's report of two consecutive years for the {basis} basis; "
                            f"found {', '.join(ordered) or 'none'}"))
    status = STATUS_NOT_ENOUGH_DATA if not obs else STATUS_COMPLETED
    return CheckResult("J1-12", cfg.get("check_version", 1), status, obs, skipped)


def run_j1_13(cfg: dict) -> CheckResult:
    result = CheckResult("J1-13", cfg.get("check_version", 1), STATUS_NEEDS_SOURCE)
    result.notes.append(
        "Delayed filings need the exchange filing dates for results and annual reports. No saved source carries them "
        "(the annual report shows only the Board approval date), so the check cannot run until a source is chosen.")
    return result


def run_text_checks(session: Session, company_id: int, basis: str, years: list[str], checks_cfg: dict) -> list[CheckResult]:
    results = [run_text_check(session, company_id, basis, years, cid, checks_cfg[cid]) for cid in ("J1-10", "J1-11")]
    results.append(run_j1_12(session, company_id, basis, years, checks_cfg["J1-12"]))
    from crest_forensic.checks.filing_dates import run_j1_13 as run_filing_dates
    results.append(run_filing_dates(session, company_id, basis, years, checks_cfg["J1-13"]))
    results += [run_text_check(session, company_id, basis, years, cid, checks_cfg[cid]) for cid in ("J1-14", "J1-15")]
    return results
