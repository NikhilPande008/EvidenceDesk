"""
Readiness, architecture and known limitations — ONE structured source for what this prototype is, what it only simulates, and what production needs.

Every capability and control is placed in exactly one of three tiers, and the documents and the Architecture page are checked against this module
(tests/test_readiness.py), so a claim cannot drift from the code:

    IMPLEMENTED_AND_DEMONSTRATED   built, and shown working by the offline test suite and/or the local run; `evidence` names the test file
    PROTOTYPE_SIMULATION           something stands in for the real thing; `simulated_by` says what, and `production` says what replaces it
    PRODUCTION_REQUIREMENT         not built here. It cannot honestly be simulated (an identity provider, a network perimeter, a regulated
                                   archive), so it is listed with what exists today and what production must add

Nothing is marked IMPLEMENTED unless a test file named in `evidence` exercises it. Live-Snowflake behaviour is a separate claim: where an item's
live behaviour has not been verified, `limits` says so.

Pure data and two helpers. No database, no Streamlit.
"""

from __future__ import annotations

from skills import po_copy as T

IMPLEMENTED, SIMULATED, PRODUCTION = "IMPLEMENTED_AND_DEMONSTRATED", "PROTOTYPE_SIMULATION", "PRODUCTION_REQUIREMENT"
TIERS = (IMPLEMENTED, SIMULATED, PRODUCTION)
TIER_LABEL = {IMPLEMENTED: "Implemented and demonstrated", SIMULATED: "Prototype simulation", PRODUCTION: "Production requirement"}
TIER_MEANING = {
    IMPLEMENTED: "Built and exercised by the offline tests and the local run.",
    SIMULATED: "A stand-in is used for the real thing; the stand-in is named.",
    PRODUCTION: "Not built here. It cannot honestly be simulated; what exists today and what production must add are stated.",
}

POSITIONING = {"title": T.POSITIONING_TITLE, "is": T.POSITIONING_IS, "is_not": T.POSITIONING_IS_NOT, "flow": T.POSITIONING_FLOW}


def _c(cid, area, capability, status, *, evidence=None, where="", simulated_by=None, production=None, limits=None):
    return {"id": cid, "area": area, "capability": capability, "status": status, "evidence": evidence, "where": where, "simulated_by": simulated_by,
            "production": production, "limits": limits}


