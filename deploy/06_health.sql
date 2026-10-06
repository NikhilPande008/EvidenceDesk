-- 06_health.sql — READ-ONLY health / proof queries. Paste into a Snowsight worksheet, or: python3 scripts/deploy_snowflake.py (health step).
-- Run as FIU_APP_ROLE. Every statement is SELECT / SHOW / LIST / DESC / USE — nothing here writes, and a test refuses the file if that changes.
--
-- Every section ends in ONE of three states (the same vocabulary as scripts/health_check.py):
--   HEALTHY      the query showed the property holds, now
--   UNAVAILABLE  the query showed it does NOT hold
--   UNVERIFIED   the query cannot establish it — shown as UNVERIFIED rather than guessed as healthy
-- SQL cannot do two things scripts/health_check.py does: download the hosted code / semantic model and compare their BYTES with the
-- repository, and run the (billed) Cortex Complete / Analyst probes. Those sections say UNVERIFIED here, on purpose.
USE ROLE FIU_APP_ROLE;
USE SECONDARY ROLES NONE;
USE WAREHOUSE FIU_WH;

-- 1. APP ROLE — session isolation (secondary roles must be NONE, otherwise no least-privilege claim holds)
SELECT '1 session' AS CHECK_NAME, CURRENT_ROLE() AS ROLE, CURRENT_SECONDARY_ROLES()::VARCHAR AS SECONDARY_ROLES,
       IFF(CURRENT_ROLE() <> 'FIU_APP_ROLE', 'UNVERIFIED',
           IFF(CURRENT_SECONDARY_ROLES()::VARCHAR ILIKE '%"roles":""%', 'HEALTHY', 'UNAVAILABLE')) AS STATUS;

