# Job Specs checklist: what is built and what is left

Checked against `CREST-Forensic-Analyst-Agent-Job-Specs-India-Listed-Public-Domain` (Jobs 1 to 4) on 2026-10-09.
Legend: `[x]` built · `[~]` partly built · `[ ]` not built. After each open item: what it is waiting for.

Standing boundary (all jobs): the agent flags and cites; a human concludes and signs. It never says "fraud".

---

## Job 1: Statement red-flag screen

**Inputs**
- [x] Annual report: balance sheet, profit and loss, cash flow, notes, auditor's report, CARO annexure (PDF reader, TCS FY2025 and FY2026)
- [x] Prior-year figures kept for trends and restatement checks
- [x] Optional context: the case records the reason for review and the exposure note
- [ ] Exchange filings and corporate announcements. *Needs: a data source decision.*
- [ ] SEBI LODR Regulation 30 material-event announcements. *Needs: a data source.*
- [ ] Quarterly shareholding patterns. *Needs: a data source.*
- [ ] Credit rating reports and rationales. *Needs: a data source.*
- [ ] MCA21 filings (AOC-4, MGT-7, charges, directors) as a cross-check. *Needs: a data source.*
- [ ] Excel input (only PDF is read today)

**Checks**
- [x] J1-01 Profit vs cash
- [x] J1-02 Accruals build-up (Sloan)
- [x] J1-03 Receivables vs revenue
- [x] J1-04 Inventory vs revenue
- [x] J1-05 Capacity mismatch: limits 3.0 / 2.0 set by the lead; the check was fixed to use them (revenue growth over fixed-asset growth).
- [~] J1-06 Beneish: the eight parts are shown, no combined score. *Needs: the lead's weights, cut-off and Ind AS adaptation, and a rule for GMI on service companies.*
- [x] J1-07 Unusual other income (the year-on-year jump limit still has no number)
- [~] J1-08 Cost capitalisation: built 2026-10-14 with the default formula (option B, proposals). *Needs: the lead to confirm it; expect false alarms for companies with large investments.*
- [x] J1-09 Restatement
- [x] J1-10 Auditor's opinion, emphasis of matter, key audit matters
- [x] J1-11 Adverse CARO clauses
- [x] J1-12 Auditor change
- [~] J1-13 Delayed filings: built 2026-10-14 for quarterly results from the exchange received time (NSE files saved by hand, TCS Dec 2021 to Sep 2026: all 20 quarters well inside 45/60 days, no flags). *Needs: the lead to confirm the due-date rule and limits (45 days quarters, 60 days year end, high above 30 days late: all proposals) and to add them to the live limits on the Limits page; annual report and AGM filing dates are not covered.*
- [x] J1-14 Related-party gaps (from the annual report notes only, not the exchange disclosures)
- [x] J1-15 Policy and estimate changes
- [x] Extra, not in the spec: J1-16 Altman Z'' and J1-17 Benford's Law

**Output and rules**
- [x] Each flag has: what was observed, location, technique, severity with its rule, figures
- [x] A flag without a checkable citation is dropped (guardrail)
- [x] Banned wording blocked; the tool describes and never concludes
- [x] Same inputs give the same flags (runs are never edited; Compare runs screen)
- [x] Analyst reviews each flag (accept or reject with a reason)
- [x] Adviser approval before escalating a portfolio company
- [x] Severity rules and limits owned and versioned by the forensic lead (Limits page)
- [x] Dashboard: acceptance rate, false-alarm rate, citation completeness
- [x] The forensic lead approved the limits on 2026-10-09 (42 proposals confirmed unchanged; the TCS screen was re-run, runs 13 and 14). Still open: J1-05 limits, the J1-07 jump limit, Beneish weights and the gross margin rule, which stay empty until the lead supplies them.

---

## Job 2: Quantitative anomaly tests

**Result set 1: ratio and accruals tables**
- [x] Sloan accruals across years
- [x] Margins, receivable days, inventory days, current ratio, cash conversion, tax rate (Ratios table; information only)
- [~] Year-on-year breaks flagged: built as J2-05 with proposed limits (5 points, 30%). *Needs: the lead to confirm the limits.*

**Result set 2: Beneish components**
- [x] Eight parts per year, each tied to its sources
- [ ] Combined M-score (see J1-06)

**Result set 3: divergence tables**
- [x] Profit vs operating cash flow
- [x] Revenue vs receivables
- [~] Tax rate vs peers: built as J2-07 against a 5-company IT-services peer set (Infosys, HCLTech, Wipro, LTM, Tech Mahindra) using Yahoo Finance figures; TCS is within 2 points of the median every year. *Needs: the lead to confirm the limits (5 / 10 points); the peer annual reports are not read yet, only the free finance data.*
- [~] Disclosed vs re-derived figures: source conflicts and the golden check exist for TCS only

