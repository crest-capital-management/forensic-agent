import pytest

from crest_forensic.documents.auditor_fees import fee_changes, parse_fee_table, parse_fee_text

TEXT = ("17)\t Auditor\ufffds remuneration\n\t\nAuditor\ufffds remuneration consists of the following:\n(` crore)\n"
        "Year ended  \nMarch 31, 2025\nYear ended  \nMarch 31, 2024\nAuditor\n12\n11\nFor taxation matters\n1\n1\n"
        "For other services\n4\n4\nFor reimbursement of expenses\n1\n1\n18)\t Segment information\n")


def test_text_and_table_readers_agree():
    from_text = parse_fee_text(TEXT)
    from_table = parse_fee_table([["", "Year ended\nMarch 31, 2025", "Year ended\nMarch 31, 2024"],
                                  ["Auditor", "12", "11"], ["For taxation matters", "1", "1"],
                                  ["For other services", "4", "4"], ["For reimbursement of expenses", "1", "1"]])
    assert from_text == from_table
    assert from_text["FY2025"]["audit_fee_cr"] == 12 and from_text["FY2024"]["audit_fee_cr"] == 11


def test_missing_fee_line_is_refused():
    with pytest.raises(ValueError):
        parse_fee_table([["", "March 31, 2025"], ["Auditor", "12"]])


def test_fee_changes():
    fees = {"FY2024": dict(audit_fee_cr=10, tax_matters_cr=1, other_services_cr=1, reimbursement_cr=0),
            "FY2025": dict(audit_fee_cr=13, tax_matters_cr=1, other_services_cr=1, reimbursement_cr=0)}
    (c,) = fee_changes(fees)
    assert c["fy"] == "FY2025" and c["audit_fee_change_pct"] == 30.0 and c["total_change_pct"] == 25.0
