"""Peer set for Job 2 peer comparisons: the five listed IT-services companies the forensic lead supplied annual reports for.

Source of the peer figures: Yahoo Finance via yfinance (free, UNOFFICIAL, provisional), one saved snapshot per peer. The annual report PDFs the lead
supplied are not read yet: their statements are laid out differently from TCS's and some are IFRS, so each would need its own reader. Only RATIOS
are compared (tax rate, margin, receivable days), so the currency label Yahoo attaches (it is wrong for some Indian companies) does not matter.
Years are Indian financial years: a column dated 31 March 2026 is FY2026.
"""
from __future__ import annotations

import datetime as dt

from sqlalchemy.orm import Session

from crest_forensic.connectors.base import RawSourceResponse
from crest_forensic.db.models import Company, PeerLink, Snapshot
from crest_forensic.ingestion.fetch_and_snapshot import save_snapshot

PROVIDER = "yfinance"
ENDPOINT = "yfinance:peer_financials"
PEERS = [
    ("Infosys Limited", "INFY", "INFY.NS"),
    ("HCL Technologies Limited", "HCLTECH", "HCLTECH.NS"),
    ("Wipro Limited", "WIPRO", "WIPRO.NS"),
    ("LTM Limited", "LTM", "LTM.NS"),               # formerly LTIMindtree
    ("Tech Mahindra Limited", "TECHM", "TECHM.NS"),
]
FIELDS = {"revenue": "Total Revenue", "pretax_income": "Pretax Income", "tax": "Tax Provision", "net_income": "Net Income",
          "receivables": "Accounts Receivable", "total_assets": "Total Assets"}


def _fy(col) -> str | None:
    return f"FY{col.year}" if col.month == 3 else None


def fetch_peer(ticker: str) -> RawSourceResponse:
    import yfinance as yf

    params = {"ticker": ticker}
    now = dt.datetime.now(dt.timezone.utc)
    try:
        tk = yf.Ticker(ticker)
        fin, bs = tk.financials, tk.balance_sheet
        currency = tk.info.get("financialCurrency")
    except Exception as exc:
        return RawSourceResponse(provider=PROVIDER, endpoint=ENDPOINT, request_params=params, status_code=0, payload={}, fetched_at=now,
                                 parse_error=f"{type(exc).__name__}: {exc}")
    if fin is None or fin.empty:
        return RawSourceResponse(provider=PROVIDER, endpoint=ENDPOINT, request_params=params, status_code=404, payload={}, fetched_at=now,
                                 parse_error=f"yfinance returned no statements for {ticker}")
    years: dict[str, dict] = {}
    for df in (fin, bs):
        for col in df.columns:
            fy = _fy(col)
            if fy is None:
                continue
            for key, label in FIELDS.items():
                if label in df.index:
                    v = df.loc[label, col]
                    if v == v:                               # not NaN
                        years.setdefault(fy, {})[key] = float(v)
    return RawSourceResponse(
        provider=PROVIDER, endpoint=ENDPOINT, request_params=params, status_code=200, fetched_at=now,
        payload={"status": "success", "meta": {"source": "yfinance (unofficial)", "ticker": ticker, "currency_label": currency,
                                                "note": "units as reported by Yahoo; only ratios are used"}, "years": years})


def ingest_peers(session: Session, subject_company_id: int, approved_by: str, note: str = "") -> list[str]:
    msgs = []
    for name, symbol, ticker in PEERS:
        peer = session.query(Company).filter_by(nse_symbol=symbol).first()
        if peer is None:
            peer = Company(name=name, nse_symbol=symbol, supported_status="PEER")
            session.add(peer)
            session.flush()
        resp = fetch_peer(ticker)
        snap = save_snapshot(session, peer.company_id, resp)
        if resp.parse_error:
            msgs.append(f"{name}: FAILED ({resp.parse_error})")
        else:
            msgs.append(f"{name}: {', '.join(sorted(resp.payload['years']))} (snapshot {snap.snapshot_id})")
        if not session.query(PeerLink).filter_by(company_id=subject_company_id, peer_company_id=peer.company_id).first():
            session.add(PeerLink(company_id=subject_company_id, peer_company_id=peer.company_id, approved_by=approved_by, note=note or None))
    session.flush()
    return msgs


def peers_of(session: Session, company_id: int) -> list[Company]:
    rows = session.query(PeerLink).filter_by(company_id=company_id).order_by(PeerLink.id).all()
    return [session.get(Company, r.peer_company_id) for r in rows]


def latest_peer_snapshot(session: Session, peer_company_id: int) -> Snapshot | None:
    for snap in session.query(Snapshot).filter_by(company_id=peer_company_id, source_provider=PROVIDER, source_endpoint=ENDPOINT).order_by(Snapshot.snapshot_id.desc()):
        if snap.raw_payload.get("years"):
            return snap
    return None
