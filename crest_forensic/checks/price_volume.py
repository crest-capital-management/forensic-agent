"""J2-02 price and volume around results: how unusual was the market's reaction to each quarterly result?

Method (plain, no model, every number reproducible from the saved snapshots):
- Event: each quarterly result, taken from the exchange received time saved by ingestion/exchange_files.py.
  Reaction day = the first trading day on or after the broadcast date, or the NEXT trading day when the result
  reached the exchange after the 15:30 India market close.
- Abnormal return of a day = the stock's daily return minus the Nifty 50's return the same day (market-adjusted).
- Step 1, against ordinary days: z-scores of the reaction day against a baseline of ESTIMATION_DAYS trading days that
  ends GAP_DAYS trading days before it (sample standard deviation): abnormal return, log volume, and the run-up
  (abnormal returns summed over the 5 trading days before, scaled by sqrt(5)). A results day is expected to be busier
  than an ordinary day, so these alone are NOT used for flags; they are shown as context.
- Step 2, against the company's OTHER results days (the population): the size of each reaction (|return z|, volume z,
  |run-up z|) is compared with the same figure at all the other saved results events (leave one out). A flag needs at
  least MIN_EVENTS other events and a population z-score above the limit (unusually LARGER than the other results days).
- Prices are Yahoo Finance (yfinance), adjusted for splits and bonuses, saved as snapshots. Unofficial and provisional.
Thresholds are the lead's (proposals until confirmed); the spec states none. A flag is a lead for a person, not a conclusion.
Reported on the consolidated run only (the market does not depend on the statement basis).
"""
from __future__ import annotations

import datetime as dt
import math
import statistics

from sqlalchemy.orm import Session

from crest_forensic.checks.base import (
    STATUS_COMPLETED, STATUS_NOT_ENOUGH_DATA, CheckResult, InputStore, Observation, Skip, severity_for,
    thresholds_applied,
)
from crest_forensic.checks.filing_dates import first_filings, fy_quarter_ends
from crest_forensic.db.models import Snapshot
from crest_forensic.ingestion.exchange_files import IST, quarter_label

FORMULA_PREFIX = "market:J2-02."
GAP_DAYS, RUNUP_DAYS, MIN_OBS, MIN_EVENTS = 10, 5, 60, 8
MARKET_CLOSE = dt.time(15, 30)
STATUS_NOT_APPLICABLE = "NOT_APPLICABLE"
METRICS = {
    "return": ("size of the price reaction against other results days (z-score)",
               "Size of the abnormal return on the reaction day, compared with the other results days"),
    "volume": ("volume on the reaction day against other results days (z-score)",
               "Trading volume on the reaction day, compared with the other results days"),
    "runup": ("size of the run-up before results against other results days (z-score)",
              "Abnormal return over the 5 trading days before the reaction day, compared with the other results days"),
}


def load_series(snapshot: Snapshot) -> dict[str, tuple[float, float]]:
    return {r["date"]: (r["close"], r["volume"]) for r in snapshot.raw_payload["data"]}


def latest_price_snapshots(session: Session, company_id: int) -> tuple[Snapshot | None, Snapshot | None]:
    """(stock, index): the newest saved price snapshot for each ticker."""
    stock = index = None
    q = session.query(Snapshot).filter_by(company_id=company_id, source_provider="yfinance", source_endpoint="yfinance:prices")
    for snap in q.order_by(Snapshot.snapshot_id.desc()):
        if not snap.raw_payload.get("data"):
            continue
        is_index = str(snap.request_params.get("ticker", "")).startswith("^")
        if is_index and index is None:
            index = snap
        elif not is_index and stock is None:
            stock = snap
    return stock, index


def reaction_day(received_at: str, trading_days: list[str]) -> str | None:
    """First trading day on/after the India date of the broadcast; the next one if it came after the close."""
    t = dt.datetime.fromisoformat(received_at).astimezone(IST)
    day = t.date() + (dt.timedelta(days=1) if t.time() >= MARKET_CLOSE else dt.timedelta(0))
    return next((d for d in trading_days if d >= day.isoformat()), None)


