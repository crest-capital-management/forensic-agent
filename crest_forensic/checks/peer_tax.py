"""J2-07 tax rate against peers (Job 2 result set 3: "tax rate vs. peers").

The company's effective tax rate (tax expense / profit before tax, from the audited statements) is compared with the same rate of each
peer in the forensic lead's peer set (ingestion/peers.py, Yahoo Finance snapshots, unofficial and provisional). The population statistics
(each peer's rate, the median, the range, the average and the standard deviation) are stored with every observation. The measure is the
gap to the peer median in percentage points; medium above 5 points and high above 10 are PROPOSALS for the lead (the spec gives none).
At least MIN_PEERS peers with data are needed. Reported on the consolidated run only: the peers' Yahoo figures are consolidated.
A flag is a lead for a person, not a conclusion: tax rates differ legitimately with the mix of countries and tax incentives.
"""
from __future__ import annotations

import statistics

from crest_forensic.checks.base import (
    STATUS_COMPLETED, STATUS_NOT_ENOUGH_DATA, CheckResult, InputStore, Missing, Observation, Skip, severity_for, thresholds_applied,
)
from crest_forensic.ingestion.peers import latest_peer_snapshot, peers_of

FORMULA_ID = "peers:J2-07.v1"
MIN_PEERS = 3
STATUS_NOT_APPLICABLE = "NOT_APPLICABLE"


def peer_rates(session, company_id: int, fy: str) -> list[dict]:
    """Each peer's effective tax rate (a fraction) for the year, from its newest saved snapshot; peers without a positive pre-tax profit are left out."""
    out = []
    for peer in peers_of(session, company_id):
        snap = latest_peer_snapshot(session, peer.company_id)
        y = (snap.raw_payload["years"].get(fy) if snap else None) or {}
        if y.get("pretax_income") and y["pretax_income"] > 0 and y.get("tax") is not None:
            out.append({"company_id": peer.company_id, "name": peer.name, "rate": y["tax"] / y["pretax_income"], "snapshot_id": snap.snapshot_id})
    return out


def population(rates: list[float]) -> dict:
    return {"n": len(rates), "median": statistics.median(rates), "min": min(rates), "max": max(rates), "mean": statistics.fmean(rates),
            "stdev": statistics.stdev(rates) if len(rates) > 1 else None}


def gap_points(own: float, rates: list[float]) -> float:
    return round((own - statistics.median(rates)) * 100, 6)


def run_j2_07(store: InputStore, years: list[str], cfg: dict) -> CheckResult:
    if store.basis != "consolidated":
        res = CheckResult("J2-07", cfg.get("check_version", 1), STATUS_NOT_APPLICABLE)
        res.notes.append("The peers' figures are consolidated, so this check is reported once, on the consolidated run.")
        return res
    session, cid = store.session, store.company_id
    obs, skipped = [], []
    for fy in years:
        tax, pbt = store.get("tax", "tax_expense", fy), store.get("pbt", "profit_before_tax", fy)
        if isinstance(tax, Missing) or isinstance(pbt, Missing):
            skipped.append(Skip(fy, "NOT_ENOUGH_DATA", "; ".join(m.text() for m in (tax, pbt) if isinstance(m, Missing))))
            continue
        if pbt.value <= 0:
            skipped.append(Skip(fy, "NOT_COMPUTABLE", "profit before tax is not above zero, so a tax rate is undefined"))
            continue
        peers = peer_rates(session, cid, fy)
        if len(peers) < MIN_PEERS:
            skipped.append(Skip(fy, "NOT_ENOUGH_DATA", f"only {len(peers)} peer(s) with data for {fy}; {MIN_PEERS} are needed"))
            continue
        own = tax.value / pbt.value
        rates = [p["rate"] for p in peers]
        pop = population(rates)
        gap = gap_points(own, rates)
        what = (f"In {fy}, the effective tax rate was {own * 100:.1f}% against a peer median of {pop['median'] * 100:.1f}% "
                f"(range {pop['min'] * 100:.1f}% to {pop['max'] * 100:.1f}% across {pop['n']} peers): a gap of {gap:+.1f} percentage points.")
        obs.append(Observation(
            check_id="J2-07", fy=fy, metric_name="effective tax rate minus the peer median (percentage points)", metric_value=gap,
            severity=severity_for(abs(gap), cfg), severity_rule_id=cfg["rule_id"], formula_id=FORMULA_ID,
            technique="Effective tax rate compared with the peer set", what_observed=what, inputs=[tax, pbt],
            thresholds_applied=thresholds_applied(cfg),
            materiality={"basis": "tax-rate gap, not an amount", "label": "unassessed"},
            figures={"own_rate_pct": round(own * 100, 4), "peer_median_pct": round(pop["median"] * 100, 4), "peer_min_pct": round(pop["min"] * 100, 4),
                     "peer_max_pct": round(pop["max"] * 100, 4), "peer_mean_pct": round(pop["mean"] * 100, 4),
                     "peer_stdev_pct": None if pop["stdev"] is None else round(pop["stdev"] * 100, 4), "peers": peers, "n_peers": pop["n"],
                     "gap_points": gap, "peer_source": "yfinance (unofficial)"},
        ))
    return CheckResult("J2-07", cfg.get("check_version", 1), STATUS_COMPLETED if obs else STATUS_NOT_ENOUGH_DATA, obs, skipped)
