from crest_forensic.db.models import Company, Shareholding, Snapshot
from crest_forensic.documents.auditor_fees import ENDPOINT, PROVIDER
from crest_forensic.review.ownership import build_ownership

CFG = {"J2-01": {"thresholds": {"medium": {"value": 2.0, "source": "spec"}}}, "J2-03": {"thresholds": {"medium": {"value": 30.0, "source": "spec"}}}}


def _co(session):
    co = Company(name="T")
    session.add(co)
    session.flush()
    snap = Snapshot(company_id=co.company_id, source_provider=PROVIDER, source_endpoint=ENDPOINT, request_params={}, payload_hash="h",
                    raw_payload={"report_fy": "FY2026", "page": 307, "document_version_id": 1, "years": {
                        "FY2025": dict(audit_fee_cr=10, tax_matters_cr=1, other_services_cr=1, reimbursement_cr=0),
                        "FY2026": dict(audit_fee_cr=12, tax_matters_cr=1, other_services_cr=2, reimbursement_cr=0)}})
    session.add(snap)
    session.flush()
    return co, snap


def _sh(session, co, snap, q, pct, pledged=None, fii=None):
    session.add(Shareholding(company_id=co.company_id, snapshot_id=snap.snapshot_id, quarter=q, promoter_pct=pct,
                             pledged_pct=pledged, fii_pct=fii, dii_pct=None))


def test_rows_labels_and_gaps(session):
    co, snap = _co(session)
    for q, p in {"Q4FY2025": 72.0, "Q1FY2026": 72.0, "Q2FY2026": 69.0, "Q3FY2026": 69.0, "Q4FY2026": 69.0}.items():
        _sh(session, co, snap, q, p, pledged=0.0, fii=10.0)
    session.flush()
    rows = {r["key"]: r for r in build_ownership(session, co.company_id, ["FY2025", "FY2026", "FY2027"], CFG)}
    assert rows["promoter"]["cells"]["FY2026"]["badge"] == "look" and "-3.00" in rows["promoter"]["cells"]["FY2026"]["what"]
    assert rows["promoter"]["cells"]["FY2026"]["display"] == "69.00%"
    assert rows["promoter"]["cells"]["FY2027"]["skipped"] == "NOT_ENOUGH_DATA"
    assert rows["dii"]["cells"]["FY2026"]["display"] == "n/a"           # not in the saved data: say so, never guess
    assert rows["pledged"]["cells"]["FY2026"]["badge"] is None
    assert rows["audit_fee"]["cells"]["FY2026"]["value"] == 12 and "+20.0%" in rows["audit_fee"]["cells"]["FY2026"]["what"]
    assert rows["total_fees"]["cells"]["FY2026"]["value"] == 15 and rows["total_fees"]["cells"]["FY2027"]["display"] == "n/a"
    assert all(c["badge"] is None for k in ("pledged", "fii", "dii") for c in rows[k]["cells"].values())


def test_fee_rows_are_labelled_by_the_live_limit(session):
    co, snap = _co(session)
    rows = {r["key"]: r for r in build_ownership(session, co.company_id, ["FY2025", "FY2026"], CFG)}
    assert rows["audit_fee"]["cells"]["FY2026"]["badge"] == "normal"          # +20%, under 30%
    assert rows["audit_fee"]["cells"]["FY2025"]["badge"] is None              # no prior year to compare
    big = {"J2-03": {"thresholds": {"medium": {"value": 10.0, "source": "x"}}}}
    rows = {r["key"]: r for r in build_ownership(session, co.company_id, ["FY2026"], big)}
    assert rows["audit_fee"]["cells"]["FY2026"]["badge"] == "look"
