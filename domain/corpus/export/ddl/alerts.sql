-- ALERTS — synthetic alert queue seeded from Phase 1 gold-standard scenarios
-- Each row represents one live alert the PO must review and dispose.
-- The scenario author's expected dispositions are NOT stored here: they live in ALERT_GOLD_LABELS (eval_labels.sql), which the application
-- role cannot read. The PO records their actual decision in DECISION_LEDGER.

CREATE TABLE IF NOT EXISTS ALERTS (
    ALERT_ID             VARCHAR(20)   NOT NULL,      -- e.g. ALERT-01
    SCENARIO_ID          VARCHAR(5)    NOT NULL,      -- links to Phase 1 scenario file
    CUSTOMER_REF         VARCHAR(20)   NOT NULL,      -- anonymised customer ID
    ALERT_DATE           DATE          NOT NULL,      -- synthetic alert generation date
    ALERT_TYPE           VARCHAR(100)  NOT NULL,      -- e.g. MULE_PASSTHROUGH, STRUCTURING
    SIGNAL_SOURCE        VARCHAR(100),                -- I4C | MULE_HUNTER | INTERNAL_RULE | DPIP
    ACCOUNT_TYPE         VARCHAR(50),                 -- SAVINGS | CURRENT | NRO | MF
    CUSTOMER_PROFILE     VARCHAR(500),                -- one-line KYC summary
    ALERT_AMOUNT_INR     NUMBER(15,2),                -- total suspicious amount in INR
    ALERT_NARRATIVE      TEXT,                        -- brief pattern description for PO queue
    RFI_TRIGGERS         VARIANT,                     -- JSON array of RFI IDs
    POE_FACTORS          VARIANT,                     -- JSON array of POE corpus IDs triggered
    RULES_CITED          VARIANT,                     -- JSON array of corpus rule IDs
    ALERT_STATUS         VARCHAR(20)   DEFAULT 'OPEN', -- OPEN | REVIEWED | CLOSED
    CONSTRAINT CHK_ALERT_STATUS CHECK (ALERT_STATUS IN ('OPEN', 'REVIEWED', 'CLOSED')),
    ASSIGNED_PO          VARCHAR(100),
    SUSPICION_FORMED_AT  TIMESTAMP_TZ,                -- when the upstream case system says suspicion formed (starts the 7-WD clock); NULL if not supplied
    CREATED_AT           TIMESTAMP_TZ  DEFAULT CURRENT_TIMESTAMP(),
    CONSTRAINT PK_ALERTS PRIMARY KEY (ALERT_ID)
);

COMMENT ON COLUMN ALERTS.SUSPICION_FORMED_AT IS
    'Optional feed field: when the upstream investigator or case system recorded that suspicion had formed. It starts the 7-working-day STR clock. NULL when the feed did not supply it; the application never infers it from ALERT_DATE, and the earliest SUSPICION_FORMED_AT in DECISION_LEDGER takes precedence over it.';

COMMENT ON TABLE ALERTS IS
    'Synthetic AML alert queue: 19 alerts (15 Phase-1 gold-standard scenarios, the ALERT-16 twin and three Gulf-remittance alerts, ALERT-17 to ALERT-19). The expected dispositions are held apart in ALERT_GOLD_LABELS, which the application role cannot read. ALERT_STATUS is seed-time only; the effective status is derived from DECISION_LEDGER by view ALERTS_CURRENT.';


-- ─── SEED DATA ──────────────────────────────────────────────────────────────
-- Seed rows live in ONE place: scripts/setup_alerts.py (idempotent MERGE — 19 alerts:
-- 15 gold-standard scenarios, ALERT-16 (the same-signal twin of ALERT-01) and ALERT-17 to ALERT-19 (Gulf remittances) — plus their 92
-- TRANSACTIONS rows). This file is DDL only: an INSERT here would silently DUPLICATE alerts on a
-- re-run (Snowflake PRIMARY KEY constraints are informational, not enforced).
--
-- Verification (after scripts/setup_alerts.py):
--   SELECT GOLD_DISPOSITION, COUNT(*) FROM ALERT_GOLD_LABELS GROUP BY 1 ORDER BY 1;   -- admin role only: CONTESTED 4, FILE 10, NOT_FILE 5
--   SELECT COUNT(*) FROM ALERTS;                                            -- 19
--   SELECT COUNT(*) FROM TRANSACTIONS;                                      -- 92
