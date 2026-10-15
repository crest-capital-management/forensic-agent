# Limits review sheet for the forensic lead

Purpose: to help you confirm or change the limits the checks use, so the DRAFT stamp can come off. Written 2026-10-09 from the live configuration (version 1) and the saved TCS screen (runs 8 and 12, FY2025 and FY2026).

UPDATE 2026-10-14: J1-13 (delayed filings) was added to the live limits as version 4. That cleared the approval of version 3, so the steps below need to be done again for the four J1-13 values (and any others you change).

Nothing here is a finding about TCS. A limit only decides when the tool points at something for a person to look at.
Where a limit came from: SPEC = stated in the CREST job specs. PROPOSAL = the developer's suggestion, not yet approved by you. NEEDS YOU = the plan gives no number, so the check shows its metric but never raises a flag.

## How to approve (7 steps)

1. Sign in to the app as the forensic lead (lead1) and open Limits in the menu.
2. Read the table below. Mark any limit you want to change.
3. On the Limits page, type a reason in the box (required for every change, confirmation and approval).
4. Change the values you disagree with, and press Save changes.
5. Press Confirm all proposals as they stand to accept the rest. (Settings with no number and marked NEEDS YOU may stay empty.)
6. Press Approve this version. The app refuses to approve while any proposal is still unconfirmed.
7. Tell the developer. The saved screen must be re-run so that its flags carry the approved stamp (no Gemini needed).

## Look at these first

- **J1-03 receivables vs revenue: a borderline case.** The standalone FY2025 ratio is 2.0036, just above the proposed high limit of 2.0. A limit of 2.5 would drop that flag from high to medium. FY2026 (3.55 standalone, 3.20 consolidated) is high either way.
- **J1-04 inventory vs revenue: high severity on tiny amounts.** TCS inventories are about 20 to 29 crore against revenue of about 2.1 lakh crore, so a 38% to 45% rise gives a ratio of 8 to 16 and a high flag, but it is marked not material. Decide whether not-material flags should be shown, dimmed or hidden (LEAD_DECISIONS section 4), and whether a flag this small should be capped below high.
- **Materiality threshold (1% of revenue) is a proposal used by most checks.** It decides which flags are called material. Please confirm the 1%.
- **J1-12 auditor change = high.** A change of auditor alone is often ordinary (rotation rules). The proposal gives it high severity; consider medium or low. TCS had no change in FY2025 or FY2026.
- **Three settings need a number or a rule from you.** J1-05 high and medium limits; the J1-07 year-on-year jump limit; and the Beneish combined score (weights, cut-off, and how to treat GMI for service companies).

## Every check

