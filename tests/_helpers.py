"""Shared builders for the offline test suites (no Snowflake required)."""

from __future__ import annotations

import json
import os
import sys
from contextlib import contextmanager
from pathlib import Path

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))

FIXTURES = Path(__file__).parent / "fixtures"


_ENV_PREFIXES = ("SNOWFLAKE_", "FIU_")


@contextmanager
def scoped_env(**overrides):
    """Set (or, with None, unset) environment variables for a block, then restore EVERY SNOWFLAKE_* / FIU_* variable exactly.
    A test that fakes credentials must never delete the developer's real ones: a default `pytest -q` runs the live suites
    in the same process, after the offline ones."""
    keys = {k for k in os.environ if k.startswith(_ENV_PREFIXES)} | set(overrides)
    saved = {k: os.environ.get(k) for k in keys}
    try:
        for k, v in overrides.items():
            os.environ.pop(k, None) if v is None else os.environ.__setitem__(k, v)
        yield
    finally:
        for k in keys | {k for k in os.environ if k.startswith(_ENV_PREFIXES)}:
            if saved.get(k) is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = saved[k]


def fixture(name: str) -> str:
    return (FIXTURES / name).read_text()


def case_context() -> dict:
    """Small synthetic case whose transactions match tests/fixtures/gos_good.txt."""
    return {
        "customer_kyc": ("Salaried employee. Declared annual income ₹3.6L. Account held since 2022. "
                         "KYC last verified 2023-01-10."),
        "transactions": [
            {"txn_id": "TXN-001", "date": "2026-08-12", "type": "CREDIT", "amount_inr": 345000,
             "channel": "UPI", "counterparty": "Unidentified individual A"},
            {"txn_id": "TXN-002", "date": "2026-08-19", "type": "CREDIT", "amount_inr": 210000,
             "channel": "UPI", "counterparty": "Unidentified individual B"},
            {"txn_id": "TXN-003", "date": "2026-08-19", "type": "DEBIT", "amount_inr": 547000,
             "channel": "UPI", "counterparty": "UPI-98XXXXXX76 (I4C flagged)", "is_flagged": True},
        ],
        "signal_tags": ["I4C_FLAG", "PASS_THROUGH"],
        "alert_narrative": "Pass-through mule pattern.",
    }


def checklist_json(applies: list[bool] | None = None) -> str:
    """A well-formed 10-item quality-check response (default: all pass)."""
    applies = applies if applies is not None else [False] * 10
    return json.dumps([
        {"item_number": i + 1, "item": f"check {i + 1}", "applies": a, "note": "ok"}
        for i, a in enumerate(applies)
    ])


def factors_json(assessment: str = "clear", triggered: tuple[str, ...] = (), drop: tuple[str, ...] = (),
                 cite: tuple[str, ...] = ("TXN-001",), evidence: str | None = None) -> str:
    """A well-formed 11-factor evaluator response. Triggered factors cite `cite` txn IDs."""
    from skills.core import POE_FACTORS
    rows = []
    for fid, fname in POE_FACTORS:
        if fid in drop:
            continue
        a = "triggered" if fid in triggered else assessment
        rows.append({"factor_id": fid, "factor_name": fname, "assessment": a,
                     "evidence": evidence or f"{fname}: evidence text",
                     "evidence_txn_ids": list(cite) if a == "triggered" else [], "rules_cited": []})
    return json.dumps(rows)


def skills(cortex_fn=None):
    """CoPilotSkills with no database (deterministic paths + injected model)."""
    from skills import CoPilotSkills
    return CoPilotSkills(None, cortex_fn=cortex_fn)


class Runner:
    """Tiny pytest-independent runner so every suite also runs as `python3 tests/x.py`."""

    def __init__(self, title: str):
        self.title = title
        self.passed = self.failed = 0

    def run(self, tests: list) -> int:
        print(f"{self.title}\n")
        for fn in tests:
            try:
                fn()
                self.passed += 1
            except Exception as exc:  # noqa: BLE001 - report every failure, keep going
                self.failed += 1
                print(f"  [FAIL] {fn.__name__}: {type(exc).__name__}: {exc}")
        print(f"\n{self.passed}/{self.passed + self.failed} tests passed.")
        return 1 if self.failed else 0