# ── what the product does, by enhancement ────────────────────────────────────
CAPABILITIES: list[dict] = [
    _c("POS-1", "Positioning", "Stated as an AML decision-defensibility and investigation copilot; signals come from other systems; no detection, legal advice, filing or compliance verification claimed",
       IMPLEMENTED, evidence="tests/test_positioning.py", where="skills/po_copy.py POSITIONING_*, README.md, My cases page"),
    _c("PRI-1", "Case prioritisation", "Transparent 9-factor priority score with a 'why this case is prioritized' explanation, separate from the FILE / NOT_FILE decision",
       IMPLEMENTED, evidence="tests/test_prioritisation.py", where="skills/prioritisation.py, My cases page",
       limits="The reporting-deadline factor scores only where a suspicion time exists: the optional case-feed field, or a time recorded with an earlier decision. The seeded feed supplies one for 9 of the 19 alerts; the other 10 contribute 0, and the application never infers a time from the alert date."),
    _c("REL-1", "Relationships", "Sourced versus inferred links among customer, account, alert, counterparties and related cases; rule-named patterns; untestable link types listed",
       IMPLEMENTED, evidence="tests/test_relationships.py", where="skills/relationships.py, Investigation desk",
       limits="Shared device / address / document links are tested only when attribute rows exist; the seeded data has none."),
    _c("REL-2", "Relationships", "Device, address and identity-document graph from an identity-resolution / device-intelligence source", PRODUCTION,
       production="A governed entity-resolution feed (customer ↔ device / address / document attribute rows) and an entity key stronger than a string match."),
    _c("EQ-1", "Evidence quality", "Per-case evidence-quality panel: missing KYC, missing or aggregated history, stale records, contradictions, unavailable documents, unsupported claims, unresolved identity — each with an effect (informational / acknowledgement / manual review / blocks filing) enforced by the decision gate",
       IMPLEMENTED, evidence="tests/test_evidence_quality.py, tests/test_gate_extensions.py", where="skills/evidence_quality.py, skills/defensibility.py, Investigation desk",
       limits="The effect of each issue is product policy, not a regulatory requirement. Findings read from free text are pattern matches and can never block."),
    _c("COR-1", "Corpus lifecycle", "Per-rule source URL, authority, effective date, last reviewed, last independently verified, owner, review SLA, supersession and approval; governance dashboard and report",
       IMPLEMENTED, evidence="tests/test_corpus_lifecycle.py", where="skills/corpus_lifecycle.py, scripts/corpus_governance_report.py, Corpus governance page",
       limits="No rule is reviewed, approved or independently verified today; the new columns are an opt-in migration and read as NOT PROVISIONED on the live table until it is applied."),
    _c("COR-2", "Corpus lifecycle", "Independent re-verification of each rule against its live primary source", PRODUCTION,
       production="A named reviewer, other than the owner, checks each PROVEN rule against the live source and records the date. The data model supports it; nobody has done it."),
    _c("FB-1", "Feedback loop", "Capture of AI acceptance / rejection (derived), override reason and a structured closure reason; monitoring of agreement, override, unsupported-claim, false-positive proxy, rework and recurring evidence gaps; never used for retraining or policy",
       IMPLEMENTED, evidence="tests/test_feedback.py, tests/test_gate_extensions.py", where="skills/feedback.py, Model quality page",
       limits="Downstream outcomes need an opt-in outcome feed (deploy/07_decision_outcomes.sql); without it they are reported as not available, never inferred."),
    _c("FB-2", "Feedback loop", "A human-led calibration review that acts on the monitoring (re-weighting a score, changing a prompt)", PRODUCTION,
       production="A documented model-risk process with sampling, sign-off and a version bump. By design, nothing in the prototype does this automatically."),
    _c("SEC-1", "Security", "Decision-maker identity taken from the Snowflake session where one is supplied, labelled as not authenticated where it is typed; the database stamps the writing user and role on every row",
       IMPLEMENTED, evidence="tests/test_gate_extensions.py", where="skills/identity.py, skills/ledger.py, Investigation desk",
       limits="Whether the hosted runtime supplies st.user, and what CURRENT_USER() returns there, has not been verified in Snowsight."),
    _c("SEC-2", "Security", "Approved-model allow-list: a configured Cortex model that is not on the list is refused, not substituted", IMPLEMENTED,
       evidence="tests/test_readiness.py", where="skills/core.py APPROVED_MODELS"),
    _c("SEC-3", "Security", "Prompt minimisation boundary: no customer reference, alert metadata, transaction owner or session identity reaches a model prompt", IMPLEMENTED,
       evidence="tests/test_gate_extensions.py", where="skills/core.py",
       limits="The KYC profile line and counterparty names are still sent verbatim; with real data they would need pseudonymisation first."),
    _c("AUD-1", "Audit durability", "Audit-export protection indicator (provisioned / current / chain valid / external copy attested), write-once packages that chain across exports and verify offline",
       IMPLEMENTED, evidence="tests/test_audit_durability.py", where="skills/audit.py, scripts/audit_ledger.py, Decision archive page",
       limits="The audit export store is opt-in and NOT provisioned in the live account; the local-directory sink is a simulation of a write-once store."),
    _c("AUD-2", "Audit durability", "A write-once copy of every export in a separate account (object-lock compliance mode)", PRODUCTION,
       production="See skills/audit.py WORM_REQUIREMENTS. Until it exists, owner-role deletion of never-exported rows is undetectable and the ledger is not immutable."),
    _c("ARC-1", "Architecture", "Reference architecture from signal ingestion to reporting integration, with low-latency deterministic stages separated from slow on-demand AI",
       IMPLEMENTED, evidence="tests/test_readiness.py", where="ARCHITECTURE.md, Architecture page"),
    _c("KPI-1", "KPIs", "KPI model with definitions, sources, caveats and a status per KPI; precision / recall / F1 against synthetic labels; a guard against claiming improvement without a baseline; a clearly marked simulated cohort",
       IMPLEMENTED, evidence="tests/test_kpis.py", where="skills/kpis.py, Business value page",
       limits="Hands-on investigation time and analyst touch time are not measurable from the ledger; no baseline exists, so no improvement is claimed."),
    _c("CORE-1", "Core controls", "Fail-closed AI output; evidence grounding; decision-defensibility gate; regulatory-basis governance; append-only ledger with row hash; audit reconstruction",
       IMPLEMENTED, evidence="tests/test_fail_closed.py, tests/test_grounding.py, tests/test_defensibility.py, tests/test_regulatory_basis.py, tests/test_ledger.py, tests/test_audit.py",
       where="skills/", limits="Verified live in earlier phases against Snowflake (EVIDENCE.md); not re-run in Phase 14."),
    _c("SIM-1", "Data", "Alerts and transactions", SIMULATED, evidence="tests/test_security_boundaries.py", where="scripts/setup_alerts.py",
       simulated_by="19 synthetic alerts and 92 synthetic transactions seeded in Snowflake, standing in for signals ingested from MuleHunter.AI, the I4C Suspect Registry, RBI DPIP and internal rules",
       production="Streaming or micro-batch ingestion of real signals and transactions behind masking and row-access policies; no real PII is loaded here."),
]