def event_stats(stock: dict, index: dict, reaction: str, estimation_days: int) -> dict | None:
    """All three z-scores for one event, or None when there are too few baseline days."""
    days = sorted(set(stock) & set(index))
    if reaction not in days:
        return None
    pos = days.index(reaction)
    ar: dict[str, float] = {}
    for prev, cur in zip(days, days[1:]):
        ar[cur] = (stock[cur][0] / stock[prev][0] - 1) - (index[cur][0] / index[prev][0] - 1)
    lo, hi = pos - GAP_DAYS - estimation_days, pos - GAP_DAYS      # baseline = days[lo:hi]
    if lo < 1 or pos < RUNUP_DAYS + 1:
        return None
    base = days[lo:hi]
    base_ar = [ar[d] for d in base]
    base_lv = [math.log(stock[d][1]) for d in base if stock[d][1] > 0]
    if len(base_ar) < MIN_OBS or len(base_lv) < MIN_OBS or stock[reaction][1] <= 0:
        return None
    m_ar, s_ar = statistics.fmean(base_ar), statistics.stdev(base_ar)
    m_lv, s_lv = statistics.fmean(base_lv), statistics.stdev(base_lv)
    if s_ar == 0 or s_lv == 0:
        return None
    runup = sum(ar[d] for d in days[pos - RUNUP_DAYS:pos])
    return {
        "reaction_day": reaction, "baseline_from": base[0], "baseline_to": base[-1], "baseline_days": len(base_ar),
        "ar": ar[reaction], "ar_mean": m_ar, "ar_std": s_ar,
        "stock_return": stock[reaction][0] / stock[days[pos - 1]][0] - 1, "index_return": index[reaction][0] / index[days[pos - 1]][0] - 1,
        "volume": stock[reaction][1], "logvol_mean": m_lv, "logvol_std": s_lv,
        "runup": runup, "runup_from": days[pos - RUNUP_DAYS],
        "z": {"return": (ar[reaction] - m_ar) / s_ar,
              "volume": (math.log(stock[reaction][1]) - m_lv) / s_lv,
              "runup": (runup - RUNUP_DAYS * m_ar) / (s_ar * math.sqrt(RUNUP_DAYS))},
    }


def event_value(stats: dict, key: str) -> float:
    """The size of a reaction in baseline z units: |return z|, volume z, |run-up z|."""
    z = stats["z"][key]
    return z if key == "volume" else abs(z)


def all_events(stock: dict, index: dict, filings: dict[str, dict], estimation_days: int) -> dict[str, dict]:
    """{period_end: stats + reaction day + filing}, for every saved results event with enough price history."""
    trading_days = sorted(set(stock) & set(index))
    out = {}
    for end, filing in filings.items():
        rday = reaction_day(filing["received_at"], trading_days)
        stats = event_stats(stock, index, rday, estimation_days) if rday else None
        if stats is not None:
            out[end] = {**stats, "filing": filing}
    return out


def population_z(events: dict[str, dict], end: str, key: str) -> dict | None:
    """The event's reaction size against all the OTHER events; None with fewer than MIN_EVENTS others."""
    others = [event_value(e, key) for k, e in events.items() if k != end]
    if len(others) < MIN_EVENTS:
        return None
    mean, std = statistics.fmean(others), statistics.stdev(others)
    if std == 0:
        return None
    x = event_value(events[end], key)
    return {"z": (x - mean) / std, "value": x, "mean": mean, "std": std, "n": len(others)}


def _estimation_days(cfg: dict) -> int | None:
    v = (cfg.get("estimation_window_days") or {}).get("value")
    return int(v) if v else None


