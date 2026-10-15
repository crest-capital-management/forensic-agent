"""Flag validation: citation check, recalculation, banned language.

Nothing here trusts the check that produced the observation. Every cited
input is re-read from the database and compared; every metric is recomputed
from those re-read values (Developer Review 5.2 levels 1-3, 7-9).
"""
from __future__ import annotations

import json
import math

from sqlalchemy import select
from sqlalchemy.orm import Session

from crest_forensic.checks import formulas
from crest_forensic.checks.base import Observation
from crest_forensic.db.models import Document, DocumentVersion, LineItem, Snapshot, TextExtract, TextFinding
from crest_forensic.documents.quotes import quote_in_page
from crest_forensic.guardrails.language import banned_terms_in

# formula_id -> function(values by input name) -> metric
RECALCULATORS = {
    "J1-01.v1": lambda v: formulas.profit_cash_gap(v["pat"], v["cfo"]),
    "J1-02.v1": lambda v: formulas.accruals_ratio(v["pat"], v["cfo"], v["total_assets"], v["total_assets_prior"]),
    "J1-07.v1": lambda v: formulas.other_income_share(v["other_income"], v["pbt"]),
    "J1-09.v1": lambda v: formulas.restatement_change_pct(v["old"], v["new"]),
    "J1-16.v1": formulas.altman_z,
}


def _growth_ratio(v: dict):
    res = formulas.growth_ratio(v["item"], v["item_prior"], v["revenue"], v["revenue_prior"])
    return None if res is None else res["ratio"]


for _fid in ("J1-03.v1", "J1-04.v1", "J1-05.v1"):
    RECALCULATORS[_fid] = _growth_ratio
RECALCULATORS["J1-05.v2"] = lambda v: formulas.capacity_ratio(v["item"], v["item_prior"], v["revenue"], v["revenue_prior"])


def _assets_vs_expenses_ratio(v: dict):
    res = formulas.assets_vs_expenses(v["ta"], v["ca"], v["ta_prior"], v["ca_prior"], v["exp"], v["exp_prior"])
    return None if res is None else res["ratio"]


RECALCULATORS["J1-08.v1"] = _assets_vs_expenses_ratio
def _ratio_break_recalc(d: dict):
    from crest_forensic.checks.ratio_breaks import change

    def f(v: dict):
        cur = d["calc"]({k[4:]: x for k, x in v.items() if k.startswith("cur:")})
        old = d["calc"]({k[5:]: x for k, x in v.items() if k.startswith("prev:")})
        return None if cur is None or old is None else change(d["kind"], cur[0], old[0])
    return f


def _register_ratio_breaks() -> None:
    from crest_forensic.review.ratios import _defs

    for _d in _defs():
        RECALCULATORS[f"J2-05.{_d['key']}.v1"] = _ratio_break_recalc(_d)


_register_ratio_breaks()
for _comp, (_fn, _) in formulas.BENEISH.items():
    RECALCULATORS[f"J1-06.{_comp}.v1"] = _fn


def _same(a: float | None, b: float | None) -> bool:
    if a is None or b is None:
        return a is b
    return math.isclose(a, b, rel_tol=1e-9, abs_tol=1e-9)