# ── production security and privacy readiness ────────────────────────────────
def _p(cid, control, category, status, today, needs, *, evidence=None, where=None):
    return {"id": cid, "control": control, "category": category, "status": status, "today": today, "production": needs, "evidence": evidence, "where": where}


PRODUCTION_CHECKLIST: list[dict] = [
    _p("SSO", "Single sign-on (SAML / OIDC)", "Identity", PRODUCTION,
       "Snowflake password login for humans and the CLI; only the built-in local OAuth integration exists (SECURITY.md §8).",
       "SAML / OIDC SSO with the institution's identity provider; password login disabled for humans."),
    _p("MFA", "Multi-factor authentication", "Identity", PRODUCTION,
       "The deploying user has no MFA; default role ACCOUNTADMIN (SECURITY.md §8).",
       "MFA enforced for every human by authentication policy; phishing-resistant for ACCOUNTADMIN and owner roles."),
    _p("AUTH-ID", "Authenticated user identity on every decision", "Identity", IMPLEMENTED,
       "The decision-maker is the Snowflake session identity where the runtime supplies one; otherwise it is typed and recorded as NOT authenticated (a warning in the stored gate). The INSERT stamps CURRENT_USER() and CURRENT_ROLE() in the database.",
       "SSO + MFA so the session identity is a person; the typed path removed.", evidence="tests/test_gate_extensions.py", where="skills/identity.py, skills/ledger.py"),
    _p("MASK", "Dynamic data masking", "Data protection", PRODUCTION,
       "Masking is opt-in and off by default (deploy/10_governance_optin.sql, probed once in the isolated environment): without it every role with SELECT reads the customer profile and counterparties in clear, and prompts and screens carry them verbatim. Free text that repeats them is not masked. All data is synthetic.",
       "Dynamic masking on CUSTOMER_PROFILE and counterparty columns; tag-based policies; derived features sent to models instead of identifiers."),
    _p("RAP", "Row-access policies", "Data protection", PRODUCTION,
       "No row-access policy exists; any role with SELECT sees every alert.",
       "Row-access policies by branch / business line / case ownership; tipping-off-sensitive FILE decisions visible only to named roles."),
    _p("LEAST", "Least privilege", "Access", IMPLEMENTED,
       "The app role holds INSERT + SELECT on the ledger and SELECT on the data it reads; UPDATE / DELETE / TRUNCATE are denied by the database and proven live (EVIDENCE.md, DEPLOY.md Step 3). PUBLIC still holds CORTEX_USER (SECURITY.md §1a).",
       "Revoke CORTEX_USER from PUBLIC; per-role access reviews; owner roles break-glass only.", evidence="tests/test_ledger.py, tests/test_health.py", where="deploy/03_grants.sql, deploy/04_verify_ledger_rbac.sql"),
    _p("NETPOL", "Network policies", "Perimeter", PRODUCTION,
       "None: any IP may attempt login (SECURITY.md §8).",
       "Account- and user-level network policies; private connectivity; service users restricted to the deploy runner."),
    _p("MODELS", "Approved-model allow-list", "AI governance", IMPLEMENTED,
       "A configured Cortex model must be on APPROVED_MODELS and have a plain name shape; otherwise the call fails closed and nothing is sent. The account still allows all models (CORTEX_MODELS_ALLOWLIST = ALL).",
       "Set the account-level model allow-list to the same list; change control for extending it.", evidence="tests/test_readiness.py", where="skills/core.py"),
    _p("PROMPT", "Prompt minimisation", "AI governance", IMPLEMENTED,
       "Customer reference, alert metadata, transaction owners and the session identity never enter a prompt (tested). The KYC profile line and counterparty names still do.",
       "Pseudonymise counterparties and strip identifiers from the profile before any prompt is built; log what was sent.", evidence="tests/test_gate_extensions.py", where="skills/core.py"),
    _p("RESIDENCY", "Data residency", "Data protection", PRODUCTION,
       "Cortex cross-region inference is enabled (ANY_REGION) on the account; the account is in AWS_AP_SOUTHEAST_7 (SECURITY.md §6).",
       "Restrict cross-region inference; confirm that no personal data leaves the permitted region; document where each model runs."),
    _p("RETENTION", "Retention and legal hold", "Records", PRODUCTION,
       "Time Travel is 1 day; no external archive; the audit export store is not provisioned (SECURITY.md §8, RECOVERY.md).",
       "Retention aligned to the institution's record-keeping obligation, held outside the account in write-once storage; legal-hold procedure."),
    _p("MONITOR", "Monitoring and alerting", "Operations", PRODUCTION,
       "Read-only health check, ledger reconciliation and a query-history monitor exist and are run by hand; there is no resource monitor.",
       "Scheduled health / reconciliation runs that page someone; resource monitors with suspend thresholds; alerts on non-app DML against the ledger.",
       evidence="tests/test_health.py", where="scripts/health_check.py, scripts/audit_ledger.py"),
    _p("SIEM", "SIEM integration", "Operations", PRODUCTION,
       "None. Login history and Access History exist in Snowflake but are not exported.",
       "Stream login history, Access History, query history for the ledger and the audit export, and the application's own security events to the institution's SIEM."),
    _p("SOD", "Separation of duties", "Access", PRODUCTION,
       "One person holds the owner role, the app role and ACCOUNTADMIN; FIU_ADMIN_ROLE is inherited by SYSADMIN (SECURITY.md §8). A distinct audit role is designed but not provisioned.",
       "Owner and audit roles held by different people, neither under SYSADMIN; maker-checker approval for FILE decisions; corpus approver distinct from corpus owner."),
]

