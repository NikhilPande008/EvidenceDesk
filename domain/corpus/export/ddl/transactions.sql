-- TRANSACTIONS — per-alert transaction ledger (Phase 7, T1)
-- Source: gold-standard scenario transaction tables (domain/scenarios/*.md)
-- Purpose: gives the deterministic evidence layer real, queryable data.
--   * validate_gos_evidence checks GoS ₹ amounts against these rows
--   * suspicion_evaluator receives them as case_context["transactions"]
--   * evidence_txn_ids resolve to real TXN_IDs
--   * the Signal Brief and Cortex Analyst aggregate over them
-- Invariant (enforced by tests/test_transactions.py):
--   SUM(AMOUNT_INR) WHERE TXN_TYPE='CREDIT'  ==  ALERTS.ALERT_AMOUNT_INR  (±1%)
-- Synthetic data only.

CREATE TABLE IF NOT EXISTS TRANSACTIONS (
    TXN_ID           VARCHAR(20)   NOT NULL,      -- e.g. T01-1
    ALERT_ID         VARCHAR(20)   NOT NULL,      -- FK → ALERTS.ALERT_ID
    CUSTOMER_REF     VARCHAR(20)   NOT NULL,      -- anonymised customer / account holder
    TXN_DATE         DATE          NOT NULL,      -- value date
    TXN_TYPE         VARCHAR(10)   NOT NULL,      -- CREDIT | DEBIT
    AMOUNT_INR       NUMBER(15,2)  NOT NULL,      -- transaction amount in INR
    CHANNEL          VARCHAR(30),                 -- UPI | NEFT | RTGS | IMPS | CASH | SWIFT
    COUNTERPARTY     VARCHAR(200),                -- other side of the transaction
    IS_FLAGGED       BOOLEAN       DEFAULT FALSE, -- counterparty on a watchlist / I4C registry
    CREATED_AT       TIMESTAMP_TZ  DEFAULT CURRENT_TIMESTAMP(),

    CONSTRAINT CHK_TXN_TYPE CHECK (TXN_TYPE IN ('CREDIT', 'DEBIT')),
    CONSTRAINT PK_TRANSACTIONS PRIMARY KEY (TXN_ID),
    CONSTRAINT FK_TXN_ALERT FOREIGN KEY (ALERT_ID) REFERENCES ALERTS (ALERT_ID)
);

COMMENT ON TABLE TRANSACTIONS IS
    'Per-alert synthetic transaction ledger seeded from the Phase-1 gold-standard scenarios. This is the governed data the deterministic evidence gate (validate_gos_evidence) and the 11-factor suspicion assessment operate on. CREDIT rows for each alert sum to ALERTS.ALERT_AMOUNT_INR (within 1%).';

-- Analyst-friendly rollup (optional; used by the Signal Brief and Cortex Analyst)
CREATE OR REPLACE VIEW ALERT_TXN_SUMMARY AS
SELECT
    t.ALERT_ID,
    COUNT(*)                                             AS TXN_COUNT,
    SUM(IFF(t.TXN_TYPE = 'CREDIT', t.AMOUNT_INR, 0))     AS TOTAL_CREDIT_INR,
    SUM(IFF(t.TXN_TYPE = 'DEBIT',  t.AMOUNT_INR, 0))     AS TOTAL_DEBIT_INR,
    COUNT(DISTINCT t.COUNTERPARTY)                       AS DISTINCT_COUNTERPARTIES,
    SUM(IFF(t.IS_FLAGGED, 1, 0))                         AS FLAGGED_TXN_COUNT,
    MIN(t.TXN_DATE)                                      AS FIRST_TXN_DATE,
    MAX(t.TXN_DATE)                                      AS LAST_TXN_DATE
FROM TRANSACTIONS t
GROUP BY t.ALERT_ID;