def validate_text_observation(
    session: Session, obs: Observation, company_id: int, basis: str
) -> list[tuple[str, str]]:
    """Text flags: re-read each cited page from the database and re-confirm the quote there,
    independently of the extraction step (Developer Review 5.2 levels 1-7)."""
    from crest_forensic.checks.text import CHECK_SECTION

    failures: list[tuple[str, str]] = []
    if not obs.evidence:
        failures.append(("citation", "text observation carries no evidence"))
    for ev in obs.evidence:
        where = f"{ev.get('role')} (page {ev.get('page')})"
        finding = session.get(TextFinding, ev.get("finding_id"))
        version = session.get(DocumentVersion, ev.get("document_version_id"))
        if finding is None or version is None:
            failures.append(("citation", f"{where}: cited finding or document does not exist"))
            continue
        document = session.get(Document, version.document_id)
        if document.company_id != company_id or finding.company_id != company_id:
            failures.append(("citation", f"{where}: belongs to a different company"))
        if finding.document_version_id != version.id:
            failures.append(("citation", f"{where}: finding does not belong to the cited document version"))
        if finding.validation_status != "PASSED":
            failures.append(("citation", f"{where}: finding did not pass validation"))
        if finding.check_id != obs.check_id:
            failures.append(("citation", f"{where}: finding is for {finding.check_id}, not {obs.check_id}"))
        if finding.basis != basis:
            failures.append(("citation", f"{where}: basis mismatch (run={basis}, finding={finding.basis})"))
        if not (document.fiscal_year == finding.financial_year == ev.get("fy")):
            failures.append(("citation", f"{where}: financial year mismatch"))
        if finding.quote != ev.get("quote") or finding.page_number != ev.get("page"):
            failures.append(("citation", f"{where}: evidence differs from the saved finding"))
        page = session.execute(select(TextExtract).where(
            TextExtract.document_version_id == version.id, TextExtract.page_number == ev.get("page"))).scalars().first()
        if page is None:
            failures.append(("citation", f"{where}: cited page does not exist in the document"))
        elif not quote_in_page(ev.get("quote", ""), page.text):
            failures.append(("citation", f"{where}: quote not found verbatim on the cited page"))
        span = (version.sections or {}).get(CHECK_SECTION[obs.check_id].format(basis=basis))
        if not span or not (span["first"] <= (ev.get("page") or 0) <= span["last"]):
            failures.append(("citation", f"{where}: page is outside the {CHECK_SECTION[obs.check_id].format(basis=basis)} section"))

    # Generated wording only: a verbatim quote from the report is evidence and may use any words.
    banned = banned_terms_in(obs.what_observed, obs.technique)
    if banned:
        failures.append(("banned_language", f"contains banned wording: {', '.join(banned)}"))
    return failures


def validate_digit_observation(
    session: Session, obs: Observation, company_id: int, basis: str
) -> list[tuple[str, str]]:
    """Digit-pattern flags: re-read the cited document from the database, recount the leading digits
    independently of the check, and require the same counts and the same score."""
    from crest_forensic.documents.digits import count_digits

    failures: list[tuple[str, str]] = []
    if len(obs.evidence) != 1:
        return [("citation", "digit observation must cite exactly one document")]
    ev = obs.evidence[0]
    version = session.get(DocumentVersion, ev.get("document_version_id"))
    if version is None:
        return [("citation", "cited document does not exist")]
    document = session.get(Document, version.document_id)
    if document.company_id != company_id:
        failures.append(("citation", "cited document belongs to a different company"))
    if document.fiscal_year != obs.fy or ev.get("fy") != obs.fy:
        failures.append(("citation", "financial year mismatch"))
    if version.file_sha256 != ev.get("document_sha256"):
        failures.append(("citation", "document fingerprint does not match the saved document"))
    if not failures:
        recount = count_digits(session, version, basis)
        if recount["counts"] != ev.get("counts") or recount["n"] != ev.get("n"):
            failures.append(("recalculation", f"digit counts {ev.get('counts')} do not match the recount {recount['counts']}"))
        expected = formulas.benford_mad(recount["counts"])
        if not _same(expected, obs.metric_value):
            failures.append(("recalculation", f"score {obs.metric_value} does not match recomputed {expected}"))
    banned = banned_terms_in(obs.what_observed, obs.technique)
    if banned:
        failures.append(("banned_language", f"contains banned wording: {', '.join(banned)}"))
    return failures


def validate_filing_observation(
    session: Session, obs: Observation, company_id: int, basis: str
) -> list[tuple[str, str]]:
    """J1-13: re-read the cited saved filing row and recompute the days after the due date."""
    import datetime as dt

    from crest_forensic.checks.filing_dates import days_late

    f, failures = obs.figures, []
    snap = session.get(Snapshot, f.get("snapshot_id"))
    if snap is None or snap.company_id != company_id:
        return [("citation", "cited filing snapshot does not exist or belongs to another company")]
    row = next((r for r in snap.raw_payload.get("rows", [])
                if r["period_end"] == f["period_end"] and r["basis"] == basis and r["received_at"] == f["received_at"]), None)
    if row is None:
        failures.append(("citation", f"no {basis} filing for {f['period_end']} received {f['received_at']} in the cited snapshot"))
    else:
        expected = days_late(dt.date.fromisoformat(f["period_end"]), row["received_at"], f["due_days"])
        if expected != obs.metric_value or expected != f["days_after_due"]:
            failures.append(("recalculation", f"days after due date {obs.metric_value} does not match recomputed {expected}"))
    banned = banned_terms_in(obs.what_observed, obs.technique)
    if banned:
        failures.append(("banned_language", f"contains banned wording: {', '.join(banned)}"))
    return failures


