# Job 3: scheme library, version 1

Purpose: this is the scheme library that Job 3 uses. Job 3 takes the flags a reviewer accepted and asks which known patterns of accounting misstatement or misuse they resemble. Every output is a hypothesis for planning the next step. The tool never says that anything wrong was done and never says who did it.

Status: version 1, in use. The developer wrote it on the forensic lead's instruction, using the public ACFE Fraud Tree structure and public ICAI FAIS titles. The lead can change any scheme. Every match still needs the lead's review, and a match that names an individual also needs a partner's review.

References: each scheme cites the named branch of the ACFE Fraud Tree and the ICAI FAIS standard titles. Page and paragraph numbers are not given; the reviewer adds them when verifying, and accepting a match asks the lead to confirm the references were checked.

How a match is scored: coverage = indicators present / indicators in the scheme. A scheme is ranked only when at least 3 indicators are present, so one strong signal never makes a match. Only flags a reviewer accepted count, and flags labelled not material do not. Missing indicators are listed, facts that cut against the scheme are kept, and innocent explanations are shown next to every match.

Public-record indicators (regulator orders, tribunal rulings, exchange announcements, credible news) are added by a person with the source, on the case screen. The tool does not search the web by itself.

## What you can still change

1. Is the list of schemes right? Add, remove or rename any.
2. Is the scoring rule acceptable (at least 3 present indicators, only accepted and material flags)?
3. Keep or drop MKT-01 (price or volume moving before results)? It is outside the public Fraud Tree.
4. Add page or paragraph references for any scheme where you want them cited more exactly.

## Schemes

### FSF-01: Revenue booked that is not earned, or booked too early

*Class (verify): Financial statement fraud > Fictitious revenues; Timing differences*

**Pattern:** Revenue is recorded before it is earned, or not earned at all; the cash does not follow, so receivables and accruals build up.

| Indicator | Counts as present when |
|---|---|
| Receivables grow much faster than revenue | J1-03 |
| Profit is not backed by operating cash flow | J1-01 |
| High accruals relative to assets (Sloan) | J1-02 |
| Beneish parts for receivables days and sales growth are high | J1-06 |
| Revenue recognition is a key audit matter or an emphasis-of-matter paragraph | J1-10 |
| The year-end quarter carries a disproportionate share of revenue | public-record item |
| Restatement of previously reported revenue or receivables | J1-09 |

*Indicators our current checks can supply: 6 of 7 (a match needs 3). *

**Facts that would cut against it:** Receivable days stable or falling while revenue grows; Operating cash flow close to or above profit for several years

**Common innocent explanations:** Longer credit terms agreed with large customers, or a change in the customer mix; Percentage-of-completion contracts, where billing and revenue timing differ by design; Seasonality that is stable year after year

**Evidence that would confirm or refute it:**
- Customer-level ageing and confirmations (NOT public: needs access to the company)
- Contract terms and revenue recognition notes (public)
- Cash collected after the year end (NOT public: needs access to the company)

**References:** ACFE Fraud Tree and Report to the Nations (Financial statement fraud: fictitious revenues; timing differences; scheme definitions and statistics by branch of the Fraud Tree). ICAI FAIS 120, Understanding Fraud Risk; ICAI FAIS 110, Understanding the Nature of Engagement.

### FSF-02: Assets carried at more than they are worth (receivables, inventory)

*Class (verify): Financial statement fraud > Improper asset valuations*

**Pattern:** Assets are carried at more than they are worth, so expenses and losses are put off.

| Indicator | Counts as present when |
|---|---|
| Inventory grows much faster than revenue | J1-04 |
| Receivables grow much faster than revenue | J1-03 |
| Restated or re-presented balance sheet figures | J1-09 |
| Valuation, impairment or provisioning is a key audit matter | J1-10 |
| Change in an accounting estimate (provisioning, useful life, impairment) | J1-15 |
| Adverse or qualified answers on records in the audit report annexure | J1-11 |

*Indicators our current checks can supply: 6 of 6 (a match needs 3). *

**Facts that would cut against it:** Inventory is small relative to revenue (the flag is then not material); Provisions and write-offs rise in line with the balances

**Common innocent explanations:** Stock build ahead of a launch, a new plant or a supply risk; A change in business model, for example from services to products

**Evidence that would confirm or refute it:**
- Stock counts, ageing and write-off policy (NOT public: needs access to the company)
- Impairment and provisioning notes (public)

**References:** ACFE Fraud Tree and Report to the Nations (Financial statement fraud: improper asset valuations; scheme definitions and statistics by branch of the Fraud Tree). ICAI FAIS 120, Understanding Fraud Risk; ICAI FAIS 110, Understanding the Nature of Engagement.

