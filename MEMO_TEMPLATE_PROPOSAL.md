# Proposed template: research assessment memo (Job 4)

Status: **proposal for the forensic lead to approve or change.** Nothing is built yet. Written 2026-10-08 from Job Spec 4 of 4. The lead owns the template (spec: "memo templates owned by the forensic lead"); everything below is a draft.

The memo is a **draft for a named human** to edit and sign. The tool never finalises it, never sends it, and never says anything occurred. It uses only flags a reviewer has **accepted** and only public-domain sources.

## 1. What goes in, what is left out

| In | Out |
|---|---|
| Flags with the decision **accepted** (with the reviewer's name, date and reason) | Flags that are unreviewed, rejected or only escalated |
| The case scope: company, years, reason, basis (standalone / consolidated) | Anything from outside the saved case (no web search, no outside knowledge) |
| Each flag's figures, check, limit applied, severity, materiality, page or figure citation | Typology matches from Job 3 (not built; the template has a slot that stays empty until then) |
| The state of the limits (approved or DRAFT) and the configuration version | Any named person: people appear only as roles ("the signing director") |

Open for the lead: for a **portfolio company**, must the adviser's approval of the escalation exist before a flag may enter the memo? (Suggestion: yes.)

## 2. The six sections (as in the spec), plus annexes

Every page carries: **"DRAFT - for human review"** until the owner signs. After signing, that line is replaced by the owner's name and the signing date, and the version is locked.

**Header block**
Memo reference · company and symbol · basis · years in scope · case number · version number and date · named owner · data as of (latest filing used) · configuration version and whether its limits are approved ("DRAFT limits" line shown until the lead approves them).

**1. Assessment scope and objective**
Taken from the case: company, years, the stated reason for opening the case, and the reviewer's scope decisions (topics in scope, checks run). One line on what the memo is not: not an audit, not a conclusion, based on public filings only.

**2. Background and trigger**
Company profile from saved fields only (name, symbol, sector, listing, portfolio status), then the case's own reason text for opening the review. Nothing is added that is not saved.

**3. Findings summary** (one block per accepted flag, ordered high to low severity, then material first)
- Statement in descriptive words: "The statements show ..." with the flag's own wording.
- The figures used and their sources (annual report page, or the saved snapshot), each with its reference.
- The check, the limit it was tested against, and whether that limit is approved.
- Severity and materiality as the tool set them.
- Reviewer decision: accepted by NAME on DATE, with the reason they gave.
- Standing line: "Statistical lead only: most anomalies have innocent explanations. Public data cannot show the reason."

**4. Open questions and gaps**
Each item says what is unknown and **whether public data can close it** (yes with what source / no, needs a formal engagement). Built from (a) a fixed list per check type, which the lead approves, and (b) anything the reviewer adds. Gaps are never left out. Examples for a receivables flag: "Which customers make up the increase?" (not available in public data); "Is there a contract or billing-timing explanation?" (not available; would need management access).

**5. Recommended next steps**
Split in two: (a) steps possible on public data (for example "read the segment note", "compare with listed peers once a peer set is approved"); (b) what a formal engagement with data access would need to resolve, listed from the same per-check library. The lead approves the library.

**6. Ownership and sign-off**
Named owner, reviewing partner where needed, date, signature line, and the version history. Until signed it is a working draft and stays internal.

**Annex A. Method and limits** - checks run, formulas, limits and their approval state, the configuration version, data sources and their precedence.
**Annex B. Citation list** - every reference used in section 3, in the order cited.
**Annex C. Change log** - every version, who made it, what changed.
**Annex D. Documentation references** - ICAI FAIS section references and the SEBI RIA record-keeping note. *The lead must supply the exact text and section numbers; the tool does not invent them.*

## 3. How the draft is written (this is a design choice to confirm)

**Version 1 uses no AI model.** The memo is filled from the saved flags, figures and reviewer decisions with fixed wording. That means no invented sentences, nothing to fact-check beyond the citations the app already holds, and no Gemini quota used. The code applies the same checks it already applies to agent answers: banned wording refused, every claim must carry a reference, no personal names, DRAFT stamp always present.

An optional later step could let a model smooth the background paragraph, under the same checks and only with the lead's approval of what may be sent to a model (decision 3 in the lead decisions document).

## 4. Versions, owner and sign-off

- Every generated draft is saved as a **new version** and never edited in place. A human edit is also a new version, with the earlier text kept and the change logged.
- If a flag decision changes or the scope changes, the memo is marked **out of date** and must be regenerated and reviewed again (as the spec requires).
- The owner is a named person with the **memo owner** role. Only the owner (and the forensic lead) can edit or sign. Signing locks the version.
- Export as a Word file and a PDF, with the DRAFT line on every page until signed. Nothing is sent from the tool; sharing outside the firm is the owner's act.

## 5. Illustration (TCS, case 1; this is how one finding would read)

> **Finding 1 (high, material).** FY2025, standalone. The statements show that trade receivables changed +12.4% while revenue grew +6.2% (growth ratio 2.00x) [flag 36; trade receivables FY2024 46,068 and FY2025 51,767 crore; revenue FY2024 202,359 and FY2025 214,853 crore]. Check J1-03, limit: high at 2.0x (**DRAFT limit, not yet approved by the forensic lead**). Accepted by `<reviewer>` on `<date>`: "`<their reason>`".
> Statistical lead only: most anomalies have innocent explanations. Public data cannot show the reason.

(The figures are real stored values; the reviewer line stays blank because no flag has been accepted yet.)

## 6. What I need from the lead

1. Approve or change the six sections and the header and annex list.
2. Portfolio company: adviser approval required before a flag enters a memo? (suggested: yes)
3. Version 1 with no AI model, as proposed? (suggested: yes)
4. Provide the ICAI FAIS references and SEBI RIA annexure text for Annex D.
5. Approve the per-check lists of open questions and next steps (I will draft them for each of J1-01 to J1-17 for review).
6. Who may own a memo: only the `memo_owner` role, or also the analyst who ran the case?
7. Naming of the memo reference (suggestion: `CREST-<symbol>-<year>-<number>`).

## 7. Build order once the template is approved

1. Memo and memo-version tables, with the rules above (accepted flags only, no names, DRAFT stamp, locking on signing).
2. Generator that fills the six sections from a case, with citation and wording checks and tests.
3. Memo page in the app (preview, edit as new version, out-of-date notice, sign) and Word/PDF export.
4. The per-check open-question and next-step libraries, after the lead approves their wording.
