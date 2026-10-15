# Decisions needed from the forensic lead

CREST Forensic Review: development build, TCS only. Until these are decided every result in the app is stamped DRAFT.
Nothing here asks for a finding about any company: these are the rules the tool applies when it flags a lead for a human to look at.

## 1. Approve the limits (the biggest blocker)

UPDATE 2026-10-09: the forensic lead (lead1) confirmed all 42 proposals unchanged and approved the limits (config version 3). The TCS screen was re-run under the approved limits (runs 13 and 14, same 12 flags). Section 1 is therefore settled, except the settings that still need a number or rule from the lead: J1-05, the J1-07 jump limit, the Beneish combined score and the gross margin rule. Sections 1A, 1B and 2 to 5 are still open. UPDATE 2026-10-14: J1-13 (delayed filings) was built and its four limits were added to the live limits as version 4. This cleared the approval of version 3, so the limits need to be confirmed and approved again.

The Limits page holds 48 settings. Today: **42 are developer proposals not yet confirmed, 4 have no number at all, and the rest come from the job specs.** Approval is refused while any proposal stays unconfirmed. On the Limits page, as forensic lead, you can edit a value, confirm it, and then approve the whole set.

What the current proposals do to TCS (for scale): 12 flags in total, 5 high and 7 medium, driven mostly by receivables and inventory growth against revenue (J1-03, J1-04) and by text findings (J1-11, J1-14).

| Check | What it looks at | Current proposal | Please decide |
|---|---|---|---|
| J1-01 Profit vs cash | gap between profit and operating cash flow | high at 40%, medium at 20% (20% is from the specs) | confirm or change |
| J1-02 Accruals (Sloan) | profit not backed by cash, as a share of average assets | high above 15%, medium above 10% | confirm or change |
| J1-03 Receivables vs revenue | receivables growing faster than revenue | high at 2.0x, medium at 1.5x; if revenue did not grow, medium | confirm or change |
| J1-04 Inventory vs revenue | same, for inventory | high at 2.0x, medium at 1.5x | confirm or change |
| J1-05 Capacity mismatch | | **no numbers yet** | supply thresholds |
| J1-07 Other income | unusual other income | high at 50%, medium at 25%; **year-on-year jump threshold has no number** | confirm, supply the jump threshold |
| J1-09 Restatement | any difference between sources | medium | confirm |
| J1-10 Auditor's opinion | qualified, adverse, disclaimer, going-concern uncertainty = high; emphasis of matter = medium | proposals | confirm |
| J1-11 CARO clauses | an adverse or qualified answer = medium | proposal | confirm |
| J1-12 Auditor change | auditor changed = high | proposal (a change alone is often ordinary) | confirm or lower |
| J1-13 Delayed filings | quarterly result due 45 days after quarter end (60 after 31 March); any day late = medium, more than 30 days late = high | proposal (due dates from memory, not yet checked against SEBI LODR; TCS filed every quarter 33 to 51 days early) | confirm or change |
| J1-14 Related-party gaps | terms not stated = medium | proposal | confirm |
| J1-15 Policy and estimate changes | change in policy or estimate = medium | proposal | confirm |
| J1-16 Financial stress (Altman Z'') | safe above 5.85, stress below 4.15; "below" = high | proposal (TCS scores 11.85, far above) | confirm |
| J1-17 Benford's Law | needs at least 1,000 numbers; close < 0.006, acceptable < 0.012, marginal < 0.015; "nonconforming" = low | proposal | confirm |
| Materiality | a flag is "material" if it is at least 1% | proposal, used by most checks | confirm |

J1-13 (delayed filings) is now built, using the exchange received time of each result; see section 1B and the table above. Not built, so no limits yet: J1-08 (cost capitalisation: no formula). It is drafted as options in section 1A below, for you to choose from or replace.

## 1A. J1-08 Cost capitalisation: please define it

The plan says only "rise in assets share versus expenses". The idea behind it: a company that books a running cost as an asset (capitalises it) makes profit look higher now, and the asset sits on the balance sheet instead of the expense hitting the profit and loss account. Below are options, all drafts. Nothing runs until you pick one and confirm the numbers, and every result stays a lead to look at, not a finding.

