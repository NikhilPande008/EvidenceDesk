"""
setup_alerts.py — Create ALERTS + TRANSACTIONS tables and seed 19 synthetic alerts
(15 gold-standard scenarios, ALERT-16 the T8 same-signal legitimate twin of ALERT-01, and ALERT-17..19 three Gulf-remittance alerts written after the nexus rule was frozen).
Uses parameterised INSERT to avoid semicolon-in-string parsing issues.

Usage:
    python3 scripts/setup_alerts.py [--upsert]
"""

import sys
import json
import argparse
from datetime import datetime, time, timedelta, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(REPO_ROOT))
from skills.connection import (  # noqa: E402
    SnowflakeConfigError, SnowflakeConnectError, connect_from_env, load_env, missing_config,
)

# ── DDL (table only — no COMMENT, no INSERT) ──────────────────────────────────
CREATE_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS FIU_COPILOT.AML.ALERTS (
    ALERT_ID             VARCHAR(20)   NOT NULL,
    SCENARIO_ID          VARCHAR(5)    NOT NULL,
    CUSTOMER_REF         VARCHAR(20)   NOT NULL,
    ALERT_DATE           DATE          NOT NULL,
    ALERT_TYPE           VARCHAR(100)  NOT NULL,
    SIGNAL_SOURCE        VARCHAR(100),
    ACCOUNT_TYPE         VARCHAR(50),
    CUSTOMER_PROFILE     VARCHAR(500),
    ALERT_AMOUNT_INR     NUMBER(15,2),
    ALERT_NARRATIVE      TEXT,
    RFI_TRIGGERS         VARIANT,
    POE_FACTORS          VARIANT,
    RULES_CITED          VARIANT,
    SUSPICION_FORMED_AT  TIMESTAMP_TZ,
    ALERT_STATUS         VARCHAR(20)   DEFAULT 'OPEN',
    ASSIGNED_PO          VARCHAR(100),
    CREATED_AT           TIMESTAMP_TZ  DEFAULT CURRENT_TIMESTAMP(),
    CONSTRAINT PK_ALERTS PRIMARY KEY (ALERT_ID)
)
"""

# ── Seed data ──────────────────────────────────────────────────────────────────
ALERTS = [
    {
        "ALERT_ID":          "ALERT-01",
        "SCENARIO_ID":       "01",
        "CUSTOMER_REF":      "CUST-01",
        "ALERT_DATE":        "2026-08-18",
        "ALERT_TYPE":        "MULE_PASSTHROUGH",
        "SIGNAL_SOURCE":     "I4C",
        "ACCOUNT_TYPE":      "SAVINGS",
        "CUSTOMER_PROFILE":  "Data entry operator; Rs.28K/month declared; Low-risk; account 14 months old",
        "ALERT_AMOUNT_INR":  345000.00,
        "ALERT_NARRATIVE":   "Credits of Rs.3.45L (12x income) from unknown UPI handles; 98.8% immediately passed to counterparty flagged in I4C Suspect Registry (online gaming scam). Consistent salary-only baseline for 13 months prior.",
        "RFI_TRIGGERS":      ["RFI-001", "RFI-005"],
        "POE_FACTORS":       ["POE-003", "POE-005", "POE-007"],
        "RULES_CITED":       ["STR-001", "STR-002", "RFI-001", "RFI-005", "POE-003", "POE-005", "POE-007", "INS-001", "INS-002"],
        "GOLD_DISPOSITION":  "FILE",
        "ALERT_STATUS":      "OPEN",
    },
    {
        "ALERT_ID":          "ALERT-02",
        "SCENARIO_ID":       "02",
        "CUSTOMER_REF":      "CUST-02A",
        "ALERT_DATE":        "2026-08-20",
        "ALERT_TYPE":        "STRUCTURING",
        "SIGNAL_SOURCE":     "INTERNAL_RULE",
        "ACCOUNT_TYPE":      "SAVINGS",
        "CUSTOMER_PROFILE":  "Daily labourer; Rs.10K/month declared; 3 linked savings accounts at same branch",
        "ALERT_AMOUNT_INR":  420000.00,
        "ALERT_NARRATIVE":   "3 linked accounts each received cash deposits of Rs.9K-9.5K daily for 15 days (structuring rule: deposits below the CTR threshold). Rs.4.2L was then transferred by NEFT to a single current account at a different bank on day 16. No single account breaches the Rs.10L CTR threshold.",
        "RFI_TRIGGERS":      ["RFI-002"],
        "POE_FACTORS":       ["POE-003", "POE-005", "POE-009", "POE-010"],
        "RULES_CITED":       ["STR-001", "CTR-001", "CTR-003", "RFI-002", "POE-003", "POE-005", "POE-009", "POE-010"],
        "GOLD_DISPOSITION":  "FILE",
        "ALERT_STATUS":      "OPEN",
    },
    {
        "ALERT_ID":          "ALERT-03",
        "SCENARIO_ID":       "03",
        "CUSTOMER_REF":      "CUST-03",
        "ALERT_DATE":        "2026-08-22",
        "ALERT_TYPE":        "DORMANT_REACTIVATION",
        "SIGNAL_SOURCE":     "INTERNAL_RULE",
        "ACCOUNT_TYPE":      "SAVINGS",
        "CUSTOMER_PROFILE":  "Retired government employee; Rs.35K/month pension; account dormant 3 years; 71 years old",
        "ALERT_AMOUNT_INR":  8500000.00,
        "ALERT_NARRATIVE":   "Account inactive for 3 years; 6 cash deposits totalling Rs.85L between 2026-08-10 and 2026-08-21 (dormant-account reactivation rule). Open item: the customer states the funds are property-sale proceeds. Sale documentation not yet produced.",
        "RFI_TRIGGERS":      ["RFI-003"],
        "POE_FACTORS":       ["POE-003", "POE-005", "POE-006", "POE-012"],
        "RULES_CITED":       ["STR-001", "STR-002", "RFI-003", "POE-003", "POE-005", "POE-006", "POE-012"],
        "GOLD_DISPOSITION":  "CONTESTED",
        "ALERT_STATUS":      "OPEN",
    },
    {
        "ALERT_ID":          "ALERT-04",
        "SCENARIO_ID":       "04",
        "CUSTOMER_REF":      "CUST-04",
        "ALERT_DATE":        "2026-08-25",
        "ALERT_TYPE":        "PEP_INCONSISTENCY",
        "SIGNAL_SOURCE":     "INTERNAL_RULE",
        "ACCOUNT_TYPE":      "SAVINGS",
        "CUSTOMER_PROFILE":  "State PWD engineer (PEP); Rs.95K/month declared (govt. salary); Medium-High risk (PEP)",
        "ALERT_AMOUNT_INR":  4770000.00,
        "ALERT_NARRATIVE":   "Rs.47.7L credits over 5 months from 4 civil construction contractors. Customer is a serving state PWD officer with procurement authority over the same contractors. EDD not triggered at account opening despite PEP status.",
        "RFI_TRIGGERS":      ["RFI-009", "RFI-006"],
        "POE_FACTORS":       ["POE-002", "POE-005", "POE-006"],
        "RULES_CITED":       ["STR-001", "RFI-009", "RFI-006", "POE-002", "POE-005", "POE-006", "SB-002"],
        "GOLD_DISPOSITION":  "FILE",
        "ALERT_STATUS":      "OPEN",
    },
    {
        "ALERT_ID":          "ALERT-05",
        "SCENARIO_ID":       "05",
        "CUSTOMER_REF":      "CUST-05",
        "ALERT_DATE":        "2026-08-28",
        "ALERT_TYPE":        "CROSS_BORDER_FATF",
        "SIGNAL_SOURCE":     "INTERNAL_RULE",
        "ACCOUNT_TYPE":      "CURRENT",
        "CUSTOMER_PROFILE":  "IT services exporter; Rs.4.2Cr declared annual turnover; GST-registered; Medium risk",
        "ALERT_AMOUNT_INR":  6420000.00,
        "ALERT_NARRATIVE":   "2 outward SWIFT payments totalling Rs.64.2L (Rs.37.5L on 2026-08-06 and Rs.26.7L on 2026-08-27) to Regal Trading FZCO, Sharjah, UAE, routed via a correspondent network linked to DPRK. Stated purpose: software development subcontracting.",
        "RFI_TRIGGERS":      ["RFI-008"],
        "POE_FACTORS":       ["POE-002", "POE-006", "POE-011"],
        "RULES_CITED":       ["STR-001", "CBTR-001", "RFI-008", "POE-002", "POE-006", "POE-011"],
        "GOLD_DISPOSITION":  "FILE",
        "ALERT_STATUS":      "OPEN",
    },
    {
        "ALERT_ID":          "ALERT-06",
        "SCENARIO_ID":       "06",
        "CUSTOMER_REF":      "CUST-06",
        "ALERT_DATE":        "2026-08-29",
        "ALERT_TYPE":        "NPO_MISUSE",
        "SIGNAL_SOURCE":     "INTERNAL_RULE",
        "ACCOUNT_TYPE":      "CURRENT",
        "CUSTOMER_PROFILE":  "Registered NGO (education/welfare); Medium risk; annual accounts filed; 3-year relationship",
        "ALERT_AMOUNT_INR":  1950000.00,
        "ALERT_NARRATIVE":   "Rs.19.5L cash deposited across 3 branches over 8 days (NTR and CTR obligations both triggered); the full amount was redistributed by UPI to 40+ individuals within 48 hours. Open item: no donation documentation has been received.",
        "RFI_TRIGGERS":      ["RFI-010"],
        "POE_FACTORS":       ["POE-002", "POE-006", "POE-007", "POE-008"],
        "RULES_CITED":       ["STR-001", "CTR-001", "NTR-001", "RFI-010", "POE-002", "POE-006", "POE-007", "POE-008"],
        "GOLD_DISPOSITION":  "FILE",
        "ALERT_STATUS":      "OPEN",
    },
    {
        "ALERT_ID":          "ALERT-07",
        "SCENARIO_ID":       "07",
        "CUSTOMER_REF":      "CUST-07",
        "ALERT_DATE":        "2026-09-01",
        "ALERT_TYPE":        "LARGE_CASH_DEPOSIT",
        "SIGNAL_SOURCE":     "INTERNAL_RULE",
        "ACCOUNT_TYPE":      "CURRENT",
        "CUSTOMER_PROFILE":  "Sole proprietor grain trader; Rs.1.8Cr annual turnover declared; GST + mandi licence on file; Medium risk",
        "ALERT_AMOUNT_INR":  4820000.00,
        "ALERT_NARRATIVE":   "Rs.48.2L deposited in cash over 45 days in 9 deposits (large cash deposit rule); monthly cash totals exceed the CTR threshold.",
        "RFI_TRIGGERS":      [],
        "POE_FACTORS":       ["POE-002", "POE-003", "POE-005", "POE-009"],
        "RULES_CITED":       ["STR-001", "CTR-001", "INS-001", "INS-003", "POE-002", "POE-003", "POE-005", "POE-009"],
        "GOLD_DISPOSITION":  "NOT_FILE",
        "ALERT_STATUS":      "OPEN",
    },
    {
        "ALERT_ID":          "ALERT-08",
        "SCENARIO_ID":       "08",
        "CUSTOMER_REF":      "CUST-08",
        "ALERT_DATE":        "2026-09-02",
        "ALERT_TYPE":        "LARGE_CREDIT",
        "SIGNAL_SOURCE":     "INTERNAL_RULE",
        "ACCOUNT_TYPE":      "SAVINGS",
        "CUSTOMER_PROFILE":  "Retired teacher; Rs.28K/month pension; Low risk; property owner (residential flat purchased 2006)",
        "ALERT_AMOUNT_INR":  7500000.00,
        "ALERT_NARRATIVE":   "Single NEFT credit of Rs.75L on 2026-08-31 from Sharma and Associates (large credit rule), against a declared pension of Rs.28K/month.",
        "RFI_TRIGGERS":      [],
        "POE_FACTORS":       ["POE-003", "POE-005", "POE-006"],
        "RULES_CITED":       ["STR-001", "INS-001", "POE-003", "POE-005", "POE-006"],
        "GOLD_DISPOSITION":  "NOT_FILE",
        "ALERT_STATUS":      "OPEN",
    },
    {
        "ALERT_ID":          "ALERT-09",
        "SCENARIO_ID":       "09",
        "CUSTOMER_REF":      "CUST-09-A",
        "ALERT_DATE":        "2026-09-03",
        "ALERT_TYPE":        "DEVICE_IDENTITY_LINKAGE",
        "SIGNAL_SOURCE":     "INTERNAL_RULE",
        "ACCOUNT_TYPE":      "SAVINGS",
        "CUSTOMER_PROFILE":  "Multiple low-income customers (factory worker/auto driver/labourer); Rs.8-15K/month declared; 7 accounts same device fingerprint",
        "ALERT_AMOUNT_INR":  2730000.00,
        "ALERT_NARRATIVE":   "7 savings accounts with different KYC identities share a single mobile device fingerprint. All 7 receive UPI credits from different unknown handles; 94.5% (Rs.25.8L) of the credits flow to a single destination handle.",
        "RFI_TRIGGERS":      ["RFI-004", "RFI-001"],
        "POE_FACTORS":       ["POE-003", "POE-005", "POE-010", "POE-011"],
        "RULES_CITED":       ["STR-001", "RFI-004", "RFI-001", "POE-003", "POE-005", "POE-010", "POE-011", "INS-002", "POE-012"],
        "GOLD_DISPOSITION":  "FILE",
        "ALERT_STATUS":      "OPEN",
    },
    {
        "ALERT_ID":          "ALERT-10",
        "SCENARIO_ID":       "10",
        "CUSTOMER_REF":      "CUST-10-A",
        "ALERT_DATE":        "2026-09-04",
        "ALERT_TYPE":        "BENEFICIARY_CONCENTRATION",
        "SIGNAL_SOURCE":     "I4C",
        "ACCOUNT_TYPE":      "SAVINGS",
        "CUSTOMER_PROFILE":  "Multiple low-income customers (courier/domestic worker/retired clerk); 5 unrelated savings accounts",
        "ALERT_AMOUNT_INR":  264000.00,
        "ALERT_NARRATIVE":   "5 unrelated savings accounts at different branches all made UPI debits to the same mobile handle (HANDLE-Z), which is flagged in the I4C Suspect Registry. 21 transfers totalling Rs.2.64L over 60 days. No KYC link between the account holders is recorded.",
        "RFI_TRIGGERS":      ["RFI-007", "RFI-001", "RFI-005"],
        "POE_FACTORS":       ["POE-003", "POE-006", "POE-010"],
        "RULES_CITED":       ["STR-001", "RFI-007", "RFI-001", "RFI-005", "POE-003", "POE-006", "POE-010"],
        "GOLD_DISPOSITION":  "FILE",
        "ALERT_STATUS":      "OPEN",
    },
    {
        "ALERT_ID":          "ALERT-11",
        "SCENARIO_ID":       "11",
        "CUSTOMER_REF":      "CUST-11",
        "ALERT_DATE":        "2026-09-05",
        "ALERT_TYPE":        "INCOME_INCONSISTENCY",
        "SIGNAL_SOURCE":     "INTERNAL_RULE",
        "ACCOUNT_TYPE":      "SAVINGS",
        "CUSTOMER_PROFILE":  "Software engineer; Rs.85K/month salary declared; Low risk; 24-month clean salary-only baseline",
        "ALERT_AMOUNT_INR":  1240000.00,
        "ALERT_NARRATIVE":   "Rs.12.4L received by NEFT from a single private individual (Mr. Vikram S.) in 3 credits between 2026-07-08 and 2026-09-03, with remarks recorded as consulting fees and professional charges. Credits total Rs.12.4L against a declared salary of Rs.85K/month. No secondary income is declared in KYC; KYC has not been updated.",
        "RFI_TRIGGERS":      ["RFI-006"],
        "POE_FACTORS":       ["POE-002", "POE-005", "POE-006", "POE-012"],
        "RULES_CITED":       ["STR-001", "STR-002", "RFI-006", "POE-002", "POE-005", "POE-006", "POE-012"],
        "GOLD_DISPOSITION":  "CONTESTED",
        "ALERT_STATUS":      "OPEN",
    },
    {
        "ALERT_ID":          "ALERT-12",
        "SCENARIO_ID":       "12",
        "CUSTOMER_REF":      "CUST-12",
        "ALERT_DATE":        "2026-09-06",
        "ALERT_TYPE":        "ATTEMPTED_SWIFT",
        "SIGNAL_SOURCE":     "INTERNAL_RULE",
        "ACCOUNT_TYPE":      "CURRENT",
        "CUSTOMER_PROFILE":  "Small business owner (electronics importer); Rs.4.5L/year declared; GST-registered; Medium risk",
        "ALERT_AMOUNT_INR":  2505000.00,
        "ALERT_NARRATIVE":   "Two outward SWIFT attempts to Zhao Trading Co., Shenzhen, China (Rs.15.03L each, 2026-09-01 and 2026-09-04) were stopped by the screening system because the beneficiary's bank is on the internal watchlist. The second attempt names the same beneficiary through a different correspondent bank (Hong Kong).",
        "RFI_TRIGGERS":      ["RFI-008"],
        "POE_FACTORS":       ["POE-002", "POE-005", "POE-011"],
        "RULES_CITED":       ["STR-001", "STR-003", "RFI-008", "POE-002", "POE-005", "POE-011", "INS-002"],
        "GOLD_DISPOSITION":  "FILE",
        "ALERT_STATUS":      "OPEN",
    },
    {
        "ALERT_ID":          "ALERT-13",
        "SCENARIO_ID":       "13",
        "CUSTOMER_REF":      "CUST-13",
        "ALERT_DATE":        "2026-09-08",
        "ALERT_TYPE":        "MF_LAYERING",
        "SIGNAL_SOURCE":     "INTERNAL_RULE",
        "ACCOUNT_TYPE":      "SAVINGS",
        "CUSTOMER_PROFILE":  "Self-employed consultant; Rs.1.8L/month declared; Medium risk; 18-month client relationship",
        "ALERT_AMOUNT_INR":  12000000.00,
        "ALERT_NARRATIVE":   "Rs.1.2Cr moved through a liquid mutual fund (bank to fund to bank) in 3-5 day holding periods over 4 months; each redemption returns to the same account within about 1% of the amount invested. No investment rationale is recorded.",
        "RFI_TRIGGERS":      ["RFI-001"],
        "POE_FACTORS":       ["POE-003", "POE-005", "POE-006", "POE-010"],
        "RULES_CITED":       ["STR-001", "RFI-001", "POE-003", "POE-005", "POE-006", "POE-010"],
        "GOLD_DISPOSITION":  "CONTESTED",
        "ALERT_STATUS":      "OPEN",
    },
    {
        "ALERT_ID":          "ALERT-14",
        "SCENARIO_ID":       "14",
        "CUSTOMER_REF":      "CUST-14",
        "ALERT_DATE":        "2026-09-10",
        "ALERT_TYPE":        "NRI_KYC_MISMATCH",
        "SIGNAL_SOURCE":     "INTERNAL_RULE",
        "ACCOUNT_TYPE":      "NRO",
        "CUSTOMER_PROFILE":  "NRI (Singapore resident); IT professional; Rs.2.5L/month declared; stale KYC (3 years); NRO account",
        "ALERT_AMOUNT_INR":  3090000.00,
        "ALERT_NARRATIVE":   "Rs.30.9L of inward SWIFT remittances from V Patel (DBS Bank Singapore) in 4 credits between 2026-07-14 and 2026-08-26, against a declared income of Rs.2.5L/month. KYC is 3 years old; the contact number is unreachable and the address is unconfirmed.",
        "RFI_TRIGGERS":      ["RFI-006"],
        "POE_FACTORS":       ["POE-003", "POE-005", "POE-006", "POE-011", "POE-012"],
        "RULES_CITED":       ["STR-001", "STR-002", "RFI-006", "POE-003", "POE-005", "POE-006", "POE-011", "POE-012"],
        "GOLD_DISPOSITION":  "CONTESTED",
        "ALERT_STATUS":      "OPEN",
    },
    {
        "ALERT_ID":          "ALERT-15",
        "SCENARIO_ID":       "15",
        "CUSTOMER_REF":      "CUST-15",
        "ALERT_DATE":        "2026-09-12",
        "ALERT_TYPE":        "FIDUCIARY_DIVERSION",
        "SIGNAL_SOURCE":     "INTERNAL_RULE",
        "ACCOUNT_TYPE":      "SAVINGS",
        "CUSTOMER_PROFILE":  "Retired bank officer; Rs.35K/month pension; Low risk; elected Treasurer of Cooperative Housing Society",
        "ALERT_AMOUNT_INR":  1785000.00,
        "ALERT_NARRATIVE":   "Rs.17.85L deposited in cash over 6 months in 19 deposits, all made between the 6th and 10th of each month (recurring cash deposit rule). Profile: elected Treasurer of a cooperative housing society.",
        "RFI_TRIGGERS":      ["RFI-001", "RFI-006"],
        "POE_FACTORS":       ["POE-002", "POE-003", "POE-005", "POE-007"],
        "RULES_CITED":       ["STR-001", "STR-002", "RFI-001", "RFI-006", "POE-002", "POE-003", "POE-005", "POE-007", "SB-002"],
        "GOLD_DISPOSITION":  "FILE",
        "ALERT_STATUS":      "OPEN",
    },
    {
        # T8: same-signal twin of ALERT-01 (MULE_PASSTHROUGH / I4C) — legitimate look-alike.
        # Same detection rule and amount; the CLOSE is justified entirely by the transaction
        # evidence: documented family senders, funds to a hospital, no flagged counterparty.
        "ALERT_ID":          "ALERT-16",
        "SCENARIO_ID":       "01B",
        "CUSTOMER_REF":      "CUST-16",
        "ALERT_DATE":        "2026-09-14",
        "ALERT_TYPE":        "MULE_PASSTHROUGH",
        "SIGNAL_SOURCE":     "I4C",
        "ACCOUNT_TYPE":      "SAVINGS",
        "CUSTOMER_PROFILE":  "Freelance designer; Rs.40K/month declared; account 3 years old; documented family remittances in history",
        "ALERT_AMOUNT_INR":  345000.00,
        "ALERT_NARRATIVE":   "Credits of Rs.3.45L from 3 senders in 3 days (UPI) match a pass-through pattern (RFI-001); an I4C linkage signal fired on the account. Rs.3.0L was then paid by NEFT to City General Hospital.",
        "RFI_TRIGGERS":      ["RFI-001", "RFI-005"],
        "POE_FACTORS":       ["POE-006"],
        "RULES_CITED":       ["STR-001", "RFI-001", "RFI-005", "POE-006", "INS-001"],
        "GOLD_DISPOSITION":  "NOT_FILE",
        "ALERT_STATUS":      "OPEN",
    },
    # R4: three GCC-flavoured alerts (inward remittances from the Gulf), written AFTER the nexus rule in skills/nexus_support.py was frozen and never used
    # to tune it. ALERT-17 and ALERT-18 carry the same total (Rs.14.2L of inward SWIFT credits); only the record separates them. Scenario ids G1-G3: these have
    # no scenario file. The labels are the author's expectation, like every other label here.
    {
        "ALERT_ID":          "ALERT-17",
        "SCENARIO_ID":       "G1",
        "CUSTOMER_REF":      "CUST-17",
        "ALERT_DATE":        "2026-09-24",
        "ALERT_TYPE":        "MULE_PASSTHROUGH",
        "SIGNAL_SOURCE":     "INTERNAL_RULE",
        "ACCOUNT_TYPE":      "SAVINGS",
        "CUSTOMER_PROFILE":  "Delivery rider; Rs.22K/month declared; account 9 months old; Low-risk",
        "ALERT_AMOUNT_INR":  1420000.00,
        "ALERT_NARRATIVE":   "Eight inward SWIFT credits totalling Rs.14.2L from eight different remitters in Gulf cities between 2026-09-14 and 2026-09-17, against a declared income of Rs.22K/month; no relationship between the customer and any remitter is recorded. Rs.13.7L left the account within five days of the first credit: ATM cash withdrawals and transfers to two accounts at other banks.",
        "RFI_TRIGGERS":      ["RFI-001", "RFI-006"],
        "POE_FACTORS":       ["POE-003", "POE-005", "POE-007", "POE-008"],
        "RULES_CITED":       ["STR-001", "STR-002", "RFI-001", "RFI-006", "POE-003", "POE-005", "POE-007", "POE-008"],
        "GOLD_DISPOSITION":  "FILE",
        "ALERT_STATUS":      "OPEN",
    },
    {
        "ALERT_ID":          "ALERT-18",
        "SCENARIO_ID":       "G2",
        "CUSTOMER_REF":      "CUST-18",
        "ALERT_DATE":        "2026-10-01",
        "ALERT_TYPE":        "LARGE_CREDIT",
        "SIGNAL_SOURCE":     "INTERNAL_RULE",
        "ACCOUNT_TYPE":      "NRE",
        "CUSTOMER_PROFILE":  "NRI (UAE resident); software engineer; about Rs.2.4L/month declared; NRE account 4 years old; KYC refreshed 2026-03",
        "ALERT_AMOUNT_INR":  1420000.00,
        "ALERT_NARRATIVE":   "Six inward SWIFT credits totalling Rs.14.2L from one remitter, Gulf Digital Solutions LLC (Dubai), between 2026-04-30 and 2026-09-30 crossed the cumulative large-credit threshold on an NRE account. The occupation on the customer profile is software engineer; the remitter is the employer named at the last KYC refresh.",
        "RFI_TRIGGERS":      ["RFI-006"],
        "POE_FACTORS":       ["POE-006"],
        "RULES_CITED":       ["STR-001", "RFI-006", "POE-006"],
        "GOLD_DISPOSITION":  "NOT_FILE",
        "ALERT_STATUS":      "OPEN",
    },
    {
        "ALERT_ID":          "ALERT-19",
        "SCENARIO_ID":       "G3",
        "CUSTOMER_REF":      "CUST-19",
        "ALERT_DATE":        "2026-09-23",
        "ALERT_TYPE":        "LARGE_CREDIT",
        "SIGNAL_SOURCE":     "INTERNAL_RULE",
        "ACCOUNT_TYPE":      "SAVINGS",
        "CUSTOMER_PROFILE":  "Returned resident (previously employed in the UAE); Rs.25K/month declared from pension and rent; account 6 years old",
        "ALERT_AMOUNT_INR":  2150000.00,
        "ALERT_NARRATIVE":   "A single inward SWIFT credit of Rs.21.5L from Gulf Logistics LLC (Abu Dhabi) on 2026-09-16, against a declared income of Rs.25K/month. Rs.20L was moved five days later to a term deposit in the customer's own name. The remittance reference reads end-of-service payment; no employment or exit documents are attached to the alert.",
        "RFI_TRIGGERS":      ["RFI-006"],
        "POE_FACTORS":       ["POE-005", "POE-006", "POE-009"],
        "RULES_CITED":       ["STR-001", "RFI-006", "POE-005", "POE-006", "POE-009"],
        "GOLD_DISPOSITION":  "NOT_FILE",
        "ALERT_STATUS":      "OPEN",
    },
]

# ── TRANSACTIONS (T1) ─────────────────────────────────────────────────────────
# Per-alert transaction ledger. Explicit rows for the demo alerts are transcribed
# verbatim from the gold-standard scenario tables; all other alerts get a
# reconciling summary row (CREDIT total == ALERT_AMOUNT_INR). Invariant checked by
# tests/test_transactions.py.

TRANSACTIONS_DDL = """
CREATE TABLE IF NOT EXISTS FIU_COPILOT.AML.TRANSACTIONS (
    TXN_ID           VARCHAR(20)   NOT NULL,
    ALERT_ID         VARCHAR(20)   NOT NULL,
    CUSTOMER_REF     VARCHAR(20)   NOT NULL,
    TXN_DATE         DATE          NOT NULL,
    TXN_TYPE         VARCHAR(10)   NOT NULL,
    AMOUNT_INR       NUMBER(15,2)  NOT NULL,
    CHANNEL          VARCHAR(30),
    COUNTERPARTY     VARCHAR(200),
    IS_FLAGGED       BOOLEAN       DEFAULT FALSE,
    CONSTRAINT CHK_TXN_TYPE CHECK (TXN_TYPE IN ('CREDIT', 'DEBIT')),
    CONSTRAINT PK_TRANSACTIONS PRIMARY KEY (TXN_ID)
)
"""

# Explicit transactions transcribed from the scenario transaction tables.
# Each row: (suffix, date, type, amount, channel, counterparty, is_flagged)
EXPLICIT_TXNS: dict[str, list[tuple]] = {
    "ALERT-01": [  # scenario 01 — mule pass-through; credits sum = 345000
        ("1", "2026-08-13", "CREDIT", 110000, "UPI",  "Unknown UPI handle A",            False),
        ("2", "2026-08-14", "CREDIT", 140000, "UPI",  "Unknown UPI handle B",            False),
        ("3", "2026-08-15", "DEBIT",  246500, "UPI",  "UPI handle C (I4C-flagged)",      True),
        ("4", "2026-08-16", "CREDIT",  95000, "UPI",  "Unknown UPI handle D",            False),
        ("5", "2026-08-17", "DEBIT",   94200, "UPI",  "UPI handle C (I4C-flagged)",      True),
    ],
    "ALERT-02": [  # scenario 02 — structuring; 15-day cash totals; credits sum = 420000
        ("1", "2026-08-19", "CREDIT", 142500, "CASH", "ACCT-02-A cash deposits (15d)",   False),
        ("2", "2026-08-19", "CREDIT", 142500, "CASH", "ACCT-02-B cash deposits (15d)",   False),
        ("3", "2026-08-19", "CREDIT", 135000, "CASH", "ACCT-02-C cash deposits (15d)",   False),
        ("4", "2026-08-20", "DEBIT",  420000, "NEFT", "Single current account (other bank)", False),
    ],
    "ALERT-04": [  # scenario 04 — PEP corporate credits; credits sum = 4,800,000 (~4.77L ±1%)
        ("1", "2026-06-15", "CREDIT",  850000, "NEFT", "ABC Infrastructure Ltd",         False),
        ("2", "2026-06-20", "CREDIT",  620000, "NEFT", "DEF Engineering Pvt Ltd",        False),
        ("3", "2026-07-15", "CREDIT", 1100000, "NEFT", "ABC Infrastructure Ltd",         False),
        ("4", "2026-07-20", "CREDIT",  480000, "NEFT", "GHI Constructions",              False),
        ("5", "2026-08-15", "CREDIT",  930000, "NEFT", "DEF Engineering Pvt Ltd",        False),
        ("6", "2026-08-20", "CREDIT",  820000, "NEFT", "JKL Roadways Pvt Ltd",           False),
    ],
    "ALERT-16": [  # T8 twin of ALERT-01 — legitimate; credits sum = 345000; no flagged party
        ("1", "2026-09-09", "CREDIT", 150000, "UPI",  "Brother (KYC-linked family)",    False),
        ("2", "2026-09-10", "CREDIT", 120000, "UPI",  "Father (KYC-linked family)",     False),
        ("3", "2026-09-11", "CREDIT",  75000, "UPI",  "Sister (KYC-linked family)",     False),
        ("4", "2026-09-12", "DEBIT",  300000, "NEFT", "City General Hospital", False),
    ],
}


def _channel_for(alert: dict) -> str:
    n = (alert.get("ALERT_NARRATIVE") or "").lower()
    if "swift" in n:            return "SWIFT"
    if "cash" in n:             return "CASH"
    if "upi" in n:              return "UPI"
    if "mutual fund" in n or "mf " in n or "sip" in n: return "IMPS"
    return "NEFT"


# ── Block 4: explicit rows for eight more alerts, transcribed from domain/scenarios/*.md ─────────────────────────────────────────────────────────
# Dates are WEEKDAYS (a counter cash deposit on a Sunday is not a thing). Credits reconcile to ALERT_AMOUNT_INR within 1% (debits for the outward-flow
# alerts 05 and 12). Counterparty labels carry the IDENTITY of the other party only: no "invoice on file", no "legitimate", no finding.
EXPLICIT_TXNS["ALERT-03"] = [  # scenario 03 — dormant account: Rs.85L cash over 12 days; credits sum = 8,500,000
    ("1", "2026-08-10", "CREDIT", 1450000, "CASH", "Cash deposit at branch counter", False),
    ("2", "2026-08-11", "CREDIT", 1200000, "CASH", "Cash deposit at branch counter", False),
    ("3", "2026-08-13", "CREDIT", 1500000, "CASH", "Cash deposit at branch counter", False),
    ("4", "2026-08-17", "CREDIT", 1350000, "CASH", "Cash deposit at branch counter", False),
    ("5", "2026-08-19", "CREDIT", 1600000, "CASH", "Cash deposit at branch counter", False),
    ("6", "2026-08-21", "CREDIT", 1400000, "CASH", "Cash deposit at branch counter", False),
]
EXPLICIT_TXNS["ALERT-05"] = [  # scenario 05 — two outward SWIFT payments (USD 45,000 ≈ Rs.37.5L, USD 32,000 ≈ Rs.26.7L); the alert is about the DEBITS: 6,420,000
    ("1", "2026-08-06", "DEBIT", 3750000, "SWIFT", "Regal Trading FZCO, Sharjah, UAE (via DPRK-linked correspondent)", True),
    ("2", "2026-08-27", "DEBIT", 2670000, "SWIFT", "Regal Trading FZCO, Sharjah, UAE (via DPRK-linked correspondent)", True),
]
EXPLICIT_TXNS["ALERT-07"] = [  # scenario 07 — grain trader: 9 cash deposits over 45 days; credits sum = 4,820,000
    ("1", "2026-07-17", "CREDIT", 540000, "CASH", "Cash deposit at branch counter", False),
    ("2", "2026-07-22", "CREDIT", 520000, "CASH", "Cash deposit at branch counter", False),
    ("3", "2026-07-27", "CREDIT", 560000, "CASH", "Cash deposit at branch counter", False),
    ("4", "2026-07-31", "CREDIT", 500000, "CASH", "Cash deposit at branch counter", False),
    ("5", "2026-08-05", "CREDIT", 530000, "CASH", "Cash deposit at branch counter", False),
    ("6", "2026-08-11", "CREDIT", 550000, "CASH", "Cash deposit at branch counter", False),
    ("7", "2026-08-17", "CREDIT", 510000, "CASH", "Cash deposit at branch counter", False),
    ("8", "2026-08-24", "CREDIT", 540000, "CASH", "Cash deposit at branch counter", False),
    ("9", "2026-08-31", "CREDIT", 570000, "CASH", "Cash deposit at branch counter", False),
]
EXPLICIT_TXNS["ALERT-08"] = [  # scenario 08 — one NEFT credit from a law firm; credits sum = 7,500,000
    ("1", "2026-08-31", "CREDIT", 7500000, "NEFT", "Sharma and Associates", False),
]
EXPLICIT_TXNS["ALERT-11"] = [  # scenario 11 — months 25-27: Rs.3.4L, 4.2L, 4.8L by NEFT from one private individual; credits sum = 1,240,000
    ("1", "2026-07-08", "CREDIT", 340000, "NEFT", "Mr. Vikram S.", False),
    ("2", "2026-08-06", "CREDIT", 420000, "NEFT", "Mr. Vikram S.", False),
    ("3", "2026-09-03", "CREDIT", 480000, "NEFT", "Mr. Vikram S.", False),
]
EXPLICIT_TXNS["ALERT-12"] = [  # scenario 12 — two outward SWIFT attempts of USD 18,000 (≈ Rs.15.03L) each, stopped by screening. The attempts are the flow: 3,006,000.
    # DELIBERATE CONTRADICTION (see HEADER_AMOUNT_CONTRADICTIONS): the alert header says Rs.25.05L; these rows sum to Rs.30.06L.
    ("1", "2026-09-01", "DEBIT", 1503000, "SWIFT", "Zhao Trading Co., Shenzhen, China (attempt stopped by screening; correspondent in Shenzhen)", True),
    ("2", "2026-09-04", "DEBIT", 1503000, "SWIFT", "Zhao Trading Co., Shenzhen, China (attempt stopped by screening; correspondent in Hong Kong)", True),
]
EXPLICIT_TXNS["ALERT-14"] = [  # scenario 14 — months 37-38: four inward SWIFT remittances from one sender; credits sum = 3,090,000
    ("1", "2026-07-14", "CREDIT", 820000, "SWIFT", "V Patel, DBS Bank Singapore", False),
    ("2", "2026-07-28", "CREDIT", 640000, "SWIFT", "V Patel, DBS Bank Singapore", False),
    ("3", "2026-08-12", "CREDIT", 880000, "SWIFT", "V Patel, DBS Bank Singapore", False),
    ("4", "2026-08-26", "CREDIT", 750000, "SWIFT", "V Patel, DBS Bank Singapore", False),
]
# scenario 15 — a treasurer's cash deposits on weekdays between the 6th and the 10th of each month; monthly sums as in the scenario table
_ALERT15 = {  # month -> [(day, amount)]
    "2026-03": [(6, 100000), (9, 90000), (10, 90000)],                      # 2,80,000
    "2026-04": [(6, 110000), (8, 100000), (10, 110000)],                    # 3,20,000
    "2026-05": [(6, 100000), (7, 95000), (8, 100000)],                      # 2,95,000
    "2026-06": [(8, 100000), (9, 105000), (10, 105000)],                    # 3,10,000
    "2026-07": [(6, 70000), (7, 70000), (8, 67500), (10, 67500)],           # 2,75,000
    "2026-08": [(6, 100000), (7, 105000), (10, 100000)],                    # 3,05,000
}
EXPLICIT_TXNS["ALERT-15"] = [
    (str(i), f"{month}-{day:02d}", "CREDIT", amount, "CASH", "Cash deposit at branch counter", False)
    for i, (month, day, amount) in enumerate(((m, d, a) for m, rows in _ALERT15.items() for d, a in rows), start=1)
]

# Block 5 (R4): the three Gulf-remittance alerts. Same total on 17 and 18 (credits sum = 1,420,000); no scenario file backs them, so the amounts are
# stated here and nowhere else. The labels carry the identity of the other party only.
EXPLICIT_TXNS["ALERT-17"] = [  # eight inward SWIFT credits from eight remitters, then cash and two accounts at other banks; credits sum = 1,420,000
    ("1",  "2026-09-14", "CREDIT", 175000, "SWIFT", "Unknown remitter, Dubai, UAE",              False),
    ("2",  "2026-09-14", "CREDIT", 190000, "SWIFT", "Unknown remitter, Abu Dhabi, UAE",          False),
    ("3",  "2026-09-15", "CREDIT", 160000, "SWIFT", "Unknown remitter, Sharjah, UAE",            False),
    ("4",  "2026-09-15", "CREDIT", 185000, "SWIFT", "Unknown remitter, Doha, Qatar",             False),
    ("5",  "2026-09-16", "CREDIT", 170000, "SWIFT", "Unknown remitter, Dubai, UAE",              False),
    ("6",  "2026-09-16", "CREDIT", 180000, "SWIFT", "Unknown remitter, Muscat, Oman",            False),
    ("7",  "2026-09-17", "CREDIT", 165000, "SWIFT", "Unknown remitter, Riyadh, Saudi Arabia",    False),
    ("8",  "2026-09-17", "CREDIT", 195000, "SWIFT", "Unknown remitter, Dammam, Saudi Arabia",    False),
    ("9",  "2026-09-18", "DEBIT",  450000, "CASH",  "ATM cash withdrawals (several machines)",   False),
    ("10", "2026-09-21", "DEBIT",  520000, "IMPS",  "Unidentified beneficiary account, other bank (first)",  False),
    ("11", "2026-09-22", "DEBIT",  400000, "NEFT",  "Unidentified beneficiary account, other bank (second)", False),
]
EXPLICIT_TXNS["ALERT-18"] = [  # six monthly inward SWIFT credits from one employer, a loan instalment and a term deposit; credits sum = 1,420,000
    ("1", "2026-04-30", "CREDIT", 236000, "SWIFT", "Gulf Digital Solutions LLC, Dubai, UAE",  False),
    ("2", "2026-05-29", "CREDIT", 236000, "SWIFT", "Gulf Digital Solutions LLC, Dubai, UAE",  False),
    ("3", "2026-06-01", "DEBIT",   85000, "NEFT",  "Housing finance company, home loan account", False),
    ("4", "2026-06-30", "CREDIT", 236000, "SWIFT", "Gulf Digital Solutions LLC, Dubai, UAE",  False),
    ("5", "2026-07-01", "DEBIT",   85000, "NEFT",  "Housing finance company, home loan account", False),
    ("6", "2026-07-31", "CREDIT", 236000, "SWIFT", "Gulf Digital Solutions LLC, Dubai, UAE",  False),
    ("7", "2026-08-03", "DEBIT",   85000, "NEFT",  "Housing finance company, home loan account", False),
    ("8", "2026-08-31", "CREDIT", 238000, "SWIFT", "Gulf Digital Solutions LLC, Dubai, UAE",  False),
    ("9", "2026-09-02", "DEBIT",  400000, "NEFT",  "Term deposit, own name, same bank",         False),
    ("10", "2026-09-30", "CREDIT", 238000, "SWIFT", "Gulf Digital Solutions LLC, Dubai, UAE", False),
]
EXPLICIT_TXNS["ALERT-19"] = [  # one inward SWIFT credit, then a term deposit; credits sum = 2,150,000
    ("1", "2026-09-16", "CREDIT", 2150000, "SWIFT", "Gulf Logistics LLC, Abu Dhabi, UAE", False),
    ("2", "2026-09-21", "DEBIT",  2000000, "NEFT",  "Term deposit, own name, same bank",  False),
]

# A seeded data-quality CONTRADICTION, kept on purpose: the alert header disagrees with its own rows. skills/evidence_quality reports it as
# AMOUNT_RECONCILIATION (the PO must check it manually) and tests/test_seed_realism.py requires that it does. Every other alert reconciles.
HEADER_AMOUNT_CONTRADICTIONS = {"ALERT-12": "header Rs.25.05L; the two SWIFT attempts in the rows total Rs.30.06L"}

# Alerts whose flow is OUTWARD: the amount reconciles to DEBITS rather than credits.
OUTWARD_FLOW_ALERTS = {"ALERT-05", "ALERT-12"}

# ── The suspicion clock ─────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────
# A case feed (the upstream investigator / case-management system) can say WHEN suspicion formed, which starts the 7-working-day STR clock. This is an
# optional field supplied with the alert: the application never infers it from the alert date, and a decision recorded in the ledger takes precedence.
# NULL = the feed did not supply one (shown as "not recorded"). Offsets are in WORKING DAYS before the moment the seed is loaded, so the queue shows a
# live mix (overdue, due today, days left) whenever the seed is run; re-run scripts/setup_alerts.py to refresh. 7 - offset = working days left.
SUSPICION_WD_AGO = {
    "ALERT-04": 8,    # 1 WD overdue
    "ALERT-15": 7,    # due today
    "ALERT-12": 6,    # 1 WD left
    "ALERT-01": 4,    # 3 WD left
    "ALERT-02": 3,    # 4 WD left
    "ALERT-07": 2,    # 5 WD left
    "ALERT-05": 1,    # 6 WD left
    "ALERT-16": 1,    # 6 WD left
    "ALERT-14": 0,    # formed today: 7 WD left
}
IST = timezone(timedelta(hours=5, minutes=30))


def suspicion_formed_at(wd_ago: int, now: datetime | None = None) -> datetime:
    """10:30 IST on the working day `wd_ago` Mon-Fri days before the last working day on or before `now` (so a seed loaded on a weekend still shows what
    the offset says). wd_ago 0 is half an hour ago, but never earlier than midnight IST today: ten past midnight would otherwise put it on the previous
    day and a clock that has not started to run would already show a working day used."""
    now = (now or datetime.now(IST)).astimezone(IST)
    if wd_ago <= 0:
        return max((now - timedelta(minutes=30)).replace(second=0, microsecond=0), datetime.combine(now.date(), time(0, 0), tzinfo=IST))
    day = now.date()
    while day.weekday() >= 5:
        day -= timedelta(days=1)
    left = wd_ago
    while left:
        day -= timedelta(days=1)
        if day.weekday() < 5:
            left -= 1
    return datetime.combine(day, time(10, 30), tzinfo=IST)


def build_transactions(alerts: list[dict]) -> list[dict]:
    """Explicit rows for demo alerts; a reconciling CREDIT summary for the rest."""
    rows: list[dict] = []
    for a in alerts:
        aid, sid, cust = a["ALERT_ID"], a["SCENARIO_ID"], a["CUSTOMER_REF"]
        if aid in EXPLICIT_TXNS:
            for suffix, date, ttype, amt, chan, cp, flagged in EXPLICIT_TXNS[aid]:
                rows.append({
                    "TXN_ID": f"T{sid}-{suffix}", "ALERT_ID": aid, "CUSTOMER_REF": cust,
                    "TXN_DATE": date, "TXN_TYPE": ttype, "AMOUNT_INR": float(amt),
                    "CHANNEL": chan, "COUNTERPARTY": cp, "IS_FLAGGED": flagged,
                })
        else:
            # Reconciling summary: one CREDIT equal to the alert amount.
            rows.append({
                "TXN_ID": f"T{sid}-1", "ALERT_ID": aid, "CUSTOMER_REF": cust,
                "TXN_DATE": a["ALERT_DATE"], "TXN_TYPE": "CREDIT",
                "AMOUNT_INR": float(a["ALERT_AMOUNT_INR"]),
                "CHANNEL": _channel_for(a),
                "COUNTERPARTY": "Multiple counterparties (see alert narrative)",
                "IS_FLAGGED": a.get("SIGNAL_SOURCE") == "I4C",
            })
    return rows


TRANSACTIONS = build_transactions(ALERTS)

TXN_MERGE_SQL = """
MERGE INTO FIU_COPILOT.AML.TRANSACTIONS AS target
USING (SELECT
    %(TXN_ID)s::VARCHAR       AS TXN_ID,
    %(ALERT_ID)s::VARCHAR     AS ALERT_ID,
    %(CUSTOMER_REF)s::VARCHAR AS CUSTOMER_REF,
    %(TXN_DATE)s::DATE        AS TXN_DATE,
    %(TXN_TYPE)s::VARCHAR     AS TXN_TYPE,
    %(AMOUNT_INR)s::NUMBER    AS AMOUNT_INR,
    %(CHANNEL)s::VARCHAR      AS CHANNEL,
    %(COUNTERPARTY)s::VARCHAR AS COUNTERPARTY,
    %(IS_FLAGGED)s::BOOLEAN   AS IS_FLAGGED
) AS source ON target.TXN_ID = source.TXN_ID
WHEN MATCHED THEN UPDATE SET
    ALERT_ID = source.ALERT_ID, CUSTOMER_REF = source.CUSTOMER_REF,
    TXN_DATE = source.TXN_DATE, TXN_TYPE = source.TXN_TYPE,
    AMOUNT_INR = source.AMOUNT_INR, CHANNEL = source.CHANNEL,
    COUNTERPARTY = source.COUNTERPARTY, IS_FLAGGED = source.IS_FLAGGED