def validate_shareholding_observation(
    session: Session, obs: Observation, company_id: int, basis: str
) -> list[tuple[str, str]]:
    """J2-01: re-read the two cited shareholding rows and recompute the step in percentage points."""
    from crest_forensic.checks.shareholding import step_points
    from crest_forensic.db.models import Shareholding

    f, failures = obs.figures, []
    rows = [session.get(Shareholding, i) for i in f.get("shareholding_ids", [])]
    if obs.check_id == "J2-04":
        if len(rows) != 1 or rows[0] is None or rows[0].company_id != company_id:
            return [("citation", "cited shareholding row does not exist or belongs to another company")]
        row = rows[0]
        if row.quarter != f["quarter"]:
            failures.append(("citation", f"cited row is {row.quarter}, not {f['quarter']}"))
        if row.pledged_pct is None or not _same(row.pledged_pct, obs.metric_value) or not _same(row.pledged_pct, f["pledged_pct"]):
            failures.append(("recalculation", f"pledged share {obs.metric_value} does not match the saved {row.pledged_pct}"))
        banned = banned_terms_in(obs.what_observed, obs.technique)
        if banned:
            failures.append(("banned_language", f"contains banned wording: {', '.join(banned)}"))
        return failures
    if len(rows) != 2 or any(r is None or r.company_id != company_id for r in rows):
        return [("citation", "cited shareholding rows do not exist or belong to another company")]
    cur, prev = rows
    if (cur.quarter, prev.quarter) != (f["quarter"], f["prior_quarter"]):
        failures.append(("citation", f"cited rows are {cur.quarter} and {prev.quarter}, not {f['quarter']} and {f['prior_quarter']}"))
    if cur.promoter_pct is None or prev.promoter_pct is None:
        failures.append(("citation", "a cited row has no promoter holding"))
    else:
        if not (_same(cur.promoter_pct, f["promoter_pct"]) and _same(prev.promoter_pct, f["prior_promoter_pct"])):
            failures.append(("citation", "figures do not match the saved shareholding rows"))
        expected = step_points(cur.promoter_pct, prev.promoter_pct)
        if not _same(expected, obs.metric_value):
            failures.append(("recalculation", f"step {obs.metric_value} does not match recomputed {expected}"))
    banned = banned_terms_in(obs.what_observed, obs.technique)
    if banned:
        failures.append(("banned_language", f"contains banned wording: {', '.join(banned)}"))
    return failures


def validate_market_observation(
    session: Session, obs: Observation, company_id: int, basis: str
) -> list[tuple[str, str]]:
    """J2-02: re-read the two saved price snapshots and the saved results time, recompute the z-score."""
    from crest_forensic.checks.price_volume import load_series

    f, failures = obs.figures, []
    stock_snap, index_snap = session.get(Snapshot, f.get("stock_snapshot_id")), session.get(Snapshot, f.get("index_snapshot_id"))
    res_snap = session.get(Snapshot, f.get("results_snapshot_id"))
    if any(s is None or s.company_id != company_id for s in (stock_snap, index_snap, res_snap)):
        return [("citation", "cited price or results snapshot does not exist or belongs to another company")]
    if not any(r["period_end"] == f["period_end"] and r["received_at"] == f["received_at"] for r in res_snap.raw_payload.get("rows", [])):
        failures.append(("citation", f"no results filing for {f['period_end']} received {f['received_at']} in the cited snapshot"))
    from crest_forensic.checks.filing_dates import first_filings
    from crest_forensic.checks.price_volume import all_events, population_z

    events = all_events(load_series(stock_snap), load_series(index_snap), first_filings(session, company_id, "consolidated"),
                        f["estimation_days"])
    key = obs.formula_id.removeprefix("market:J2-02.").removesuffix(".v1")
    pop = population_z(events, f["period_end"], key) if f["period_end"] in events else None
    if pop is None:
        failures.append(("recalculation", "the population z-score cannot be recomputed from the saved prices and results times"))
    else:
        if events[f["period_end"]]["reaction_day"] != f["reaction_day"]:
            failures.append(("citation", f"reaction day {f['reaction_day']} does not match {events[f['period_end']]['reaction_day']}"))
        if not _same(round(pop["z"], 6), obs.metric_value):
            failures.append(("recalculation", f"z-score {obs.metric_value} does not match recomputed {round(pop['z'], 6)}"))
    banned = banned_terms_in(obs.what_observed, obs.technique)
    if banned:
        failures.append(("banned_language", f"contains banned wording: {', '.join(banned)}"))
    return failures