**Result set 4: outlier tables**
- [x] Auditor-fee jumps (above 30%): built as J2-03 with the spec's 30% limit in the live limits; TCS FY2022 to FY2026 shows no jump (largest +22% audit fee, +13% total; fees are whole crores so the check shows the rounding range). *Still open: auditor change or resignation is J1-12 (built); consolidated-group fees are not printed in the notes.*
- [~] Related-party concentration: built as J2-06 (related-party revenue and purchases as a share of revenue and expenses, read from the notes) with proposed limits (25% / 50%). *Needs: the lead to confirm the limits.*
- [~] Promoter pledging and shareholding step changes (above 2 percentage points): the step-change check (J2-01) is BUILT (largest TCS step 0.64 points, no flags); the pledging rule is not. Data loaded for TCS, 20 quarters (Sep 2021 to Jun 2026; pledging 0.47% of promoter holding until Dec 2023, then 0.28%, nil since Dec 2024; largest promoter step 0.64 points). *Needs: the checks, the limits (the pledging rule from the lead) and matrix rows (not built yet).*
- [~] Price and volume z-scores around results dates: BUILT as J2-02 for TCS (5 years of yfinance prices, 19 results events, one medium lead). *Needs: the lead to confirm the method and the proposed limits (z above 3 / 4 against the company's other results days), a matrix row, and announcement-date events beyond results.*

**Other Job 2 items**
- [~] 3 to 5 years of data: the matrix supports up to 10 years; only TCS FY2022 to FY2026 is loaded
- [ ] Quarterly results and shareholding data
- [x] Peer-set construction: the lead's 5 peers are stored as the approved peer set (table peer_links)
- [ ] Cross-source consistency against MCA21 and results announcements
- [~] False-positive tracking: the dashboard shows the rate; retuning limits from it is manual

---

## Job 3: Fraud-scheme matching

- [x] Scheme library: 8 schemes mapped to the ACFE Fraud Tree branches, each with indicators (present, missing, contradicting), innocent explanations and evidence to confirm or refute (public or not)
- [x] Ranked matches by coverage of the whole pattern (at least 3 indicators), only from accepted, material flags
- [x] Every match labelled a hypothesis; missing indicators listed; contradicting facts kept
- [x] Lead reviews every match (reason and "references checked" tick); a partner reviews any match that names an individual
- [x] References: ACFE Fraud Tree branch and FAIS standard titles on every scheme (a scheme without both is refused). *Page and paragraph numbers are left for the reviewer.*
- [x] Public-record input: a person adds regulator, tribunal, exchange or news facts with the source; they count as indicators by tag
- [x] Case screen, API, database tables, and Annex E in memos (Word, PDF, page)
- [~] Public enforcement record: entered by hand (the sites block scripts); no automatic search
- [ ] Agent chat tools for matches
- [ ] Reviewer calibration statistics (lead acceptance rate of matches) on the dashboard

---

## Job 4: Research memo drafting

- [x] Six sections: scope, background, findings, open questions, next steps, ownership and sign-off
- [x] Only accepted flags (portfolio company: also adviser-approved)
- [x] Every claim cited; banned wording withheld; no personal names from the tool's own text
- [x] "DRAFT - for human review" on every page until signed
- [x] Version-controlled: every generate or edit is a new version, with a change log
- [x] Out-of-date warning and regenerate when a flag decision changes
- [x] Named owner signs; signing locks the memo; nothing is sent from the tool
- [x] Word and PDF export; a Memos page and a Research memos block on each case
- [~] Annex D (ICAI FAIS and SEBI RIA record-keeping text): empty. *Needs: the lead to supply the text.*
- [~] Open-question and next-step wording per check: draft. *Needs: the lead's approval.*
- [ ] Template approved by the forensic lead. *Needs: the lead (LEAD_DECISIONS section 5).*
- [x] Input from Job 3 typology matches: Annex E lists matches the lead accepted (and the partner, where a named individual is involved)
- [~] Reviewer reasons are copied in as typed: banned words are caught, personal names are not. The owner must read them.

---

## Across all jobs

- [x] Sign-in, roles, access control, sign-in audit log
- [ ] HTTPS and a hosted setup before anyone else uses it. *Needs: where it will run.*
- [ ] Per-case permissions (today every signed-in user can read every case). *Needs: a decision.*
- [ ] Supabase decision (would also replace SQLite)
- [ ] Production reader tested live: the Claude model path is only tested with a fake client. *Needs: an Anthropic key.*
- [~] Text checks: TCS FY2026 done; FY2025 and the Gemini J1-15 cross-check pending. *Needs: Gemini free quota (the model has been overloaded, so retry in the morning).*
- [ ] More than one company: second company, and the Satyam and Coffee Day test cases. *Needs: their annual report PDFs.*
- [ ] Agent tools for running a check or a screen and for shareholding. *Needs: a design decision (the agent is read-only on purpose).*
- [ ] Maharlika font file for the wordmark. *Needs: the file.*
- [ ] Reviewer trial on a test group. *Needs: people and Gemini quota.*

---

## Where to look next

1. ~~The lead approves the limits~~ done 2026-10-09. Next: the lead's remaining decisions (J1-05, J1-07 jump, Beneish, J1-08, J1-13, memo template).
2. Pick the data sources (exchange filings, shareholding and pledging, filing dates, auditor fees, prices): this unlocks J1-13, most of Job 1's missing inputs, and most of Job 2.
3. Obtain the licensed ACFE and FAIS texts before starting Job 3.

Keep this file in step with `HANDOFF.md` and `LEAD_DECISIONS.docx`.