| Check | What it asks | Current limits | Source | TCS scores | Flags it makes | Your decision |
|---|---|---|---|---|---|---|
| **J1-01** Profit vs cash | How far reported profit differs from cash from operations, as a share of profit. | High above 40%. Medium above 20%. | Medium 20% is SPEC. High 40% is PROPOSAL. | Standalone 15.1% (FY2025), 7.1% (FY2026). Consolidated 0.2%, 5.3%. | No flags. | Confirm the 40%. |
| **J1-02** Accruals build-up | Profit not backed by cash, as a share of average total assets. | High above 15%. Medium above 10%. | PROPOSAL. | Standalone 5.7%, 2.5%. Consolidated -0.1%, -1.5%. | No flags. | Confirm or change both. |
| **J1-03** Receivables vs revenue | Receivables growth divided by revenue growth. Above 1 means customers owe a growing share. | High at 2.0 times. Medium at 1.5 times. If revenue did not grow, medium. | PROPOSAL. | Standalone 2.00 and 3.55. Consolidated 1.70 and 3.20. | 4 flags: 3 high, 1 medium (consolidated FY2025 is the medium one). | Confirm or change. See the borderline note above. |
| **J1-04** Inventory vs revenue | Inventory growth divided by revenue growth. | High at 2.0 times. Medium at 1.5 times. If revenue did not grow, medium. | PROPOSAL. | Standalone -4.20 and 15.89. Consolidated -4.17 and 8.32. | 2 flags, both high and marked not material. | Confirm or change. See the note above. |
| **J1-05** Capacity mismatch | Revenue growth divided by fixed-asset growth. | No numbers yet. | NEEDS YOU. | Standalone 0.02 and -0.37. Consolidated 2.85 and 0.11 (metric only). | Never raises a flag until you set limits. | Supply high and medium limits, or leave it metric-only. |
| **J1-06** Beneish components | Eight directional indicators of earnings pressure, shown one by one. | No limits. The combined M-score is not shown. | NEEDS YOU. | Parts shown for FY2025 and FY2026. GMI cannot be worked out for TCS (no cost of goods). | No flags. | Decide the weights, cut-off, Ind AS adaptation and the GMI rule. |
| **J1-07** Unusual other income | Other income as a share of profit before tax. | High above 50%. Medium above 25%. The year-on-year jump limit has no number. | PROPOSAL, and the jump is NEEDS YOU. | Standalone 15.4% and 16.0%. Consolidated 6.1% and 6.7%. | No flags. | Confirm, and supply the jump limit. |
| **J1-08** Cost capitalisation | Not built: the plan gives no formula. | None. | NEEDS YOU. | Not run. | Not run. | Pick a formula (LEAD_DECISIONS section 1A). |
| **J1-09** Restatement | Any difference between two saved versions of the same figure. | Any difference is medium. | PROPOSAL. | No differences found. | No flags. | Confirm medium. |
| **J1-10** Auditor's opinion | The model points at passages in the auditor's report; code verifies the quotes. | Qualified, adverse, disclaimer or going-concern uncertainty: high. Emphasis of matter: medium. Unmodified opinion and key audit matters: shown, no flag. | PROPOSAL. | Passages found, none with a severity. | No flags. | Confirm each severity. |
| **J1-11** Adverse CARO clauses | An unfavourable or qualified answer in the CARO annexure. | Medium. | PROPOSAL. | 3 passages: 2 standalone, 1 consolidated. | 3 medium flags. | Confirm medium. |
| **J1-12** Auditor change | Whether the auditor's firm registration number changed between years. | Changed: high. Unchanged: no flag. | PROPOSAL. | Unchanged in FY2025 and FY2026. | No flags. | Confirm, or lower to medium. |
| **J1-13** Delayed filings | When each quarterly result reached the exchange, against a due date. A late result is a lead, not a conclusion. | Due 45 days after the quarter end, 60 days after 31 March. Late by any day: medium. Late by more than 30 days: high. | PROPOSAL (4 values). Due dates not yet checked against SEBI LODR. | All 20 quarters, Dec 2021 to Sep 2026, both bases: filed 33 to 51 days before the due date. | No flags. | Confirm or change the due days and the 30 days; check the due dates against the current SEBI LODR text. |
| **J1-14** Related-party gaps | Related-party items that state no pricing, terms or basis. | Medium. | PROPOSAL. | 3 passages found. | 3 medium flags. | Confirm medium. |
| **J1-15** Policy and estimate changes | A stated change of accounting policy or estimate. | Policy change: medium. Estimate change: medium. Adoption of a new standard: shown, no flag. | PROPOSAL. | 1 passage found, no severity. | No flags. | Confirm. |
| **J1-16** Financial stress (Altman Z'') | A published stress score for emerging-market companies. Higher is healthier. | Safe above 5.85. Stress below 4.15. Below 4.15: high; in between: shown only. | PROPOSAL. | Consolidated 12.41 and 11.85 (far above 5.85). | No flags. | Confirm. Not meant for banks or insurers. |
| **J1-17** Digit pattern (Benford's Law) | Whether the leading digits of the statement figures follow the usual pattern. A weak signal. | At least 1,000 numbers. Close below 0.006, acceptable below 0.012, marginal below 0.015; nonconforming: low. | PROPOSAL. | 0.0113 (FY2025) and 0.0097 (FY2026): acceptable. | No flags. | Confirm. |
| **All** Materiality | A flag is called material if the amount is at least 1% of revenue. | 1% of revenue. | PROPOSAL. | Marks J1-04 as not material. | Affects which flags are called material. | Confirm the 1%. |

After you approve: the DRAFT stamp is removed from new runs and from the matrix labels. The saved TCS flags keep the DRAFT stamp until the screen is re-run, and the AI narrative is marked out of date until someone writes it again. A changed limit may add or remove flags.