# ── near-real-time reference architecture ────────────────────────────────────
LATENCY_FAST = "Deterministic · low latency (milliseconds to seconds)"
LATENCY_AI = "On-demand AI · slow (observed 11–120 s per Cortex call, two 120 s timeouts in 19)"
LATENCY_HUMAN = "Human · minutes to days"

ARCHITECTURE_STAGES: list[dict] = [
    {"n": 1, "name": "Event / stream ingestion", "latency": LATENCY_FAST, "status": SIMULATED,
     "prototype": "Seed scripts load 19 synthetic alerts and 92 transactions in batch (scripts/setup_alerts.py).",
     "production": "Streaming or micro-batch ingestion (for example Snowpipe Streaming / Kafka) of transactions and signals into partitioned tables, behind masking."},
    {"n": 2, "name": "Deterministic monitoring / external signal source", "latency": LATENCY_FAST, "status": SIMULATED,
     "prototype": "The alerts stand in for signals from MuleHunter.AI, the I4C Suspect Registry, RBI DPIP and internal rules. This application detects nothing.",
     "production": "The institution's transaction-monitoring system and external registries raise signals; this application ingests them."},
    {"n": 3, "name": "Prioritised case queue", "latency": LATENCY_FAST, "status": IMPLEMENTED,
     "prototype": "Nine-factor deterministic priority score with an explanation, computed on read (skills/prioritisation.py).",
     "production": "The same score computed incrementally at ingest (a dynamic table or stream) and stored, so the queue is a sorted, paged read."},
    {"n": 4, "name": "Asynchronous AI enrichment", "latency": LATENCY_AI, "status": SIMULATED,
     "prototype": "The officer clicks to run the 11-factor assessment; it runs synchronously in the page (40–120 s). Optional, labelled, grounded and fail-closed.",
     "production": "A queued worker (Snowflake tasks / streams) enriches high-priority cases ahead of the officer, stores the result with its model and prompt version, and the officer reads it later."},
    {"n": 5, "name": "Principal Officer review", "latency": LATENCY_HUMAN, "status": IMPLEMENTED,
     "prototype": "Four-zone investigation desk, evidence-quality panel, decision checkpoint and gate (skills/defensibility.py).",
     "production": "The same, with SSO, maker-checker for FILE decisions and case-assignment rules."},
    {"n": 6, "name": "Decision ledger", "latency": LATENCY_FAST, "status": IMPLEMENTED,
     "prototype": "Append-only for the application role, row-hashed, with provenance; audit export and write-once packages (skills/ledger.py, skills/audit.py).",
     "production": "The same, plus an independent write-once copy in another account, retention and legal hold."},
    {"n": 7, "name": "External reporting / case-management integration", "latency": LATENCY_HUMAN, "status": PRODUCTION,
     "prototype": "None. Recording FILE stores a decision; filing through FINGate is a separate manual step. No STR is submitted.",
     "production": "An integration to the institution's case-management system and the regulator's reporting channel, with outcomes fed back to the outcome table."},
]

