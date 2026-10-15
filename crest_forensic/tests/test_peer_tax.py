import datetime as dt

from crest_forensic.checks.base import InputStore
from crest_forensic.checks.peer_tax import gap_points, population, run_j2_07
from crest_forensic.connectors.base import RawSourceResponse
from crest_forensic.db.models import Company, PeerLink
from crest_forensic.guardrails.validate import validate_observation
from crest_forensic.ingestion.fetch_and_snapshot import save_snapshot
from crest_forensic.ingestion.peers import ENDPOINT, PROVIDER
from crest_forensic.review.ownership import build_ownership
from crest_forensic.screen import load_check_config
from crest_forensic.tests.helpers import make_snapshot, seed

CFG = load_check_config()["checks"]["J2-07"]


def _peer(session, subject, name, pretax, tax, fy="FY2025"):
    peer = Company(name=name, nse_symbol=name[:6].upper(), supported_status="PEER")
    session.add(peer)
    session.flush()
    save_snapshot(session, peer.company_id, RawSourceResponse(
        provider=PROVIDER, endpoint=ENDPOINT, request_params={"ticker": name}, status_code=200, fetched_at=dt.datetime.now(dt.timezone.utc),
        payload={"years": {fy: {"pretax_income": pretax, "tax": tax, "net_income": pretax - tax, "revenue": pretax * 5, "receivables": pretax}}}))
    session.add(PeerLink(company_id=subject.company_id, peer_company_id=peer.company_id, approved_by="lead"))
    session.flush()
    return peer


def _subject(session, company, pbt=1000.0, tax=250.0):
    snap = make_snapshot(session, company)
    seed(session, company, snap, "profit_before_tax", {"FY2025": pbt}, basis="consolidated")
    seed(session, company, snap, "tax_expense", {"FY2025": tax}, basis="consolidated")
    seed(session, company, snap, "profit_after_tax", {"FY2025": pbt - tax}, basis="consolidated")
    seed(session, company, snap, "revenue_from_operations", {"FY2025": pbt * 5}, basis="consolidated")
    seed(session, company, snap, "trade_receivables", {"FY2025": pbt}, basis="consolidated")


def test_gap_population_and_limits_are_proposals():
    assert gap_points(0.30, [0.20, 0.22, 0.24]) == 8.0
    assert population([0.2, 0.3, 0.4])["median"] == 0.3
    assert {t["source"] for t in CFG["thresholds"].values()} == {"proposal"}


def test_a_gap_above_the_limit_is_flagged_with_population_statistics_and_passes_the_guardrail(session, company):
    _subject(session, company, tax=100.0)                                      # 10% against peers at about 25%
    for n, t in (("PeerA", 250), ("PeerB", 240), ("PeerC", 260), ("PeerD", 255)):
        _peer(session, company, n, 1000.0, float(t))
    (o,) = run_j2_07(InputStore(session, company.company_id, "consolidated"), ["FY2025"], CFG).observations
    assert o.severity == "high" and o.metric_value < -10 and o.figures["n_peers"] == 4 and len(o.figures["peers"]) == 4
    assert o.figures["peer_min_pct"] <= o.figures["peer_median_pct"] <= o.figures["peer_max_pct"]
    assert validate_observation(session, o, company.company_id, "consolidated") == []
    object.__setattr__(o, "metric_value", 0.0)
    assert any(g == "recalculation" for g, _ in validate_observation(session, o, company.company_id, "consolidated"))


def test_in_line_rate_is_not_flagged_fewer_than_three_peers_is_refused_and_standalone_is_not_applicable(session, company):
    _subject(session, company, tax=250.0)
    _peer(session, company, "PeerA", 1000.0, 250.0)
    _peer(session, company, "PeerB", 1000.0, 240.0)
    res = run_j2_07(InputStore(session, company.company_id, "consolidated"), ["FY2025"], CFG)
    assert not res.observations and "3 are needed" in res.skipped[0].detail            # only 2 peers
    _peer(session, company, "PeerC", 1000.0, 260.0)
    (o,) = run_j2_07(InputStore(session, company.company_id, "consolidated"), ["FY2025"], CFG).observations
    assert o.severity is None and abs(o.metric_value) < 5
    assert run_j2_07(InputStore(session, company.company_id, "standalone"), ["FY2025"], CFG).status == "NOT_APPLICABLE"


def test_peer_rows_in_the_matrix_label_only_the_tax_rate(session, company):
    _subject(session, company, tax=100.0)
    for n, t in (("PeerA", 250), ("PeerB", 240), ("PeerC", 260)):
        _peer(session, company, n, 1000.0, float(t))
    rows = {r["key"]: r for r in build_ownership(session, company.company_id, ["FY2025"], {"J2-07": {"thresholds": {"medium": {"value": 5.0}}}})}
    assert rows["peer_tax"]["cells"]["FY2025"]["badge"] == "look"
    assert rows["peer_margin"]["cells"]["FY2025"]["badge"] is None and rows["peer_recv_days"]["cells"]["FY2025"]["badge"] is None