def validate_fee_observation(
    session: Session, obs: Observation, company_id: int, basis: str
) -> list[tuple[str, str]]:
    """J2-03: re-read the two cited fee snapshots and recompute the year-on-year change."""
    from crest_forensic.checks.auditor_fees import amount, change_pct, reread_amounts

    f, failures = obs.figures, []
    snaps = [session.get(Snapshot, i) for i in f.get("snapshot_ids", [])]
    if len(snaps) != 2 or any(s is None or s.company_id != company_id for s in snaps):
        return [("citation", "cited auditor fee snapshots do not exist or belong to another company")]
    got = reread_amounts(session, f, obs.fy, f["prior_fy"])
    if got is None:
        return [("citation", "the cited snapshots do not hold the fee note for the years named")]
    key = obs.formula_id.removeprefix("fees:J2-03.").removesuffix(".v1")
    cur, old = amount(got[0], key), amount(got[1], key)
    if (cur, old) != (f["amount_cr"], f["prior_amount_cr"]):
        failures.append(("citation", f"figures {f['amount_cr']} and {f['prior_amount_cr']} do not match the saved {cur} and {old}"))
    expected = change_pct(cur, old)
    if expected is None or not _same(expected, obs.metric_value):
        failures.append(("recalculation", f"change {obs.metric_value} does not match recomputed {expected}"))
    banned = banned_terms_in(obs.what_observed, obs.technique)
    if banned:
        failures.append(("banned_language", f"contains banned wording: {', '.join(banned)}"))
    return failures


def validate_relparty_observation(
    session: Session, obs: Observation, company_id: int, basis: str
) -> list[tuple[str, str]]:
    """J2-06: the related-party amount comes from the cited snapshot, the denominator from its saved line item; recompute the share."""
    from crest_forensic.checks.related_party import MEASURES, share_pct

    f, failures = obs.figures, []
    snap = session.get(Snapshot, f.get("snapshot_id"))
    if snap is None or snap.company_id != company_id or snap.raw_payload.get("basis") != basis:
        return [("citation", "cited related-party snapshot does not exist, belongs to another company or is for another basis")]
    key = obs.formula_id.removeprefix("relparty:J2-06.").removesuffix(".v1")
    field = MEASURES[key][0]
    amount = ((snap.raw_payload.get("years") or {}).get(obs.fy) or {}).get(field)
    if amount is None or amount != f["related_party_cr"]:
        failures.append(("citation", f"amount {f['related_party_cr']} does not match the saved {amount}"))
    if len(obs.inputs) != 1:
        return failures + [("citation", "the denominator is not cited")]
    inp = obs.inputs[0]
    li = session.get(LineItem, inp.line_item_id)
    if li is None or li.company_id != company_id or li.basis != basis or li.financial_year != obs.fy or li.normalized_value is None \
            or not _same(li.normalized_value, inp.value):
        failures.append(("citation", f"denominator {inp.standard_field} {inp.fy} does not match its saved row"))
    elif amount is not None:
        expected = share_pct(amount, li.normalized_value)
        if expected is None or not _same(expected, obs.metric_value):
            failures.append(("recalculation", f"share {obs.metric_value} does not match recomputed {expected}"))
    banned = banned_terms_in(obs.what_observed, obs.technique)
    if banned:
        failures.append(("banned_language", f"contains banned wording: {', '.join(banned)}"))
    return failures


