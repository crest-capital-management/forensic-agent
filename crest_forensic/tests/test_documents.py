import datetime as dt
from pathlib import Path

import pymupdf
import pytest
from sqlalchemy import select

from crest_forensic.db.models import DataQualityEvent, Document, DocumentVersion, LineItem, Snapshot, TextExtract
from crest_forensic.documents.ingest import ingest_document
from crest_forensic.documents.quotes import MIN_QUOTE_CHARS, find_quote_page, normalize, quote_in_page
from crest_forensic.documents.sections import locate_sections
from crest_forensic.documents.statements import (
    PROVIDER, _parse_value, extract_statement_lines, find_row,
)

# --- quote verification ----------------------------------------------------------------

PAGE = ("We are independent of the Company in accordance with the Code of Ethics issued by the\n"
        "Institute of Chartered Accountants of India. Auditor\ufffds responsibilities are described\n"
        "in the \ufffdCompany\ufffd section of our report.")


def test_exact_quote_matches_despite_line_breaks():
    assert quote_in_page("the Code of Ethics issued by the Institute of Chartered Accountants of India", PAGE)


def test_replacement_character_matches_curly_and_straight_quotes():
    assert quote_in_page("Auditor\u2019s responsibilities are described in the", PAGE)
    assert quote_in_page("Auditor's responsibilities are described in the", PAGE)
    assert quote_in_page('in the \u201cCompany\u201d section of our report', PAGE)


def test_a_paraphrase_never_matches():
    assert not quote_in_page("The auditor is independent of the company and follows the ICAI ethics code", PAGE)
    assert not quote_in_page("We are independent of the Company in accordance with the Code of Conduct issued by the", PAGE)


def test_a_quote_that_is_too_short_is_rejected_even_if_it_appears():
    assert "Company" in PAGE
    assert len("Company") < MIN_QUOTE_CHARS and not quote_in_page("Company", PAGE)


def test_find_quote_page_reports_which_page():
    pages = {10: "nothing here", 11: PAGE}
    assert find_quote_page("Code of Ethics issued by the Institute of Chartered Accountants", pages) == 11
    assert find_quote_page("a sentence that is nowhere in the document at all", pages) is None


def test_normalize_collapses_dashes_and_ligatures():
    assert normalize("pro\ufb01t \u2013 loss") == "profit - loss"


# --- parsing a printed row ---------------------------------------------------------------

def test_parse_values_indian_grouping_negative_and_nil():
    assert _parse_value("2,67,021") == 267021
    assert _parse_value("(4,778)") == -4778
    assert _parse_value("-") is None
    assert _parse_value("135.70") == 135.70


def _page(*lines):
    return {1: "\n".join(lines)}


def test_row_with_a_note_column_drops_the_note():
    row = find_row(_page("Revenue from operations", "10", "2,20,938", "2,14,853", "Other income"), "Revenue from operations")
    assert row["tokens"] == ["2,20,938", "2,14,853"]


def test_row_with_alphanumeric_note_and_small_values_is_not_misread():
    row = find_row(_page("Inventories", "8(d)", "29", "20", "Financial assets"), "Inventories")
    assert row["tokens"] == ["29", "20"]


def test_row_without_a_note_column():
    row = find_row(_page("Unbilled", "10,084", "8,904", "Cash and cash equivalents"), "Unbilled")
    assert row["tokens"] == ["10,084", "8,904"]


def test_nth_occurrence_of_a_repeated_label():
    page = _page("Billed", "8(b)", "99", "91", "Unbilled", "114", "38",
                 "Billed", "8(b)", "57,630", "50,142", "Unbilled", "10,084", "8,904")
    assert find_row(page, "Billed", 0)["tokens"] == ["99", "91"]
    assert find_row(page, "Billed", 1)["tokens"] == ["57,630", "50,142"]
    assert find_row(page, "Billed", 2) is None


def test_label_not_printed_returns_none_instead_of_guessing():
    assert find_row(_page("Revenue from operations", "10", "1", "2"), "Net sales") is None


# --- locating sections -----------------------------------------------------------------------

