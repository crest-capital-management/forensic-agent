import datetime as dt
import math
import random

from crest_forensic.checks.base import InputStore
from crest_forensic.checks.price_volume import (
    all_events, event_stats, population_z, reaction_day, run_j2_02,
)
from crest_forensic.connectors.base import RawSourceResponse
from crest_forensic.db.models import Company
from crest_forensic.guardrails.validate import validate_observation
from crest_forensic.ingestion.exchange_files import NSE_RESULTS
from crest_forensic.ingestion.fetch_and_snapshot import save_snapshot
from crest_forensic.screen import load_check_config

CFG = load_check_config()["checks"]["J2-02"]


def _days(n, start=dt.date(2025, 1, 1)):
    out, d = [], start
    while len(out) < n:
        if d.weekday() < 5:
            out.append(d.isoformat())
        d += dt.timedelta(days=1)
    return out


def _series(days, shocks=None, seed=1):
    """Random-walk stock and flat-ish index; shocks = {day_index: (extra stock return, volume multiple)}."""
    rnd, shocks = random.Random(seed), shocks or {}
    stock, index, ps, pi = {}, {}, 100.0, 1000.0
    for i, d in enumerate(days):
        extra, vol_x = shocks.get(i, (0.0, 1.0))
        ps *= 1 + rnd.gauss(0, 0.01) + extra
        pi *= 1 + rnd.gauss(0, 0.005)
        stock[d] = (ps, 1_000_000 * vol_x * math.exp(rnd.gauss(0, 0.1)))
        index[d] = (pi, 0)
    return stock, index


def test_reaction_day_waits_for_the_next_session_after_the_close():
    days = ["2026-07-09", "2026-07-10", "2026-07-13"]
    assert reaction_day("2026-07-09T18:36:12+05:30", days) == "2026-07-10"     # after 15:30: next day
    assert reaction_day("2026-07-09T11:00:00+05:30", days) == "2026-07-09"     # during the session: same day
    assert reaction_day("2026-07-10T18:00:00+05:30", days) == "2026-07-13"     # Friday evening: Monday


def test_a_big_move_scores_high_against_ordinary_days_and_short_history_is_refused():
    days = _days(200)
    stock, index = _series(days, {150: (0.08, 6.0)})
    st = event_stats(stock, index, days[150], 100)
    assert st["z"]["return"] > 5 and st["z"]["volume"] > 5 and st["baseline_days"] == 100
    assert event_stats(stock, index, days[20], 100) is None


def _setup(session, shocks, n_events=10):
    """n_events results events 12 trading days apart; every event is quiet except the ones in `shocks`."""
    days = _days(125 + 14 * n_events + 5)
    event_idx = [125 + 14 * k for k in range(n_events)]
    stock, index = _series(days, {event_idx[k]: v for k, v in shocks.items()})
    co = Company(name="T")
    session.add(co)
    session.flush()
    for ticker, series in (("T.NS", stock), ("^NSEI", index)):
        save_snapshot(session, co.company_id, RawSourceResponse(
            provider="yfinance", endpoint="yfinance:prices", request_params={"ticker": ticker}, status_code=200,
            fetched_at=dt.datetime.now(dt.timezone.utc),
            payload={"data": [{"date": d, "close": c, "volume": v} for d, (c, v) in series.items()]}))
    rows = []
    for k, i in enumerate(event_idx):
        end = dt.date(2025 + k // 4, [3, 6, 9, 12][k % 4], [31, 30, 30, 31][k % 4])
        prev_day = days[i - 1]    # results arrive in the evening of the day before the reaction day
        rows.append({"period_end": end.isoformat(), "basis": "consolidated", "received_at": f"{prev_day}T19:00:00+05:30", "xbrl_url": "x"})
    save_snapshot(session, co.company_id, RawSourceResponse(
        provider=NSE_RESULTS, endpoint="file:t.csv", request_params={}, status_code=200,
        fetched_at=dt.datetime.now(dt.timezone.utc), payload={"rows": rows}))
    session.flush()
    return co, rows


def test_population_z_flags_the_unusual_event_and_survives_the_guardrail(session):
    co, rows = _setup(session, {9: (0.12, 8.0)})
    years = [f"FY{y}" for y in range(2025, 2029)]
    res = run_j2_02(InputStore(session, co.company_id, "consolidated"), years, CFG)
    by = {(o.figures["period_end"], o.figures["metric"]): o for o in res.observations}
    last = rows[9]["period_end"]
    assert by[(last, "return")].severity == "high" and by[(last, "volume")].severity == "high"
    assert by[(rows[0]["period_end"], "return")].severity is None
    assert all(validate_observation(session, o, co.company_id, "consolidated") == [] for o in res.observations)
    tampered = by[(last, "return")]
    object.__setattr__(tampered, "metric_value", 0.5)
    assert any(g == "recalculation" for g, _ in validate_observation(session, tampered, co.company_id, "consolidated"))


def test_too_few_other_results_days_gives_no_comparison(session):
    co, rows = _setup(session, {}, n_events=6)
    res = run_j2_02(InputStore(session, co.company_id, "consolidated"), ["FY2025", "FY2026", "FY2027"], CFG)
    assert not res.observations and res.status == "NOT_ENOUGH_DATA"
    assert population_z({str(i): {"z": {"return": 1.0 + i, "volume": 0.0, "runup": 0.0}} for i in range(5)}, "0", "return") is None


def test_standalone_run_is_not_applicable_and_missing_window_needs_definition(session):
    co, _ = _setup(session, {})
    assert run_j2_02(InputStore(session, co.company_id, "standalone"), ["FY2025"], CFG).status == "NOT_APPLICABLE"
    assert run_j2_02(InputStore(session, co.company_id, "consolidated"), ["FY2025"], {"rule_id": "x", "thresholds": {}}).status == "NEEDS_DEFINITION"