def validate_peer_observation(
    session: Session, obs: Observation, company_id: int, basis: str
) -> list[tuple[str, str]]:
    """J2-07: re-read the company's tax and profit rows and every cited peer snapshot, recompute the gap to the peer median."""
    from crest_forensic.checks.peer_tax import MIN_PEERS, gap_points
    from crest_forensic.db.models import PeerLink

    f, failures = obs.figures, []
    if len(obs.inputs) != 2:
        return [("citation", "the company's tax expense and profit before tax are not both cited")]
    vals = {}
    for inp in obs.inputs:
        li = session.get(LineItem, inp.line_item_id)
        if li is None or li.company_id != company_id or li.basis != basis or li.financial_year != obs.fy or li.normalized_value is None \
                or not _same(li.normalized_value, inp.value):
            failures.append(("citation", f"{inp.standard_field} {inp.fy} does not match its saved row"))
        else:
            vals[inp.standard_field] = li.normalized_value
    rates = []
    for p in f.get("peers", []):
        snap = session.get(Snapshot, p["snapshot_id"])
        linked = session.query(PeerLink).filter_by(company_id=company_id, peer_company_id=p["company_id"]).first()
        y = ((snap.raw_payload.get("years") or {}).get(obs.fy) if snap is not None and snap.company_id == p["company_id"] else None) or {}
        if linked is None or not y.get("pretax_income") or y["pretax_income"] <= 0 or y.get("tax") is None:
            failures.append(("citation", f"peer {p.get('name')} is not in the peer set or its snapshot does not carry {obs.fy}"))
            continue
        rate = y["tax"] / y["pretax_income"]
        if not _same(rate, p["rate"]):
            failures.append(("citation", f"peer {p.get('name')} rate {p['rate']} does not match the saved {rate}"))
        rates.append(rate)
    if len(rates) < MIN_PEERS:
        failures.append(("citation", f"fewer than {MIN_PEERS} valid peers are cited"))
    elif not failures and vals.get("profit_before_tax"):
        expected = gap_points(vals["tax_expense"] / vals["profit_before_tax"], rates)
        if not _same(expected, obs.metric_value):
            failures.append(("recalculation", f"gap {obs.metric_value} does not match recomputed {expected}"))
    banned = banned_terms_in(obs.what_observed, obs.technique)
    if banned:
        failures.append(("banned_language", f"contains banned wording: {', '.join(banned)}"))
    return failures


def validate_observation(
    session: Session, obs: Observation, company_id: int, basis: str
) -> list[tuple[str, str]]:
    """Returns [(guardrail, detail)]. Empty list = the flag may be created."""
    if obs.formula_id.startswith("peers:"):
        return validate_peer_observation(session, obs, company_id, basis)
    if obs.formula_id.startswith("relparty:"):
        return validate_relparty_observation(session, obs, company_id, basis)
    if obs.formula_id.startswith("fees:"):
        return validate_fee_observation(session, obs, company_id, basis)
    if obs.formula_id.startswith("market:"):
        return validate_market_observation(session, obs, company_id, basis)
    if obs.formula_id.startswith("shareholding:"):
        return validate_shareholding_observation(session, obs, company_id, basis)
    if obs.formula_id.startswith("filing:"):
        return validate_filing_observation(session, obs, company_id, basis)
    if obs.formula_id.startswith("text:"):
        return validate_text_observation(session, obs, company_id, basis)
    if obs.formula_id.startswith("digits:"):
        return validate_digit_observation(session, obs, company_id, basis)
    failures: list[tuple[str, str]] = []
    reread: dict[str, float] = {}

    for inp in obs.inputs:
        li = session.get(LineItem, inp.line_item_id)
        snap = session.get(Snapshot, inp.snapshot_id)
        where = f"{inp.name} ({inp.standard_field} {inp.fy})"
        if li is None or snap is None:
            failures.append(("citation", f"{where}: cited row does not exist"))
            continue
        if li.company_id != company_id or snap.company_id != company_id:
            failures.append(("citation", f"{where}: cited row belongs to a different company"))
        if li.basis != basis or inp.basis != basis:
            failures.append(("citation", f"{where}: basis mismatch (run={basis}, row={li.basis})"))
        if li.financial_year != inp.fy or li.standard_field != inp.standard_field:
            failures.append(("citation", f"{where}: cited row is for {li.standard_field} {li.financial_year}"))
        if li.snapshot_id != inp.snapshot_id:
            failures.append(("citation", f"{where}: line item does not belong to the cited snapshot"))
        if li.normalized_value is None or not _same(li.normalized_value, inp.value):
            failures.append(("citation", f"{where}: figure {inp.value} does not match saved value {li.normalized_value}"))
        reread[inp.name] = li.normalized_value

    recalc = RECALCULATORS.get(obs.formula_id)
    if recalc is None:
        failures.append(("recalculation", f"no recalculation registered for {obs.formula_id}"))
    elif not failures:
        try:
            expected = recalc(reread)
        except KeyError as exc:
            failures.append(("recalculation", f"missing input {exc} for {obs.formula_id}"))
        else:
            if not _same(expected, obs.metric_value):
                failures.append(("recalculation",
                                 f"metric {obs.metric_value} does not match recomputed {expected}"))

    banned = banned_terms_in(obs.what_observed, obs.technique, json.dumps(obs.figures, default=str))
    if banned:
        failures.append(("banned_language", f"contains banned wording: {', '.join(banned)}"))

    return failures