def _what(key: str, label: str, f: dict, pop: dict) -> str:
    z = f["z"][key]
    if key == "return":
        part = (f"the stock moved {f['stock_return'] * 100:+.2f}% against {f['index_return'] * 100:+.2f}% for the Nifty 50, an abnormal return of "
                f"{f['ar'] * 100:+.2f} points (z {z:+.2f} against ordinary days)")
    elif key == "volume":
        part = f"{f['volume']:,.0f} shares traded (z {z:+.2f} against ordinary days)"
    else:
        part = (f"the abnormal returns of the 5 trading days before it summed to {f['runup'] * 100:+.2f} points "
                f"(z {z:+.2f} against ordinary days)")
    return (f"For the {label} results, on the reaction day {f['reaction_day']} {part}. Compared with the other {pop['n']} saved results days "
            f"(average {pop['mean']:.2f}, standard deviation {pop['std']:.2f} in these units), this reaction scores {pop['value']:.2f}, "
            f"a population z-score of {pop['z']:+.2f}. Results reached the exchange at {f['filing']['received_at'][:16].replace('T', ' ')} India time.")


def run_j2_02(store: InputStore, years: list[str], cfg: dict) -> CheckResult:
    if store.basis != "consolidated":
        res = CheckResult("J2-02", cfg.get("check_version", 1), STATUS_NOT_APPLICABLE)
        res.notes.append("Market reaction does not depend on the statement basis, so this check is reported once, on the consolidated run.")
        return res
    session, company_id = store.session, store.company_id
    window = _estimation_days(cfg)
    res = CheckResult("J2-02", cfg.get("check_version", 1), STATUS_NOT_ENOUGH_DATA)
    if window is None:
        res.notes.append("The saved limits have no baseline window for J2-02 yet; add it on the Limits page (proposed: 100 trading days).")
        res.status = "NEEDS_DEFINITION"
        return res
    stock_snap, index_snap = latest_price_snapshots(session, company_id)
    if stock_snap is None or index_snap is None:
        res.skipped.append(Skip("*", "NOT_ENOUGH_DATA", "no saved daily prices for the company and the Nifty 50 (run ingest-prices)"))
        return res
    events = all_events(load_series(stock_snap), load_series(index_snap), first_filings(session, company_id, "consolidated"), window)
    obs = []
    for fy in years:
        found = 0
        for end in fy_quarter_ends(fy):
            f = events.get(end.isoformat())
            if f is None:
                continue
            label = quarter_label(end)
            for key, (metric_name, technique) in METRICS.items():
                pop = population_z(events, end.isoformat(), key)
                if pop is None:
                    continue
                found += 1
                obs.append(Observation(
                    check_id="J2-02", fy=fy, metric_name=metric_name, metric_value=round(pop["z"], 6),
                    severity=severity_for(pop["z"], cfg), severity_rule_id=cfg["rule_id"], formula_id=f"{FORMULA_PREFIX}{key}.v1",
                    technique=technique, what_observed=_what(key, label, f, pop), inputs=[],
                    thresholds_applied=thresholds_applied(cfg),
                    materiality={"basis": "market reaction, not an amount", "label": "unassessed"},
                    figures={"period_end": end.isoformat(), "quarter": label, "metric": key, "received_at": f["filing"]["received_at"],
                             "estimation_days": window, "gap_days": GAP_DAYS,
                             **{k: v for k, v in f.items() if k not in ("z", "filing")},
                             "baseline_z": f["z"][key], "population": pop, "population_events": len(events),
                             "results_snapshot_id": f["filing"]["snapshot_id"],
                             "stock_snapshot_id": stock_snap.snapshot_id, "index_snapshot_id": index_snap.snapshot_id,
                             "stock_ticker": stock_snap.request_params.get("ticker"), "price_source": "yfinance (unofficial, adjusted)"},
                ))
        if not found:
            res.skipped.append(Skip(fy, "NOT_ENOUGH_DATA", f"no results event in {fy} with enough saved price history and enough other results days to compare with"))
    res.observations = obs
    res.status = STATUS_COMPLETED if obs else STATUS_NOT_ENOUGH_DATA
    return res