-- 2. APP ROLE — active grants, compared with the exact least-privilege set of deploy/03_grants.sql.
--    Platform-owned objects of the role's own container-runtime Streamlit app (ownership of the app + its internal stage, service usage) are counted separately.
SHOW GRANTS TO ROLE FIU_APP_ROLE;
WITH g AS (
  SELECT "privilege" AS PRIV, "granted_on" AS ON_TYPE, "name" AS NAME,
         (("granted_on" = 'STREAMLIT' AND "privilege" = 'OWNERSHIP' AND "name" = 'FIU_COPILOT.AML.FIU_AML_COPILOT')
          OR ("granted_on" = 'STAGE' AND "privilege" = 'OWNERSHIP' AND "name" LIKE 'FIU_COPILOT.AML."Streamlit_internal_%')
          OR ("granted_on" IN ('SERVICE', 'SERVICE ROLE') AND "privilege" IN ('USAGE', 'MONITOR') AND "name" LIKE 'FIU_COPILOT.AML.STPLATSTREAMLIT%')) AS PLATFORM,
         (("privilege", "granted_on", "name") IN (
           ('USAGE','WAREHOUSE','FIU_WH'), ('USAGE','DATABASE','FIU_COPILOT'), ('USAGE','SCHEMA','FIU_COPILOT.AML'),
           ('USAGE','DATABASE_ROLE','SNOWFLAKE.CORTEX_USER'), ('USAGE','CORTEX_SEARCH_SERVICE','FIU_COPILOT.AML.CORPUS_SEARCH'),
           ('READ','STAGE','FIU_COPILOT.AML.SEMANTIC_STAGE'),
           ('INSERT','TABLE','FIU_COPILOT.AML.DECISION_LEDGER'), ('SELECT','TABLE','FIU_COPILOT.AML.DECISION_LEDGER'),
           ('SELECT','TABLE','FIU_COPILOT.AML.REGULATORY_CORPUS'), ('SELECT','TABLE','FIU_COPILOT.AML.ALERTS'), ('SELECT','TABLE','FIU_COPILOT.AML.TRANSACTIONS'),
           ('SELECT','VIEW','FIU_COPILOT.AML.ALERT_TXN_SUMMARY'), ('SELECT','VIEW','FIU_COPILOT.AML.ALERTS_CURRENT'),
           ('SELECT','VIEW','FIU_COPILOT.AML.DECISION_LEDGER_INTEGRITY_V'))) AS EXPECTED,
         -- read access to the audit-export store (deploy/05_audit_export.sql) and the outcome feed (deploy/07_decision_outcomes.sql), each given only if that opt-in store is provisioned: allowed, never required
         (("privilege", "granted_on", "name") IN (('USAGE','SCHEMA','FIU_COPILOT.AUDIT'), ('SELECT','TABLE','FIU_COPILOT.AUDIT.LEDGER_EXPORT'), ('SELECT','TABLE','FIU_COPILOT.AUDIT.DECISION_OUTCOMES'))) AS AUDIT_OPTIONAL
  FROM TABLE(RESULT_SCAN(LAST_QUERY_ID()))
), led AS (
  SELECT LISTAGG(DISTINCT PRIV, ',') WITHIN GROUP (ORDER BY PRIV) AS PRIVS FROM g WHERE ON_TYPE = 'TABLE' AND NAME = 'FIU_COPILOT.AML.DECISION_LEDGER'
)
SELECT '2 grants' AS CHECK_NAME,
       COUNT_IF(NOT g.PLATFORM)                                  AS DATA_AND_OTHER_GRANTS,
       COUNT_IF(g.PLATFORM)                                      AS PLATFORM_OWNED_APP_OBJECTS,
       COUNT_IF(NOT g.PLATFORM AND NOT g.EXPECTED AND NOT g.AUDIT_OPTIONAL) AS BEYOND_LEAST_PRIVILEGE,
       COUNT_IF(g.AUDIT_OPTIONAL)                                AS AUDIT_EXPORT_READ_GRANTS,
       COUNT_IF(g.PRIV LIKE 'CREATE%')                           AS CREATE_PRIVILEGES,
       ANY_VALUE(led.PRIVS)                                      AS LEDGER_PRIVILEGES,
       IFF(COUNT_IF(NOT g.PLATFORM AND NOT g.EXPECTED AND NOT g.AUDIT_OPTIONAL) = 0 AND COUNT_IF(g.PRIV LIKE 'CREATE%') = 0 AND ANY_VALUE(led.PRIVS) = 'INSERT,SELECT',
           'HEALTHY', 'UNAVAILABLE')                             AS STATUS
FROM g CROSS JOIN led;

-- 3. LEDGER — who holds ANY privilege on it (expected: the owner role, the app role INSERT+SELECT, ACCOUNTADMIN, the audit role SELECT only if provisioned; never PUBLIC)
SHOW GRANTS ON TABLE FIU_COPILOT.AML.DECISION_LEDGER;
SELECT '3 ledger grantees' AS CHECK_NAME,
       LISTAGG("grantee_name" || ':' || "privilege", ', ') WITHIN GROUP (ORDER BY "grantee_name", "privilege") AS GRANTS,
       IFF(COUNT_IF("grantee_name" NOT IN ('FIU_ADMIN_ROLE', 'FIU_APP_ROLE', 'ACCOUNTADMIN', 'FIU_AUDIT_ROLE')) = 0
           AND COUNT_IF("grantee_name" = 'FIU_APP_ROLE' AND "privilege" NOT IN ('INSERT', 'SELECT')) = 0
           AND COUNT_IF("grantee_name" = 'FIU_AUDIT_ROLE' AND "privilege" <> 'SELECT') = 0, 'HEALTHY', 'UNAVAILABLE') AS STATUS
FROM TABLE(RESULT_SCAN(LAST_QUERY_ID()));

