-- ALERT_GOLD_LABELS: the answer key for the synthetic alerts, held APART from the application's reach.
--
-- Why a table of its own: a label in ALERTS or ALERTS_CURRENT is readable by the application role, and Cortex Analyst runs as that role, so an
-- officer could ask the copilot for "the correct answer" to the case in front of them. Here it is readable only by the owner/admin role.
-- There is deliberately NO grant on this table to FIU_APP_ROLE: deploy/03_grants.sql names every table the app role may read one by one (no
-- schema-wide or future grant), and deploy/04_verify_ledger_rbac.sql PROVES the denial (a failed read, and zero grants on this name).
-- Labels are used only offline, by scripts/eval_label_agreement.py and the tests, under an admin role.
-- Idempotent. Run after alerts.sql.

CREATE TABLE IF NOT EXISTS ALERT_GOLD_LABELS (
    ALERT_ID          VARCHAR(20)   NOT NULL,
    GOLD_DISPOSITION  VARCHAR(20)   NOT NULL,      -- FILE | NOT_FILE | CONTESTED
    LABEL_SOURCE      VARCHAR(100)  DEFAULT 'scenario author (synthetic)',
    LOADED_AT         TIMESTAMP_TZ  DEFAULT CURRENT_TIMESTAMP(),
    CONSTRAINT PK_ALERT_GOLD_LABELS PRIMARY KEY (ALERT_ID),
    CONSTRAINT CHK_GOLD_DISP CHECK (GOLD_DISPOSITION IN ('FILE', 'NOT_FILE', 'CONTESTED'))
);

COMMENT ON TABLE ALERT_GOLD_LABELS IS
    'Answer key for the 19 synthetic alerts (the scenario author''s labels, not adjudicated outcomes). NOT readable by FIU_APP_ROLE and absent from the semantic model, so neither the app nor Cortex Analyst can see it.';
