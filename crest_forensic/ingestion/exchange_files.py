"""Readers for exchange files the user downloads by hand (the exchanges block scripts).

- NSE "financial results" CSV: when each result reached the exchange (J1-13 input).
- BSE shareholding-pattern XBRL (SHP_*.xml): promoter / FII / DII percentages and
  whether any promoter shares are pledged.

Raw-first: each file is saved as one immutable snapshot (provisional). Nothing here
judges lateness; that needs the lead's limits.
"""
from __future__ import annotations

import csv
import datetime as dt
import hashlib
import xml.etree.ElementTree as ET
from pathlib import Path

from sqlalchemy.orm import Session

from crest_forensic.connectors.base import RawSourceResponse
from crest_forensic.db.models import Shareholding, Snapshot
from crest_forensic.ingestion.fetch_and_snapshot import compute_payload_hash, save_snapshot

IST = dt.timezone(dt.timedelta(hours=5, minutes=30))
NSE_RESULTS = "nse_results_csv"
BSE_SHP = "bse_shp_xml"
NSE_SHP = "nse_shp_csv"


def _ist(text: str) -> str | None:
    text = (text or "").strip()
    if not text:
        return None
    return dt.datetime.strptime(text, "%d-%b-%Y %H:%M:%S").replace(tzinfo=IST).isoformat()


def parse_results_csv(path: Path) -> list[dict]:
    """One dict per filing. Times are stamped India time (the file has no zone)."""
    rows = []
    with open(path, encoding="utf-8-sig", newline="") as fh:
        reader = csv.DictReader(fh)
        reader.fieldnames = [(n or "").strip() for n in reader.fieldnames]
        if "BROADCAST DATE/TIME" in reader.fieldnames:
            return _parse_integrated_rows(reader)
        for r in reader:
            end =dt.datetime.strptime(r["PERIOD ENDED"].strip(), "%d-%b-%Y").date()
            rows.append({
                "period_end": end.isoformat(),
                "period": r["PERIOD"].strip(),
                "relating_to": r["RELATING TO"].strip(),
                "basis": "consolidated" if r["CONSOLIDATED / NON-CONSOLIDATED"].strip().lower() == "consolidated" else "standalone",
                "audited": r["AUDITED / UNAUDITED"].strip(),
                "cumulative": r["CUMULATIVE / NON-CUMULATIVE"].strip(),
                "received_at": _ist(r["Exchange Received Time"]),
                "disseminated_at": _ist(r["Exchange Dissemination Time"]),
                "xbrl_url": r["** XBRL"].strip(),
            })
    return rows


def _parse_integrated_rows(reader) -> list[dict]:
    """NSE Integrated Filing (Financials) CSV, used from Mar 2025 quarter on."""
    rows = []
    for r in reader:
        r = {k: (v or "").strip() for k, v in r.items() if k}
        end = dt.datetime.strptime(r["QUARTER END DATE"], "%d-%b-%Y").date()
        rows.append({
            "period_end": end.isoformat(),
            "period": "Quarterly",
            "relating_to": quarter_label(end),
            "basis": "consolidated" if r["CONSOLIDATED / STANDALONE"].lower() == "consolidated" else "standalone",
            "audited": r["AUDITED / UNAUDITED"],
            "cumulative": None,
            "submission_type": r["TYPE OF SUBMISSION"],
            "received_at": _ist(r["BROADCAST DATE/TIME"]),
            "disseminated_at": _ist(r["EXCHANGE DISSEMINATION TIME"]),
            "revised_at": _ist(r["REVISED DATE/TIME"]),
            "revision_remarks": r["REVISION REMARKS"] or None,
            "xbrl_url": r["XBRL"],
        })
    return rows


def parse_shareholding_csv(path: Path) -> list[dict]:
    """NSE shareholding-pattern list: one row per quarter (promoter and public totals, filing times).
    Pledging and the institution split are NOT in this file; they stay empty."""
    rows = []
    with open(path, encoding="utf-8-sig", newline="") as fh:
        for r in csv.DictReader(fh):
            end = dt.datetime.strptime(r["AS ON DATE"].strip(), "%d-%b-%Y").date()
            rows.append({
                "period_end": end.isoformat(),
                "quarter": quarter_label(end),
                "promoter_pct": float(r["PROMOTER & PROMOTER GROUP (A)"]),
                "public_pct": float(r["PUBLIC (B)"]),
                "employee_trust_pct": float(r["SHARES HELD BY EMPLOYEE TRUSTS (C2)"] or 0),
                "status": r["STATUS"].strip(),
                "submitted_on": dt.datetime.strptime(r["SUBMISSION DATE"].strip(), "%d-%b-%Y").date().isoformat(),
                "revised_on": (dt.datetime.strptime(r["REVISION DATE"].strip(), "%d-%b-%Y").date().isoformat()
                               if r["REVISION DATE"].strip() else None),
                "broadcast_at": _ist(r["BROADCAST DATE/TIME"]),
                "xbrl_url": r["ACTION"].strip(),
            })
    return rows


