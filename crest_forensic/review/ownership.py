"""Ownership and auditor-fee rows for the multi-year matrix.

Same saved data the checks use (shareholding table, auditor-fee snapshots); nothing new is calculated.
Information tables like the plain ratios: they are never in the matrix summary or in the narrative facts.
The one label is the promoter-holding row, which uses the live J2-01 limit (a quarterly step above 2 percentage
points = "Worth a look"). The auditor-fee rows use the live J2-03 limit (a rise of more than 30% in a year = "Worth a look").
Fees are the STANDALONE notes of the annual report whichever basis the matrix shows (the consolidated notes do not print them).
"""
from __future__ import annotations

from sqlalchemy.orm import Session

from crest_forensic.checks.filing_dates import fy_quarter_ends
from crest_forensic.checks.shareholding import _row, prior_quarter_end, step_points
from crest_forensic.documents.auditor_fees import ROWS as FEE_LINES
from crest_forensic.documents.auditor_fees import fee_changes, load_auditor_fees
from crest_forensic.ingestion.exchange_files import quarter_label


def _gap(fy: str, why: str) -> dict:
    return {"value": None, "display": "n/a", "badge": None, "skipped": "NOT_ENOUGH_DATA", "what": f"{fy}: {why}"}


def _shareholding_rows(session: Session, company_id: int, years: list[str], limit: float | None) -> list[dict]:
    promoter, pledged, fii, dii = {}, {}, {}, {}
    for fy in years:
        end = fy_quarter_ends(fy)[-1]                       # 31 March of the financial year
        row = _row(session, company_id, end)
        if row is None or row.promoter_pct is None:
            for cells in (promoter, pledged, fii, dii):
                cells[fy] = _gap(fy, f"no saved shareholding pattern for {quarter_label(end)}")
            continue
        label = quarter_label(end)
        steps = []
        for q_end in fy_quarter_ends(fy):
            cur, prev = _row(session, company_id, q_end), _row(session, company_id, prior_quarter_end(q_end))
            if cur and prev and cur.promoter_pct is not None and prev.promoter_pct is not None:
                steps.append((abs(step_points(cur.promoter_pct, prev.promoter_pct)), q_end, step_points(cur.promoter_pct, prev.promoter_pct)))
        biggest = max(steps) if steps else None
        badge = None
        if biggest is not None and limit is not None:
            badge = "look" if biggest[0] > limit else "normal"
        step_txt = (f" Largest quarterly step in {fy}: {biggest[2]:+.2f} percentage points (to {quarter_label(biggest[1])})."
                    f" Limit for a label: more than {limit} points (the Job 2 spec).") if biggest else " No quarterly step could be computed."
        promoter[fy] = {"value": row.promoter_pct, "display": f"{row.promoter_pct:.2f}%", "badge": badge,
                        "what": f"Promoter group holding at {end.isoformat()} ({label}).{step_txt}"}
        pledged[fy] = ({"value": row.pledged_pct, "display": f"{row.pledged_pct:.2f}%", "badge": None,
                        "what": f"Shares pledged by the promoter group at {label}, as a percent of the promoter group's shares. Information only."}
                       if row.pledged_pct is not None else _gap(fy, f"pledging not in the saved {label} data"))
        fii[fy] = ({"value": row.fii_pct, "display": f"{row.fii_pct:.2f}%", "badge": None,
                    "what": f"Foreign institutions' share of all shares at {label}. Information only."}
                   if row.fii_pct is not None else _gap(fy, f"foreign institution total not in the saved {label} data"))
        dii[fy] = ({"value": row.dii_pct, "display": f"{row.dii_pct:.2f}%", "badge": None,
                    "what": f"Domestic institutions' share of all shares at {label}. Information only."}
                   if row.dii_pct is not None else _gap(fy, f"domestic institution total not in the saved {label} data"))
    return [
        {"key": "promoter", "name": "Promoter holding", "question": "Share held by the promoter group at 31 March", "cells": promoter,
         "rule": "A quarterly step of more than the limit (2 percentage points) in the year makes it Worth a look.",
         "caveat": "From the exchange shareholding filings saved by hand."},
        {"key": "pledged", "name": "Promoter pledging", "question": "Pledged shares as a share of the promoter group's holding", "cells": pledged,
         "rule": "Information only: the lead has not set a pledging rule.", "caveat": None},
        {"key": "fii", "name": "Foreign institutions", "question": "Their share of all shares at 31 March", "cells": fii,
         "rule": "Information only.", "caveat": "Not available in the older (2021 to mid 2022) filing layout."},
        {"key": "dii", "name": "Domestic institutions", "question": "Their share of all shares at 31 March", "cells": dii,
         "rule": "Information only.", "caveat": "Not available in the older (2021 to mid 2022) filing layout."},
    ]