# ── recording fake connection (connector-style: no `.sql` attribute) ─────────
class FakeCursor:
    def __init__(self, conn):
        self.conn, self._rows, self.description = conn, [], None

    def execute(self, sql, params=None):
        self.conn.log.append(sql)
        self._rows = self.conn.respond(sql)
        return self

    def fetchall(self):
        return list(self._rows)

    def fetchone(self):
        return self._rows[0] if self._rows else None

    def close(self):
        pass


class FakeConn:
    """Records every statement. `responders` = [(substring, rows_or_callable)] checked in order."""

    def __init__(self, responders=None, in_txn=False, integrity="INTACT"):
        self.log: list[str] = []
        self.in_txn = in_txn
        self.responders = list(responders or [])
        self.integrity = integrity

    def cursor(self, *_a, **_k):
        return FakeCursor(self)

    def respond(self, sql):
        for needle, rows in self.responders:
            if needle in sql:
                return rows(sql) if callable(rows) else rows
        if "CURRENT_TRANSACTION" in sql:
            return [{"T": "12345" if self.in_txn else None}]
        if "INTEGRITY_STATUS" in sql:
            return [{"INTEGRITY_STATUS": self.integrity, "STORED_HASH": "a" * 64}] if self.integrity else []
        if "COUNT(DISTINCT CORPUS_VERSION)" in sql:
            return [{"VERSION": "1.1.0", "N_VERSIONS": 1, "SNAPSHOT": "2026-09-17", "TOTAL": 49, "PROVEN": 15,
                     "ASSUMED": 21, "NV": 13, "VERIFIED": 0, "SUPERSEDED": 0}]
        if "REGULATORY_CORPUS WHERE RULE_ID IN" in sql:
            return corpus_rows(sql)
        return []

    # statements of a given kind that were executed
    def stmts(self, prefix: str) -> list[str]:
        return [s for s in self.log if s.lstrip().upper().startswith(prefix.upper())]


# Governance columns for a few real corpus rules, in the shape the database returns them (upper-case keys).
CORPUS_FIXTURE = {
    "STR-001": dict(EVIDENCE_LEVEL="PROVEN", SOURCE_AUTHORITY="STATUTE", REVIEW_STATUS="AUTHOR_ASSERTED"),
    "STR-002": dict(EVIDENCE_LEVEL="PROVEN", SOURCE_AUTHORITY="FIU_IND_GUIDANCE", REVIEW_STATUS="AUTHOR_ASSERTED"),
    "POE-003": dict(EVIDENCE_LEVEL="ASSUMED", SOURCE_AUTHORITY="PRODUCT_COMPILED", REVIEW_STATUS="AUTHOR_ASSERTED"),
    "INS-001": dict(EVIDENCE_LEVEL="ASSUMED", SOURCE_AUTHORITY="FIU_IND_PUBLICATION", REVIEW_STATUS="AUTHOR_ASSERTED"),
    "RFI-001": dict(EVIDENCE_LEVEL="NEEDS-VERIFICATION", SOURCE_AUTHORITY="INDUSTRY_PRACTICE", REVIEW_STATUS="DRAFT"),
}


def corpus_rows(sql: str, overrides: dict | None = None) -> list[dict]:
    """The rows a `... REGULATORY_CORPUS WHERE RULE_ID IN ('A', 'B')` query would return from CORPUS_FIXTURE
    (+ `overrides` {rule_id: {COLUMN: value} or None to drop the rule})."""
    import re
    book = dict(CORPUS_FIXTURE)
    for rid, edit in (overrides or {}).items():
        if edit is None:
            book.pop(rid, None)                       # drop the rule: the corpus has no such row
        else:
            book[rid] = {**book.get(rid, {}), **edit}  # edit columns of the rule (merge, not replace)
    rows = []
    for rid in re.findall(r"'([^']+)'", sql.split("RULE_ID IN", 1)[1]):
        spec = book.get(rid)
        if spec is None:
            continue
        rows.append({"RULE_ID": rid, "CORPUS_VERSION": "1.1.0", "SNAPSHOT_DATE": "2026-09-11", "LAST_VERIFIED": None,
                     "VERIFIED_BY": None, "SUPERSEDED_BY": None, **spec})
    return rows


def basis_for(ids, overrides: dict | None = None, error: str | None = None) -> dict:
    """A decision-level regulatory basis built (as the recorder does) from CORPUS_FIXTURE rows. `overrides`
    {rule_id: {COLUMN: value} | None} edits / drops fixture rules (e.g. SUPERSEDED_BY, REVIEW_STATUS, a missing rule)."""
    from skills.governance import build_regulatory_basis
    sql = "WHERE RULE_ID IN (" + ", ".join(f"'{i}'" for i in ids) + ")"
    rows = [{k.lower(): v for k, v in r.items()} for r in corpus_rows(sql, overrides)]
    return build_regulatory_basis(list(ids), rows, corpus_version="1.1.0", snapshot_date="2026-09-17", error=error)