def test_sections_are_found_by_heading_and_by_statement_content_not_title():
    pages = {
        1: "Contents",
        2: "To the Members of X Limited Report on the Audit of the Consolidated Financial Statements Opinion",
        3: "Key audit matters ...",
        4: "(Referred to in paragraph 1) ... Annexure A to the Independent Auditor\ufffds Report on the Consolidated Financial Statements",
        5: "ASSETS ... TOTAL ASSETS 100 EQUITY AND LIABILITIES TOTAL EQUITY AND LIABILITIES 100",   # consolidated BS, no title
        6: "To the Members of X Limited Report on the Audit of the Standalone Financial Statements Opinion",
        7: "Annexure A to the Independent Auditor\ufffds Report on the Standalone Financial Statements",
        8: "Annexure B to the Independent Auditor\ufffds Report on the standalone financial statements",
        9: "ASSETS ... TOTAL ASSETS 90 ... TOTAL EQUITY AND LIABILITIES 90",
    }
    s = locate_sections(pages)
    assert s["consolidated_auditors_report_full"] == {"first": 2, "last": 4}
    assert s["consolidated_balance_sheet"]["first"] == 5          # basis comes from position
    assert s["standalone_auditors_report_full"] == {"first": 6, "last": 8}
    assert s["standalone_annexure_a"] == {"first": 7, "last": 7}
    assert s["standalone_balance_sheet"]["first"] == 9


# --- ingest + statement reading (synthetic data) ------------------------------------------------

def _make_pdf(path: Path, pages: list[str]) -> None:
    doc = pymupdf.open()
    for text in pages:
        page = doc.new_page()
        page.insert_text((72, 72), text, fontsize=9)
    doc.save(path)
    doc.close()


def test_ingest_stores_pages_hash_and_is_idempotent(session, company, tmp_path):
    pdf = tmp_path / "ar.pdf"
    _make_pdf(pdf, ["Integrated Annual Report\n196\nHello page one", "page two text"])

    v1, created1 = ingest_document(session, company.company_id, pdf, "annual_report", "FY2026")
    v2, created2 = ingest_document(session, company.company_id, pdf, "annual_report", "FY2026")

    assert created1 and not created2 and v1.id == v2.id
    assert v1.page_count == 2 and len(v1.file_sha256) == 64
    pages = session.execute(select(TextExtract).where(TextExtract.document_version_id == v1.id)
                            .order_by(TextExtract.page_number)).scalars().all()
    assert [p.page_number for p in pages] == [1, 2]
    assert pages[0].printed_page == "196" and "Hello page one" in pages[0].text
    assert len(session.execute(select(Document)).scalars().all()) == 1


def _statement_version(session, company, pages: dict[int, str], sections: dict, fy="FY2026") -> DocumentVersion:
    doc = Document(company_id=company.company_id, doc_type="annual_report", fiscal_year=fy, title="Test AR")
    session.add(doc)
    session.flush()
    version = DocumentVersion(document_id=doc.id, file_name="t.pdf", file_sha256="ab" * 32, page_count=len(pages),
                              extractor="test", sections=sections,
                              created_at=dt.datetime(2026, 10, 1, tzinfo=dt.timezone.utc))
    session.add(version)
    session.flush()
    for n, text in pages.items():
        session.add(TextExtract(document_version_id=version.id, page_number=n, text=text, text_sha256="x"))
    session.flush()
    return version


BALANCE_SHEET = "\n".join([
    "Standalone Balance Sheet", "(H crore)", "Inventories", "8(d)", "29", "20",
    "Billed", "6(b)", "99", "91", "Unbilled", "102", "44",
    "Billed", "6(b)", "48,892", "44,392", "Unbilled", "8,084", "7,375",
    "Total current assets", "1,10,270", "1,03,163", "TOTAL ASSETS", "1,49,268", "1,32,788",
    "Total equity", "84,676", "75,617",
    "Total non-current liabilities", "9,632", "7,989", "Total current liabilities", "54,960", "49,182",
])
CASH_FLOW = "\n".join(["Standalone Statement of Cash Flows", "(H crore)",
                       "Net cash flows generated from operating activities", "45,597", "40,816"])


def test_statement_lines_are_read_scaled_to_rupees_and_labelled_by_year(session, company):
    v = _statement_version(session, company, {10: BALANCE_SHEET, 11: CASH_FLOW}, {
        "standalone_balance_sheet": {"first": 10, "last": 10}, "standalone_cash_flow": {"first": 11, "last": 11}})
    items = extract_statement_lines(session, v, company.company_id)
    got = {(i.standard_field, i.financial_year): i for i in items}

    assert got[("cash_flow_from_operations", "FY2026")].normalized_value == 45597 * 1e7
    assert got[("cash_flow_from_operations", "FY2025")].normalized_value == 40816 * 1e7
    assert got[("trade_receivables", "FY2026")].normalized_value == (48892 + 8084) * 1e7   # current billed + unbilled
    assert got[("trade_receivables_billed", "FY2025")].normalized_value == 44392 * 1e7
    assert got[("inventories", "FY2026")].normalized_value == 29 * 1e7
    assert got[("total_liabilities", "FY2026")].normalized_value == (9632 + 54960) * 1e7
    assert all(i.basis == "standalone" and i.period_type == "annual" and i.derivation_method is None for i in items)
    assert all(i.source_ref.startswith("pdf:standalone_") for i in items)