def _fee_rows(session: Session, company_id: int, years: list[str], limit: float | None) -> list[dict]:
    fees, notes = load_auditor_fees(session, company_id)
    changes = {c["fy"]: c for c in fee_changes(fees)}
    audit, total = {}, {}
    for fy in years:
        v = fees.get(fy)
        if v is None:
            audit[fy] = total[fy] = _gap(fy, "no saved auditor fee note for this year")
            continue
        t = sum(v[k] for k in FEE_LINES.values())
        c = changes.get(fy)
        parts = (f"audit {v['audit_fee_cr']}, taxation matters {v['tax_matters_cr']}, other services {v['other_services_cr']}, "
                 f"reimbursement {v['reimbursement_cr']}")
        chg = (f" Change on the year before: audit fee {c['audit_fee_change_pct']:+.1f}%, total {c['total_change_pct']:+.1f}%."
               if c else "")
        src = f" Source: {v['report_fy']} annual report, page {v['page']}."
        def badge(change):
            return None if limit is None or change is None else ("look" if change > limit else "normal")

        lim = f" Limit for a label: a rise of more than {limit:g}% (the Job 2 spec); fees are in whole crores." if limit is not None else ""
        audit[fy] = {"value": v["audit_fee_cr"], "display": f"{v['audit_fee_cr']} cr", "badge": badge(c["audit_fee_change_pct"] if c else None),
                     "what": f"{fy}: statutory audit fee (INR crore): {parts}.{chg}{src}{lim}"}
        total[fy] = {"value": t, "display": f"{t} cr", "badge": badge(c["total_change_pct"] if c else None),
                     "what": f"{fy}: all fees paid to the auditor (INR crore): {parts}; total {t}.{chg}{src}{lim}"}
    caveat = "Standalone notes, whole crores (small changes are invisible). " + " ".join(notes)
    return [
        {"key": "audit_fee", "name": "Audit fee", "question": "Statutory audit fee paid to the auditor", "cells": audit,
         "rule": "A rise of more than the limit (30%, from the Job 2 spec) in a year makes it Worth a look.",
         "caveat": caveat.strip()},
        {"key": "total_fees", "name": "Total auditor fees", "question": "Audit, tax, other services and reimbursement together", "cells": total,
         "rule": "A rise of more than the limit (30%) in a year makes it Worth a look.", "caveat": caveat.strip()},
    ]


