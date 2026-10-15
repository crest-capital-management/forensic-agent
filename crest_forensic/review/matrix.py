"""Multi-year matrix: four forensic measures side by side across the years we have data for.

Nothing here is a new calculation. Each cell comes from the same check code a screen uses (J1-02 accruals,
J1-06 Beneish parts, J1-16 Altman Z'', J1-17 digit pattern), read with the live limits, so the numbers match the flags.
It is a live view: it writes nothing; run a screen to save results with their citations.

Plain ratios (review/ratios.py) ride along under "ratios": information only, never labelled, never in the summary or the narrative.
Ownership and auditor fees (review/ownership.py) ride along under "ownership" the same way (one label: promoter step vs the J2-01 limit).

Badges are review wording, never verdicts:  normal / look (worth a look) / review (review first) / None (no limit set).
The combined Beneish M-score is NOT shown: the plan requires the forensic lead to approve its weights, cut-off and the
Indian adaptation first. The eight parts are shown instead.
"""
from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from crest_forensic import config_store
from crest_forensic.checks import formulas
from crest_forensic.checks.altman import run_j1_16
from crest_forensic.checks.base import InputStore
from crest_forensic.checks.benford import run_j1_17
from crest_forensic.checks.beneish import run_j1_06
from crest_forensic.checks.profit_cash import run_j1_02
from crest_forensic.db.models import Company, Document, LineItem
from crest_forensic.ingestion.supported_status import UNSUPPORTED_ENTITY_TYPE
from crest_forensic.review.ownership import build_ownership
from crest_forensic.review.ratios import build_ratios
from crest_forensic.review.service import RuleError

MAX_YEARS = 10
BASES = ("consolidated", "standalone")
BEN_PARTS = {"DSRI": "Days sales in receivables index", "GMI": "Gross margin index", "AQI": "Asset quality index",
             "SGI": "Sales growth index", "DEPI": "Depreciation index", "SGAI": "Sales, general and admin. index",
             "LVGI": "Leverage index", "TATA": "Total accruals to total assets"}
BADGE_WORDS = {"normal": "Normal", "look": "Worth a look", "review": "Review first"}


def candidate_years(session: Session, company_id: int, basis: str) -> list[str]:
    """Years with revenue data, newest 10, and nothing after the newest saved annual report (later years are partial)."""
    found = {fy for (fy,) in session.execute(select(LineItem.financial_year).where(
        LineItem.company_id == company_id, LineItem.basis == basis, LineItem.standard_field == "revenue_from_operations",
        LineItem.period_type == "annual").distinct()).all()}
    report_years = [fy for (fy,) in session.execute(select(Document.fiscal_year).where(
        Document.company_id == company_id, Document.doc_type == "annual_report")).all()]
    if report_years:
        newest = max(report_years)
        found = {fy for fy in found if fy <= newest}
    return sorted(found)[-MAX_YEARS:]


def _cell(obs, badge: str | None, display: str, extra: dict | None = None) -> dict:
    return {"value": obs.metric_value, "display": display, "badge": badge, "what": obs.what_observed,
            "providers": sorted({p for i in obs.inputs for p in (i.providers or (i.provider,))}), **(extra or {})}


def _skip_cell(skip) -> dict:
    return {"value": None, "display": "not enough data", "badge": None, "skipped": skip.reason, "what": skip.detail}


def _fill(cells: dict, result, make) -> None:
    for o in result.observations:
        key = make(o)
        if key is not None:
            cells[o.fy] = key
    for s in result.skipped:
        cells.setdefault(s.fy, _skip_cell(s))


def _sloan_badge(sev: str | None) -> str:
    return {"high": "review", "medium": "look"}.get(sev or "", "normal")


