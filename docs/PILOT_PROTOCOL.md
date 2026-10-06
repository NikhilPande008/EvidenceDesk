# Pilot protocol

**Status: a plan. No pilot has been run, and no result below is a prediction.** The data in this repository is synthetic; nothing here is a measurement of any
institution. This document says how a pilot would produce a number that could be believed, so that EvidenceDesk is judged on evidence rather than on a claim.

## The question a pilot answers

For a Principal Officer and the financial-crime operations team that prepares each decision (in a bank's India operations or in a global capability centre that
works its alerts): does working an alert in EvidenceDesk produce a decision record that is more complete and easier to defend later, and does it cost the team
less or more time than the way they work today?

Nothing about detection quality is measured. EvidenceDesk does not detect anything.

## What is measured, and where each number comes from

Every figure below is computed from the decision ledger or the case record by code in this repository. None needs a stopwatch except the baseline.

| Measure | Definition | Source | Status today |
|---|---|---|---|
| Decision-record completeness | Share of decisions whose provenance holds a transaction-evidence digest and a regulatory basis that permits a conclusion | `skills/kpis.py`, `complete_evidence_and_basis` | Measured on the ledger |
| Time on the desk | Seconds from first opening a case to recording the decision, minus time waiting for a model (an upper bound: idle time is included) | ledger `desk_session`, KPI `investigation_time` | Proxy, stored from this version on |
| Filing before the clock runs out | FILE decisions recorded with working days left ÷ FILE decisions | `filing_timeliness` | Measured on the ledger |
| Unsupported facts stopped before recording | Filings blocked by the evidence gate for a fact that is not in the record, counted from the blocked attempts the pilot logs | pilot log (the gate's findings), not the ledger | To be captured |
| Override rate | Decisions that overrode a definite AI recommendation ÷ decisions where the AI ran | `override_rate` | Measured on the ledger |
| Repeat decisions | Alerts decided again after a concluding decision ÷ decided alerts | `audit_rework_rate` (proxy) | Proxy |
| Reconstructability | Share of sampled decisions an inspector can verify with `scripts/verify_dossier.py` and a reviewer can follow from the pack | inspection pack, offline verifier | A reviewer sample |

## Baseline: before any claim

A claim of improvement needs a **baseline measured the same way** over a comparable period, with **at least 30 decisions in each period**
(`skills/kpis.py`, `improvement()` refuses otherwise).

1. **Baseline period (2 weeks).** The team works as it does today. The same measures are taken from the artefacts it already produces (case notes, tickets,
   spreadsheet logs): the time between opening and closing a case as the team's own system records it, and a reviewer's score of each recorded rationale
   against the same checklist the ledger uses (transaction evidence cited, rule basis named, override and acknowledgement present).
2. **Working period (2 weeks).** The same team, the same alert types, the same reviewer, working in EvidenceDesk.
3. **Compare** with the difference and its interval, per measure. State the case mix of each period. A difference is not proof of cause.

## Roles

- **Principal Officer / decision-maker:** decides; owns the rationale.
- **Analyst:** prepares the case; their time is part of the measure.
- **Reviewer (second line):** scores a sample of decisions in both periods against the same checklist, without knowing which period they are from.
- **Corpus owner:** the named person who reviews the regulatory rules the basis rests on. Today none of the rules is independently verified.
- **Sponsor:** can stop the pilot.

## Preconditions

- The feed contract ([DATA_CONTRACT.md](DATA_CONTRACT.md)) is met by an export from the institution's own system, with pseudonymous references.
- The Snowflake account has the roles in [DEPLOY.md](../DEPLOY.md), and the production controls listed in [SECURITY.md](../SECURITY.md) exist before real data is loaded.
- Cortex model access and data residency have been approved by the institution.
- The regulatory scope is stated to the team: India only. A question about another regime is declined and routed to the parent entity's compliance function.

## When to stop, and when to go on

Stop at once if: a real customer identifier appears where a pseudonymous reference was expected; a model call sends data the institution has not approved; or the
reviewer finds a recorded rationale that states a fact the record does not contain and the gate did not stop it. Record that case and publish it with the result.

Go on to a longer pilot only if the working period shows, with at least 30 decisions, a record at least as complete as the baseline's **and** a time on the desk
that is not worse, and the reviewer's checklist scores are not lower. These are conditions to decide on, not forecasts.

## What will not be claimed

- Accuracy on real cases, or any figure for time saved, before the baseline exists.
- That the regulatory corpus is legally verified: it is not, and PROVEN means only that its author cites a primary source.
- That EvidenceDesk finds fraud, files reports or decides anything.
