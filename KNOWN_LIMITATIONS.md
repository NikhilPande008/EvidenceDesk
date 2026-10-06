# KNOWN_LIMITATIONS.md — what this prototype does not do, and what was left out on purpose

The lists below are rendered from [`skills/readiness.py`](skills/readiness.py) (`KNOWN_LIMITATIONS`, `ROADMAP`) by `python3 scripts/render_readiness_docs.py --write`; `tests/test_readiness.py` fails if they drift. They are also on the *Tools · Architecture & readiness* page.

## Limitations

<!-- readiness:limitations:start -->
1. This application does not detect fraud, give legal advice, file reports or verify regulatory compliance. It supports a human decision and records why.
2. All data is synthetic. No real personal data may be loaded: masking is opt-in and off by default, there is no row-access policy and no pseudonymisation.
3. Two decisions submitted at the same moment on an alert that has none can both be recorded: the ledger is append-only, Snowflake does not lock concurrent inserts and uniqueness is not enforced on this account. Both rows are kept, each records how many decisions the ledger held for that alert when it was written, and the reconciliation reports the pair as CONCURRENT_DECISIONS. They are detected, not prevented.
4. No regulatory rule has been independently verified against its live primary source (0 of 49). PROVEN means a primary source is cited by the corpus author.
5. The Snowflake ledger is append-only for the application role. It is not immutable: the owner role can delete rows, and rows never exported cannot be shown missing. The audit export is opt-in and not provisioned in the live account; the local write-once sink is a simulation.
6. The effects of evidence-quality findings, the priority weights and the severity table are product policy, not regulatory requirements. Findings read from free text are pattern matches.
7. Hands-on investigation time and analyst touch time cannot be measured from the ledger. No baseline exists, so no business improvement is claimed. Precision, recall and F1 are computed against synthetic scenario labels.
8. The reporting deadline is scored only where a suspicion time was recorded (Mon–Fri, no holiday calendar), from the optional case-feed field or a time recorded with an earlier decision. The seeded feed supplies one for 9 of the 19 alerts; the other 10 have no clock, and none is invented.
9. Shared device, address and document links cannot be tested: the dataset holds no such identifiers. Counterparty matching is string equality after a stated normalisation, not entity resolution.
10. A clean-room environment (name suffix CR2) was redeployed from the 6 October code, and its hosted app was byte-identical to the source at that moment (evidence/cleanroom-2026-10-06). The pre-existing production database was migrated and redeployed by its owner on 6 October; no run record of that is kept in this repository. What Snowsight renders, and what st.user and CURRENT_USER() return there, have never been verified. Snowflake documents st.user.user_name and st.user.email as the viewer's, but this deployment has not been seen to supply them.
11. The live suites (tests/test_skills_smoke.py, tests/test_live_e2e.py) were run in full against the clean room as the owner and the app role on 6 October with no failures (evidence/cleanroom-2026-10-06/live_suites_rerun.log); they were not run against the production database. The first fresh deploy failed on an unescaped apostrophe in a table comment that no offline test could see; it is fixed and guarded. On the pre-existing production database the opt-in migrations 08 and 09 were first applied in the wrong order (the schema step stopped because a column that migration 09 adds did not exist yet); the order is now in DEPLOY.md. Behaviour under concurrent users was not exercised.
12. Cortex latency is long and variable (11–120 s per call observed, two timeouts in 19); behaviour under concurrent users has not been tested.
13. No penetration test, supply-chain scan or Streamlit content-security-policy review has been done.
<!-- readiness:limitations:end -->

## Prioritised roadmap of what is intentionally not built

P0 = needed before any real data; P1 = needed to make the new views real; P2 = scale and workflow; P3 = operational completeness and assurance.

<!-- readiness:roadmap:start -->
| Priority | Item | Why |
|---|---|---|
| P0 | SSO + MFA, network policies, and removal of the typed decision-maker path | Attribution and perimeter are the precondition for any real data. |
| P0 | Independent write-once archive of the audit export (separate account, compliance-mode retention) and scheduled verification | Closes the owner-role deletion risk; until then the ledger is not immutable. |
| P0 | Independent verification of the PROVEN rules against their live primary sources, by a reviewer who is not the owner | 0 of 49 rules are verified; the whole basis rests on citation, not re-checking. |
| P1 | Masking, row-access policies, pseudonymised prompts and restricted cross-region inference | Prerequisite for loading real customer data. |
| P1 | Entity-resolution / device-intelligence feed (attribute rows) for shared-device, address and document links | Turns the relationship view from string matching into real linkage. |
| P1 | Outcome feed (QA review, FIU-IND queries, STR returned for rework) written by a second-line process | Turns the false-positive and rework proxies into measurements. |
| P1 | Server-side case-open and decision timestamps for hands-on investigation time; a baseline period before any improvement is claimed | Business value cannot be claimed without a baseline. |
| P2 | Streaming ingestion, stored incremental scores and a paged queue | Scale to millions of transactions. |
| P2 | Asynchronous AI enrichment worker with spend caps | Removes the 40–120 s wait from the officer's path. |
| P2 | Maker-checker approval for FILE decisions; a corpus approver distinct from the corpus owner | Separation of duties. |
| P3 | Case-management and regulator-channel integration; SIEM export; resource monitors; disaster-recovery replication | Operational completeness. |
| P3 | Penetration test, CSP review, supply-chain scanning, incident-response runbooks | Assurance. |
<!-- readiness:roadmap:end -->

## What "not claimed" means here

* **No autonomous fraud detection.** Signals come from other systems.
* **No legal advice and no compliance verification.** The corpus is a governed set of cited rules, none independently verified; PROVEN means a primary source is cited by the corpus author.
* **No autonomous filing.** Recording `FILE` stores a decision. Submission through FINGate is a separate manual step.
* **No realised business improvement.** There is no baseline and hands-on time is not measured. Figures marked *simulated* are illustrations of a dashboard, not measurements.
* **No immutability.** The ledger is append-only for the application role; the owner role can delete rows, and a write-once external copy does not exist.

Earlier phases' limits are unchanged and are in [SECURITY.md §7](SECURITY.md), [RECOVERY.md](RECOVERY.md) and [HANDOFF.md](HANDOFF.md).