def quarter_label(period_end: dt.date) -> str:
    """Indian financial year: Jun = Q1, Sep = Q2, Dec = Q3, Mar = Q4 (e.g. Q1FY2027)."""
    q = {6: 1, 9: 2, 12: 3, 3: 4}[period_end.month]
    fy = period_end.year + 1 if period_end.month >= 4 else period_end.year
    return f"Q{q}FY{fy}"


def _norm(ctx: str) -> str:
    """Context ids differ between the three XBRL layouts BSE/NSE have used ('Name_ContextI' or 'NameI')."""
    for suffix in ("_ContextI", "I"):
        if ctx.endswith(suffix):
            return ctx[: -len(suffix)]
    return ctx


def parse_shp_xml(path: Path) -> dict:
    """Read one shareholding-pattern XBRL file (any of the layouts used since 2021).

    Percentages come back as percent (71.77). Pledge: the pledged-share count on the promoter-group total row
    (older layouts; the same figure repeats on the subtotal rows above it, so it is NOT summed), shown as a
    percent of the promoter group's shares; the newest
    layout only has a yes/no flag, so with 'false' the pledge is 0 and with 'true' it stays empty.
    FII / DII are filled only where the file has the foreign / domestic institution totals."""
    root = ET.parse(path).getroot()
    ns = "{http://www.xbrl.org/2003/instance}"
    dates = {c.attrib["id"]: (c.findtext(f".//{ns}instant") or "") for c in root.iter(f"{ns}context")}
    pct_raw: dict[str, float] = {}
    shares: dict[str, float] = {}
    pledged_by_ctx: dict[str, float] = {}
    flags: dict[str, str] = {}
    for el in root.iter():
        ctx, tag = el.attrib.get("contextRef"), el.tag.split("}")[-1]
        if not ctx or el.text is None:
            continue
        text = el.text.strip()
        if tag == "ShareholdingAsAPercentageOfTotalNumberOfShares":
            pct_raw[_norm(ctx)] = float(text)
        elif tag == "NumberOfShares":
            shares[_norm(ctx)] = float(text)
        elif tag == "PledgedOrEncumberedNumberOfShares":
            pledged_by_ctx[_norm(ctx)] = float(text)
        elif tag == "WhetherAnySharesHeldByPromotersAreEncumberedUnderPledgedForPromoterAndPromoterGroup":
            flags["pledged"] = text
        elif tag == "DateOfReport":
            flags["date"] = text
    promoter, public = pct_raw["ShareholdingOfPromoterAndPromoterGroup"], pct_raw["PublicShareholding"]
    factor = 1 if abs(promoter + public - 100) < 0.5 else 100 if abs(promoter + public - 1) < 0.005 else None
    if factor is None:
        raise ValueError(f"promoter + public percentages do not add to 100 ({promoter} + {public})")

    def pct(name: str) -> float | None:
        return None if name not in pct_raw else round(pct_raw[name] * factor, 4)

    date_text = next((d for ctx, d in dates.items() if _norm(ctx) == "ShareholdingOfPromoterAndPromoterGroup" and d), None) \
        or flags.get("date")
    end = dt.date.fromisoformat(date_text)
    promoter_shares, total_shares = shares.get("ShareholdingOfPromoterAndPromoterGroup"), shares.get("ShareholdingPattern")
    flag = flags.get("pledged")
    pledged_total = pledged_by_ctx.get("ShareholdingOfPromoterAndPromoterGroup")
    if pledged_total is not None:
        pledged_shares = pledged_total
        pledged_pct = round(pledged_total / promoter_shares * 100, 4) if promoter_shares else None
    else:
        pledged_shares = 0.0 if flag == "false" else None
        pledged_pct = 0.0 if flag == "false" else None
    return {
        "scrip_code": next((e.text for e in root.iter() if e.tag.endswith("identifier")), None),
        "period_end": end.isoformat(),
        "quarter": quarter_label(end),
        "promoter_pct": pct("ShareholdingOfPromoterAndPromoterGroup"),
        "fii_pct": pct("InstitutionsForeign"),
        "dii_pct": pct("InstitutionsDomestic"),
        "public_pct": pct("PublicShareholding"),
        "promoter_pledge_flag": flag,                 # "false" / "true" as filed (newest layout only)
        "pledged_shares": pledged_shares,
        "promoter_shares": promoter_shares,
        "pledged_pct": pledged_pct,                   # percent of the promoter group's shares
        "pledged_pct_of_total": (round(pledged_shares / total_shares * 100, 4)
                                 if pledged_shares is not None and total_shares else None),
    }


