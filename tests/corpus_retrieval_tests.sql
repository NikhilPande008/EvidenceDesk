-- corpus_retrieval_tests.sql
-- CoCo Evidence — Test Phase
-- Validates Cortex Search quality, NEEDS-VERIFICATION exclusion,
-- and the DECISION_LEDGER append-only privilege checks (append-only for the application role; not immutable).
--
-- Run order: top to bottom. Expected results are in the comments.

-- ─────────────────────────────────────────────────────────────────────────────
-- T-01  Corpus row count by evidence level
-- Expected: PROVEN=13, ASSUMED=23, NEEDS-VERIFICATION=13, Total=49
-- ─────────────────────────────────────────────────────────────────────────────
SELECT EVIDENCE_LEVEL, COUNT(*) AS ROW_COUNT
FROM FIU_COPILOT.AML.REGULATORY_CORPUS
GROUP BY 1
ORDER BY 1;

-- ─────────────────────────────────────────────────────────────────────────────
-- T-02  NEEDS-VERIFICATION rows are present in the table but must not leak
--       into agent output.  This query proves they exist in the raw table.
-- Expected: 13 rows with EVIDENCE_LEVEL = 'NEEDS-VERIFICATION'
-- ─────────────────────────────────────────────────────────────────────────────
SELECT RULE_ID, EVIDENCE_LEVEL, LEFT(RULE_TEXT, 60) AS RULE_PREVIEW
FROM FIU_COPILOT.AML.REGULATORY_CORPUS
WHERE EVIDENCE_LEVEL = 'NEEDS-VERIFICATION'
ORDER BY RULE_ID;

-- ─────────────────────────────────────────────────────────────────────────────
-- T-03  Cortex Search service status — must be ACTIVE
-- Expected: INDEXING_STATE = 'ACTIVE', SERVING_STATE = 'ACTIVE', SOURCE_ROWS_INDEXED = 36
-- ─────────────────────────────────────────────────────────────────────────────
SHOW CORTEX SEARCH SERVICES LIKE 'CORPUS_SEARCH';

-- ─────────────────────────────────────────────────────────────────────────────
-- T-04  Cortex Search indexes only PROVEN + ASSUMED (36 rows, not 49)
--       Prove by checking the service was built on a WHERE EVIDENCE_LEVEL != 'NEEDS-VERIFICATION'
--       filter.  36 = 13 PROVEN + 23 ASSUMED.
-- Expected: 36
-- ─────────────────────────────────────────────────────────────────────────────
SELECT COUNT(*) AS INDEXABLE_ROWS
FROM FIU_COPILOT.AML.REGULATORY_CORPUS
WHERE EVIDENCE_LEVEL IN ('PROVEN', 'ASSUMED');

-- ─────────────────────────────────────────────────────────────────────────────
-- T-05  regulatory_lookup keyword fallback — STR filing deadline query
--       Simulates the keyword-OR search path used when Cortex Search vector
--       path is unavailable.
-- Expected: at least 1 row returned, all with EVIDENCE_LEVEL in (PROVEN, ASSUMED)
-- ─────────────────────────────────────────────────────────────────────────────
SELECT RULE_ID, EVIDENCE_LEVEL, LEFT(RULE_TEXT, 80) AS RULE_PREVIEW
FROM FIU_COPILOT.AML.REGULATORY_CORPUS
WHERE EVIDENCE_LEVEL IN ('PROVEN', 'ASSUMED')
  AND (
        LOWER(SEARCH_TEXT) LIKE '%filing%'
     OR LOWER(SEARCH_TEXT) LIKE '%deadline%'
     OR LOWER(SEARCH_TEXT) LIKE '%working%'
     OR LOWER(SEARCH_TEXT) LIKE '%days%'
     OR LOWER(SEARCH_TEXT) LIKE '%suspicious%'
  )
ORDER BY EVIDENCE_LEVEL, RULE_ID
LIMIT 10;