### FSF-03: Costs booked as assets, or liabilities left out

*Class (verify): Financial statement fraud > Concealed liabilities and expenses; Timing differences*

**Pattern:** Running costs are booked as assets, or liabilities are left out, so profit looks higher.

| Indicator | Counts as present when |
|---|---|
| Non-current assets grow much faster than total expenses | J1-08 |
| High asset-quality or depreciation index (Beneish AQI, DEPI) | J1-06 |
| High accruals relative to assets | J1-02 |
| Change in accounting policy or estimate that raises profit | J1-15 |
| Unusually large other income lifting profit | J1-07 |
| Contingent liabilities or guarantees growing without explanation | public-record item |

*Indicators our current checks can supply: 5 of 6 (a match needs 3). *

**Facts that would cut against it:** Growth in assets is explained by an acquisition or by investments disclosed in the notes; Capital work in progress is capitalised and then depreciated on schedule

**Common innocent explanations:** Genuine capital expenditure or an acquisition; Growth in treasury investments, which also lifts non-current assets

**Evidence that would confirm or refute it:**
- Fixed-asset and intangible additions by type (public)
- Ledger entries behind capitalised items (NOT public: needs access to the company)

**References:** ACFE Fraud Tree and Report to the Nations (Financial statement fraud: concealed liabilities and expenses; timing differences; scheme definitions and statistics by branch of the Fraud Tree). ICAI FAIS 120, Understanding Fraud Risk; ICAI FAIS 110, Understanding the Nature of Engagement.

### FSF-04: Missing or poor disclosures

*Class (verify): Financial statement fraud > Improper disclosures*

**Pattern:** Related-party dealings, contingencies, auditor concerns or accounting changes are not disclosed, or are disclosed without the facts needed to judge them.

| Indicator | Counts as present when |
|---|---|
| Related-party items disclosed without pricing, terms or basis | J1-14 |
| Adverse answers in the audit report annexure (loans, statutory dues, related parties) | J1-11 |
| Qualified opinion, emphasis of matter or going-concern uncertainty | J1-10 |
| Auditor change | J1-12 |
| Late filing of results | J1-13 |
| Jump in auditor fees | J2-03 |
| Auditor resignation, or a company announcement about a disagreement | public-record item |

*Indicators our current checks can supply: 6 of 7 (a match needs 3). *

**Facts that would cut against it:** Unmodified opinion with no emphasis of matter; on-time filings; scheduled auditor rotation

**Common innocent explanations:** Terms are not stated because the dealings are on standard group terms or are eliminated on consolidation; A scheduled auditor rotation required by law

**Evidence that would confirm or refute it:**
- Related-party agreements and approval records (NOT public: needs access to the company)
- Exchange announcements on auditor appointment, resignation and reasons (public)

**References:** ACFE Fraud Tree and Report to the Nations (Financial statement fraud: improper disclosures; scheme definitions and statistics by branch of the Fraud Tree). ICAI FAIS 120, Understanding Fraud Risk; ICAI FAIS 110, Understanding the Nature of Engagement.

### FSF-05: Earnings smoothing and window dressing through one-offs

*Class (verify): Financial statement fraud > Timing differences (net income overstatement)*

**Pattern:** Gains, reversals or other income are timed to hold reported profit steady or to meet a target.

| Indicator | Counts as present when |
|---|---|
| Other income is a large or jumping share of profit before tax | J1-07 |
| Profit is not backed by operating cash flow | J1-01 |
| Change in accounting policy or estimate that moves profit | J1-15 |
| Receivables rising while profit meets targets | J1-03 |

*Indicators our current checks can supply: 4 of 4 (a match needs 3). *

**Facts that would cut against it:** Other income is steady and mostly interest on cash balances

**Common innocent explanations:** Treasury income that follows the size of cash and investment balances

**Evidence that would confirm or refute it:**
- Components of other income (public)

**References:** ACFE Fraud Tree and Report to the Nations (Financial statement fraud: timing differences; net income overstatement; scheme definitions and statistics by branch of the Fraud Tree). ICAI FAIS 120, Understanding Fraud Risk; ICAI FAIS 110, Understanding the Nature of Engagement.

### AM-01: Company funds moved to promoter-linked parties

*Class (verify): Asset misappropriation > Fraudulent disbursements (misuse of company funds)*

**Pattern:** Cash leaves the company to related entities through loans, deposits or guarantees, while promoters raise money against their own shares.

| Indicator | Counts as present when |
|---|---|
| Loans, deposits or guarantees to related parties, without stated terms | J1-14 |
| Promoter shares pledged at a high level | J2-04 |
| Promoter holding stepping down quickly | J2-01 |
| Adverse answer in the audit report annexure on loans or related-party compliance | J1-11 |
| Cash balances that do not fit the interest income earned | public-record item |
| Enforcement or tribunal orders about the company or its promoters | public-record item |