def build_matrix(session: Session, company_id: int, basis: str) -> dict:
    if basis not in BASES:
        raise RuleError("basis must be consolidated or standalone")
    company = session.get(Company, company_id)
    if company is None:
        raise RuleError("Company not found.", 404)
    if company.supported_status == UNSUPPORTED_ENTITY_TYPE:
        raise RuleError(f"{company.name} is an unsupported entity type (for example a bank or insurer); these models do not apply.")
    config = config_store.active_config(session)
    cfg = config["checks"]
    years = candidate_years(session, company_id, basis)
    store = InputStore(session, company_id, basis)

    sloan = run_j1_02(store, years, cfg["J1-02"])
    beneish = run_j1_06(store, years, cfg["J1-06"])
    altman = run_j1_16(store, years, cfg["J1-16"])
    benford = run_j1_17(store, years, cfg["J1-17"])

    sloan_cells: dict = {}
    _fill(sloan_cells, sloan, lambda o: _cell(o, _sloan_badge(o.severity), f"{o.metric_value * 100:+.1f}%"))
    altman_cells: dict = {}
    _fill(altman_cells, altman, lambda o: _cell(
        o, {"above": "normal", "between": "look", "below": "review"}[o.figures["zone"]], f"{o.metric_value:.2f}",
        {"zone": o.figures["zone"]}))
    benford_cells: dict = {}
    _fill(benford_cells, benford, lambda o: _cell(
        o, {"close": "normal", "acceptable": "normal", "marginal": "look", "nonconforming": "review"}[o.figures["band"]],
        f"{o.metric_value:.4f}", {"band": o.figures["band"], "numbers_counted": o.figures["numbers_counted"]}))

    parts = {}
    for comp in BEN_PARTS:
        cells: dict = {}
        for o in beneish.observations:
            if o.metric_name == comp:
                cells[o.fy] = _cell(o, None, f"{o.metric_value:.2f}")
        for s in beneish.skipped:
            if s.detail.startswith(f"{comp}:"):
                cells.setdefault(s.fy, _skip_cell(s))
        parts[comp] = cells
    parts_count = {fy: sum(1 for c in parts.values() if fy in c and c[fy].get("value") is not None) for fy in years}

    z, ben, slo = cfg["J1-16"].get("zones", {}), cfg["J1-17"].get("mad_bands", {}), cfg["J1-02"].get("thresholds", {})
    rows = [
        {"key": "beneish", "name": "Beneish M-score", "question": "Earnings manipulation indicators",
         "kind": "parts", "cells": {fy: {"value": None, "display": f"{parts_count[fy]}/8 parts", "badge": None} for fy in years},
         "message": ("The combined M-score is not shown yet. The plan requires the forensic lead to approve its weights, "
                     "cut-off and the Indian adaptation first. The eight parts are listed below; GMI cannot be computed for "
                     "service companies (no cost of goods), so the original eight-part score could not be built for them anyway."),
         "parts": [{"key": k, "name": f"{k} · {BEN_PARTS[k]}", "cells": parts[k]} for k in BEN_PARTS]},
        {"key": "altman", "name": "Altman Z″ (emerging-market)", "question": "Financial stress", "kind": "score",
         "cells": altman_cells,
         "rule": f"Above {(z.get('safe_above') or {}).get('value')}: normal. Between {(z.get('stress_below') or {}).get('value')} and "
                 f"{(z.get('safe_above') or {}).get('value')}: worth a look. Below {(z.get('stress_below') or {}).get('value')}: review first.",
         "caveat": "Uses Other equity as the stand-in for retained earnings. Not for banks or insurers."},
        {"key": "benford", "name": "Benford's Law", "question": "Digit pattern in the statements and notes", "kind": "score",
         "cells": benford_cells,
         "rule": f"Mean deviation below {(ben.get('acceptable_below') or {}).get('value')}: normal; below "
                 f"{(ben.get('marginal_below') or {}).get('value')}: worth a look; above: review first.",
         "caveat": "A weak, low-confidence signal: many ordinary figures do not follow the pattern."},
        {"key": "sloan", "name": "Sloan accruals", "question": "Profit not backed by cash", "kind": "score",
         "cells": sloan_cells,
         "rule": f"(Profit − operating cash flow) ÷ average assets. Up to {(slo.get('medium') or {}).get('value')}: normal; "
                 f"above it: worth a look; above {(slo.get('high') or {}).get('value')}: review first.",
         "caveat": None},
    ]
    summary = {}
    for fy in years:
        tally = {"normal": 0, "look": 0, "review": 0, "no_data": 0}
        for r in rows[1:]:
            c = r["cells"].get(fy)
            tally[c["badge"] if c and c["badge"] else "no_data"] += 1
        summary[fy] = tally
    return {
        "company": {"company_id": company.company_id, "name": company.name, "symbol": company.nse_symbol or company.sc_id},
        "basis": basis, "years": years, "rows": rows, "summary": summary,
        "ratios": build_ratios(store, years),
        "ownership": build_ownership(session, company_id, years, cfg),
        "config_approved": bool((config.get("approval") or {}).get("approved_by")),
        "badge_words": BADGE_WORDS,
        "notes": ["Statistical leads only: most anomalies have innocent explanations. Public data cannot show the reason.",
                  "This is a live view built from saved data with the live limits; it writes nothing. Run a screen to save results with their citations."],
    }