def _peer_rows(session: Session, company_id: int, years: list[str], limit: float | None) -> list[dict]:
    """TCS against the lead's peer set (consolidated): tax rate (labelled by the J2-07 limit), net margin and receivable days (information only)."""
    import statistics

    from crest_forensic.checks.base import InputStore, Missing
    from crest_forensic.checks.peer_tax import MIN_PEERS
    from crest_forensic.ingestion.peers import latest_peer_snapshot, peers_of

    store = InputStore(session, company_id, "consolidated")
    peers = peers_of(session, company_id)
    if not peers:
        return []
    snaps = {p.company_id: latest_peer_snapshot(session, p.company_id) for p in peers}
    spec = {
        "tax": ("peer_tax", "Tax rate against peers", "Effective tax rate, with the peer median and range", "pct"),
        "margin": ("peer_margin", "Net margin against peers", "Profit after tax as a share of revenue, with the peer median and range", "pct"),
        "recv": ("peer_recv_days", "Receivable days against peers", "Trade receivables in days of revenue, with the peer median and range", "days"),
    }
    cells: dict[str, dict] = {k: {} for k in spec}

    def own_value(kind: str, fy: str):
        g = lambda n, f: store.get(n, f, fy)   # noqa: E731
        if kind == "tax":
            a, b = g("a", "tax_expense"), g("b", "profit_before_tax")
            return None if isinstance(a, Missing) or isinstance(b, Missing) or b.value <= 0 else a.value / b.value
        if kind == "margin":
            a, b = g("a", "profit_after_tax"), g("b", "revenue_from_operations")
            return None if isinstance(a, Missing) or isinstance(b, Missing) or b.value <= 0 else a.value / b.value
        a, b = g("a", "trade_receivables"), g("b", "revenue_from_operations")
        return None if isinstance(a, Missing) or isinstance(b, Missing) or b.value <= 0 else a.value / b.value * 365

    def peer_value(kind: str, y: dict):
        if kind == "tax":
            return y["tax"] / y["pretax_income"] if y.get("pretax_income", 0) > 0 and y.get("tax") is not None else None
        if kind == "margin":
            return y["net_income"] / y["revenue"] if y.get("revenue", 0) > 0 and y.get("net_income") is not None else None
        return y["receivables"] / y["revenue"] * 365 if y.get("revenue", 0) > 0 and y.get("receivables") is not None else None

    for fy in years:
        for kind in spec:
            own = own_value(kind, fy)
            vals = []
            for p in peers:
                s = snaps.get(p.company_id)
                y = (s.raw_payload["years"].get(fy) if s else None) or {}
                v = peer_value(kind, y) if y else None
                if v is not None:
                    vals.append((p.name, v))
            if own is None or len(vals) < MIN_PEERS:
                cells[kind][fy] = _gap(fy, "the company's figure or at least 3 peers' figures are not available")
                continue
            med, lo, hi = statistics.median(v for _, v in vals), min(v for _, v in vals), max(v for _, v in vals)
            fmt = (lambda v: f"{v * 100:.1f}%") if spec[kind][3] == "pct" else (lambda v: f"{v:.0f} days")
            badge = None
            if kind == "tax" and limit is not None:
                badge = "look" if abs(own - med) * 100 > limit else "normal"
            cells[kind][fy] = {
                "value": own, "display": fmt(own), "badge": badge,
                "what": (f"{fy}: {fmt(own)} against a peer median of {fmt(med)} (range {fmt(lo)} to {fmt(hi)}); peers: "
                         + "; ".join(f"{n} {fmt(v)}" for n, v in vals) + ". Peer figures are Yahoo Finance (unofficial). "
                         + (f"Limit for a label: a gap of more than {limit:g} percentage points from the median." if kind == "tax" and limit is not None else "Information only."))}
    caveats = {"tax": "Consolidated. Tax rates differ legitimately with the countries a company earns in and with tax incentives.",
               "margin": "Consolidated; peers' own definitions of profit may differ slightly.",
               "recv": "Peers' receivables are Yahoo's 'accounts receivable' line, which may not match TCS's trade receivables definition exactly."}
    return [{"key": spec[k][0], "name": spec[k][1], "question": spec[k][2], "cells": cells[k],
             "rule": "A gap of more than the limit from the peer median makes it Worth a look." if k == "tax" else "Information only.",
             "caveat": caveats[k]} for k in spec]


def build_ownership(session: Session, company_id: int, years: list[str], cfg: dict) -> list[dict]:
    limit = ((cfg.get("J2-01") or {}).get("thresholds", {}).get("medium") or {}).get("value")
    fee_limit = ((cfg.get("J2-03") or {}).get("thresholds", {}).get("medium") or {}).get("value")
    peer_limit = ((cfg.get("J2-07") or {}).get("thresholds", {}).get("medium") or {}).get("value")
    return (_shareholding_rows(session, company_id, years, limit) + _fee_rows(session, company_id, years, fee_limit)
            + _peer_rows(session, company_id, years, peer_limit))
