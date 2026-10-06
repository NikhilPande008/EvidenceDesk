-- REGULATORY_CORPUS + DECISION_LEDGER — Snowflake DDL
-- Source: domain/corpus/rules/*.yaml  →  scripts/load_corpus.py (MERGE)
-- Corpus version / snapshot date: domain/corpus/manifest.yaml (single source of truth; every row
-- carries CORPUS_VERSION, and each rule its own SNAPSHOT_DATE).
-- Run as FIU_ADMIN_ROLE (object owner) — see deploy/01_roles.sql. Idempotent: safe to re-run.

CREATE TABLE IF NOT EXISTS REGULATORY_CORPUS (
    -- Identity
    RULE_ID              VARCHAR(50)       NOT NULL,     -- e.g. STR-001, RFI-007
    CATEGORY             VARCHAR(100)      NOT NULL,     -- REPORTING_OBLIGATION | REPORT_STRUCTURE | ...
    SUBCATEGORY          VARCHAR(200),                   -- finer-grain label

    -- The regulatory fact
    RULE_TEXT            TEXT              NOT NULL,     -- the rule as stated in the source
    APPLIES_TO           VARIANT,                        -- JSON array of RE-type strings

    -- Source citation
    SOURCE_DOCUMENT      TEXT              NOT NULL,     -- document name + section
    SOURCE_URL           VARCHAR(1000),                  -- best-known URL; may be base URL
    SOURCE_URL_VERIFIED  BOOLEAN           DEFAULT FALSE, -- true = manually confirmed live
    SOURCE_SECTION       VARCHAR(500),                   -- section/clause reference
    SOURCE_ACCESSED_DATE DATE,                           -- null = not yet accessed

    -- Temporal
    EFFECTIVE_DATE       DATE,                           -- null if unknown
    SNAPSHOT_DATE        DATE              NOT NULL,     -- "as of" date for this entry
    LAST_VERIFIED        DATE,                           -- null = never verified by a person

    -- Governance (finding #4) — who stands behind the rule, and how far it has been checked
    SOURCE_AUTHORITY     VARCHAR(40),                    -- STATUTE | RBI_DIRECTION | FIU_IND_GUIDANCE | FIU_IND_PUBLICATION | INTERNATIONAL_STANDARD | INDUSTRY_PRACTICE | PRODUCT_COMPILED
    CORPUS_VERSION       VARCHAR(20),                    -- release containing this rule (manifest.yaml)
    REVIEW_STATUS        VARCHAR(20),                    -- DRAFT | AUTHOR_ASSERTED | VERIFIED | STALE (VERIFIED needs LAST_VERIFIED + VERIFIED_BY)
    OWNER                VARCHAR(200),                   -- accountable maintainer
    VERIFIED_BY          VARCHAR(200),                   -- reviewer who re-checked the live source; LAST_VERIFIED is the verified date
    SUPERSEDED_BY        VARCHAR(200),                   -- rule ID / instrument replacing this rule; non-null => never shown as current
    REPLACES             VARCHAR(500),                   -- instrument this rule replaces (e.g. STR-006 replaces FINnet direct upload)

    -- Claim audit
    EVIDENCE_LEVEL       VARCHAR(30)       NOT NULL,     -- PROVEN | ASSUMED | NEEDS-VERIFICATION
    CONSTRAINT CHK_EVIDENCE_LEVEL CHECK (
        EVIDENCE_LEVEL IN ('PROVEN', 'ASSUMED', 'NEEDS-VERIFICATION')
    ),

    -- Synthesis and gaps
    MY_SYNTHESIS         TEXT,                           -- PO-lens interpretation (not source)
    GAP_NOTES            TEXT,                           -- open verification tasks

    -- Cross-references
    RELATED_RULES        VARIANT,                        -- JSON array of RULE_ID strings

    -- Cortex Search input (computed)
    SEARCH_TEXT          TEXT AS (
        COALESCE(RULE_TEXT, '') || ' ' || COALESCE(MY_SYNTHESIS, '')
    ),

    -- Audit timestamps
    CREATED_AT           TIMESTAMP_TZ      DEFAULT CURRENT_TIMESTAMP(),
    UPDATED_AT           TIMESTAMP_TZ      DEFAULT CURRENT_TIMESTAMP(),

    CONSTRAINT PK_REGULATORY_CORPUS PRIMARY KEY (RULE_ID)
);

-- Migration for tables created before corpus 1.1.0 (no-ops on a fresh table).
ALTER TABLE REGULATORY_CORPUS ADD COLUMN IF NOT EXISTS SOURCE_AUTHORITY VARCHAR(40);
ALTER TABLE REGULATORY_CORPUS ADD COLUMN IF NOT EXISTS CORPUS_VERSION   VARCHAR(20);
ALTER TABLE REGULATORY_CORPUS ADD COLUMN IF NOT EXISTS REVIEW_STATUS    VARCHAR(20);
ALTER TABLE REGULATORY_CORPUS ADD COLUMN IF NOT EXISTS OWNER            VARCHAR(200);
ALTER TABLE REGULATORY_CORPUS ADD COLUMN IF NOT EXISTS VERIFIED_BY      VARCHAR(200);
ALTER TABLE REGULATORY_CORPUS ADD COLUMN IF NOT EXISTS SUPERSEDED_BY    VARCHAR(200);
ALTER TABLE REGULATORY_CORPUS ADD COLUMN IF NOT EXISTS REPLACES         VARCHAR(500);

-- Lifecycle (Phase 14, skills/corpus_lifecycle.py): when the owner last REVIEWED the rule, the review SLA, and the approval record.
-- All optional; the app reads them with a fallback, so a table that has not been migrated still works (they are reported NOT PROVISIONED).
-- LAST_VERIFIED (above) stays the date of the last INDEPENDENT re-check; LAST_REVIEWED is the owner's own review.
ALTER TABLE REGULATORY_CORPUS ADD COLUMN IF NOT EXISTS LAST_REVIEWED    DATE;
ALTER TABLE REGULATORY_CORPUS ADD COLUMN IF NOT EXISTS REVIEW_SLA_DAYS  NUMBER;
ALTER TABLE REGULATORY_CORPUS ADD COLUMN IF NOT EXISTS APPROVAL_STATUS  VARCHAR(20);
ALTER TABLE REGULATORY_CORPUS ADD COLUMN IF NOT EXISTS APPROVED_BY      VARCHAR(200);
ALTER TABLE REGULATORY_CORPUS ADD COLUMN IF NOT EXISTS APPROVED_ON      DATE;

COMMENT ON TABLE REGULATORY_CORPUS IS
    'Structured Indian AML regulatory knowledge corpus. Each row is a versioned, source-cited regulatory fact. EVIDENCE_LEVEL determines whether a row is surfaced in Cortex Search output — NEEDS-VERIFICATION rows are excluded by default. CORPUS_VERSION / snapshot: see domain/corpus/manifest.yaml. No row is REVIEW_STATUS=VERIFIED unless LAST_VERIFIED and VERIFIED_BY are set.';

COMMENT ON COLUMN REGULATORY_CORPUS.EVIDENCE_LEVEL IS
    'PROVEN: stated in primary source, URL expected to be confirmable. ASSUMED: widely accepted, consistent with source, not independently verified. NEEDS-VERIFICATION: material risk of being outdated or misremembered — do NOT surface in generated compliance output.';

COMMENT ON COLUMN REGULATORY_CORPUS.SEARCH_TEXT IS
    'Computed: RULE_TEXT + MY_SYNTHESIS. Used as the Cortex Search index column.';


-- ─── CORTEX SEARCH SERVICE ────────────────────────────────────────────────────
-- IF NOT EXISTS so a re-run of this script never rebuilds the index or drops its grants.
-- To change the definition: DROP CORTEX SEARCH SERVICE CORPUS_SEARCH; then re-run.
-- The service indexes whatever rows exist; load the corpus (scripts/load_corpus.py) and it
-- refreshes within TARGET_LAG (or: ALTER CORTEX SEARCH SERVICE CORPUS_SEARCH REFRESH).
-- Layer 1 NV filter: WHERE EVIDENCE_LEVEL IN ('PROVEN', 'ASSUMED') excludes
-- all NEEDS-VERIFICATION rows at index time, so they can never surface via search.
-- Layer 2 NV filter: regulatory_lookup skill adds the same WHERE clause to its
-- JOIN query as a defence-in-depth guardrail.

CREATE CORTEX SEARCH SERVICE IF NOT EXISTS CORPUS_SEARCH
  ON SEARCH_TEXT
  ATTRIBUTES RULE_ID, CATEGORY, EVIDENCE_LEVEL, SOURCE_DOCUMENT, SOURCE_URL, SNAPSHOT_DATE
  WAREHOUSE = FIU_WH
  TARGET_LAG = '1 hour'
  AS (
    SELECT
        RULE_ID,
        SEARCH_TEXT,
        CATEGORY,
        SUBCATEGORY,
        EVIDENCE_LEVEL,
        SOURCE_DOCUMENT,
        SOURCE_URL,
        SOURCE_URL_VERIFIED,
        SNAPSHOT_DATE
    FROM REGULATORY_CORPUS
    WHERE EVIDENCE_LEVEL IN ('PROVEN', 'ASSUMED')
  );


-- ─── DECISION_LEDGER (companion table) ───────────────────────────────────────
-- APPEND-ONLY, enforced at the DATABASE layer (not by convention):
--   * the application role FIU_APP_ROLE holds SELECT + INSERT only (deploy/03_grants.sql);
--     UPDATE / DELETE / TRUNCATE are never granted, and deploy/04_verify_ledger_rbac.sql PROVES the
--     denial by attempting all three as that role;
--   * the table is OWNED by FIU_ADMIN_ROLE (never by the app role);
--   * every row carries ROW_HASH — SHA-256 over all decision columns — recomputed by the view
--     DECISION_LEDGER_INTEGRITY_V from the STORED row (same SQL expression the INSERT used).
-- Residual risk (documented in SECURITY.md): the owner role can still alter data; ROW_HASH makes
-- in-place edits DETECTABLE, not impossible, and does not detect deleted rows.

CREATE TABLE IF NOT EXISTS DECISION_LEDGER (
    DECISION_ID          VARCHAR(50)       NOT NULL,     -- UUID or ULID
    ALERT_ID             VARCHAR(100)      NOT NULL,     -- source system alert reference
    CUSTOMER_REF         VARCHAR(200)      NOT NULL,     -- anonymised customer identifier
    DISPOSITION          VARCHAR(20)       NOT NULL,     -- FILE | NOT_FILE | ESCALATE | DEFERRED
    CONSTRAINT CHK_DISPOSITION CHECK (
        DISPOSITION IN ('FILE', 'NOT_FILE', 'ESCALATE', 'DEFERRED')
    ),
    DECISION_MAKER_ID    VARCHAR(200)      NOT NULL,     -- PO or delegated officer ID
    SUSPICION_FORMED_AT  TIMESTAMP_TZ,                   -- when suspicion arose (SLA clock start)
    DECISION_MADE_AT     TIMESTAMP_TZ      NOT NULL,     -- when the FILE/NOT-FILE was recorded
    SLA_DAYS_REMAINING   NUMBER,                         -- 7 working days (Mon–Fri) − elapsed working days
    RATIONALE_TEXT       TEXT              NOT NULL,     -- the documented reason / Ground of Suspicion (mandatory)
    RULES_CITED          VARIANT,                        -- JSON array of RULE_IDs relied upon
    POE_FACTORS_ASSESSED VARIANT,                        -- JSON: {factor_id: triggered|clear|insufficient_data}
    RFI_TRIGGERS         VARIANT,                        -- JSON array of RFI-NNN IDs triggered
    STR_REFERENCE        VARCHAR(200),                   -- FINGate STR reference if DISPOSITION=FILE
    METADATA_JSON        VARIANT,                        -- provenance for decision reconstruction (skills/ledger.py)
    ROW_HASH             VARCHAR(64),                    -- SHA-256 tamper evidence (see DECISION_LEDGER_INTEGRITY_V)
    CREATED_AT           TIMESTAMP_TZ      DEFAULT CURRENT_TIMESTAMP(),

    CONSTRAINT PK_DECISION_LEDGER PRIMARY KEY (DECISION_ID)
);

-- Migration for ledgers created before Phase 8 (no-ops on a fresh table).
ALTER TABLE DECISION_LEDGER ADD COLUMN IF NOT EXISTS METADATA_JSON VARIANT;
ALTER TABLE DECISION_LEDGER ADD COLUMN IF NOT EXISTS ROW_HASH VARCHAR(64);

COMMENT ON TABLE DECISION_LEDGER IS
    'Append-only AML disposition record. Every FILE / NOT_FILE / DEFERRED / ESCALATE decision is recorded with rationale, rules cited, SLA timestamp, full provenance (METADATA_JSON) and a SHA-256 ROW_HASH. The application role has INSERT+SELECT only; UPDATE/DELETE are denied by RBAC.';

-- Tamper-evidence: recompute the hash from the STORED row and compare. The expression is the SAME
-- one the recorder embeds in its INSERT (skills/ledger.py HASH_EXPR — tests/test_ledger.py fails if
-- they diverge). Rows written before the hash existed report LEGACY_UNHASHED (never 'INTACT').
CREATE OR REPLACE VIEW DECISION_LEDGER_INTEGRITY_V AS
SELECT
    DECISION_ID, ALERT_ID, DISPOSITION, DECISION_MADE_AT,
    ROW_HASH AS STORED_HASH,
    COMPUTED_HASH,
    IFF(ROW_HASH IS NULL, 'LEGACY_UNHASHED',
        IFF(ROW_HASH = COMPUTED_HASH, 'INTACT', 'TAMPERED')) AS INTEGRITY_STATUS
FROM (
    SELECT *, SHA2(TO_JSON(OBJECT_CONSTRUCT_KEEP_NULL('decision_id', DECISION_ID, 'alert_id', ALERT_ID, 'customer_ref', CUSTOMER_REF, 'disposition', DISPOSITION, 'decision_maker_id', DECISION_MAKER_ID, 'suspicion_formed_at', TO_VARCHAR(CONVERT_TIMEZONE('UTC', SUSPICION_FORMED_AT), 'YYYY-MM-DD"T"HH24:MI:SS.FF6'), 'decision_made_at', TO_VARCHAR(CONVERT_TIMEZONE('UTC', DECISION_MADE_AT), 'YYYY-MM-DD"T"HH24:MI:SS.FF6'), 'sla_days_remaining', SLA_DAYS_REMAINING, 'rationale_text', RATIONALE_TEXT, 'rules_cited', RULES_CITED, 'poe_factors_assessed', POE_FACTORS_ASSESSED, 'rfi_triggers', RFI_TRIGGERS, 'str_reference', STR_REFERENCE, 'metadata', METADATA_JSON)), 256) AS COMPUTED_HASH
    FROM DECISION_LEDGER
);

COMMENT ON VIEW DECISION_LEDGER_INTEGRITY_V IS
    'INTACT = stored ROW_HASH equals the hash recomputed from the stored row; TAMPERED = it does not; LEGACY_UNHASHED = row predates ROW_HASH. Detects edited rows only (not deleted rows).';
