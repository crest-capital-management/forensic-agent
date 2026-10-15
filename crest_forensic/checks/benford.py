"""J1-17 digit pattern (Benford's Law) for each annual report, as a LOW-CONFIDENCE signal.

Benford's Law says the first digits of many naturally occurring amounts follow a known pattern. A deviation is a
weak lead at best: lots of ordinary figures (round amounts, fixed prices, rounding to a unit) do not follow it.
The measure is the mean absolute deviation (MAD) between observed and expected digit shares, read against the
bands in the config. With too few numbers the test is skipped rather than guessed.
"""
from __future__ import annotations

from sqlalchemy import select

from crest_forensic.checks import formulas
from crest_forensic.checks.base import CheckResult, InputStore, Observation, Skip, finish
from crest_forensic.db.models import Document, DocumentVersion
from crest_forensic.documents.digits import count_digits

BANDS = ("close", "acceptable", "marginal", "nonconforming")
BAND_WORDS = {
    "close": "close to the expected pattern",
    "acceptable": "within the usual range of the expected pattern",
    "marginal": "slightly outside the usual range of the expected pattern",
    "nonconforming": "outside the usual range of the expected pattern",
}


def band_for(mad: float, cfg: dict) -> str:
    b = cfg.get("mad_bands") or {}
    close, acc, marg = (b.get(k, {}).get("value") for k in ("close_below", "acceptable_below", "marginal_below"))
    if close is not None and mad < close:
        return "close"
    if acc is not None and mad < acc:
        return "acceptable"
    if marg is not None and mad < marg:
        return "marginal"
    return "nonconforming"


def run_j1_17(store: InputStore, years: list[str], cfg: dict) -> CheckResult:
    obs, skipped = [], []
    min_n = (cfg.get("min_numbers") or {}).get("value")
    sev_cfg = cfg.get("band_severity") or {}
    versions = {}
    for doc, ver in store.session.execute(
            select(Document, DocumentVersion).join(DocumentVersion, DocumentVersion.document_id == Document.id)
            .where(Document.company_id == store.company_id, Document.doc_type == "annual_report")
            .order_by(DocumentVersion.id)).all():
        versions[doc.fiscal_year] = (doc, ver)          # the newest version of each year's report wins

    for fy in years:
        if fy not in versions:
            skipped.append(Skip(fy, "NOT_ENOUGH_DATA", f"no annual report is saved for {fy}"))
            continue
        doc, ver = versions[fy]
        res = count_digits(store.session, ver, store.basis)
        if not res["sections"]:
            skipped.append(Skip(fy, "NOT_ENOUGH_DATA", f"the {store.basis} statements and notes were not found in the {fy} report"))
            continue
        if min_n is None or res["n"] < min_n:
            skipped.append(Skip(fy, "NOT_ENOUGH_DATA",
                                f"only {res['n']:,} numbers were found in the {fy} {store.basis} statements and notes; "
                                f"the test needs at least {min_n:,} to mean anything"))
            continue
        mad = formulas.benford_mad(res["counts"])
        band = band_for(mad, cfg)
        severity = (sev_cfg.get(band) or {}).get("value")
        n = res["n"]
        share = [round(c / n, 4) for c in res["counts"]]
        evidence = [{
            "role": "digit_test", "kind": "digit_test", "fy": fy, "document_version_id": ver.id,
            "document_sha256": ver.file_sha256, "file_name": ver.file_name,
            "sections": {k: list(v) for k, v in res["sections"].items()}, "counts": res["counts"], "n": n,
            "mad": mad, "page": min(f for f, _ in res["sections"].values()), "printed_page": None,
        }]
        obs.append(Observation(
            check_id="J1-17", fy=fy, metric_name="Benford first-digit MAD", metric_value=mad,
            severity=severity, severity_rule_id=cfg["rule_id"], formula_id=f"digits:{store.basis}",
            technique="Leading-digit pattern of the amounts in the statements and notes (low-confidence signal)",
            what_observed=(f"In the {fy} annual report ({store.basis}), the leading digits of {n:,} amounts in the "
                           f"statements and notes were {BAND_WORDS[band]} (average difference {mad:.4f}). "
                           "This is a weak signal: many ordinary figures do not follow the pattern."),
            inputs=[], thresholds_applied={"mad_bands": cfg.get("mad_bands"), "min_numbers": cfg.get("min_numbers")},
            materiality={"label": "not_assessed", "basis": "a pattern across many numbers, not one amount"},
            figures={"mad": round(mad, 5), "band": band, "numbers_counted": n, "digit_counts": res["counts"],
                     "digit_share": share, "expected_share": [round(p, 4) for p in formulas.BENFORD_EXPECTED]},
            evidence=evidence,
        ))
    return finish("J1-17", cfg, obs, skipped)