WHEN NOT MATCHED THEN INSERT (
    TXN_ID, ALERT_ID, CUSTOMER_REF, TXN_DATE, TXN_TYPE, AMOUNT_INR, CHANNEL, COUNTERPARTY, IS_FLAGGED
) VALUES (
    source.TXN_ID, source.ALERT_ID, source.CUSTOMER_REF, source.TXN_DATE, source.TXN_TYPE,
    source.AMOUNT_INR, source.CHANNEL, source.COUNTERPARTY, source.IS_FLAGGED
)
"""


MERGE_SQL = """
MERGE INTO FIU_COPILOT.AML.ALERTS AS target
USING (SELECT
    %(ALERT_ID)s::VARCHAR        AS ALERT_ID,
    %(SCENARIO_ID)s::VARCHAR     AS SCENARIO_ID,
    %(CUSTOMER_REF)s::VARCHAR    AS CUSTOMER_REF,
    %(ALERT_DATE)s::DATE         AS ALERT_DATE,
    %(ALERT_TYPE)s::VARCHAR      AS ALERT_TYPE,
    %(SIGNAL_SOURCE)s::VARCHAR   AS SIGNAL_SOURCE,
    %(ACCOUNT_TYPE)s::VARCHAR    AS ACCOUNT_TYPE,
    %(CUSTOMER_PROFILE)s::VARCHAR AS CUSTOMER_PROFILE,
    %(ALERT_AMOUNT_INR)s::NUMBER  AS ALERT_AMOUNT_INR,
    %(ALERT_NARRATIVE)s::TEXT    AS ALERT_NARRATIVE,
    PARSE_JSON(%(RFI_TRIGGERS)s) AS RFI_TRIGGERS,
    PARSE_JSON(%(POE_FACTORS)s)  AS POE_FACTORS,
    PARSE_JSON(%(RULES_CITED)s)  AS RULES_CITED,
    %(SUSPICION_FORMED_AT)s::TIMESTAMP_TZ AS SUSPICION_FORMED_AT,
    %(ALERT_STATUS)s::VARCHAR    AS ALERT_STATUS
) AS source ON target.ALERT_ID = source.ALERT_ID
WHEN MATCHED THEN UPDATE SET
    SCENARIO_ID      = source.SCENARIO_ID,
    CUSTOMER_REF     = source.CUSTOMER_REF,
    ALERT_DATE       = source.ALERT_DATE,
    ALERT_TYPE       = source.ALERT_TYPE,
    SIGNAL_SOURCE    = source.SIGNAL_SOURCE,
    ACCOUNT_TYPE     = source.ACCOUNT_TYPE,
    CUSTOMER_PROFILE = source.CUSTOMER_PROFILE,
    ALERT_AMOUNT_INR = source.ALERT_AMOUNT_INR,
    ALERT_NARRATIVE  = source.ALERT_NARRATIVE,
    RFI_TRIGGERS     = source.RFI_TRIGGERS,
    POE_FACTORS      = source.POE_FACTORS,
    RULES_CITED      = source.RULES_CITED,
    SUSPICION_FORMED_AT = source.SUSPICION_FORMED_AT
