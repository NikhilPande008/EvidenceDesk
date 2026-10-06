"""
Independent-review protocol — UI behaviour under the feature flag (FIU_HUMAN_REVIEW), via Streamlit AppTest.

Proves (flag ON): the AI reveal is held until a first impression is saved; saving unlocks it; the provisional
read is per-case and does not migrate; a higher-risk closure shows the reconciliation panel and the record
button stays disabled until it is complete. And (flag OFF): none of this appears — behaviour is unchanged.

Offline. No Snowflake, no model, no network.
"""

from __future__ import annotations

import sys

from _helpers import ROOT

sys.path.insert(0, str(ROOT / "tests"))
from skills import po_copy as T  # noqa: E402
from skills import review_monitor as rvm  # noqa: E402
from test_ui_states import _choose, _disposition, _everything, _no_exception, _record_button, run_app  # noqa: E402

FLAG = "FIU_HUMAN_REVIEW"
SAVED_PROV = {"view": "SUSPICION_SUPPORTED", "evidence_refs": ["x"], "unanswered_question": "q", "saved_at": "2026-10-02T00:00:00Z"}


def _run_btn(at):
    return next((b for b in at.button if "Run 11-Factor" in (b.label or "")), None)


# ── flag OFF: nothing changes ──────────────────────────────────────────────────
def test_flag_off_no_provisional_panel_and_ai_runnable(monkeypatch):
    monkeypatch.delenv(FLAG, raising=False)
    at = _disposition("ALERT-01")
    _no_exception(at)
    assert T.HR_PROVISIONAL_TITLE not in _everything(at)
    assert _run_btn(at) is not None, "with the flag off the assessment is runnable as before"
    print("  [PASS] flag off: no First-impression panel; the AI assessment is runnable exactly as before")


# ── flag ON: the AI reveal is gated by a saved first impression ────────────────
def test_ai_locked_until_first_impression_saved(monkeypatch):
    monkeypatch.setenv(FLAG, "1")
    at = _disposition("ALERT-01")
    _no_exception(at)
    page = _everything(at)
    assert T.HR_PROVISIONAL_TITLE in page, "the First-impression panel is shown"
    assert T.HR_AI_LOCKED in page, "the AI reveal is locked"
    assert _run_btn(at) is None, "no Run button is offered while locked"
    print("  [PASS] flag on, no first impression: AI held back (exact lock copy), no Run button")


def test_saving_first_impression_unlocks_ai(monkeypatch):
    monkeypatch.setenv(FLAG, "1")
    at = _disposition("ALERT-01", state={"prov_read_ALERT-01": SAVED_PROV})
    _no_exception(at)
    assert T.HR_AI_LOCKED not in _everything(at), "once saved, the lock is gone"
    assert _run_btn(at) is not None, "the assessment is now runnable"
    print("  [PASS] flag on, first impression saved: AI reveal unlocked, Run button offered")


def test_provisional_read_does_not_migrate_between_cases(monkeypatch):
    monkeypatch.setenv(FLAG, "1")
    # a first impression saved for ALERT-01 must not unlock a DIFFERENT case
    at = _disposition("ALERT-16", state={"prov_read_ALERT-01": SAVED_PROV})
    _no_exception(at)
    assert T.HR_AI_LOCKED in _everything(at), "ALERT-16 stays locked; ALERT-01's read must not migrate"
    assert _run_btn(at) is None
    print("  [PASS] flag on: a first impression is per-case; it does not unlock another case")


# ── flag ON: a higher-risk closure requires reconciliation before recording ────
def test_flagged_closure_requires_reconciliation_and_disables_record(monkeypatch):
    monkeypatch.setenv(FLAG, "1")
    # ALERT-01 has an I4C-flagged counterparty; closing it is a CLOSE_WITH_FLAGGED_TXN trigger (no AI needed).
    body = "Closing: the credits are documented and the onward transfer has an invoice on file; no suspicion formed here."
    at = _disposition("ALERT-01", state={"prov_read_ALERT-01": SAVED_PROV,
                                          "gos_text_ALERT-01": body, "_keep_gos_text_ALERT-01": body, "po_id": "PO-T", "_keep_po_id": "PO-T"})
    at = _choose(at, "NOT_FILE")
    _no_exception(at)
    assert T.HR_RECONCILE_TITLE in _everything(at), "the reconciliation panel appears for a flagged-transaction closure"
    btn = _record_button(at)
    assert btn is not None and btn.disabled, "recording is disabled until the reconciliation is complete"
    print("  [PASS] flag on: a flagged-transaction closure shows the reconciliation panel and blocks recording until complete")


def test_dashboard_shows_second_line_monitoring_when_flag_on(monkeypatch):
    monkeypatch.setenv(FLAG, "1")
    at = run_app(page="Dashboard")
    _no_exception(at)
    assert "NOT an officer scorecard" in _everything(at), "the second-line monitoring disclaimer is present"
    print("  [PASS] flag on: the Dashboard shows the second-line review-monitoring panel with its disclaimer")


def test_dashboard_has_no_monitoring_panel_when_flag_off(monkeypatch):
    monkeypatch.delenv(FLAG, raising=False)
    at = run_app(page="Dashboard")
    _no_exception(at)
    assert "NOT an officer scorecard" not in _everything(at), "no monitoring panel when the flag is off"
    print("  [PASS] flag off: the Dashboard shows no review-monitoring panel (unchanged)")


def test_flag_off_flagged_closure_has_no_reconciliation_panel(monkeypatch):
    monkeypatch.delenv(FLAG, raising=False)
    body = "Closing: the credits are documented and the onward transfer has an invoice on file; no suspicion formed here."
    at = _disposition("ALERT-01", state={"gos_text_ALERT-01": body, "_keep_gos_text_ALERT-01": body, "po_id": "PO-T", "_keep_po_id": "PO-T"})
    at = _choose(at, "NOT_FILE")
    _no_exception(at)
    assert T.HR_RECONCILE_TITLE not in _everything(at), "with the flag off there is no reconciliation gate"
    print("  [PASS] flag off: the same flagged closure shows no reconciliation panel (unchanged behaviour)")
