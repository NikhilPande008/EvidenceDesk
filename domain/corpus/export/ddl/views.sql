-- ALERTS_CURRENT — alert queue with workflow status DERIVED from the append-only ledger.
--
-- Why: the application role has INSERT+SELECT only (no UPDATE anywhere), so the app can no longer
-- flip ALERTS.ALERT_STATUS. The ledger is the single source of truth for "has this alert been
-- decided?"; this view exposes that as ALERT_STATUS for the UI and for Cortex Analyst.
--   REVIEWED  latest ledger decision is FILE / NOT_FILE / ESCALATE
--   DEFERRED  latest ledger decision is DEFERRED (still open work)
--   OPEN      no decision recorded
-- Run after alerts.sql and the DECISION_LEDGER DDL (regulatory_corpus.sql). Idempotent.

CREATE OR REPLACE VIEW ALERTS_CURRENT (
    ALERT_ID, SCENARIO_ID, CUSTOMER_REF, ALERT_DATE, ALERT_TYPE, SIGNAL_SOURCE, ACCOUNT_TYPE,
    CUSTOMER_PROFILE, ALERT_AMOUNT_INR, ALERT_NARRATIVE, RFI_TRIGGERS, POE_FACTORS, RULES_CITED,
    SUSPICION_FORMED_AT, ALERT_STATUS, ASSIGNED_PO, LAST_DISPOSITION, LAST_DECISION_AT
) AS
SELECT
    a.ALERT_ID, a.SCENARIO_ID, a.CUSTOMER_REF, a.ALERT_DATE, a.ALERT_TYPE, a.SIGNAL_SOURCE, a.ACCOUNT_TYPE,
    a.CUSTOMER_PROFILE, a.ALERT_AMOUNT_INR, a.ALERT_NARRATIVE, a.RFI_TRIGGERS, a.POE_FACTORS, a.RULES_CITED,
    a.SUSPICION_FORMED_AT,
    CASE WHEN d.DISPOSITION IN ('FILE', 'NOT_FILE', 'ESCALATE') THEN 'REVIEWED'
         WHEN d.DISPOSITION = 'DEFERRED'                        THEN 'DEFERRED'
         ELSE 'OPEN' END                                         AS ALERT_STATUS,
    a.ASSIGNED_PO,
    d.DISPOSITION                                                AS LAST_DISPOSITION,
    d.DECISION_MADE_AT                                           AS LAST_DECISION_AT
FROM ALERTS a
LEFT JOIN (
    SELECT ALERT_ID, DISPOSITION, DECISION_MADE_AT
    FROM DECISION_LEDGER
    QUALIFY ROW_NUMBER() OVER (PARTITION BY ALERT_ID ORDER BY DECISION_MADE_AT DESC) = 1
) d ON a.ALERT_ID = d.ALERT_ID;

COMMENT ON VIEW ALERTS_CURRENT IS
    'ALERTS + workflow status derived from the append-only DECISION_LEDGER (ALERTS.ALERT_STATUS is seed-time only and is never updated by the app).';
