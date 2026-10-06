# Real-world fit: where an alert becomes a decision, and where EvidenceDesk sits

**Status.** This page describes the path of one alert using only the regulatory rules the application already carries in its corpus, and shows where each part of EvidenceDesk acts on that path. It is not a description of any institution's practice: no practitioner has reviewed it (A1 in [the claim audit](submission/CLAIM_AUDIT.md)). Every rule below shows the corpus's evidence level. PROVEN means the corpus author cites a primary source; no rule has been independently verified (0 of 49).

## The path of one alert, and where EvidenceDesk acts

| # | Step | What the corpus rule says | Rule (level) | What EvidenceDesk does at this step |
|---|---|---|---|---|
| 1 | A monitoring system raises an alert | Out of scope | none | Nothing. The alert and its transactions arrive as a feed that must meet [the data contract](DATA_CONTRACT.md) |
| 2 | Someone decides whether there are grounds to suspect | An STR is filed when there are reasonable grounds to believe a transaction involves proceeds of an offence, whatever its amount | STR-001 (PROVEN) | Opens on the source facts, then the rule basis, then an optional AI proposal that is labelled as one. The officer decides |
| 3 | The reporting clock starts | Seven working days from the date the reporting entity forms suspicion | STR-002 (PROVEN) | Shows days left only where the feed supplies the time suspicion formed. It never infers one |
| 4 | The reason is written | An STR has three parts (KYC profile, transactions, ground of suspicion), and the ground of suspicion is a free-text narrative the Principal Officer writes | RS-001, RS-004 (PROVEN) | Checks every amount, date, identifier, channel, place and entity in the text against the case record. An unsupported fact blocks the filing and cannot be overridden. A draft is optional and has to be edited |
| 5 | The right person decides | Inspectors verify that filing decisions were made by authorised staff | INS-002 (PROVEN) | Records the deciding officer's ID. **It does not record who prepared the case** (see the end of this page) |
| 6 | Not filing is examined too | Inspectors examine alerts that were raised and not filed | INS-001 (ASSUMED) | A closure needs a written rationale. Facts in it that the record does not hold are flagged as a warning, not a block: only a filing is hard-blocked. A second decision on an alert needs its own written reason |
| 7 | The customer must not be told | Tipping-off is prohibited | STR-004, SB-003 (ASSUMED) | A request to tell the customer about a report or a suspicion is refused by a screen, and the refusal says why |
| 8 | The report is filed | Through the regulator's portal | STR-006 (ASSUMED) | **Nothing is submitted.** EvidenceDesk produces a checked text and a record, not a filing |
| 9 | The record is kept and may be inspected later | Transaction records are kept for at least five years | RR-001 (PROVEN) | An append-only decision record with provenance and a row hash, a reconstruction of what the officer saw and acknowledged, and an inspection pack that an offline verifier checks without Snowflake (proven on a test harness; not yet on a pack downloaded from the hosted app, S2) |

Two rules close to this path are not used: RR-002 (retention of STR-related records) and INS-004 (templated narratives) are NEEDS-VERIFICATION and are excluded from the lookup index.

## Public context, with sources

| Fact | Source | How it was read |
|---|---|---|
| India hosts 2,117 global capability centres in 3,728 units, employing about 2.36 million people, with market revenue of $98.4 billion; data as of March 2026 (FY26); 32% growth in centres since FY2021 | Zinnov and Nasscom, [India GCC Landscape Report 2026](https://zinnov.com/centers-of-excellence/zinnov-nasscom-india-gcc-landscape-2026-report/) | The landing page, read on 2026-10-06 through a summarising fetch tool. The same figures appear in [The Tribune's report of 3 July 2026](https://www.tribuneindia.com/news/business/india-s-gccs-are-increasingly-leading-the-ai-mandate-for-global-enterprises-driving-global-value-creation-nasscom-zinnov-report/) |
| Suspicious transaction reports filed: 6,45,905 in FY 2022-23, 3,68,592 in FY 2023-24 and 4,34,668 in FY 2024-25 (645,905; 368,592; 434,668) | FIU-IND, [Annual Report 2024-25](https://fiuindia.gov.in/pdfs/downloads/AnnualReport2024_25.pdf), printed page 20 | The PDF was downloaded and the page read as an image, 2026-10-07 |
| The report describes a regulatory action against a commercial bank. The violations it lists include deficient alert management (PML Rules 3(1)(D) and 7(3)) and non-filing of STRs (Rule 8(2)); the penalty was Rs.1,66,25,000; the directions included strengthening transaction monitoring and resolving alerts within prescribed timelines. In all, the report records 5 monetary penalties totalling Rs.30,48,65,000 | the same report, printed pages 50 and 51 | Read as images |
| 6,908 priority STRs were passed to law-enforcement agencies in FY 2024-25, and the report says about 40% of priority STRs were found useful over four years | the same report, printed pages 5 and 22 | Text layer |

**What these do not show.** The Zinnov page does not mention banking, financial services or insurance as a vertical, nor risk, compliance or financial-crime functions. The size of the sector therefore says nothing about how many centres work AML alerts. That EvidenceDesk fits a centre's operations team stays ASSUMED (A1).
**What the FIU-IND report shows and does not.** It shows the scale (hundreds of thousands of STRs a year) and that the regulator treats how alerts are managed as something it can penalise. It does not say how any institution documents the reasons for a decision, and it does not say whether the written rationale was part of the case it describes. It names deficient alert management and non-filing, not the rationale. What EvidenceDesk does is one part of alert management, the defensible record of what was decided and why; it does not detect, set thresholds or file. The description of current practice therefore stays ASSUMED.
**What was not read.** 26 of the report's 112 pages have no text layer and were not read. The report is not stored here (138 MB, the publisher's work). [The evidence note](../evidence/public-sources/2026-10-07/FIU-IND-annual-report-2024-25.md) gives its size, SHA-256 and the printed page of every figure, so the copy can be checked.

## What is not known, and how it would be found out

- **Does a practitioner recognise this path, and what would they change?** [The interview kit](practitioner/INTERVIEW_KIT.md) is a 15-minute script that asks about their practice before showing the product. Nobody has been asked yet.
- **Does it save time?** Nothing has been measured (S5). The kit includes a small timing exercise that gives an observation from two or three people, not a measurement. [The pilot protocol](PILOT_PROTOCOL.md) says how a real number would be produced, with a baseline and at least 30 decisions in each period.
- **Who would pay?** Unknown (A5).

## Gaps this path shows in the product itself

These are choices of scope, not claims. Each would change the product.

1. **No record of who prepared a case.** Where an analyst prepares and an officer decides, the record names only the officer. Recording the preparer, and refusing a case where preparer and decider are the same person, is a two-person (maker-checker) control that we understand to be common in banking; that understanding has not been checked with a practitioner. It would be a small change to the record.
2. **One regime.** The corpus is India only. A centre that serves several regimes gets a refusal, routed to the parent entity's compliance function, and not an answer.
3. **No real feed.** Only synthetic and sample-shaped files have been loaded (S3).