def test_figures_cite_an_audited_snapshot_that_records_the_printed_rows(session, company):
    v = _statement_version(session, company, {11: CASH_FLOW}, {"standalone_cash_flow": {"first": 11, "last": 11}})
    (item,) = extract_statement_lines(session, v, company.company_id)[:2][:1]
    snap = session.get(Snapshot, item.snapshot_id)
    assert snap.source_provider == PROVIDER and snap.provisional is False
    assert snap.raw_payload["rows"]["cash_flow_from_operations"][0]["page"] == 11
    assert snap.raw_payload["rows"]["cash_flow_from_operations"][0]["tokens"] == ["45,597", "40,816"]


def test_re_reading_reuses_the_snapshot_instead_of_creating_another(session, company):
    v = _statement_version(session, company, {11: CASH_FLOW}, {"standalone_cash_flow": {"first": 11, "last": 11}})
    extract_statement_lines(session, v, company.company_id)
    session.query(LineItem).delete()
    extract_statement_lines(session, v, company.company_id)
    assert len(session.execute(select(Snapshot).where(Snapshot.source_provider == PROVIDER)).scalars().all()) == 1


def test_a_section_without_a_crore_header_is_not_read_and_is_logged(session, company):
    no_unit = CASH_FLOW.replace("(H crore)", "(amounts as printed)")
    v = _statement_version(session, company, {11: no_unit}, {"standalone_cash_flow": {"first": 11, "last": 11}})
    assert extract_statement_lines(session, v, company.company_id) == []
    events = session.execute(select(DataQualityEvent)).scalars().all()
    assert any(e.issue_type == "UNIT_MISMATCH" for e in events)


def test_a_missing_printed_row_is_logged_not_guessed(session, company):
    page = "\n".join(["(H crore)", "Revenue from operations", "10", "5,00,000", "4,00,000"])
    v = _statement_version(session, company, {12: page}, {"standalone_profit_and_loss": {"first": 12, "last": 12}})
    items = extract_statement_lines(session, v, company.company_id)
    assert {i.standard_field for i in items} == {"revenue_from_operations"}
    events = session.execute(select(DataQualityEvent).where(DataQualityEvent.issue_type == "MISSING_FIELD")).scalars().all()
    assert any(e.field_name == "profit_before_tax" for e in events)


# --- the real reports (skipped when the PDFs are not on this machine) -----------------------------

_DOCS = Path(r"A:\CREST\Forensic Accountant\Documents\Test")
_AR26, _AR25 = _DOCS / "AR_TCS_2025-2026.pdf", _DOCS / "AR_TCS_2024_2025.pdf"
needs_real_reports = pytest.mark.skipif(not (_AR26.exists() and _AR25.exists()), reason="TCS annual-report PDFs not present")


@needs_real_reports
def test_real_report_sections_match_the_page_ranges_in_the_users_notes(session, company):
    """Documents/Test/Notes.xlsx: auditor's reports at 158-166 / 240-252 (FY26) and 172-180 / 242-252 (FY25)."""
    v26, _ = ingest_document(session, company.company_id, _AR26, "annual_report", "FY2026")
    v25, _ = ingest_document(session, company.company_id, _AR25, "annual_report", "FY2025")
    assert v26.sections["consolidated_auditors_report_full"] == {"first": 158, "last": 166}
    assert v26.sections["standalone_auditors_report_full"] == {"first": 240, "last": 252}
    assert v25.sections["consolidated_auditors_report_full"] == {"first": 172, "last": 180}
    assert v25.sections["standalone_auditors_report_full"] == {"first": 242, "last": 252}
    assert v26.sections["consolidated_balance_sheet"]["first"] == 167 and v25.sections["consolidated_balance_sheet"]["first"] == 181


@needs_real_reports
def test_real_report_figures_equal_the_hand_transcribed_answer_key(session, company):
    from crest_forensic.ingestion.golden import evaluate_golden, load_golden

    golden = load_golden(Path(__file__).parent / "golden" / "tcs_golden.yaml")
    for fy, path in (("FY2026", _AR26), ("FY2025", _AR25)):
        version, _ = ingest_document(session, company.company_id, path, "annual_report", fy)
        extract_statement_lines(session, version, company.company_id)
    for basis in ("consolidated", "standalone"):
        rows = evaluate_golden(session, company.company_id, golden, basis, PROVIDER)
        bad = [r for r in rows if r["status"] != "MATCH"]
        assert bad == [], bad
