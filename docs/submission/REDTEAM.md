# Submission red-team: EvidenceDesk

**Run 2026-10-06 by the same reviewer that built most of the package, so read the score as a self-assessment, not an independent judgement. Hours to deadline: unknown (the deadline is not in the repository).**

```
SUBMISSION RED-TEAM: EvidenceDesk
Inventory gaps: 6 (all need you) | Live-walk defects: 1 (fixed, re-verified) | Claim-audit verdict: SHIP
Pitch-defense open: Cortex Code CLI use, build window, buyer or practitioner evidence, scale
Judge score estimate: Relevance 23 to 25 / 30, Technical 34 to 36 / 40, Completeness 24 to 26 / 30 (about 81 to 87 of 100)
Highest-severity risk: a CoCo CLI hackathon entry with no recorded Cortex Code CLI session
Verdict: FIX-LIST-THEN-SUBMIT
```

## Phase 0: deliverables inventory

The submission card and rules page are not in the repository, so "Required?" is inferred from the 6-slide hackathon template and from what such hackathons ask. **Send me the card and this table becomes exact.**

| Deliverable | Required? | Exists? | Owner | Verified live? |
|---|---|---|---|---|
| Public repository | Yes (assumed) | Yes locally. **Not pushed.** Work is on `hardening-2026-10-05`, not the default branch | You | No |
| Demo video | Likely | Script written (`DEMO_SCRIPT.md`). **Not recorded** | You | n/a |
| Slide deck (hackathon template, 6 slides) | Yes (template provided) | Yes, dated 4 October, with four statements the audit does not support. Corrected copy in `DECK_COPY.md` | You | Text audited; slide 6 is the template's thank-you |
| Writeup | Likely | Yes: `WRITEUP.md` | Done | n/a |
| Cortex Code CLI evidence | Probably (it is the hackathon's subject) | Five skill files; **no recorded session** | You | No |
| Live app URL | Unknown | The clean-room app is private to the Snowflake account; judges may not be able to open it | You | Walked locally against the same environment, not in Snowsight |
| License | Unknown | **None in the repository** | You | n/a |
| Cover image or thumbnail | Unknown | Four screenshots in `docs/screenshots/` | You | n/a |

Ordering rule applied: the first six rows are inventory gaps and come before any polish.

## Phase 1: clean-clone gate

**Passed, with one stated limit.** Fresh `git clone`, fresh virtualenv, `pip install -r requirements.txt`, `python -m py_compile`, `python -m pytest tests -q`: 603 passed, 20 skipped. All 46 standalone suites exit 0. No cached outputs are needed by the tests;
the shipped saved responses are real captured replies, labelled as saved on screen and in the ledger row.
**Limit:** the demo path itself needs a Snowflake account, the roles in `DEPLOY.md` and Cortex access. A reviewer without one can run the offline suite, the benchmark, the sample inspection pack (`python scripts/verify_dossier.py docs/sample/decision-pack-sample.json`)
and the feed dry run, and can read the screenshots and evidence, but cannot open the application. The README says a Snowflake environment is required.

## Phase 2: live walk

Walked the application running locally against the isolated clean-room environment as the application role (read-only; **nothing was recorded**):

| Step | Result |
|---|---|
| Queue | 19 alerts, deadline mix, "10 pending cases have no usable recorded suspicion time" matches the seed |
| ALERT-16: **Load the saved assessment (no wait)** | The button appears against the real database (the prompt hash matches). Screen: "saved model response captured 6 Oct 2026 (UTC) by llama3.3-70b, not generated now. The checks on it ran just now". Recommendation REVIEW; POE-007 and POE-010 each "not counted toward FILE" with the reason |
| ALERT-01: true filing text plus the planted ₹25 lakh SWIFT-to-Dubai sentence, File STR | "BLOCKS RECORDING ... amount ₹25.00L; date 2026-08-27; channel SWIFT; geography Dubai ... You cannot override this for a filing." The record button is `disabled` |
| Regulatory reference: UAE goAML question | "Outside this corpus. This corpus covers India only ... gives no regulatory guidance and shows no rules. Route it to the parent entity's compliance function (MLRO)" |
| Defect found | The sidebar showed an internal code ("POE framework: product-compiled (DG-19)"). **Fixed** to plain words, re-verified live after a restart, and the isolated app redeployed (30 of 30 files identical to the source) |

**Not walked:** recording a decision and the Reconstruct page (they write a permanent row), downloading an inspection pack from the app, the Decision archive and the Tools pages beyond the regulatory reference, any role other than the application role, and the real Snowsight render.
A jargon sweep of those pages is still open.

## Phase 3: claim audit

`CLAIM_AUDIT.md`: 17 PROVEN, 8 STUBBED, 3 ASSUMED, 7 never claimed. Three wording defects fixed. **Verdict: SHIP**, with the labels carried into the writeup and README.
The deck is the one artifact that still carries unsupported statements until you paste the corrected slides.

## Phase 4: pitch defense

`PITCH_DEFENSE.md`. Open (no honest one-breath answer yet): where the Cortex Code CLI was used; whether the build window or prior-work rules affect a repository whose first commit is 2026-10-04; a buyer or practitioner; any scale number.

## Phase 5: judge's-eye score against the published weights

| Criterion | Estimate | Why, as a skeptical judge with 40 other entries |
|---|---|---|
| Real-World Relevance (30) | 23 to 25 | A real problem with a clear user and an honest scope; GCC fit and the feed contract and pilot protocol help. Held back by no buyer, no practitioner, no baseline and nothing measured on real data |
| Technical Execution (40) | 34 to 36 | Deterministic gate re-derived at write time, a measured model comparison, a measured validator-versus-model comparison, a held-out miss reported, offline-verifiable records, least privilege proven live. Held back by the hosted render never seen, no Cortex Agent or CLI-driven workflow, one model and one run per comparison, and the recommendation layer still wrong on legitimate cross-border cases |
| Solution Completeness (30) | 24 to 26 | End to end on the clean room with evidence, a feed loader, a sample pack, a pilot protocol. Held back by no video and no updated deck yet, judges possibly unable to open the app, and no recorded CLI session |

The previous scores were 70.0 and 79.0 from the same method. Moving from 79 to the low or mid 80s is plausible. The single largest avoidable loss is a CoCo CLI hackathon entry with no CLI evidence.

## Fix list, in order

1. Send the submission card and rules; fix the inventory table and the deadline.
2. Record at least one Cortex Code CLI session per skill (prompts in `evidence/coco/README.md`), or decide to submit without and keep the current wording.
3. Merge and push, add a license, and decide about the commit history's name and email.
4. Paste the corrected slides 3, 4 and 5; record the video from `DEMO_SCRIPT.md`.
5. Check the hackathon's build-window and prior-work rules.
6. Finish the jargon sweep on the pages not walked.