-- 4. CORTEX SEARCH — service status and indexed row count (36 = 13 PROVEN + 23 ASSUMED; NEEDS-VERIFICATION is excluded at index time)
SHOW CORTEX SEARCH SERVICES LIKE 'CORPUS_SEARCH' IN SCHEMA FIU_COPILOT.AML;
SELECT '4 search service' AS CHECK_NAME, "indexing_state" AS INDEXING, "serving_state" AS SERVING, "source_data_num_rows" AS ROWS_INDEXED, "target_lag" AS TARGET_LAG,
       IFF("indexing_state" = 'ACTIVE' AND "serving_state" = 'ACTIVE' AND "source_data_num_rows" = 36, 'HEALTHY', 'UNAVAILABLE') AS STATUS
FROM TABLE(RESULT_SCAN(LAST_QUERY_ID()));

-- 4b. CORTEX SEARCH — it actually ANSWERS (serving, not just state); a result outside PROVEN/ASSUMED would be a defect
SELECT '4b search probe' AS CHECK_NAME, ARRAY_SIZE(r.v:results) AS RESULTS, ARRAY_TO_STRING(TRANSFORM(r.v:results, x -> x:RULE_ID::VARCHAR || ':' || x:EVIDENCE_LEVEL::VARCHAR), ', ') AS TOP_RULES,
       IFF(ARRAY_SIZE(r.v:results) > 0 AND ARRAY_SIZE(FILTER(r.v:results, x -> x:EVIDENCE_LEVEL::VARCHAR NOT IN ('PROVEN', 'ASSUMED'))) = 0, 'HEALTHY', 'UNAVAILABLE') AS STATUS
FROM (SELECT PARSE_JSON(SNOWFLAKE.CORTEX.SEARCH_PREVIEW('FIU_COPILOT.AML.CORPUS_SEARCH',
        '{"query": "STR filing deadline 7 working days", "columns": ["RULE_ID", "EVIDENCE_LEVEL"], "limit": 3}')) AS v) r;

-- 5. CORPUS — version and counts (domain/corpus/manifest.yaml: v1.1.1 · PROVEN 13 · ASSUMED 23 · NEEDS-VERIFICATION 13)
SELECT '5 corpus' AS CHECK_NAME, MAX(CORPUS_VERSION) AS CORPUS_VERSION, COUNT(DISTINCT CORPUS_VERSION) AS VERSIONS,
       COUNT_IF(EVIDENCE_LEVEL = 'PROVEN') AS PROVEN, COUNT_IF(EVIDENCE_LEVEL = 'ASSUMED') AS ASSUMED, COUNT_IF(EVIDENCE_LEVEL = 'NEEDS-VERIFICATION') AS NEEDS_VERIFICATION,
       COUNT_IF(SOURCE_AUTHORITY IS NULL OR REVIEW_STATUS IS NULL OR OWNER IS NULL) AS GOVERNANCE_NULLS,
       IFF(COUNT(DISTINCT CORPUS_VERSION) = 1 AND MAX(CORPUS_VERSION) = '1.1.1' AND COUNT_IF(EVIDENCE_LEVEL = 'PROVEN') = 13 AND COUNT_IF(EVIDENCE_LEVEL = 'ASSUMED') = 23
           AND COUNT_IF(EVIDENCE_LEVEL = 'NEEDS-VERIFICATION') = 13 AND COUNT_IF(SOURCE_AUTHORITY IS NULL OR REVIEW_STATUS IS NULL OR OWNER IS NULL) = 0,
           'HEALTHY', 'UNAVAILABLE') AS STATUS
FROM FIU_COPILOT.AML.REGULATORY_CORPUS;

-- 6. SEMANTIC MODEL — is it on the stage? (byte-identity with the repository needs scripts/health_check.py: LIST shows the ENCRYPTED size/md5)
LIST @FIU_COPILOT.AML.SEMANTIC_STAGE;
SELECT '6 semantic model' AS CHECK_NAME, COUNT(*) AS FILES, MAX("last_modified") AS LAST_MODIFIED,
       IFF(COUNT_IF("name" LIKE '%semantic_model.yaml') = 0, 'UNAVAILABLE', 'UNVERIFIED') AS STATUS,
       'present on the stage; identical-to-repository is NOT established by SQL (run scripts/health_check.py)' AS NOTE
