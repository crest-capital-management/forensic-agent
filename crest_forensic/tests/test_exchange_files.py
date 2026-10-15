import datetime as dt

from crest_forensic.db.models import Company, Shareholding
from crest_forensic.ingestion.exchange_files import (
    ingest_exchange_file,
    load_filing_times,
    parse_results_csv,
    parse_shp_xml,
    quarter_label,
)

CSV = (
    '"COMPANY NAME","AUDITED / UNAUDITED","CUMULATIVE / NON-CUMULATIVE","CONSOLIDATED / NON-CONSOLIDATED",'
    '"IND AS/ NON IND AS","PERIOD","PERIOD ENDED","RELATING TO","** XBRL","Exchange Received Time",'
    '"Exchange Dissemination Time","Time Taken"\n'
    '"T","Audited","Non-cumulative","Consolidated","Ind-AS New","Quarterly","30-Sep-2024","Second Quarter",'
    '"http://x","10-Oct-2024 18:59:44","10-Oct-2024 19:00:10","00:00:26"\n'
)

PCT = "ShareholdingAsAPercentageOfTotalNumberOfShares"
XML = (
    '<x xmlns:b="urn:b"><b:DateOfReport contextRef="MainI">2026-06-30</b:DateOfReport>'
    '<b:WhetherAnySharesHeldByPromotersAreEncumberedUnderPledgedForPromoterAndPromoterGroup contextRef="MainI">false</b:WhetherAnySharesHeldByPromotersAreEncumberedUnderPledgedForPromoterAndPromoterGroup>'
    f'<b:{PCT} contextRef="ShareholdingOfPromoterAndPromoterGroup_ContextI">0.7177</b:{PCT}>'
    f'<b:{PCT} contextRef="PublicShareholding_ContextI">0.2823</b:{PCT}>'
    f'<b:{PCT} contextRef="InstitutionsForeign_ContextI">0.0906</b:{PCT}>'
    '</x>'
)
# older layout: counts, percent units, and the pledged count repeated on every subtotal row
OLD_XML = (
    '<x xmlns:b="urn:b"><b:DateOfReport contextRef="MainI">2021-09-30</b:DateOfReport>'
    f'<b:{PCT} contextRef="ShareholdingOfPromoterAndPromoterGroupI">72.19</b:{PCT}>'
    f'<b:{PCT} contextRef="PublicShareholdingI">27.81</b:{PCT}>'
    '<b:NumberOfShares contextRef="ShareholdingOfPromoterAndPromoterGroupI">1000</b:NumberOfShares>'
    '<b:NumberOfShares contextRef="ShareholdingPatternI">1385</b:NumberOfShares>'
    '<b:PledgedOrEncumberedNumberOfShares contextRef="ShareholdingOfPromoterAndPromoterGroupI">10</b:PledgedOrEncumberedNumberOfShares>'
    '<b:PledgedOrEncumberedNumberOfShares contextRef="IndianI">10</b:PledgedOrEncumberedNumberOfShares>'
    '<b:PledgedOrEncumberedNumberOfShares contextRef="ShareholdingPatternI">10</b:PledgedOrEncumberedNumberOfShares>'
    '</x>'
)


def test_quarter_label():
    assert quarter_label(dt.date(2026, 6, 30)) == "Q1FY2027"
    assert quarter_label(dt.date(2025, 3, 31)) == "Q4FY2025"


def test_results_csv_and_dedupe(session, tmp_path):
    co = Company(name="T")
    session.add(co)
    session.flush()
    f = tmp_path / "res.csv"
    f.write_text(CSV, encoding="utf-8")
    rows = parse_results_csv(f)
    assert rows[0]["basis"] == "consolidated" and rows[0]["received_at"] == "2024-10-10T18:59:44+05:30"
    assert "snapshot" in ingest_exchange_file(session, co.company_id, f)
    assert "already saved" in ingest_exchange_file(session, co.company_id, f)
    assert len(load_filing_times(session, co.company_id)) == 1


def test_shp_xml(session, tmp_path):
    co = Company(name="T")
    session.add(co)
    session.flush()
    f = tmp_path / "SHP_1.xml"
    f.write_text(XML, encoding="utf-8")
    d = parse_shp_xml(f)
    assert d["promoter_pct"] == 71.77 and d["pledged_pct"] == 0.0 and d["quarter"] == "Q1FY2027"
    ingest_exchange_file(session, co.company_id, f)
    assert session.query(Shareholding).one().promoter_pct == 71.77


def test_integrated_filing_csv(tmp_path):
    f = tmp_path / "int.csv"
    f.write_text(
        '"SYMBOL \n","COMPANY NAME \n","QUARTER END DATE \n","TYPE OF SUBMISSION \n","AUDITED / UNAUDITED \n",'
        '"CONSOLIDATED / STANDALONE \n","DETAILS \n","XBRL \n","BROADCAST DATE/TIME \n","REVISED DATE/TIME \n",'
        '"REVISION REMARKS \n","EXCHANGE DISSEMINATION TIME \n","TIME TAKEN \n"\n'
        '"TCS","T","30-SEP-2026","Original","Audited","Standalone","d","x","08-Oct-2026 22:07:30",,,"08-Oct-2026 22:07:52","00:00:22"\n',
        encoding="utf-8",
    )
    r = parse_results_csv(f)[0]
    assert r["period_end"] == "2026-09-30" and r["basis"] == "standalone"
    assert r["received_at"] == "2026-10-08T22:07:30+05:30" and r["revised_at"] is None


def test_shareholding_csv(session, tmp_path):
    co = Company(name="T")
    session.add(co)
    session.flush()
    f = tmp_path / "CF-Shareholding-Pattern-x.csv"
    f.write_text(
        '"COMPANY","PROMOTER & PROMOTER GROUP (A)","PUBLIC (B)","SHARES HELD BY EMPLOYEE TRUSTS (C2)","STATUS","AS ON DATE",'
        '"SUBMISSION DATE","REVISION DATE","ACTION","BROADCAST DATE/TIME","EXCHANGE DISSEMINATION TIME","TIME TAKEN"\n'
        '"T","71.77","28.23","0","-","30-JUN-2026","21-JUL-2026",,"u","21-JUL-2026 15:44:00","21-JUL-2026 15:44:06","00:00:06"\n',
        encoding="utf-8",
    )
    assert "1 new shareholding rows" in ingest_exchange_file(session, co.company_id, f)
    row = session.query(Shareholding).one()
    assert row.quarter == "Q1FY2027" and row.promoter_pct == 71.77 and row.pledged_pct is None


def test_older_layout_pledge_is_not_summed_over_subtotals(tmp_path):
    f = tmp_path / "SHP_old.xml"
    f.write_text(OLD_XML, encoding="utf-8")
    d = parse_shp_xml(f)
    assert d["quarter"] == "Q2FY2022" and d["promoter_pct"] == 72.19
    assert d["pledged_shares"] == 10 and d["pledged_pct"] == 1.0 and d["pledged_pct_of_total"] == round(10 / 1385 * 100, 4)
