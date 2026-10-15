"""Draft wording for memo sections 4 (open questions) and 5 (next steps), one entry per check.

APPROVED 2026-10-14: the forensic lead reviewed an exported memo (memo-1.docx) built on this wording and asked the developer to finish the job.
Set LIBRARY_APPROVED = False to bring the "not approved" line back on every memo.
Rules the wording follows: describe, never conclude; a question asks, it does not suggest a cause; each question says whether
public data can close it ("yes", "partly" or "no") and how; people appear only as roles.
"""
from __future__ import annotations

LIBRARY_APPROVED = True

NAMES = {
    "J1-01": "Profit versus cash", "J1-02": "Accruals build-up", "J1-03": "Receivables versus revenue",
    "J1-04": "Inventory versus revenue", "J1-05": "Capacity mismatch", "J1-06": "Beneish parts",
    "J1-07": "Unusual other income", "J1-09": "Restatement", "J1-10": "Auditor's opinion", "J1-11": "Adverse CARO clauses",
    "J1-12": "Auditor change", "J1-14": "Related-party gaps", "J1-15": "Policy and estimate changes",
    "J1-16": "Financial stress (Altman Z'')", "J1-17": "Digit pattern (Benford's Law)",
    "J1-13": "Delayed filings", "J2-01": "Shareholding step change", "J2-02": "Price and volume around results", "J2-03": "Auditor-fee jump", "J2-04": "Promoter pledging", "J2-05": "Year-on-year ratio break", "J2-06": "Related-party concentration", "J2-07": "Tax rate against peers", "J1-08": "Cost capitalisation",
}

# (question, can public data close it?, how / what would be needed)
Q = {
    "J1-01": [("What explains the difference between reported profit and cash flow from operations in the flagged years?", "partly",
               "The cash flow statement and notes show which items moved; the reasons behind them are not in public data.")],
    "J1-02": [("Which balance sheet items carry the profit that was not matched by cash?", "partly",
               "Year-on-year movements in receivables, inventory and payables are public; the business reasons are not.")],
    "J1-03": [("Which customers or contracts make up the increase in receivables?", "no",
               "Customer-level balances are not public; segment or ageing disclosures may give partial context."),
              ("Is there a change in credit terms or billing timing in the period?", "partly",
               "The notes and management commentary may mention it; the contract terms are not public.")],
    "J1-04": [("What makes up the change in inventory, and is the balance small enough to be ordinary for this business?", "partly",
               "The inventory note gives the split; the reasons are not public.")],
    "J1-05": [("How do the changes in fixed assets relate to the change in revenue?", "partly",
               "The fixed asset note and capital commitments are public; capacity data is not.")],
    "J1-06": [("Which of the Beneish parts moved most, and do the underlying line items have an ordinary explanation?", "partly",
               "Each part is built from public line items; the reasons are not public.")],
    "J1-07": [("What does other income consist of, and is it recurring?", "yes",
               "The other income note lists its components and the prior-year comparatives.")],
    "J1-09": [("Why does the same figure differ between saved versions of the filing?", "partly",
               "A restatement or re-presentation note may explain it; otherwise the company would have to.")],
    "J1-10": [("What led to the auditor's wording, and how did the company respond?", "partly",
               "The report and the notes referred to in it are public; discussions with the auditor are not.")],
    "J1-11": [("What is the background to the unfavourable or qualified answers in the audit report annexure?", "partly",
               "The annexure text and related notes are public; the underlying facts may not be.")],
    "J1-12": [("Why did the auditor change, and was a resignation or a scheduled rotation involved?", "yes",
               "Exchange filings on auditor appointment, resignation and AGM notices state it.")],
    "J1-13": [("Why was the result filed after the due date, and did the company or the exchange say so?", "yes",
               "Exchange announcements and the company's own notices usually state a reason for a late filing.")],
    "J2-01": [("What caused the change in the promoter group's holding (sale, transfer, buyback, allotment or a change in the share count)?", "yes",
               "Exchange disclosures of promoter transactions and the shareholding filings themselves usually show it.")],
    "J1-14": [("What are the pricing, terms and basis of the related-party items that do not state them?", "no",
               "Terms that the notes do not give are not public; the company or the auditor would have to supply them."),
              ("Were the related-party items approved through the required committee and shareholder process?", "partly",
               "Exchange disclosures and AGM notices may show approvals; the detail of the process is not public.")],
    "J1-15": [("What prompted the change in accounting policy or estimate, and what was its effect on profit?", "partly",
               "The notes usually give the effect; the reason may be only partly stated.")],
    "J1-16": [("What lies behind the movement in the stress score: the balance sheet, profit or leverage?", "partly",
               "The inputs are public line items; reasons are not.")],
    "J1-17": [("Is the digit pattern explained by the kind of numbers in the statements (for example fixed-range figures)?", "yes",
               "The statements and notes are public; a weak, low-confidence signal at best.")],
}