FROM TABLE(RESULT_SCAN(LAST_QUERY_ID()));

-- 7. LEDGER — integrity census (per-row hashes recomputed from the STORED row). TAMPERED → UNAVAILABLE; legacy rows (no hash) → UNVERIFIED.
SELECT '7 ledger census' AS CHECK_NAME, COUNT(*) AS ROWS_TOTAL, COUNT_IF(INTEGRITY_STATUS = 'INTACT') AS INTACT, COUNT_IF(INTEGRITY_STATUS = 'TAMPERED') AS TAMPERED,
       COUNT_IF(INTEGRITY_STATUS = 'LEGACY_UNHASHED') AS LEGACY_UNHASHED,
       IFF(COUNT_IF(INTEGRITY_STATUS = 'TAMPERED') > 0, 'UNAVAILABLE', IFF(COUNT_IF(INTEGRITY_STATUS = 'LEGACY_UNHASHED') > 0, 'UNVERIFIED', 'HEALTHY')) AS STATUS
FROM FIU_COPILOT.AML.DECISION_LEDGER_INTEGRITY_V;

-- 8. LATEST RECONCILIATION — the per-row part, in SQL (the full reconciliation incl. provenance completeness: scripts/audit_ledger.py report).
SELECT '8 reconciliation' AS CHECK_NAME, (SELECT COUNT(*) FROM FIU_COPILOT.AML.DECISION_LEDGER) AS LEDGER_ROWS,
       (SELECT MAX(DECISION_MADE_AT) FROM FIU_COPILOT.AML.DECISION_LEDGER) AS LATEST_DECISION_AT,
       (SELECT COUNT(*) FROM FIU_COPILOT.AML.DECISION_LEDGER_INTEGRITY_V WHERE INTEGRITY_STATUS = 'TAMPERED') AS TAMPERED,
       CURRENT_TIMESTAMP() AS CHECKED_AT,
       'see section 7 for the status; provenance completeness needs scripts/audit_ledger.py report' AS NOTE;

-- 9. DELETION WITNESS — is the audit export provisioned? If not, DELETION OF LEDGER ROWS BY THE OWNER ROLE IS NOT DETECTABLE.
SELECT '9 deletion witness' AS CHECK_NAME, COUNT(*) AS AUDIT_SCHEMAS_VISIBLE_TO_THIS_ROLE,
       'UNVERIFIED' AS STATUS,
       IFF(COUNT(*) = 0, 'no audit export is visible to this role: owner-role deletion would NOT be detected (deploy/05_audit_export.sql)',
           'an audit schema is visible: reconcile it with scripts/audit_ledger.py report — SQL alone does not verify the hash chain') AS NOTE
FROM FIU_COPILOT.INFORMATION_SCHEMA.SCHEMATA WHERE SCHEMA_NAME = 'AUDIT';

-- 10. APPLICATION — the hosted app: owner, warehouse, runtime, deployment version. (Byte-identity of the code: scripts/health_check.py. What Snowsight RENDERED: no query can see it.)
SHOW STREAMLITS LIKE 'FIU_AML_COPILOT' IN SCHEMA FIU_COPILOT.AML;
SELECT '10 application' AS CHECK_NAME, "name" AS APP, "owner" AS OWNER, "query_warehouse" AS WAREHOUSE, "url_id" AS URL_ID, "created_on" AS CREATED_ON,
       IFF("owner" = 'FIU_APP_ROLE' AND "query_warehouse" = 'FIU_WH', 'UNVERIFIED', 'UNAVAILABLE') AS STATUS,
       'owner and warehouse are as designed; deployed-code identity and the rendered page are NOT established by SQL' AS NOTE
FROM TABLE(RESULT_SCAN(LAST_QUERY_ID()));
DESC STREAMLIT FIU_COPILOT.AML.FIU_AML_COPILOT;
LIST 'snow://streamlit/FIU_COPILOT.AML.FIU_AML_COPILOT/versions/live/';