def rule_row(rid: str, level: str, **kw) -> dict:
    """A full REGULATORY_CORPUS row (every column the lookup selects), upper-case keys as the database returns them."""
    base = dict(RULE_ID=rid, RULE_TEXT=f"text {rid}", MY_SYNTHESIS="", EVIDENCE_LEVEL=level, SOURCE_DOCUMENT="d", SOURCE_URL="u",
                SOURCE_URL_VERIFIED=False, SNAPSHOT_DATE="2026-09-17", CATEGORY="C", SOURCE_AUTHORITY="STATUTE", CORPUS_VERSION="1.1.0",
                REVIEW_STATUS="AUTHOR_ASSERTED", OWNER="o", LAST_VERIFIED=None, VERIFIED_BY=None, SUPERSEDED_BY=None, REPLACES=None)
    base.update(kw)
    return base


def recorder_kwargs(**over) -> dict:
    """A valid FILE call for the recorder, grounded in case_context()."""
    ctx = case_context()
    ctx["context_dates"] = ["2026-08-19"]
    kw = dict(
        alert_id="ALERT-01", customer_ref="CUST-01", disposition="FILE",
        rationale_text=fixture("gos_good.txt"), rules_cited=["STR-001", "RFI-001"], rfi_triggers=["RFI-001"],
        poe_assessment=json.loads(factors_json(triggered=("POE-003", "POE-005", "POE-007"))),
        decision_maker_id="PO-TEST", ai_recommendation="FILE", case_context=ctx,
        gos_quality={"status": "READY", "quality_score": 10, "hard_gate_passed": True, "ai_output_valid": True},
    )
    kw.update(over)
    return kw


# ── minimal Snowflake SQL scanner (for injection tests) ─────────────────────
_ESC = {"n": "\n", "t": "\t", "r": "\r", "0": "\0", "b": "\b", "f": "\f", "\\": "\\", "'": "'", '"': '"'}


def scan_sql(sql: str) -> tuple[int, list[str]]:
    """(number of top-level statements, decoded single-quoted literals) using Snowflake rules:
    '' and backslash escapes inside '...', $$...$$ raw strings, -- and /* */ comments."""
    i, n, stmts, has, lits = 0, len(sql), 0, False, []
    while i < n:
        c = sql[i]
        if c == "'":
            j, buf = i + 1, []
            while True:
                if j >= n:
                    raise ValueError("unterminated string literal — quoting was broken")
                if sql[j] == "\\" and j + 1 < n:
                    buf.append(_ESC.get(sql[j + 1], sql[j + 1])); j += 2; continue
                if sql[j] == "'":
                    if j + 1 < n and sql[j + 1] == "'":
                        buf.append("'"); j += 2; continue
                    break
                buf.append(sql[j]); j += 1
            lits.append("".join(buf)); i, has = j + 1, True
            continue
        if sql.startswith("$$", i):
            end = sql.index("$$", i + 2)
            lits.append(sql[i + 2:end]); i, has = end + 2, True
            continue
        if sql.startswith("--", i):
            i = sql.find("\n", i); i = n if i < 0 else i
            continue
        if sql.startswith("/*", i):
            i = sql.index("*/", i) + 2
            continue
        if c == ";":
            stmts += 1 if has else 0
            has, i = False, i + 1
            continue
        if not c.isspace():
            has = True
        i += 1
    return stmts + (1 if has else 0), lits


HOSTILE_STRINGS = [
    "'; DROP TABLE FIU_COPILOT.AML.DECISION_LEDGER; --",
    "\\'; DROP TABLE FIU_COPILOT.AML.DECISION_LEDGER; --",
    "\\\\'; DROP TABLE x; --",
    "x\\",
    "$$; DROP TABLE x; $$",
    "') OR 1=1; DELETE FROM FIU_COPILOT.AML.DECISION_LEDGER; --",
    "%s %(name)s {0} {{x}} %%",
    "line1\nline2\r\nline3\ttab",
    "unicode ₹ 😀 é 你好",
    "'" * 41,
    "\\" * 41,
    "/* comment */ -- trailing",
    "A" * 20000,
]