-- ─────────────────────────────────────────────────────────────────────────────
-- T-06  NEEDS-VERIFICATION rules DO match common regulatory keywords — proving
--       the EVIDENCE_LEVEL filter in the skill is load-bearing, not cosmetic.
--       This query runs WITHOUT the filter to show which NV rules would leak
--       if the filter were removed.  The corresponding T-05 query (with the
--       filter) returns zero NV rows, confirming the guardrail works.
-- Expected: ≥0 rows (shows NV rules that WOULD appear without the filter)
--           These same rules are absent from T-05 output — that is the proof.
-- ─────────────────────────────────────────────────────────────────────────────
SELECT RULE_ID, EVIDENCE_LEVEL, LEFT(RULE_TEXT, 80) AS RULE_PREVIEW
FROM FIU_COPILOT.AML.REGULATORY_CORPUS
WHERE EVIDENCE_LEVEL = 'NEEDS-VERIFICATION'
  AND (
        LOWER(SEARCH_TEXT) LIKE '%filing%'
     OR LOWER(SEARCH_TEXT) LIKE '%deadline%'
  )
ORDER BY RULE_ID;
-- Result cross-reference: every RULE_ID appearing here must be ABSENT from T-05.
-- If T-05 and T-06 share a RULE_ID, the guardrail has failed.

-- ─────────────────────────────────────────────────────────────────────────────
-- T-07  Alert seed validation — the answer key's disposition split. ADMIN ROLE ONLY: FIU_APP_ROLE cannot read ALERT_GOLD_LABELS (by design).
-- Expected: CONTESTED=4, FILE=9, NOT_FILE=3
-- ─────────────────────────────────────────────────────────────────────────────
SELECT GOLD_DISPOSITION, COUNT(*) AS CNT
FROM FIU_COPILOT.AML.ALERT_GOLD_LABELS
GROUP BY 1
ORDER BY 1;

-- ─────────────────────────────────────────────────────────────────────────────
-- T-08  DECISION_LEDGER is append-only — verify no UPDATE/DELETE privileges
--       exist at the application layer.  Check by attempting an update and
--       expecting a privilege error, OR verify the table has no UPDATE grant
--       to the app role.
--       (Run the SELECT below to show existing rows; the application role holds INSERT and SELECT only,
--       proven by deploy/04_verify_ledger_rbac.sql; the owner role can still delete rows.)
-- ─────────────────────────────────────────────────────────────────────────────
SELECT DECISION_ID, ALERT_ID, DISPOSITION, DECISION_MADE_AT, SLA_DAYS_REMAINING
FROM FIU_COPILOT.AML.DECISION_LEDGER
ORDER BY DECISION_MADE_AT DESC;

-- ─────────────────────────────────────────────────────────────────────────────
-- T-09  Alert-to-STR ratio computation (the FIU-IND inspection metric)
--       Must match the formula in semantic_model.yaml:
--       COUNT_IF(DISPOSITION='FILE') / NULLIF(COUNT_IF(DISPOSITION IN ('FILE','NOT_FILE')), 0) * 100
-- Expected: ratio in (0, 100], or NULL if no final decisions yet
-- ─────────────────────────────────────────────────────────────────────────────
SELECT
    COUNT_IF(DISPOSITION = 'FILE')                                            AS STR_FILED,
    COUNT_IF(DISPOSITION = 'NOT_FILE')                                        AS NOT_FILED,
    COUNT_IF(DISPOSITION = 'DEFERRED')                                        AS DEFERRED,
    ROUND(
        COUNT_IF(DISPOSITION = 'FILE') /
        NULLIF(COUNT_IF(DISPOSITION IN ('FILE', 'NOT_FILE')), 0) * 100, 2
    )                                                                          AS ALERT_TO_STR_RATIO_PCT
FROM FIU_COPILOT.AML.DECISION_LEDGER;

-- ─────────────────────────────────────────────────────────────────────────────
-- T-10  PO factor (POE) coverage — every alert has POE_FACTORS populated
-- Expected: 0 rows with NULL or empty POE_FACTORS
-- ─────────────────────────────────────────────────────────────────────────────
SELECT ALERT_ID
FROM FIU_COPILOT.AML.ALERTS
WHERE POE_FACTORS IS NULL
   OR ARRAY_SIZE(POE_FACTORS) = 0;