def ingest_exchange_file(session: Session, company_id: int, path: Path) -> str:
    """Detect the file type, save a snapshot (once per identical content), return a summary line."""
    path = Path(path)
    sha = hashlib.sha256(path.read_bytes()).hexdigest()
    suffix = path.suffix.lower()
    if suffix == ".csv" and "Shareholding" in path.name:
        provider, rows = NSE_SHP, parse_shareholding_csv(path)
        payload = {"file": path.name, "file_sha256": sha, "rows": rows}
    elif suffix == ".csv":
        provider, rows = NSE_RESULTS, parse_results_csv(path)
        payload = {"file": path.name, "file_sha256": sha, "rows": rows}
    elif suffix == ".xml" and path.name.upper().startswith("SHP"):
        provider, parsed = BSE_SHP, parse_shp_xml(path)
        payload = {"file": path.name, "file_sha256": sha, **parsed}
    else:
        raise ValueError(f"Unrecognised file: {path.name} (expected an NSE results .csv or a BSE SHP_*.xml)")

    old = (
        session.query(Snapshot)
        .filter_by(company_id=company_id, source_provider=provider, payload_hash=compute_payload_hash(payload))
        .first()
    )
    if old:
        return f"{path.name}: already saved as snapshot {old.snapshot_id}, nothing added"

    resp = RawSourceResponse(
        provider=provider, endpoint=f"file:{path.name}", request_params={"file": path.name},
        status_code=200, payload=payload, fetched_at=dt.datetime.now(dt.timezone.utc),
    )
    snap = save_snapshot(session, company_id, resp)
    if provider == NSE_SHP:
        added = 0
        for r in sorted(rows, key=lambda r: r["broadcast_at"] or ""):   # a later (revised) row wins over an earlier one
            if not session.query(Shareholding).filter_by(company_id=company_id, quarter=r["quarter"]).first():
                session.add(Shareholding(company_id=company_id, snapshot_id=snap.snapshot_id, quarter=r["quarter"],
                                         promoter_pct=r["promoter_pct"], pledged_pct=None, fii_pct=None, dii_pct=None))
                added += 1
        return f"{path.name}: {len(rows)} quarters ({min(r['period_end'] for r in rows)} to {max(r['period_end'] for r in rows)}), {added} new shareholding rows (promoter % only; pledging not in this file) (snapshot {snap.snapshot_id})"
    if provider == BSE_SHP:
        row = session.query(Shareholding).filter_by(company_id=company_id, quarter=payload["quarter"]).first()
        warn = ""
        if row is None:
            session.add(Shareholding(
                company_id=company_id, snapshot_id=snap.snapshot_id, quarter=payload["quarter"],
                promoter_pct=payload["promoter_pct"], pledged_pct=payload["pledged_pct"],
                fii_pct=payload["fii_pct"], dii_pct=payload["dii_pct"],
            ))
        else:   # the NSE list row has only the promoter %; the XML adds pledging and institutions
            if row.promoter_pct is not None and abs(row.promoter_pct - payload["promoter_pct"]) > 0.011:
                warn = f" WARNING: promoter % {payload['promoter_pct']} differs from the NSE list ({row.promoter_pct})"
            row.snapshot_id, row.promoter_pct = snap.snapshot_id, payload["promoter_pct"]
            row.pledged_pct, row.fii_pct, row.dii_pct = payload["pledged_pct"], payload["fii_pct"], payload["dii_pct"]
        return (f"{path.name}: {payload['quarter']} promoter {payload['promoter_pct']}%, FII {payload['fii_pct']}%, "
                f"DII {payload['dii_pct']}%, pledged {payload['pledged_shares']} shares = {payload['pledged_pct']}% of promoter holding "
                f"(snapshot {snap.snapshot_id}){warn}")
    return f"{path.name}: {len(rows)} filings, {min(r['period_end'] for r in rows)} to {max(r['period_end'] for r in rows)} (snapshot {snap.snapshot_id})"


def load_filing_times(session: Session, company_id: int) -> list[dict]:
    """All saved results filings merged across files; one row per period and basis, newest first."""
    seen: dict[tuple, dict] = {}
    q = session.query(Snapshot).filter_by(company_id=company_id, source_provider=NSE_RESULTS).order_by(Snapshot.snapshot_id)
    for snap in q:
        for r in snap.raw_payload.get("rows", []):
            seen[(r["period_end"], r["basis"])] = {**r, "snapshot_id": snap.snapshot_id}
    return sorted(seen.values(), key=lambda r: (r["period_end"], r["basis"]), reverse=True)