# (steps possible on public data, what a formal engagement with data access would need)
S = {
    "J1-01": (["Read the cash flow statement and the notes on working capital changes for the flagged years."],
              ["Ledger and bank data to trace the items behind the gap."]),
    "J1-02": (["Compare the movement in each accrual-related balance sheet item year on year."],
              ["Journal entry data for the accrual items."]),
    "J1-03": (["Read the receivables note, including ageing and any segment disclosure.", "Compare with listed peers once a peer set is approved."],
              ["Customer-level ageing, contracts and subsequent receipts."]),
    "J1-04": (["Read the inventory note for the split and the basis of valuation."],
              ["Stock records and count results."]),
    "J1-05": (["Read the fixed asset and capital commitments notes."],
              ["Capacity and capital project records."]),
    "J1-06": (["Read the line items behind each part in the filing."], ["Detailed ledgers for the items behind the parts."]),
    "J1-07": (["Read the other income note and compare components across years."], ["Ledger detail for the components."]),
    "J1-09": (["Compare the two versions of the filing and read any restatement note."], ["Prior-period working papers."]),
    "J1-10": (["Read the full audit report and the notes it refers to."], ["Auditor correspondence and working papers."]),
    "J1-11": (["Read the annexure and the related notes."], ["Records supporting the annexure answers."]),
    "J1-12": (["Check exchange filings and AGM notices on the auditor appointment or resignation."], ["Auditor correspondence."]),
    "J1-13": (["Check the exchange announcements around the due date for a stated reason."], ["Management's explanation of the delay."]),
    "J2-01": (["Read the two shareholding filings and the exchange disclosures of promoter transactions."], ["Records of the transactions behind the change."]),
    "J1-14": (["Read the related-party note and the exchange disclosures on related-party transactions."],
              ["Agreements, approvals and pricing records for the related-party items."]),
    "J1-15": (["Read the accounting policies note and the note on the change."], ["Management's basis for the change."]),
    "J1-16": (["Read the balance sheet and profit and loss statement behind the score."], ["Management accounts and debt documents."]),
    "J1-17": (["Treat as a low-confidence signal; read the largest statement items instead."], ["Transaction-level data."]),
}

GENERAL_QUESTIONS = [("Which of these findings reflect ordinary business activity?", "no",
                      "Public data cannot show the reason for a figure; this would need access to the company.")]
GENERAL_ENGAGEMENT = ["Access to management and records under a formal engagement, to resolve the open questions that public data cannot answer."]


def questions_for(check_ids: list[str]) -> list[dict]:
    seen, out = set(), []
    for cid in sorted(set(check_ids)):
        for text, public, how in Q.get(cid, []):
            if text not in seen:
                seen.add(text)
                out.append({"text": text, "public_data": public, "how": how, "check_id": cid})
    for text, public, how in GENERAL_QUESTIONS:
        out.append({"text": text, "public_data": public, "how": how, "check_id": None})
    return out


def steps_for(check_ids: list[str]) -> dict:
    pub, eng = [], list(GENERAL_ENGAGEMENT)
    for cid in sorted(set(check_ids)):
        a, b = S.get(cid, ([], []))
        pub += [x for x in a if x not in pub]
        eng += [x for x in b if x not in eng]
    return {"public": pub, "engagement": eng}