SCALABILITY: list[dict] = [
    {"topic": "Millions of transactions", "prototype": "92 rows; the queue reads them all on each load.",
     "approach": "Precompute per-alert aggregates (counts, credit / debit totals, flagged share, counterparty keys) at ingest; the queue reads those and the case page reads one alert's rows. Cluster the transaction table by alert and date; never scan it per page load."},
    {"topic": "Priority and evidence-quality scores", "prototype": "Computed in Python on read.",
     "approach": "Compute at ingest or on change and store with the policy version. Page the queue and sort in SQL. Re-score only when an input changes."},
    {"topic": "Cross-case relationship links", "prototype": "String match over the other 15 cases in memory.",
     "approach": "A counterparty-key index (normalised key → cases) maintained at ingest; link lookups are index reads. Entity resolution replaces string equality before real data."},
    {"topic": "AI enrichment load", "prototype": "One synchronous call per click, 40–120 s.",
     "approach": "Queue enrichment for the top-priority cases only; cap concurrency; cache by evidence fingerprint so an unchanged case is not re-run; bound spend with a resource monitor."},
    {"topic": "Regulatory documents", "prototype": "49 rules in one table; a Cortex Search service over 36.",
     "approach": "Partition the corpus by authority and version; keep rule metadata (lifecycle) separate from text; index text for search only; version every rule and keep superseded rules queryable but excluded from conclusions."},
    {"topic": "Ledger and audit export", "prototype": "Reconciliation reads every row.",
     "approach": "Reconcile incrementally from the last verified chain head; export per decision or per minute; verify packages in the external store on a schedule."},
]