*Indicators our current checks can supply: 4 of 6 (a match needs 3). *

**Facts that would cut against it:** No pledging; promoter holding steady; related-party items small relative to revenue and on disclosed terms

**Common innocent explanations:** Intra-group treasury deposits on arm's-length terms, approved by the audit committee

**Evidence that would confirm or refute it:**
- Approval records, interest charged and repayment history (NOT public: needs access to the company)
- Exchange disclosures of pledge invocation and of related-party transactions (public)

**References:** ACFE Fraud Tree and Report to the Nations (Asset misappropriation: fraudulent disbursements; scheme definitions and statistics by branch of the Fraud Tree). ICAI FAIS 120, Understanding Fraud Risk; ICAI FAIS 110, Understanding the Nature of Engagement.

### COR-01: Undisclosed conflict of interest in related-party dealings

*Class (verify): Corruption > Conflicts of interest*

**Pattern:** Insiders benefit from deals with entities they own or influence, and the link is not made clear.

| Indicator | Counts as present when |
|---|---|
| Related-party items without stated terms | J1-14 |
| Group structure with many related entities relative to the business | public-record item |
| Adverse answers in the audit report annexure on related parties | J1-11 |
| Enforcement or media record naming the company, its promoters or its auditor | public-record item |

*Indicators our current checks can supply: 2 of 4 (a match needs 3). Cannot be matched until a public-record input (enforcement orders, news, exchange announcements) is added.*

**Facts that would cut against it:** Related-party dealings are limited to wholly owned subsidiaries and eliminated on consolidation

**Common innocent explanations:** A large group where shared services are charged between companies

**Evidence that would confirm or refute it:**
- Related-party register and board approvals (NOT public: needs access to the company)
- Public enforcement and tribunal records (public)

**References:** ACFE Fraud Tree and Report to the Nations (Corruption: conflicts of interest; scheme definitions and statistics by branch of the Fraud Tree). ICAI FAIS 120, Understanding Fraud Risk; ICAI FAIS 110, Understanding the Nature of Engagement.

### MKT-01: Price or volume moving before results

*Class (verify): Outside the Fraud Tree (securities-market pattern)*

**Pattern:** Price or volume moves before results are published, in a way the usual pattern does not explain.

| Indicator | Counts as present when |
|---|---|
| Unusually large run-up before the results day | J2-02 |
| Unusually large price reaction against other results days | J2-02 |
| Unusual volume on the reaction day | J2-02 |
| Insider trade disclosures near the results | public-record item |

*Indicators our current checks can supply: 3 of 4 (a match needs 3). *

**Facts that would cut against it:** Reaction and volume inside the range of the other results days

**Common innocent explanations:** Sector news, index rebalancing or a peer's results published just before

**Evidence that would confirm or refute it:**
- Insider trading disclosures filed under SEBI rules (public)
- Order and trade records of specific accounts (NOT public: needs access to the company)

**References:** ACFE Fraud Tree and Report to the Nations (not a Fraud Tree branch; included as a market pattern for the reviewer to keep or drop). ICAI FAIS 120, Understanding Fraud Risk.

## How it would score on the saved TCS screens (illustration only, not a finding)

- Flags counted from runs 18, 17: J1-03, J1-11, J1-14.
- J1-03 FY2025 (consolidated) is labelled not material, so it does not count
- J1-04 FY2023 (consolidated) is labelled not material, so it does not count
- J1-04 FY2023 (standalone) is labelled not material, so it does not count
- J1-04 FY2026 (consolidated) is labelled not material, so it does not count
- J1-04 FY2026 (standalone) is labelled not material, so it does not count

| Scheme | Indicators present | Ranked? |
|---|---|---|
| FSF-01 Revenue booked that is not earned, or booked too early | 1 of 7 | no (fewer than 3) |
| FSF-02 Assets carried at more than they are worth (receivables, inventory) | 2 of 6 | no (fewer than 3) |
| FSF-03 Costs booked as assets, or liabilities left out | 0 of 6 | no (fewer than 3) |
| FSF-04 Missing or poor disclosures | 2 of 7 | no (fewer than 3) |
| FSF-05 Earnings smoothing and window dressing through one-offs | 1 of 4 | no (fewer than 3) |
| AM-01 Company funds moved to promoter-linked parties | 2 of 6 | no (fewer than 3) |
| COR-01 Undisclosed conflict of interest in related-party dealings | 2 of 4 | no (fewer than 3) |
| MKT-01 Price or volume moving before results | 0 of 4 | no (fewer than 3) |