| Option | Formula | Needs data we do not hold yet? | Notes |
|---|---|---|---|
| **A. Asset share rise** | "Soft assets" = total assets minus current assets minus property, plant and equipment. Share = soft assets / total assets. Flag the year-on-year rise in that share. | No: all three figures are already saved | The same idea as the Beneish AQI part that the matrix already shows, so A would largely repeat it. Cheap, but weak: a purchase of another company or goodwill also raises it. |
| **B. Assets versus expenses growth** (the plan's wording) | Growth in (property, plant and equipment + soft assets) divided by growth in total expenses. Flag when assets grow much faster than expenses. | No: total expenses is already saved | Follows the plan's sentence most closely. Same style as J1-03 and J1-04 (a growth ratio), so the Limits page and flag text can reuse the pattern. |
| **C. Spending on assets versus depreciation** | Purchase of fixed assets (from the cash flow statement) divided by depreciation, and the same for intangible additions and capital work in progress. Flag when it rises sharply while operating expenses fall as a share of revenue. | **Yes**: purchases of fixed assets, intangible additions and capital work in progress are not extracted today | Closest to what the check is meant to catch, but needs new lines read from the statements and notes of every report. |

**My suggestion (the decision is yours):** start with B, because it needs no new data and matches the plan's wording; add C later once more lines are extracted. Treat A as already covered by the Beneish AQI part.

If B: please decide
- the limits. Proposal, same as J1-03 and J1-04: high at 2.0x, medium at 1.5x. (unconfirmed proposal)
- the materiality rule. Proposal: the increase in assets is at least 1% of revenue. (unconfirmed proposal)
- the treatment when expenses did not grow (ratio undefined). Proposal: medium if assets grew, as in J1-03.
- how to treat acquisitions, which raise assets for a good reason. Options: ignore, or show a note when goodwill or an acquisition is mentioned in the filing.

## 1B. J1-13 Delayed filings: built, please confirm the due dates

UPDATE 2026-10-14: a source now exists, and the check is built. The exchange's own received time for each quarterly result (NSE files downloaded by hand: option 2 below, as spreadsheets instead of PDFs) is saved for TCS from Dec 2021 to Sep 2026, standalone and consolidated. On it, every one of the 20 quarters was filed 33 to 51 days before the proposed due date, so no flag is raised. The check uses four proposed values (45 days for quarters, 60 days for the year end, high above 30 days late, medium for any day late), now in the live limits as version 4. What is left for you: confirm the due dates against the current SEBI LODR text, confirm or change the 30 days, and approve again. Not covered: the annual report and the AGM date. A late quarter is a lead for a person to look at, never a conclusion.

The check compares the date a company filed with the exchange against the date it was due. We hold no filing dates today (the annual report PDF gives the date the board approved the accounts and the auditor signed, not the date it reached the exchange).

Due dates (from the SEBI listing rules; **please have these confirmed against the current rule text, I have not checked them against the filings**): quarterly results within 45 days of quarter end, annual audited results within 60 days of year end, shareholding pattern within 21 days of quarter end, annual report to the exchange by the time it goes to shareholders, with the AGM within 6 months of year end.

| Source option | What it gives | Concerns |
|---|---|---|
| **1. Exchange announcement pages** (BSE corporate announcements, NSE corporate filings) | the filing date and time of each result, shareholding pattern and annual report | NSE blocks bots (as tcs.com does). BSE has an unofficial public feed, which may break or breach the site terms. Needs your OK on terms of use. |
| **2. The PDFs themselves, saved by us** | the exchange's received stamp on the first page of a result filing | Manual download and reading; slow but accurate, and fits how the annual reports are handled today. |
| **3. A paid data provider** | structured filing dates | Cost and a licence. The RapidAPI plan in use allows no exploratory calls, so I could not check whether it carries dates. |
| **4. Date of the auditor's report** (already in the annual report) | only how late the board approved the accounts | Not the filing date, so it cannot say a filing was late. Only a weak substitute. |

Please decide: the due dates (45 and 60 days are proposals from memory), how many days late counts as medium and high (proposal: any day late = medium; more than 30 days = high), and whether the annual report and AGM dates should be added later (they need a source we do not hold).

## 2. Beneish M-score (needed before the combined score can be shown)

The tool shows the eight Beneish parts but **not the combined score**. To show it we need your decision on:
- the eight weights and the cut-off (the original model's, or a version adapted for Indian reporting under Ind AS);
- how to handle **GMI (gross margin index)**: it cannot be worked out for service companies like TCS because there is no cost of goods sold. Options: leave GMI out and rescale, use a proxy, or only show the score for companies that report cost of materials.

## 3. What text may be sent to an AI model (Developer Review 18.1)

Today the agent and the matrix narrative send the model: the matrix numbers, flags, extracted figures, and pages of the filing it reads. Please decide whether page text from filings may be sent to an outside model, and whether the model must be one with a no-training agreement. Development currently uses Gemini's free tier, which is **not** suitable for confidential material.

## 4. Smaller rules

- **Review decisions after a re-run:** built as a default for you to confirm. A decision belongs to one specific flag, so after a re-run new flags start unreviewed. If a new flag is identical to one already reviewed (same figures, evidence and severity), the earlier decision is shown on it, labelled "earlier run", and the reviewer is asked to confirm or change it. A flag whose figures changed in any way is not carried over. Please confirm, or ask for this to be turned off.
- **Hide not-material flags?** Many checks mark a flag "not material". Show them, show them dimmed, or hide by default?
- **Receivables definition:** trade receivables only, or receivables plus other financial assets?
- **Source precedence:** annual report first, then the free finance data, then the paid API; a difference of more than 0.1% is shown as a conflict. Confirm.
- **Separation of duties:** may the same person edit the limits and approve them, or must they be two people?
- **Plain ratios on the matrix page** (revenue growth, margins, effective tax rate, receivable days, inventory days, current ratio, cash conversion): shown for information with no labels, because no limits exist. Please confirm the definitions: year-end balances rather than averages, inventory days measured on revenue because services companies report no cost of goods, and whether you want year-on-year breaks flagged (that needs a limit from you).

## 5. Research memo template (Job 4)

Job Spec 4 asks the tool to draft a research assessment memo that a named person edits and signs. The spec says the lead owns the template. The full proposal is in MEMO_TEMPLATE_PROPOSAL.md; this is the short version. Nothing is built until you approve it.

The memo uses only flags a reviewer has accepted, public-domain sources only, and names appear only as roles. Every page says "DRAFT - for human review" until the owner signs.

- **Sections:** 1 scope and objective; 2 background and trigger; 3 findings summary (each accepted flag with its figures, citation, limit applied, severity, materiality and the reviewer's name, date and reason); 4 open questions and gaps (each marked as closable by public data or not); 5 recommended next steps (what public data allows, and what a formal engagement would need); 6 ownership and sign-off.
- **Annexes:** A method and limits (with the approval state of the limits); B citation list; C change log of versions; D ICAI FAIS and SEBI RIA references.
- **Version 1 uses no AI model:** the memo is filled from saved data with fixed wording and the same wording and citation checks the agent already has. A model could smooth the background paragraph later, if you approve what may be sent (section 3).
- **Versions:** every draft is a new saved version; signing locks it. If a flag decision or the scope changes, the memo is marked out of date and must be redrafted and reviewed again.

Status: a first version is BUILT with the suggested answers as defaults, so you can try it and change them. Case page, Research memos: New memo (owner = a memo-owner or forensic-lead user, who alone signs). Defaults in use: accepted flags only; for a portfolio company the adviser's approval of the escalation is required; no AI model; the wording of open questions and next steps is a DRAFT (memo says so) until you approve it; Annex D stays empty until you supply the ICAI FAIS and SEBI RIA text; only the named owner signs, and signing locks the memo.

Please decide:
- Approve or change the six sections, the header and the annex list.
- For a portfolio company, must the adviser's approval of an escalation exist before a flag may enter a memo? (Suggestion: yes.)
- Version 1 with no AI model? (Suggestion: yes.)
- Please supply the ICAI FAIS section references and the SEBI RIA record-keeping text for Annex D. The tool does not invent them.
- Approve the lists of open questions and next steps for each check. We will draft them for J1-01 to J1-17 for your review.
- Who may own a memo: only the memo-owner role, or also the analyst who ran the case?
- Memo reference format. Suggestion: CREST-<symbol>-<year>-<number>.

## What happens after you decide

Confirming and approving the limits removes the DRAFT stamp from new runs and from the matrix labels. Items that change the numbers (any limit, the Beneish choices) need the screen to be re-run to refresh the saved flags; the matrix labels update on their own, and the AI narrative is marked out of date until someone writes it again.