KNOWN_LIMITATIONS: list[str] = [
    "This application does not detect fraud, give legal advice, file reports or verify regulatory compliance. It supports a human decision and records why.",
    "All data is synthetic. No real personal data may be loaded: masking is opt-in and off by default, there is no row-access policy and no pseudonymisation.",
    "Two decisions submitted at the same moment on an alert that has none can both be recorded: the ledger is append-only, Snowflake does not lock concurrent inserts and uniqueness is not enforced on this account. Both rows are kept, each records how many decisions the ledger held for that alert when it was written, and the reconciliation reports the pair as CONCURRENT_DECISIONS. They are detected, not prevented.",
    "No regulatory rule has been independently verified against its live primary source (0 of 49). PROVEN means a primary source is cited by the corpus author.",
    "The Snowflake ledger is append-only for the application role. It is not immutable: the owner role can delete rows, and rows never exported cannot be shown missing. The audit export is opt-in and not provisioned in the live account; the local write-once sink is a simulation.",
    "The effects of evidence-quality findings, the priority weights and the severity table are product policy, not regulatory requirements. Findings read from free text are pattern matches.",
    "Hands-on investigation time and analyst touch time cannot be measured from the ledger. No baseline exists, so no business improvement is claimed. Precision, recall and F1 are computed against synthetic scenario labels.",
    "The reporting deadline is scored only where a suspicion time was recorded (Mon–Fri, no holiday calendar), from the optional case-feed field or a time recorded with an earlier decision. The seeded feed supplies one for 9 of the 19 alerts; the other 10 have no clock, and none is invented.",
    "Shared device, address and document links cannot be tested: the dataset holds no such identifiers. Counterparty matching is string equality after a stated normalisation, not entity resolution.",
    "A clean-room environment (name suffix CR2) was redeployed from the 6 October code, and its hosted app was byte-identical to the source at that moment (evidence/cleanroom-2026-10-06). The pre-existing production database was migrated and redeployed by its owner on 6 October; no run record of that is kept in this repository. What Snowsight renders, and what st.user and CURRENT_USER() return there, have never been verified. Snowflake documents st.user.user_name and st.user.email as the viewer's, but this deployment has not been seen to supply them.",
    "The live suites (tests/test_skills_smoke.py, tests/test_live_e2e.py) were run in full against the clean room as the owner and the app role on 6 October with no failures (evidence/cleanroom-2026-10-06/live_suites_rerun.log); they were not run against the production database. The first fresh deploy failed on an unescaped apostrophe in a table comment that no offline test could see; it is fixed and guarded. On the pre-existing production database the opt-in migrations 08 and 09 were first applied in the wrong order (the schema step stopped because a column that migration 09 adds did not exist yet); the order is now in DEPLOY.md. Behaviour under concurrent users was not exercised.",
    "Cortex latency is long and variable (11–120 s per call observed, two timeouts in 19); behaviour under concurrent users has not been tested.",
    "No penetration test, supply-chain scan or Streamlit content-security-policy review has been done.",
]

ROADMAP: list[dict] = [
    {"priority": "P0", "item": "SSO + MFA, network policies, and removal of the typed decision-maker path", "why": "Attribution and perimeter are the precondition for any real data."},
    {"priority": "P0", "item": "Independent write-once archive of the audit export (separate account, compliance-mode retention) and scheduled verification", "why": "Closes the owner-role deletion risk; until then the ledger is not immutable."},
    {"priority": "P0", "item": "Independent verification of the PROVEN rules against their live primary sources, by a reviewer who is not the owner", "why": "0 of 49 rules are verified; the whole basis rests on citation, not re-checking."},
    {"priority": "P1", "item": "Masking, row-access policies, pseudonymised prompts and restricted cross-region inference", "why": "Prerequisite for loading real customer data."},
    {"priority": "P1", "item": "Entity-resolution / device-intelligence feed (attribute rows) for shared-device, address and document links", "why": "Turns the relationship view from string matching into real linkage."},
    {"priority": "P1", "item": "Outcome feed (QA review, FIU-IND queries, STR returned for rework) written by a second-line process", "why": "Turns the false-positive and rework proxies into measurements."},
    {"priority": "P1", "item": "Server-side case-open and decision timestamps for hands-on investigation time; a baseline period before any improvement is claimed", "why": "Business value cannot be claimed without a baseline."},
    {"priority": "P2", "item": "Streaming ingestion, stored incremental scores and a paged queue", "why": "Scale to millions of transactions."},
    {"priority": "P2", "item": "Asynchronous AI enrichment worker with spend caps", "why": "Removes the 40–120 s wait from the officer's path."},
    {"priority": "P2", "item": "Maker-checker approval for FILE decisions; a corpus approver distinct from the corpus owner", "why": "Separation of duties."},
    {"priority": "P3", "item": "Case-management and regulator-channel integration; SIEM export; resource monitors; disaster-recovery replication", "why": "Operational completeness."},
    {"priority": "P3", "item": "Penetration test, CSP review, supply-chain scanning, incident-response runbooks", "why": "Assurance."},
]


def by_tier(items: list[dict]) -> dict[str, list[dict]]:
    return {t: [i for i in items if i["status"] == t] for t in TIERS}


def summary() -> dict:
    """Counts by tier for the capabilities, the checklist and the architecture stages."""
    return {"capabilities": {t: len(v) for t, v in by_tier(CAPABILITIES).items()}, "checklist": {t: len(v) for t, v in by_tier(PRODUCTION_CHECKLIST).items()},
            "architecture": {t: len(v) for t, v in by_tier(ARCHITECTURE_STAGES).items()}}