WHEN NOT MATCHED THEN INSERT (
    ALERT_ID, SCENARIO_ID, CUSTOMER_REF, ALERT_DATE, ALERT_TYPE,
    SIGNAL_SOURCE, ACCOUNT_TYPE, CUSTOMER_PROFILE, ALERT_AMOUNT_INR,
    ALERT_NARRATIVE, RFI_TRIGGERS, POE_FACTORS, RULES_CITED,
    SUSPICION_FORMED_AT, ALERT_STATUS
) VALUES (
    source.ALERT_ID, source.SCENARIO_ID, source.CUSTOMER_REF, source.ALERT_DATE, source.ALERT_TYPE,
    source.SIGNAL_SOURCE, source.ACCOUNT_TYPE, source.CUSTOMER_PROFILE, source.ALERT_AMOUNT_INR,
    source.ALERT_NARRATIVE, source.RFI_TRIGGERS, source.POE_FACTORS, source.RULES_CITED,
    source.SUSPICION_FORMED_AT, source.ALERT_STATUS
)
"""

# The answer key is loaded into a table the application role cannot read (domain/corpus/export/ddl/eval_labels.sql). The seed rows above still
# carry the label in Python so the tests can use it; it never goes into ALERTS.
GOLD_LABELS = {a["ALERT_ID"]: a["GOLD_DISPOSITION"] for a in ALERTS}

LABELS_CREATE_SQL = """
CREATE TABLE IF NOT EXISTS FIU_COPILOT.AML.ALERT_GOLD_LABELS (
    ALERT_ID          VARCHAR(20)   NOT NULL,
    GOLD_DISPOSITION  VARCHAR(20)   NOT NULL,
    LABEL_SOURCE      VARCHAR(100)  DEFAULT 'scenario author (synthetic)',
    LOADED_AT         TIMESTAMP_TZ  DEFAULT CURRENT_TIMESTAMP(),
    CONSTRAINT PK_ALERT_GOLD_LABELS PRIMARY KEY (ALERT_ID)
)
"""

LABELS_MERGE_SQL = """
MERGE INTO FIU_COPILOT.AML.ALERT_GOLD_LABELS AS target
USING (SELECT %(ALERT_ID)s::VARCHAR AS ALERT_ID, %(GOLD_DISPOSITION)s::VARCHAR AS GOLD_DISPOSITION) AS source ON target.ALERT_ID = source.ALERT_ID
WHEN MATCHED THEN UPDATE SET GOLD_DISPOSITION = source.GOLD_DISPOSITION
WHEN NOT MATCHED THEN INSERT (ALERT_ID, GOLD_DISPOSITION) VALUES (source.ALERT_ID, source.GOLD_DISPOSITION)
"""


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    load_env(REPO_ROOT)

    if args.dry_run:
        conn = None
    else:
        if missing_config():
            print("ERROR: missing Snowflake configuration: " + ", ".join(missing_config()) +
                  " (copy .env.example to .env).", file=sys.stderr)
            sys.exit(1)
        try:
            conn = connect_from_env()
        except (SnowflakeConfigError, SnowflakeConnectError) as err:
            print(f"ERROR: {err}", file=sys.stderr)
            sys.exit(1)
    cur = conn.cursor() if conn else None

    if args.dry_run:
        print(f"DRY RUN: {len(ALERTS)} alerts + {len(TRANSACTIONS)} transactions ready to load")
        for a in ALERTS:
            n = sum(1 for t in TRANSACTIONS if t["ALERT_ID"] == a["ALERT_ID"])
            print(f"  {a['ALERT_ID']} | {a['ALERT_TYPE']:30s} | {a['GOLD_DISPOSITION']:9s} | {n} txns")
        return

    # Create table
    cur.execute(CREATE_TABLE_SQL)
    print("Table ALERTS: ready")

    # Upsert rows
    ok, failed = 0, []
    for alert in ALERTS:
        row = {k: v for k, v in alert.items() if k != "GOLD_DISPOSITION"}      # the answer key is not an ALERTS column
        wd = SUSPICION_WD_AGO.get(alert["ALERT_ID"])
        row["SUSPICION_FORMED_AT"] = suspicion_formed_at(wd).isoformat() if wd is not None else None
        row["RFI_TRIGGERS"] = json.dumps(row["RFI_TRIGGERS"])
        row["POE_FACTORS"]  = json.dumps(row["POE_FACTORS"])
        row["RULES_CITED"]  = json.dumps(row["RULES_CITED"])
        try:
            cur.execute(MERGE_SQL, row)
            ok += 1
        except Exception as e:
            failed.append((alert["ALERT_ID"], str(e)))

    # The answer key, in a table the application role cannot read
    cur.execute(LABELS_CREATE_SQL)
    label_failed = []
    for aid, label in GOLD_LABELS.items():
        try:
            cur.execute(LABELS_MERGE_SQL, {"ALERT_ID": aid, "GOLD_DISPOSITION": label})
        except Exception as e:
            label_failed.append((aid, str(e)))
    print(f"Table ALERT_GOLD_LABELS: {len(GOLD_LABELS) - len(label_failed)} labels loaded (not readable by the app role)")

    # Create + seed TRANSACTIONS (T1)
    cur.execute(TRANSACTIONS_DDL)
    print("Table TRANSACTIONS: ready")
    txn_ok, txn_failed = 0, []
    for txn in TRANSACTIONS:
        try:
            cur.execute(TXN_MERGE_SQL, txn)
            txn_ok += 1
        except Exception as e:
            txn_failed.append((txn["TXN_ID"], str(e)))

    cur.close()
    conn.close()

    print(f"Seeded ALERTS: {ok} rows OK, {len(failed)} failed")
    for aid, err in failed:
        print(f"  FAILED {aid}: {err}")
    print(f"Seeded TRANSACTIONS: {txn_ok} rows OK, {len(txn_failed)} failed")
    for tid, err in txn_failed:
        print(f"  FAILED {tid}: {err}")

    for aid, err in label_failed:
        print(f"  FAILED label {aid}: {err}")
    if not failed:
        print("\nVerification query (admin role only; the app role is denied this table):")
        print("  SELECT GOLD_DISPOSITION, COUNT(*) FROM FIU_COPILOT.AML.ALERT_GOLD_LABELS GROUP BY 1 ORDER BY 1;")
        print("  Expected: CONTESTED=4, FILE=10, NOT_FILE=5")


if __name__ == "__main__":
    main()
