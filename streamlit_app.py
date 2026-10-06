"""
FIU-IND AML Defensible-Disposition Copilot
Streamlit-in-Snowflake — Principal Officer workflow

An AML decision-defensibility and investigation copilot. Fraud and mule-risk signals are generated or ingested by other systems; this
application investigates, prioritises, explains and supports a defensible disposition by a Principal Officer, and records why.
It does not detect fraud, give legal advice, file reports or verify regulatory compliance (skills/po_copy.py POSITIONING_*).

Pages (sidebar):
  1. Alert Queue        — prioritised cases (transparent score) + the judge-demo twin pair (ALERT-01 vs ALERT-16)
  2. Disposition Panel  — source facts + evidence quality + relationships | regulatory basis | AI inference | counter-evidence | human decision
  3. Decision Ledger    — append-only audit trail, integrity status, audit-export protection status, decision reconstruction
  4. Dashboard          — alert-to-STR ratio + Cortex Analyst NL questions
  5. Regulatory Search  — Cortex Search over the corpus, PROVEN vs ASSUMED, superseded handling
  6. Corpus Governance  — rule lifecycle: review, verification, approval, supersession (read-only)
  7. Model Quality      — human feedback and model-quality monitoring (read-only; never changes a policy)
  8. Business Value     — KPI model: measured, proxy, not measured, simulated
  9. Architecture       — reference architecture, implemented / simulated / production, security readiness, limitations

Design rules this file enforces (each has a test):
  * SOURCE FACTS (deterministic, from TRANSACTIONS) are visually separate from AI INFERENCE (Cortex).
  * READY / FILE are decided by skills.llm_output.gos_readiness and the recorder — never by UI defaults.
  * Every dynamic value inside HTML is escaped (esc()).
  * Every database / Cortex failure renders an explicit error state that says what still works.
"""

import hashlib
import html
import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import streamlit as st

ROOT = Path(__file__).parent
sys.path.insert(0, str(ROOT))
PACK_APP_VERSION = "2026-10"       # written into every inspection pack beside the prompt and skill versions

# ── connection ────────────────────────────────────────────────────────────────
def _get_connection():
    """Snowpark Session inside Streamlit-in-Snowflake; connector connection locally (.env)."""
    try:
        from snowflake.snowpark.context import get_active_session
        return get_active_session()
    except Exception:
        pass
    from skills.connection import connect_from_env, load_env
    load_env(ROOT)
    return connect_from_env()        # raises SnowflakeConfigError / SnowflakeConnectError (actionable, secret-free)


@st.cache_resource
def get_conn():
    return _get_connection()


def sql(query: str) -> list[dict]:
    """Execute SQL and return rows as list of dicts (raises on error)."""
    conn = get_conn()
    if hasattr(conn, "sql"):                          # Snowpark Session
        return [row.as_dict() for row in conn.sql(query).collect()]
    import snowflake.connector
    cur = conn.cursor(snowflake.connector.DictCursor)
    try:
        cur.execute(query)
        return cur.fetchall()
    finally:
        cur.close()


def query(query_text: str, area: str = "This page"):
    """(rows, message). A database failure becomes a short, actionable message for the PO (skills/errors.py) — never a stack trace,
    never SQL or object names; the technical line goes to the server log, redacted."""
    from skills.errors import explain
    try:
        return sql(query_text), None
    except Exception as err:  # noqa: BLE001
        return [], explain(err, area)["message"]


def get_skills():
    from skills import CoPilotSkills
    return CoPilotSkills(get_conn())


def get_analyst():
    from skills import CorpusAnalyst
    # _snowflake is only importable from the top-level SiS app scope, not from submodules; inject it.
    snow_api_fn = None
    try:
        import _snowflake
        snow_api_fn = _snowflake.send_snow_api_request
    except ImportError:
        pass
    return CorpusAnalyst(get_conn(), snow_api_fn=snow_api_fn)


# ── presentation helpers ──────────────────────────────────────────────────────
PAGE_LABELS = {
    "Alert Queue": "My cases",
    "Disposition Panel": "Investigation desk",
    "Decision Ledger": "Decision archive",
    "Dashboard": "Tools · Inspection overview",
    "Regulatory Reference": "Tools · Regulatory reference",
    "Corpus Governance": "Tools · Corpus governance",
    "Model Quality": "Tools · Model quality",
    "Business Value": "Tools · Business value",
    "Architecture": "Tools · Architecture & readiness",
}
DISPOSITION_PAGE = "Disposition Panel"


def apply_visual_foundation():
    """Presentation only. Native widgets retain labels, focus and stable state keys.

    Keep this inline so the existing SiS source-file manifest needs no new asset.
    Theme-aware surfaces leave native input and alert contrast to Streamlit.
    """
    st.markdown("""<style>
    [data-testid="stAppViewContainer"] {
        font-variant-numeric: tabular-nums;
        background: var(--background-color);
    }
    .stMainBlockContainer { max-width: 1500px; padding-top: 2rem; padding-bottom: 3rem; }
    h1, h2, h3 { letter-spacing: -0.025em; }
    h2 { font-weight: 650; }
    [data-testid="stCaptionContainer"] { line-height: 1.5; }
    [data-testid="stMetricValue"] { font-variant-numeric: tabular-nums; font-size: 1.65rem; }
    [data-testid="stMetricLabel"] { font-size: 0.85rem; }
    [data-testid="stSidebar"] { border-right: 1px solid #8693a340; }
    [data-testid="stSidebar"] [role="radiogroup"] { gap: 0.25rem; }
    [data-testid="stSidebar"] [role="radiogroup"] > label {
        padding: 0.55rem 0.65rem; border-radius: 3px;
    }
    [data-testid="stSidebar"] [role="radiogroup"] > label:has(input:checked) {
        background: #7d94ad22; box-shadow: inset 3px 0 #647f9c;
    }
    [data-testid="stSidebar"] [role="radiogroup"] > label:nth-child(4) {
        margin-top: 1.25rem; border-top: 1px solid #8693a340; padding-top: 1rem;
    }
    .stButton button { border-radius: 4px; min-height: 2.5rem; box-shadow: none; }
    .stButton button[kind="primary"] { background: #203a53; border-color: #203a53; color: #ffffff; }
    .stButton button[kind="primary"]:hover:not(:disabled) { background: #304e6b; border-color: #304e6b; color: #ffffff; }
    .stButton button:disabled { opacity: 0.5; }
    button:focus-visible, a:focus-visible, input:focus-visible, textarea:focus-visible {
        outline: 3px solid #6486ab !important; outline-offset: 3px;
    }
    [data-testid="stVerticalBlockBorderWrapper"] { box-shadow: none; }
    .desk-brand { font-size: 1.4rem; font-weight: 650; letter-spacing: -0.035em; margin: 0; }
    .desk-kicker { font-size: 0.72rem; letter-spacing: 0.12em; font-weight: 650; margin-bottom: 0.4rem; }
    .case-contents { display: flex; flex-wrap: wrap; gap: 0.55rem 1.4rem; padding: 0.8rem 0;
        border-top: 1px solid #8693a340; border-bottom: 1px solid #8693a340; margin-bottom: 1.2rem; }
    .case-contents a { color: inherit; text-underline-offset: 4px; }
    .case-anchor { scroll-margin-top: 5rem; }
    .money-flow { display: grid; grid-template-columns: 1fr auto 1fr auto 1fr; gap: 0.5rem;
        align-items: stretch; margin: 0.8rem 0; }
    .money-node { border: 1px solid #8693a370; border-radius: 4px; padding: 0.7rem; min-width: 0;
        overflow-wrap: anywhere; }
    .money-node strong { display: block; font-size: 1.05rem; margin: 0.3rem 0; }
    .money-node small { display: block; line-height: 1.5; }
    .money-arrow { align-self: center; }
    .net-flow { display: grid; grid-template-columns: 1fr auto 1fr auto 1fr; gap: 0.5rem; align-items: start; margin: 0.6rem 0; }
    .net-col, .net-centre { display: flex; flex-direction: column; gap: 0.4rem; min-width: 0; }
    .net-head { font-size: 0.72rem; letter-spacing: 0.1em; font-weight: 650; opacity: 0.85; }
    .net-chip { border: 1px solid #8693a370; border-radius: 4px; padding: 0.45rem 0.6rem; overflow-wrap: anywhere; }
    .net-chip.flag { border-width: 2px; border-color: #c62828; }
    .net-chip small { display: block; line-height: 1.45; opacity: 0.9; }
    .net-arrow { align-self: center; }
    .arch-stage { border: 1px solid #8693a370; border-left-width: 6px; border-radius: 4px; padding: 0.6rem 0.8rem; margin: 0.4rem 0; overflow-wrap: anywhere; }
    .arch-stage small { display: block; line-height: 1.5; }
    @media (max-width: 760px) {
        .net-flow { grid-template-columns: 1fr; }
        .net-arrow { text-align: center; transform: rotate(90deg); }
    }
    @media (max-width: 1000px) {
        .st-key-case_workspace > [data-testid="stLayoutWrapper"] > [data-testid="stHorizontalBlock"] {
            flex-direction: column;
        }
        .st-key-case_workspace > [data-testid="stLayoutWrapper"] > [data-testid="stHorizontalBlock"] > [data-testid="stColumn"] {
            width: 100% !important; flex: 1 1 100% !important;
        }
    }
    @media (max-width: 520px) {
        .money-flow { grid-template-columns: 1fr; }
        .money-arrow { text-align: center; transform: rotate(90deg); }
    }
    @media (prefers-color-scheme: light) {
        [data-testid="stAppViewContainer"] { background: var(--background-color, #faf9f6); }
    }
    @media (max-width: 760px) {
        .stMainBlockContainer { padding: 1.25rem 1rem 2rem; }
        [data-testid="stMetricValue"] { font-size: 1.35rem; }
    }
    </style>""", unsafe_allow_html=True)


def esc(value) -> str:
    """HTML-escape any dynamic value before it goes into unsafe_allow_html markup. Two defences against the Markdown parser that also reads this
    markup: `](` is written as an entity (displays the same, can never start a link or image), and whitespace is collapsed (HTML collapses it
    anyway) because a BLANK LINE ends an HTML block and everything after it would be parsed as Markdown."""
    return html.escape(" ".join(("" if value is None else str(value)).split()), quote=True).replace("](", "]&#40;")


def md_safe(value) -> str:
    """Neutralise Markdown in UNTRUSTED text (alert narratives, claims echoed from a narrative, AI output) before it goes into
    st.markdown, so hostile evidence cannot inject links/images (an outbound request) or restyle the page."""
    import re
    return re.sub(r"([\\`*_{}\[\]()#+\-.!|<>~$:&])", r"\\\1", "" if value is None else str(value))


_LABEL_MAP = str.maketrans({"`": "′", "[": "［", "]": "］", "<": "＜", ">": "＞", "$": "＄"})


def label_safe(value) -> str:
    """Untrusted text in a widget LABEL or OPTION (expander, checkbox, select / multiselect option): Streamlit renders these as Markdown, and links and
    images in them are live. Backslash escapes (md_safe) would show as literal backslashes wherever a label turns out to be plain text, so the few
    characters that form links, images, HTML, code spans and maths are replaced with look-alikes. Ordinary IDs and names are unchanged."""
    return " ".join(("" if value is None else str(value)).split()).translate(_LABEL_MAP)


def safe_url(value) -> str | None:
    """A corpus-supplied source link, or None. Only a plain http(s) URL with no characters that could end a Markdown link or start another construct."""
    import re
    text = ("" if value is None else str(value)).strip()
    return text if re.fullmatch(r"https?://[^\s<>()\[\]`\"'\\]+", text) else None


def code_safe(value) -> str:
    """Untrusted text destined for a `code span`: a backtick would end the span, so it is replaced; newlines are flattened."""
    return " ".join(("" if value is None else str(value)).replace("`", "′").split())


def badge(text: str, bg: str, fg: str) -> str:
    return (f'<span style="background:{bg};color:{fg};padding:2px 8px;'
            f'border-radius:4px;font-size:0.78em;font-weight:600">{esc(text)}</span>')


def bordered():
    """st.container(border=True) needs Streamlit ≥1.29; older Streamlit-in-Snowflake runtimes get a plain container."""
    try:
        return st.container(border=True)
    except TypeError:
        return st.container()


def toggle(label: str, key: str) -> bool:
    return st.toggle(label, key=key) if hasattr(st, "toggle") else st.checkbox(label, key=key)


def html_md(markup: str):
    st.markdown(markup, unsafe_allow_html=True)


DISP_COLORS = {"FILE": "#38546c", "NOT_FILE": "#38546c", "CONTESTED": "#9a600a", "DEFERRED": "#9a600a",
               "ESCALATE": "#8e24aa", "OPEN": "#1e88e5", "REVIEWED": "#8e24aa", "CLOSED": "#546e7a"}
EVIDENCE_BADGE = {
    "PROVEN":             ("🟢", "#e8f5e9", "#2e7d32"),
    "ASSUMED":            ("🟡", "#fff8e1", "#f57f17"),
    "NEEDS-VERIFICATION": ("🔴", "#fce4ec", "#c62828"),
}
STATUS_STYLE = {   # GoS / quality status → (colour, label)
    "READY":               ("#2e7d32", "READY"),
    "NEEDS_REVISION":      ("#e65100", "NEEDS REVISION"),
    "REJECT":              ("#c62828", "REJECT"),
    "NEEDS_MANUAL_REVIEW": ("#283593", "NEEDS MANUAL REVIEW"),
    "NOT_CHECKED":         ("#546e7a", "NOT CHECKED"),
    "STALE":               ("#546e7a", "EDITED SINCE CHECK"),
}
DEMO_PAIR = ("ALERT-01", "ALERT-16")     # same signal, different evidence, opposite defensible outcomes


def disp_badge(disposition: str) -> str:
    color = DISP_COLORS.get(disposition, "#607d8b")
    return badge(disposition, color + "22", color)


def evidence_badge(level: str) -> str:
    _, bg, fg = EVIDENCE_BADGE.get(level, ("⚪", "#f5f5f5", "#333"))
    return badge(level, bg, fg)


def _short(err) -> str:
    """Kept for the few messages that are ALREADY curated by our own code (connection setup, validators). Anything that can carry a
    database or model exception goes through explain() instead."""
    return (str(err).strip().splitlines() or [type(err).__name__])[0][:220]


def explained(err, area: str) -> str:
    from skills.errors import explain
    return explain(err, area)["message"]


def db_error(err_message: str):
    """`err_message` is already the explained, PO-facing sentence(s) from query()/explained()."""
    st.error(err_message)


# ── SLA helpers (shared arithmetic: skills.ledger) ────────────────────────────
from skills import po_copy as T  # noqa: E402
from skills.saved_responses import SOURCE_SAVED, SavedResponseUnavailable  # noqa: E402
from skills import human_review as hr  # noqa: E402
from skills import review_monitor as rvm  # noqa: E402
from skills import audit as aud  # noqa: E402
from skills import corpus_lifecycle as cl  # noqa: E402
from skills import evidence_quality as eq  # noqa: E402
from skills import feedback as fbk  # noqa: E402
from skills import identity as ident  # noqa: E402
from skills import kpis as kpi  # noqa: E402
from skills import prioritisation as prio  # noqa: E402
from skills import readiness as rdy  # noqa: E402
from skills import relationships as rel  # noqa: E402
from skills.ledger import MIN_OVERRIDE_REASON_CHARS  # noqa: E402
from skills.ledger import IST, SLA_WORKING_DAYS, working_days_elapsed  # noqa: E402


def sla_days_left(alert_date) -> int:
    """Working days (Mon–Fri) left in the 7-WD window counted from the alert date. Negative = overdue."""
    return SLA_WORKING_DAYS - working_days_elapsed(alert_date, datetime.now(IST))


def sla_color(days: int) -> str:
    return "#e53935" if days <= 1 else ("#fb8c00" if days <= 4 else "#43a047")


def sla_pill(days: int) -> str:
    label = f"{-days} WD overdue" if days < 0 else ("Due today" if days == 0 else f"{days} WD left")
    color = sla_color(days)
    return badge(label, color + "22", color)


def _session_user_id() -> str:
    """The AUTHENTICATED session identity, or '' when there is none.

    * Inside Streamlit-in-Snowflake (the connection is a Snowpark session) the runtime supplies the viewer's Snowflake user name
      (`st.user["user_name"]`): that is an authenticated identity.
    * A locally configured OIDC login (`st.user.is_logged_in`) supplies a verified e-mail: also authenticated.
    * Streamlit's local-development placeholder (for example `test@localhost.com` / `test@example.com`) is NOT an identity. An earlier build
      pre-filled the officer's ID from it; it is now ignored, so a typed ID is honestly labelled as typed.
    Whether the hosted runtime supplies `user_name`, and for which user, has not been verified in Snowsight (KNOWN_LIMITATIONS.md)."""
    for attr in ("user", "experimental_user"):
        try:
            u = getattr(st, attr, None)
            if not u:
                continue
            hosted = hasattr(get_conn(), "sql")
            name = u.get("user_name")
            if name and hosted:
                return str(name)
            if u.get("is_logged_in") and u.get("email"):
                return str(u.get("email"))
        except Exception:
            continue
    return ""


def _sticky(key: str, default):
    """Streamlit drops an unrendered widget's state on page switch; restore it from a shadow key."""
    shadow = f"_keep_{key}"
    if key not in st.session_state:
        st.session_state[key] = st.session_state.get(shadow, default)
    return shadow


# ── cached reads ──────────────────────────────────────────────────────────────
@st.cache_data(ttl=300, show_spinner=False)
def cached_corpus_summary() -> dict:
    return get_skills().corpus_summary()


@st.cache_data(ttl=60, show_spinner=False)
def cached_rule_basis(rule_ids: tuple) -> dict:
    """The decision-level regulatory-basis object for the rules an alert cites (skills.governance.build_regulatory_basis)."""
    return get_skills().rule_basis(list(rule_ids))


@st.cache_data(ttl=60, show_spinner=False)
def cached_transactions(alert_id: str) -> list[dict]:
    return get_skills().load_transactions(alert_id)


def load_txns(alert_id: str):
    """(transactions, error). An unreadable ledger is an ERROR state — never silently 'no transactions'."""
    try:
        return cached_transactions(alert_id), None
    except Exception as err:  # noqa: BLE001
        return [], explained(err, "The transaction record")


@st.cache_data(ttl=60, show_spinner=False)
def cached_all_transactions() -> tuple[dict, dict]:
    """({alert_id: [transactions]}, {alert_id: {txn_id: customer_ref}}) for every alert, in one read (queue priority + cross-case links)."""
    return get_skills().load_all_transactions()


@st.cache_data(ttl=60, show_spinner=False)
def cached_case_index() -> list[dict]:
    """One row per alert (ALERTS_CURRENT) — the metadata the cross-case relationship links compare against."""
    return sql("SELECT ALERT_ID, CUSTOMER_REF, ALERT_TYPE, SIGNAL_SOURCE, ALERT_AMOUNT_INR, ALERT_STATUS, ALERT_DATE FROM FIU_COPILOT.AML.ALERTS_CURRENT")


@st.cache_data(ttl=60, show_spinner=False)
def cached_txn_owners(alert_id: str) -> dict:
    return get_skills().load_transaction_owners(alert_id)


def load_all_txns():
    """(({alert_id: txns}, {alert_id: owners}), error). A failure disables priority and cross-case links; it never takes the page down."""
    try:
        return cached_all_transactions(), None
    except Exception as err:  # noqa: BLE001
        return ({}, {}), explained(err, "The transaction record")


def score_case(alert: dict, txns: list[dict], owners: dict | None, sla_days, txn_error: bool = False):
    """(evidence quality, priority) for one case — pure, deterministic, no model. A failure yields (None, None): priority is then simply absent."""
    from skills.evidence import signal_brief
    try:
        quality = eq.assess(alert, txns, now=datetime.now(timezone.utc), txn_owners=owners, transactions_error=txn_error)
        return quality, prio.prioritise(alert, signal_brief(txns) if txns else None, quality, sla_days_remaining=sla_days, now=datetime.now(IST))
    except Exception:  # noqa: BLE001 - a scoring defect must not take the queue down
        return None, None


# ── page: Alert Queue ─────────────────────────────────────────────────────────
def recorded_suspicion_times():
    """Read existing ledger timestamps without changing schemas or inferring suspicion from alert age."""
    rows, err = query("""
        SELECT ALERT_ID, MIN(SUSPICION_FORMED_AT) AS RECORDED_SUSPICION_AT
        FROM FIU_COPILOT.AML.DECISION_LEDGER
        WHERE SUSPICION_FORMED_AT IS NOT NULL
        GROUP BY ALERT_ID
    """, area="Recorded suspicion times")
    return {r["ALERT_ID"]: r.get("RECORDED_SUSPICION_AT") for r in rows}, err


def effective_suspicion(alert, ledger_times):
    """(suspicion time, where it came from). A decision recorded in the ledger takes precedence; otherwise the time the case feed supplied with the alert
    (ALERTS.SUSPICION_FORMED_AT). Never inferred from the alert date: no time means no clock."""
    recorded = (ledger_times or {}).get(alert.get("ALERT_ID"))
    if recorded:
        return recorded, "ledger"
    supplied = alert.get("SUSPICION_FORMED_AT")
    return (supplied, "feed") if supplied else (None, None)


def _feed_suspicion_ist(alert):
    """The feed-supplied suspicion time as an IST datetime, or None (absent, unreadable or in the future)."""
    value = alert.get("SUSPICION_FORMED_AT")
    if not value:
        return None
    try:
        dt = value if isinstance(value, datetime) else datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        dt = (dt.replace(tzinfo=timezone.utc) if dt.tzinfo is None else dt).astimezone(IST)
    except (ValueError, TypeError):
        return None
    return dt if dt <= datetime.now(IST) else None


def case_clock(alert, formed_at=None, unavailable=False, now=None, source=None):
    """Presentation of recorded time only; a missing timestamp is not evidence that a clock never started."""
    from skills.ledger import to_ist_date, sla_days_remaining
    now = now or datetime.now(IST)
    try:
        age = max(0, (to_ist_date(now) - to_ist_date(alert["ALERT_DATE"])).days)
        age_label = f"{age} calendar days old"
    except (ValueError, TypeError, KeyError):
        age_label = "Alert date unavailable"
    days = None
    label = "Suspicion time unavailable" if unavailable else "Suspicion time not recorded"
    if not unavailable and formed_at:
        try:
            if to_ist_date(formed_at) > to_ist_date(now):
                raise ValueError("Future timestamp")
            days = sla_days_remaining(formed_at, now)
            label = f"{abs(days)} WD overdue" if days < 0 else ("Due today" if days == 0 else f"{days} WD left")
        except (ValueError, TypeError):
            label = "Suspicion time needs review"
    return {"age": age_label, "days": days, "label": label, "source": source if days is not None else None}


def page_alert_queue():
    st.header("My cases")
    with bordered():
        st.markdown(f"##### {T.WHO_TITLE}")
        for line in T.WHO_LINES:
            st.markdown(line)
    st.caption(T.POSITIONING_IS)
    st.caption(T.POSITIONING_IS_NOT)
    st.caption("Recorded deadlines first, then by priority score. Case age and reporting time are shown separately. " + T.PRIORITY_CAPTION)
    _judge_demo_path()

    rows, err = query("""
        SELECT ALERT_ID, ALERT_TYPE, SIGNAL_SOURCE, ACCOUNT_TYPE, CUSTOMER_PROFILE, ALERT_AMOUNT_INR,
               CUSTOMER_REF, ALERT_NARRATIVE, ALERT_STATUS, ALERT_DATE, LAST_DISPOSITION, LAST_DECISION_AT, SUSPICION_FORMED_AT,
               ARRAY_TO_STRING(PARSE_JSON(RFI_TRIGGERS::VARCHAR)::ARRAY, ', ') AS RFIS
        FROM FIU_COPILOT.AML.ALERTS_CURRENT
    """, area="The alert queue")
    if err:
        db_error(err)
        if st.button("Retry", key="retry_queue"):
            st.rerun()
        return
    if not rows:
        st.info(T.EMPTY_QUEUE)
        return

    times, time_error = recorded_suspicion_times()
    if time_error:
        st.warning(time_error)
    for r in rows:
        formed, source = effective_suspicion(r, times)
        r["CLOCK"] = case_clock(r, formed, bool(time_error), source=source)
        r["SLA_DAYS"] = r["CLOCK"]["days"]
        r["AMOUNT"] = float(r["ALERT_AMOUNT_INR"] or 0)
        r["WORK_STATUS"] = r["ALERT_STATUS"]

    (all_txns, all_owners), txn_err = load_all_txns()
    for r in rows:
        r["QUALITY"], r["PRIORITY"] = (None, None) if txn_err else score_case(r, all_txns.get(r["ALERT_ID"], []), all_owners.get(r["ALERT_ID"]), r["SLA_DAYS"])
    if txn_err:
        st.caption(T.PRIORITY_UNAVAILABLE)

    _pair_banner(rows)

    pending = [r for r in rows if r["WORK_STATUS"] != "REVIEWED"]
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Awaiting decision", len(pending))
    c2.metric("Due within 1 WD · recorded", sum(1 for r in pending if r["SLA_DAYS"] is not None and 0 <= r["SLA_DAYS"] <= 1))
    c3.metric("Overdue · recorded", sum(1 for r in pending if r["SLA_DAYS"] is not None and r["SLA_DAYS"] < 0))
    c4.metric("Pending amount", f"₹{sum(r['AMOUNT'] for r in pending) / 1e7:.2f}Cr")

    statuses = sorted({r["WORK_STATUS"] for r in rows})
    types = sorted({r["ALERT_TYPE"] for r in rows})
    sources = sorted({r["SIGNAL_SOURCE"] or "UNKNOWN" for r in rows})
    max_l = max(1.0, round(max(r["AMOUNT"] for r in rows) / 1e5 + 0.5, 0))

    defaults = {"aq_search": "", "aq_status": [s for s in statuses if s != "REVIEWED"] or statuses,
                "aq_type": [], "aq_src": [], "aq_amt": (0.0, float(max_l)), "aq_sort": T.SORT_OPTIONS[0]}
    for key, default in defaults.items():
        _sticky(key, default)
    for key, options in (("aq_status", statuses), ("aq_type", types), ("aq_src", sources)):
        st.session_state[key] = [v for v in st.session_state[key] if v in options]
    lo, hi = st.session_state["aq_amt"]
    st.session_state["aq_amt"] = (min(float(lo), max_l), min(float(hi), max_l))

    f_search, f_status, f_type = st.columns([2, 1.5, 2])
    st.session_state["aq_sort"] = st.session_state["aq_sort"] if st.session_state.get("aq_sort") in T.SORT_OPTIONS else T.SORT_OPTIONS[0]   # re-assigned every run, like the other filters
    f_src, f_sort, f_amt = st.columns([1.7, 2.6, 3])
    search = f_search.text_input("Search", placeholder="Alert ID or customer", key="aq_search").strip().lower()
    sel_status = f_status.multiselect("Status", statuses, format_func=label_safe, key="aq_status")
    sel_type = f_type.multiselect("Type", types, format_func=lambda t: label_safe(t.replace("_", " ").title()), key="aq_type")
    sel_src = f_src.multiselect("Signal source", sources, format_func=label_safe, key="aq_src")
    sort_choice = f_sort.selectbox(T.SORT_LABEL, T.SORT_OPTIONS, key="aq_sort")
    amt_lo, amt_hi = f_amt.slider("Amount (₹ lakh)", 0.0, float(max_l), key="aq_amt")
    for key in defaults:
        st.session_state[f"_keep_{key}"] = st.session_state[key]

    shown = [
        r for r in rows
        if (not sel_status or r["WORK_STATUS"] in sel_status)
        and (not sel_type or r["ALERT_TYPE"] in sel_type)
        and (not sel_src or (r["SIGNAL_SOURCE"] or "UNKNOWN") in sel_src)
        and amt_lo <= r["AMOUNT"] / 1e5 <= amt_hi
        and (not search or search in r["ALERT_ID"].lower() or search in str(r.get("CUSTOMER_REF") or "").lower()
             or search in str(r["CUSTOMER_PROFILE"] or "").lower())
    ]
    def _priority_key(r):
        return prio.sort_key({"alert": r, "priority": r["PRIORITY"]}) if r.get("PRIORITY") else (1, "9999", 0.0, str(r["ALERT_ID"]))
    done = lambda r: r["WORK_STATUS"] == "REVIEWED"  # noqa: E731 - decided cases always sink
    if sort_choice == T.SORT_OPTIONS[1]:
        shown.sort(key=lambda r: (done(r), *_priority_key(r)))
    elif sort_choice == T.SORT_OPTIONS[2]:
        shown.sort(key=lambda r: (done(r), str(r["ALERT_DATE"]), -r["AMOUNT"], str(r["ALERT_ID"])))
    elif sort_choice == T.SORT_OPTIONS[3]:
        shown.sort(key=lambda r: (done(r), -r["AMOUNT"], str(r["ALERT_ID"])))
    else:           # default: a RECORDED reporting deadline outranks a computed score; the score orders everything else
        shown.sort(key=lambda r: (done(r), r["SLA_DAYS"] is None, r["SLA_DAYS"] if r["SLA_DAYS"] is not None else 0, *_priority_key(r), str(r["ALERT_DATE"]), -r["AMOUNT"]))
    st.caption(f"Showing {len(shown)} of {len(rows)} alerts")
    st.caption(f"{sum(r['SLA_DAYS'] is None for r in pending)} pending cases have no usable recorded suspicion time. "
               "Deadline estimates use the earliest stored suspicion time, Mon–Fri only; holidays and actual filing completion are not verified.")
    resume = st.session_state.get("selected_alert")
    if any(r["ALERT_ID"] == resume for r in shown):
        st.markdown(f"[Return to last case row](#case-{hashlib.sha256(str(resume).encode()).hexdigest()[:12]})")
    st.divider()
    if not shown:
        st.info(T.EMPTY_FILTER)
        return

    widths = [1.1, 2.1, 1.1, 1.1, 1.7, 1.4, 1.25]
    for col, label in zip(st.columns(widths), ("Case / age", "Trigger / source", "Amount", T.PRIORITY_COLUMN, "Reporting time", "Last action", "Open")):
        col.markdown(f"**{label}**")
    for r in shown:
        alert_id = r["ALERT_ID"]
        html_md(f'<span id="case-{hashlib.sha256(str(alert_id).encode()).hexdigest()[:12]}"></span>')
        col_id, col_type, col_amt, col_prio, col_sla, col_last, col_action = st.columns(widths)
        col_id.markdown(f"**{md_safe(alert_id)}**")
        col_id.caption(r["CLOCK"]["age"])
        pair_tag = (f"  \n*{T.PAIR_TAG.format(other=DEMO_PAIR[1] if alert_id == DEMO_PAIR[0] else DEMO_PAIR[0])}*" if alert_id in DEMO_PAIR else "")
        col_type.markdown(md_safe(r["ALERT_TYPE"].replace("_", " ").title()) + pair_tag)
        col_type.caption(md_safe(r["SIGNAL_SOURCE"]))
        col_amt.markdown(f"₹{r['AMOUNT']:,.0f}")
        pr = r.get("PRIORITY")
        if pr:
            col_prio.markdown(f"**{pr['score']}**/100")
            col_prio.caption(pr["band"])
        else:
            col_prio.caption("Not scored")
        if r["WORK_STATUS"] == "REVIEWED":
            col_sla.caption("Decision recorded · see archive")
        else:
            col_sla.markdown(sla_pill(r["SLA_DAYS"]) if r["SLA_DAYS"] is not None else md_safe(r["CLOCK"]["label"]), unsafe_allow_html=True)
            if r["CLOCK"].get("source") == "feed":
                col_sla.caption("from the case feed")
        col_last.markdown(disp_badge(r.get("LAST_DISPOSITION") or r["WORK_STATUS"]), unsafe_allow_html=True)
        col_last.caption(md_safe(str(r.get("LAST_DECISION_AT") or "No recorded decision")[:32]))
        with col_action:
            if st.button("Review →", key=f"review_{alert_id}", use_container_width=True,
                         type="primary" if r["WORK_STATUS"] != "REVIEWED" else "secondary"):
                st.session_state["selected_alert"] = alert_id
                st.session_state["_goto"] = "Disposition Panel"   # applied by main() before the nav radio exists
                st.rerun()
        if pr:
            with st.expander(f"{T.PRIORITY_WHY_TITLE} · {label_safe(alert_id)}", expanded=False):
                _render_priority(pr, r.get("QUALITY"))
        with st.expander(f"Case context · {label_safe(alert_id)}", expanded=False):
            st.markdown(f"**Trigger reported by detector:** {md_safe(r.get('ALERT_NARRATIVE') or 'Narrative unavailable')}")
            st.caption("Detector statements require investigation; this preview does not establish evidence sufficiency.")
            st.markdown(f"{md_safe(r['CUSTOMER_PROFILE'])}  \n**Account type:** {md_safe(r['ACCOUNT_TYPE'])}  ·  "
                        f"**Alert date:** {md_safe(r['ALERT_DATE'])}  ·  **Status:** {md_safe(r['WORK_STATUS'])}")
            st.caption(f"Customer: {md_safe(r.get('CUSTOMER_REF') or 'Not supplied')} · Signal tags: {md_safe(r.get('RFIS') or 'None supplied')}")


def _open_demo_case(alert_id: str):
    """Route a judge from the compact queue guide into an existing case workflow."""
    st.session_state["selected_alert"] = alert_id
    st.session_state["_goto"] = DISPOSITION_PAGE
    st.rerun()


def _judge_demo_path():
    """A short, non-authoritative map through the seeded judge workflow.

    The buttons only navigate to existing screens; they never run AI, select a decision, or write a ledger row.
    """
    with bordered():
        st.markdown("#### Judge demo path")
        st.caption("A three-minute guide through the synthetic demonstration. Each step opens an existing view; the Principal Officer still chooses whether to record a decision.")
        steps = (
            ("1", "Compare ALERT-01 and ALERT-16", "Same signal, different supplied evidence.", "Open ALERT-01", "case_01"),
            ("2", "Review regulatory basis and AI assessment", "Cortex Search and the optional labelled assessment.", "Review the case", "case_review"),
            ("3", "Test the evidence gate", "Add an unsupported filing fact and see the deterministic block.", "Open evidence gate", "case_gate"),
            ("4", "Record and reconstruct a decision", "The officer records the outcome, then opens the ledger dossier.", "Open decision archive", "ledger"),
        )
        for col, (number, title, detail, action, key) in zip(st.columns(4), steps):
            with col:
                st.markdown(f"**{number}. {title}**")
                st.caption(detail)
                if st.button(action, key=f"judge_demo_{key}", use_container_width=True):
                    if key == "ledger":
                        st.session_state["_goto"] = "Decision Ledger"
                    else:
                        _open_demo_case("ALERT-01")
                    st.rerun()


def _render_priority(pr: dict, quality: dict | None = None):
    """Why this case is prioritized: the score, the factors with their points and sentences, the data gaps — and what priority is not."""
    st.markdown(md_safe(pr["explanation"]))
    for f in pr["factors"]:
        st.markdown(f"- **{md_safe(f['label'])}** — {f['points']} of {f['max_points']}: {md_safe(f['detail'])}" + (f" _{md_safe(f['note'])}_" if f.get("note") else ""))
    for gap in pr["data_gaps"]:
        st.caption("Not scored: " + md_safe(gap))
    if quality:
        st.caption(f"Evidence sufficiency {quality['sufficiency_pct']}% · {quality['counts'].get(eq.BLOCKS_FILING, 0)} blocking, "
                   f"{quality['counts'].get(eq.REQUIRES_MANUAL_REVIEW, 0)} for manual review, {quality['counts'].get(eq.REQUIRES_ACKNOWLEDGEMENT, 0)} to acknowledge.")
    st.caption(pr["disclaimer"])


def _pair_banner(rows):
    """The same-signal pair, discoverable from the queue: same detector, same amount — different evidence, different defensible outcomes.
    Leads with the source facts and says WHY the dispositions differ (computed from the data, no AI)."""
    by_id = {r["ALERT_ID"]: r for r in rows}
    if not all(a in by_id for a in DEMO_PAIR):
        return
    a, b = (by_id[x] for x in DEMO_PAIR)
    with bordered():
        st.markdown(f"#### {T.PAIR_TITLE}")
        st.caption(T.PAIR_THESIS)
        _twin_table(a, b, compact=True)
        _pair_explanation(a, b)
        st.caption(T.PAIR_START)
        c1, c2, _ = st.columns([1.3, 1.3, 1.4])
        for col, alert in ((c1, a), (c2, b)):
            if col.button(f"Open {alert['ALERT_ID']} — source facts first →", key=f"pair_{alert['ALERT_ID']}", use_container_width=True):
                st.session_state["selected_alert"] = alert["ALERT_ID"]
                st.session_state["_goto"] = "Disposition Panel"   # applied by main() before the nav radio exists
                st.rerun()


def _pair_explanation(a_meta: dict, b_meta: dict):
    """Why equal signals do not mean equal dispositions — every sentence computed from the two alerts' transaction rows."""
    from skills.evidence import explain_pair, signal_brief
    ta, ea = load_txns(a_meta["ALERT_ID"])
    tb, eb = load_txns(b_meta["ALERT_ID"])
    if ea or eb or not ta or not tb:
        return
    ex = explain_pair(a_meta, signal_brief(ta), b_meta, signal_brief(tb))
    st.markdown(f"**{ex['title']}**")
    for line in ex["same"]:
        st.markdown(f"- {md_safe(line)}")
    for line in ex["different"]:
        st.markdown(f"- {md_safe(line)}")
    if ex["conclusion"]:
        st.markdown(f"**{md_safe(ex['conclusion'])}**")


def _twin_table(a_meta: dict, b_meta: dict, compact: bool = False):
    from skills.evidence import compare_signals, signal_brief
    ta, ea = load_txns(a_meta["ALERT_ID"])
    tb, eb = load_txns(b_meta["ALERT_ID"])
    if ea or eb or not ta or not tb:
        st.warning(T.PAIR_UNAVAILABLE)
        return
    rows = compare_signals(a_meta, signal_brief(ta), b_meta, signal_brief(tb))
    import pandas as pd
    df = pd.DataFrame(rows).rename(columns={"metric": "Source fact (deterministic)", "a": a_meta["ALERT_ID"], "b": b_meta["ALERT_ID"]})
    df["Differs"] = df.pop("differs").map({True: "◀ differs", False: ""})
    st.dataframe(df, hide_index=True, use_container_width=True, height=36 * (len(df) + 1) + 3)
    st.caption("Every figure above is a SUM/COUNT over the TRANSACTIONS table — no AI involved.")


# ── page: Disposition Panel ───────────────────────────────────────────────────
ZONE_STYLE = {"facts": ("#1565c0", "solid"), "basis": ("#6a1b9a", "solid"), "ai": ("#78909c", "dashed"), "human": ("#00796b", "solid")}


def _zone(kind: str):
    """The visual identity of a zone. Four zones, four looks — facts: blue, solid · basis: violet, solid · AI: grey, DASHED (tentative) ·
    human: teal, solid. Every string is a constant from skills/po_copy.py."""
    name, tagline = T.ZONES[kind]
    color, line = ZONE_STYLE[kind]
    html_md(f'<div style="border-left:6px {line} {color};background:{color}14;padding:7px 14px;margin:22px 0 8px 0;border-radius:2px">'
            f'<span style="font-weight:800;letter-spacing:.08em;color:{color}">{esc(name)}</span>'
            f'<span style="opacity:.85"> — {esc(tagline)}</span></div>')


def _abstain(body: str, title: str, *consequences: str):
    """The copilot declines to give regulatory guidance. Constants only — never model or corpus text."""
    st.warning(f"**{title}.** {body}" + "".join(f"  \n{c}" for c in consequences))


# ── independent-review protocol (flag-gated: FIU_HUMAN_REVIEW; design/HUMAN_REVIEW_SPEC.md) ──
def _hr_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _ref_context(alert, txns, basis):
    """(ReferenceContext, option list) for this case: txn ids + usable (PROVEN/ASSUMED) rule ids + fact keys.
    Offering a fixed option set is how the UI keeps a reference from ever being an arbitrary free-text string."""
    from skills.evidence import signal_brief
    rule_ids = list((basis or {}).get("proven_rule_ids") or []) + list((basis or {}).get("assumed_rule_ids") or [])
    snap = hr.fact_key_snapshot(signal_brief=signal_brief(txns) if txns else {}, alert_meta=alert)
    opts = [t.get("txn_id") for t in (txns or []) if t.get("txn_id")] + rule_ids + list(snap)
    return hr.ReferenceContext(txn_ids=[t.get("txn_id") for t in (txns or [])], rule_ids=rule_ids, fact_snapshot=snap), opts


def _provisional_key(selected) -> str:
    return f"prov_read_{selected}"


def _provisional_saved(selected):
    return st.session_state.get(_provisional_key(selected))


def _provisional_panel(selected, alert, txns, basis, ai_ran: bool):
    """First impression — recorded BEFORE AI advice is revealed. Keyed to this case (never migrates); revisable until reveal,
    then frozen. Not a commitment and not scored; changing it later is expected."""
    ctx, opts = _ref_context(alert, txns, basis)
    saved = _provisional_saved(selected)
    with bordered():
        st.markdown(f"##### {T.HR_PROVISIONAL_TITLE}")
        st.caption(T.HR_PROVISIONAL_FRAMING)
        if saved and ai_ran:                                   # frozen once AI has been revealed
            st.markdown(f"- **View:** {md_safe(T.HR_VIEWS.get(saved.get('view'), saved.get('view')))}")
            st.markdown(f"- **Evidence:** {md_safe(', '.join(saved.get('evidence_refs') or []) or '—')}")
            st.markdown(f"- **Open question:** {md_safe(saved.get('unanswered_question') or '—')}")
            return
        vkey, rkey, qkey = f"prov_view_{selected}", f"prov_refs_{selected}", f"prov_q_{selected}"
        views = list(T.HR_VIEWS)
        dv = saved.get("view") if saved else None
        try:
            view = st.radio("Your current view", views, format_func=lambda k: T.HR_VIEWS[k],
                            index=views.index(dv) if dv in views else None, key=vkey, horizontal=True)
        except TypeError:                                      # older Streamlit without index=None
            view = st.radio("Your current view", [None] + views, key=vkey,
                            format_func=lambda k: "— choose —" if k is None else T.HR_VIEWS[k])
        dref = [r for r in ((saved or {}).get("evidence_refs") or []) if r in opts]
        refs = st.multiselect(T.HR_PROVISIONAL_REF_LABEL, opts, default=dref, key=rkey, format_func=label_safe)
        q = st.text_input(T.HR_PROVISIONAL_Q_LABEL, value=(saved or {}).get("unanswered_question") or "", key=qkey)
        if st.button(T.HR_PROVISIONAL_REVISE if saved else T.HR_PROVISIONAL_SAVE, key=f"prov_save_{selected}"):
            candidate = {"view": view, "evidence_refs": list(refs), "unanswered_question": q, "saved_at": _hr_now()}
            missing = hr.provisional_missing(candidate, ctx)
            if missing:
                st.warning("Still needed: " + ", ".join(missing))
            else:
                st.session_state[_provisional_key(selected)] = candidate
                st.rerun()
        if saved:
            st.caption(T.HR_PROVISIONAL_SAVED)


def _reconciliation(sk, selected, alert, choice, rec, ai_state, assessment, txns, terr, basis, gen):
    """Render the reconciliation (only when the decision is higher-risk) and build the human_review payload for the recorder.
    Returns (payload, incomplete). The server-side recorder re-checks everything; this is UX, not the control."""
    ctx, opts = _ref_context(alert, txns, basis)
    ai_ran = ai_state == "VALID"
    usable = list((basis or {}).get("proven_rule_ids") or []) + list((basis or {}).get("assumed_rule_ids") or [])
    req = hr.independent_review_required(
        disposition=choice, transactions=txns, transactions_readable=not bool(terr), has_supported_basis=bool(usable),
        ai_ran=ai_ran, ai_recommendation=rec,
        sufficiency=sk.evidence_sufficiency_summary(assessment, txns) if ai_ran else None,
        challenge=sk._challenge_record(choice, assessment or [], txns))
    fr = {"final_decision": choice}
    incomplete = False
    if req["required"]:
        with bordered():
            st.markdown(f"##### {T.HR_RECONCILE_TITLE}")
            st.caption(T.HR_RECONCILE_WHY + " " + md_safe("; ".join(t["detail"] for t in req["triggers"][:4])))
            k = lambda s: f"hr_{s}_{selected}_{gen}"  # noqa: E731
            fr["material_counter_evidence"] = st.text_area(T.HR_RECONCILE_COUNTER, key=k("counter"), height=70)
            fr["none_material"] = st.checkbox(T.HR_RECONCILE_NONE_MATERIAL, key=k("none"))
            fr["counter_evidence_refs"] = [] if fr["none_material"] else list(
                st.multiselect(T.HR_RECONCILE_REF_LABEL, opts, key=k("cref"), format_func=label_safe))
            if choice == "FILE":
                fr["change_reason"] = st.text_area(T.HR_RECONCILE_FILE_JUSTIFY, key=k("just"), height=70)
            elif choice in ("NOT_FILE", "ESCALATE"):
                fr["accepted_innocent_explanation"] = st.text_area(T.HR_RECONCILE_ACCEPTED, key=k("acc"), height=70)
                fr["accepted_explanation_refs"] = list(st.multiselect(T.HR_RECONCILE_REF_LABEL + " (for the explanation)", opts, key=k("aref"), format_func=label_safe))
                fr["remaining_uncertainty"] = st.text_input(T.HR_RECONCILE_UNCERTAINTY, key=k("unc"))
            elif choice == "DEFERRED":
                fr["next_evidence_needed"] = st.text_input(T.HR_RECONCILE_NEXT, key=k("next"))
            if hr.reconciliation_missing(fr, disposition=choice, ctx=ctx):
                incomplete = True
                st.caption(T.HR_RECONCILE_INCOMPLETE)
    payload = {
        "provisional": _provisional_saved(selected) or {},
        "ai_reveal": {"assessment_used": ai_ran, "recommendation": rec, "revealed_at": _hr_now() if ai_ran else None},
        "final_reconciliation": fr,
        "interaction_observations": {},
        "ai_draft": st.session_state.get(f"ai_draft_{selected}"),
    }
    return payload, incomplete


def page_disposition():
    alerts, err = query("SELECT ALERT_ID, ALERT_TYPE FROM FIU_COPILOT.AML.ALERTS_CURRENT ORDER BY ALERT_ID", area="The alert list")
    if err:
        db_error(err)
        return
    options = [r["ALERT_ID"] for r in alerts]
    if not options:
        st.info(T.EMPTY_QUEUE)
        return
    alert_id = st.session_state.get("selected_alert")
    idx = options.index(alert_id) if alert_id in options else 0

    head_l, head_r = st.columns([3, 1])
    head_l.header("Investigation desk")
    if head_l.button("← Back to my cases", key="back_to_cases"):
        st.session_state["_goto"] = "Alert Queue"
        st.rerun()
    selected = head_r.selectbox("Alert", options, index=idx, format_func=label_safe)
    st.session_state["selected_alert"] = selected
    _desk_open(selected)

    try:
        sk = get_skills()
        alert = sk.load_alert(selected)
    except Exception as err:  # noqa: BLE001
        db_error(explained(err, f"Alert {selected}"))
        return
    if not alert:
        st.error("That alert is no longer in the queue. Go back to the queue and pick another.")
        return
    txns, terr = load_txns(selected)
    try:
        owners = cached_txn_owners(selected)
    except Exception:  # noqa: BLE001 - the owner map only sharpens one identity check; its absence never blocks the case
        owners = {}
    quality = sk.evidence_quality_for(alert, txns, txn_owners=owners, transactions_error=bool(terr))

    if st.session_state.get("last_decision"):
        _last_decision_banner()

    clock = _case_header(alert)
    _priority_panel(alert, txns, terr, owners, quality, clock)
    prior, prior_err = None, None
    try:
        prior = sk.prior_decisions(selected)
    except Exception as err:  # noqa: BLE001 - the recorder reads this itself and refuses to write if it cannot
        prior_err = err
    if alert.get("ALERT_STATUS") == "REVIEWED" or prior:
        latest = (prior or [{}])[0]
        st.info(T.ALREADY_DECIDED.format(disposition=md_safe(alert.get("LAST_DISPOSITION") or latest.get("disposition")),
                                         when=md_safe(str(alert.get("LAST_DECISION_AT") or latest.get("decided_at") or "")[:16])))
    if prior:
        with st.expander(T.PRIOR_DECISIONS_TITLE.format(n=len(prior))):
            for p in prior:
                st.markdown(f"- `{code_safe(p['disposition'])}` · {md_safe(p['decision_maker_id'])} · {md_safe(p['decided_at'][:16])} · `{code_safe(p['decision_id'])}`")
    elif prior_err is not None:
        st.warning(T.PRIOR_DECISIONS_UNREADABLE)
    st.caption(T.READ_ORDER_NOTE)

    case_id = hashlib.sha256(str(selected).encode()).hexdigest()[:12]
    def anchor(part):
        html_md(f'<div class="case-anchor" id="{part}-{case_id}"></div>')
    html_md('<nav class="case-contents" aria-label="Case contents">' + ''.join(
        f'<a href="#{part}-{case_id}">{label}</a>' for part, label in
        (("facts", "Source facts"), ("money", "Money movement"), ("quality", "Evidence quality"), ("network", "Relationships"), ("basis", "Regulatory basis"),
         ("assessment", "AI assessment · optional"), ("note", "Working note & decision"))) + '</nav>')
    # All sections stay mounted: anchor navigation never discards a hidden widget.
    # DOM/reading order remains facts → basis → AI → human, including when stacked.
    try:
        workspace = st.container(key="case_workspace")
        split_layout = True
    except TypeError:  # older SiS: retain safe single-column layout
        workspace = st.container()
        split_layout = False
    with workspace:
        evidence, note = st.columns([3, 2], gap="large") if split_layout else (st.container(), st.container())
        with evidence:
            anchor("facts")
            _facts_zone(sk, selected, alert, txns, terr)
            anchor("quality")
            _evidence_quality_panel(quality)
            anchor("network")
            _relationships_panel(alert, txns, terr)
            anchor("basis")
            basis = _basis_zone(sk, alert)
            anchor("assessment")
            if hr.enabled():
                _provisional_panel(selected, alert, txns, basis, ai_ran=_current_assessment(selected) is not None)
            _zone("ai")
            locked = hr.enabled() and _provisional_saved(selected) is None and _current_assessment(selected) is None
            _ai_inference_panel(sk, selected, alert, txns, locked=locked)
        with note:
            anchor("note")
            st.caption("WORKING NOTE · retained for this case in this session; not saved to the ledger until you record a decision.")
            _decision_zone(sk, selected, alert, txns, terr, basis, quality, owners, prior=prior)


def _case_header(alert):
    amt = float(alert["ALERT_AMOUNT_INR"] or 0)
    times, err = recorded_suspicion_times()
    formed, source = effective_suspicion(alert, times)
    clock = case_clock(alert, formed, bool(err), source=source)
    html_md(f"<div style='font-size:1.35rem;font-weight:700'>{esc(alert['ALERT_ID'])} — {esc(str(alert['ALERT_TYPE']).replace('_', ' ').title())} "
            f"</div>")
    basis = T.CLOCK_BASIS_FEED if source == "feed" else "Based on earliest stored suspicion time; Mon–Fri, no holiday calendar."
    st.caption(f"{clock['age']} · {clock['label']} · {basis}")
    st.markdown(f"₹{amt:,.0f} ({amt / 1e5:.1f}L)  ·  `{code_safe(alert['SIGNAL_SOURCE'])}`  ·  {md_safe(alert['ACCOUNT_TYPE'])}  ·  "
                f"alerted {md_safe(alert['ALERT_DATE'])}  \n{md_safe(alert['CUSTOMER_PROFILE'])}")
    return clock


def _priority_panel(alert, txns, terr, owners, quality, clock):
    """Priority beside the case — the same score the queue shows, with its reasons. It orders work; it is not part of the decision."""
    _, pr = score_case(alert, txns, owners, clock.get("days"), txn_error=bool(terr))
    if not pr:
        return
    with st.expander(f"{T.PRIORITY_WHY_TITLE} · priority {pr['score']}/100 ({pr['band']})", expanded=False):
        _render_priority(pr, quality)


EFFECT_STYLE = {eq.BLOCKS_FILING: ("#c62828", "✕"), eq.REQUIRES_MANUAL_REVIEW: ("#e65100", "!"), eq.REQUIRES_ACKNOWLEDGEMENT: ("#9a600a", "✎"),
                eq.INFORMATIONAL: ("#546e7a", "i")}


def _evidence_quality_panel(quality: dict):
    """What is missing, stale, contradictory, unavailable or unresolved in THIS case's record, and what each issue means for the decision.
    Deterministic; the same assessment the decision gate enforces. Suggested next evidence is labelled a suggestion, not a conclusion."""
    import pandas as pd
    with bordered():
        st.markdown(f"#### {T.EQ_TITLE}")
        st.caption(T.EQ_SUBTITLE)
        st.caption(T.EQ_POLICY_NOTE)
        c = quality["counts"]
        top, mid = st.columns(2), st.columns(2)
        top[0].metric("Evidence sufficiency", f"{quality['sufficiency_pct']}%", help="How much of a decision-grade record is present: KYC profile, transaction rows, individual rows, reconciled amount, identified counterparties, consistency, history, corroborated claims, documentation.")
        for col, effect in zip((top[1], mid[0], mid[1]), (eq.BLOCKS_FILING, eq.REQUIRES_MANUAL_REVIEW, eq.REQUIRES_ACKNOWLEDGEMENT)):
            col.metric(eq.EFFECT_LABEL[effect], c.get(effect, 0))
        if not quality["findings"]:
            st.info(T.EQ_NONE)
        for effect in (eq.BLOCKS_FILING, eq.REQUIRES_MANUAL_REVIEW, eq.REQUIRES_ACKNOWLEDGEMENT, eq.INFORMATIONAL):
            items = [f for f in quality["findings"] if f["effect"] == effect]
            if not items:
                continue
            color, glyph = EFFECT_STYLE[effect]
            html_md(f'<div style="border-left:4px solid {color};padding:4px 10px;margin:12px 0 2px 0;font-weight:700">{glyph}&nbsp; {esc(eq.EFFECT_LABEL[effect])} · {len(items)}</div>')
            st.caption(eq.EFFECT_MEANING[effect])
            for f in items:
                st.markdown(f"- **{md_safe(f['title'])}** — {md_safe(f['detail'])}")
                st.caption(f"{md_safe(f['why'])}" + (f" {T.EQ_TEXT_PATTERN_NOTE}" if f["source"] == "text_pattern" else "")
                           + (f" Rows: {md_safe(', '.join(f['refs'][:6]))}" if f.get("refs") else "")
                           + (" The decision gate already blocks this under a separate rule." if f.get("enforced_by") else ""))
        with st.expander(f"{T.EQ_NEXT_TITLE} ({len(quality['next_evidence'])})", expanded=False):
            st.caption(T.EQ_NEXT_NOTE)
            for step in quality["next_evidence"]:
                st.markdown(f"- {md_safe(step['step'])}")
            if not quality["next_evidence"]:
                st.caption("No further evidence is suggested by these checks.")
        with st.expander(T.EQ_LIMITS_TITLE, expanded=False):
            for limit in quality["limits"]:
                st.markdown(f"- {md_safe(limit)}")
        with st.expander("How the sufficiency percentage is built", expanded=False):
            st.dataframe(pd.DataFrame([{"Check": x["check"], "Weight": x["weight"], "Met": f"{x['met'] * 100:.0f}%"} for x in quality["sufficiency_checks"]]),
                         hide_index=True, use_container_width=True)


def _flow_chip(c: dict) -> str:
    notes = (["flag recorded on the feed"] if c.get("flagged") else []) + (["not identified"] if c.get("unidentified") else [])
    detail = f"₹{float(c['amount'] or 0):,.0f}" + (f" · {int(c['count'])} rows" if (c.get("count") or 1) > 1 else "") + ("".join(f" · {n}" for n in notes))
    return f'<div class="net-chip{" flag" if c.get("flagged") else ""}"><strong>{esc(c["label"])}</strong><small>{esc(detail)}</small></div>'


def _relationships_panel(alert: dict, txns: list[dict], terr):
    """The case's network: who paid in, who was paid, what else is connected — each link SOURCED (stated by the record) or INFERRED (a named rule
    match). Link types that cannot be tested with the data supplied are listed, not hidden. Everything dynamic is escaped."""
    import pandas as pd
    with bordered():
        st.markdown(f"#### {T.REL_TITLE}")
        st.caption(T.REL_SUBTITLE)
        other_cases = None
        try:
            index = cached_case_index()
            (all_txns, _), all_err = load_all_txns()
            if not all_err:
                other_cases = [{"alert": a, "transactions": all_txns.get(a["ALERT_ID"], [])} for a in index if a["ALERT_ID"] != alert["ALERT_ID"]]
        except Exception:  # noqa: BLE001 - cross-case links are reported as untested, never guessed
            other_cases = None
        net = rel.build_network(alert, [] if terr else txns, other_cases=other_cases)
        html_md(badge("SOURCED", "#e3f2fd", "#0d47a1") + "&nbsp; " + esc(net["legend"][rel.SOURCED]) + "<br>" + badge("INFERRED", "#fff8e1", "#8a5a00") + "&nbsp; " + esc(net["legend"][rel.INFERRED]))
        flow = rel.flow_columns(net)
        centre = flow["centre"]
        left = "".join(_flow_chip(c) for c in flow["paid_in"]) or '<div class="net-chip"><small>No individual paying-in rows</small></div>'
        right = "".join(_flow_chip(c) for c in flow["paid_out"]) or '<div class="net-chip"><small>No individual paying-out rows</small></div>'
        html_md(f'<div class="net-flow"><div class="net-col"><span class="net-head">PAID IN BY</span>{left}</div><span class="net-arrow" aria-hidden="true">→</span>'
                f'<div class="net-centre"><span class="net-head">THIS CASE</span><div class="net-chip"><strong>{esc(centre["customer"])}</strong><small>{esc(centre["account"])} · {esc(centre["alert"])}</small></div></div>'
                f'<span class="net-arrow" aria-hidden="true">→</span><div class="net-col"><span class="net-head">PAID OUT TO</span>{right}</div></div>')
        if net["truncated"]["counterparties"]:
            st.caption(f"{net['truncated']['counterparties']} further counterparties are not drawn (the table below lists the strongest links).")
        st.markdown("**Patterns found (inferred by rule)**")
        if not net["patterns"]:
            st.caption("No rule matched. That does not show that nothing is connected: see the link types that could not be tested.")
        for p in net["patterns"]:
            st.markdown(f"- **{md_safe(p['title'])}** (inferred · `{code_safe(p['rule'])}`) — {md_safe(p['explanation'])}")
            st.caption("Does not show: " + md_safe(p["does_not_show"]))
        if net["related_cases"]:
            st.markdown("**Related cases**")
            for r in net["related_cases"]:
                st.markdown(f"- {md_safe(r['alert_id'])} — {md_safe('; '.join(r['reasons']))}")
        st.caption(T.REL_INFERRED_NOTE)
        untested = [k for k, v in net["coverage"].items() if not v.get("evaluable") and v.get("reason")]
        if untested or net["unresolved"]:
            with st.expander(T.REL_NOT_TESTED_TITLE, expanded=False):
                for k in untested:
                    st.markdown(f"- {md_safe(net['coverage'][k]['reason'])}")
                for u in net["unresolved"]:
                    st.markdown(f"- {md_safe(u)}")
        with st.expander(f"All links ({len(net['edges'])})", expanded=False):
            st.dataframe(pd.DataFrame(rel.edge_rows(net)), hide_index=True, use_container_width=True)


def _current_assessment(selected):
    return st.session_state.get("poe_assessment") if st.session_state.get("assessed_alert") == selected else None


def _current_gos(selected):
    return st.session_state.get("gos_result") if st.session_state.get("gos_alert") == selected else None


def _sha(text: str) -> str:
    return hashlib.sha256((text or "").encode("utf-8")).hexdigest()


def _status_pill(status: str) -> str:
    color, label = STATUS_STYLE.get(status, ("#546e7a", status))
    return badge(label, color + "22", color)


def _last_decision_banner():
    d = st.session_state["last_decision"]
    with bordered():
        st.success(f"Decision recorded and persisted — `{code_safe(d['decision_id'])}` · {md_safe(d['alert_id'])} · **{md_safe(d['disposition'])}** · "
                   f"SLA days remaining at decision: **{md_safe(d['sla_days_remaining'])}**")
        st.markdown("##### Decision record complete")
        c1, c2 = st.columns(2)
        c1.markdown(f"**Final human disposition:** {md_safe(d.get('disposition') or 'Not supplied')}")
        c1.markdown(f"**Principal Officer:** {md_safe(d.get('po_id') or 'Not supplied')}")
        c1.markdown(f"**Recorded:** {md_safe(d.get('recorded_at') or 'Recorded in this session')}")
        c2.markdown("**Evidence references:** " + md_safe(", ".join(d.get("evidence_txn_ids") or []) or "No AI-derived transaction references were stored"))
        c2.markdown("**Regulatory basis:** " + md_safe(
            f"{len(d.get('proven_rule_ids') or [])} PROVEN · {len(d.get('assumed_rule_ids') or [])} ASSUMED"))
        if d.get("assumed_rule_ids"):
            c2.caption("ASSUMED-rule acknowledgement: " + ("recorded" if d.get("assumed_basis_acknowledged") else "not recorded"))
        st.text("Ledger reference: " + str(d["decision_id"]))
        st.caption("Receipt for a ledger decision only; no STR was submitted to FINGate by this application.")
        if st.button("Open reconstruction", key="open_last_reconstruction", type="primary"):
            st.session_state["reconstruct_decision_id"] = d["decision_id"]
            st.session_state["_goto"] = "Decision Ledger"
            st.rerun()
        if st.button("Dismiss", key="dismiss_last"):
            st.session_state.pop("last_decision", None)
            st.rerun()


def _ai_state(sk, selected, assessment) -> str:
    from skills.defensibility import AI_INVALID, AI_NOT_RUN, AI_UNAVAILABLE, AI_VALID
    if assessment is not None:
        return AI_VALID if sk.assessment_validity(assessment)["valid"] else AI_INVALID
    return AI_UNAVAILABLE if st.session_state.get(f"ai_failed_{selected}") else AI_NOT_RUN


def _challenge_panel(sk, assessment, txns, rec):
    """What argues AGAINST the leading call — shown before the PO decides, and recorded with the decision (recorder-computed)."""
    proposed = "FILE" if rec == "FILE" else "NOT_FILE"
    chal = sk.challenge_disposition(proposed, assessment, txns)
    with bordered():
        call_label = ('File STR' if proposed == 'FILE' else 'Close — no suspicion formed') if rec in {"FILE", "NOT_FILE"} else "No settled call; testing the case for closure (not a recommendation)"
        st.markdown(f"**{T.CHALLENGE_TITLE}** · leading call: {call_label} · "
                    f"strength: **{chal['challenge_strength']}**")
        st.caption(T.CHALLENGE_SUBTITLE)
        st.caption("These are deterministic challenge observations, not probabilities. Factor evidence is AI interpretation; transaction flags and documentation labels are supplied-record facts, not independent verification.")
        st.markdown("**Observations supporting the leading call**")
        supporting = sk.challenge_disposition("NOT_FILE" if proposed == "FILE" else "FILE", assessment, txns)
        support = [c for c in supporting["counter_evidence"] if c["type"] not in
                   {"insufficient_evidence", "ungrounded_factor"}]
        if not support:
            st.caption("No supporting observation produced by the existing challenge rules. This is not proof of the opposite conclusion.")
        for c in support:
            st.markdown("- " + md_safe(c["detail"]) +
                        (" · references: " + md_safe(", ".join(map(str, c["refs"]))) if c.get("refs") else ""))
        st.markdown("**Observations challenging the leading call**")
        if not chal["counter_evidence"] and not chal["open_gaps"]:
            st.caption(T.CHALLENGE_NONE)
        for c in chal["counter_evidence"]:
            refs = f" (transactions: {', '.join(str(r) for r in c['refs'])})" if c.get("refs") else ""
            st.markdown(f"- {md_safe(c['detail'])}{md_safe(refs)}")
        if chal["open_gaps"]:
            st.markdown("**Evidence gaps — still unresolved**")
            for gap in chal["open_gaps"]:
                st.markdown(f"- **{md_safe(gap['factor_id'])}:** {md_safe(gap.get('evidence') or 'No supporting detail supplied.')}")


def _decision_zone(sk, selected, alert, txns, terr, basis, record_quality=None, owners=None, prior=None):
    """HUMAN DECISION: the PO's words, the PO's choice, then the checkpoint that says exactly what the choice needs."""
    from skills.defensibility import checkpoint
    from skills.evidence import signal_brief
    from skills.ledger import sla_days_remaining
    _zone("human")
    st.caption("Evidence gate · Deterministic grounding before filing. It checks the exact rationale before a filing can be recorded; a human Principal Officer still decides.")
    assessment = _current_assessment(selected)
    gos = _current_gos(selected)
    ai_state = _ai_state(sk, selected, assessment)
    rec = sk.evidence_sufficiency_summary(assessment, txns)["recommendation"] if ai_state == "VALID" else None
    if rec:
        _challenge_panel(sk, assessment, txns, rec)

    if terr:
        st.error(f"{terr} FILE is blocked. You can still defer or close with a reason.")
    elif not txns:
        st.warning(T.NO_TRANSACTIONS)

    text_key = f"gos_text_{selected}"
    if st.session_state.pop("_clear_text_for", None) == selected:      # a decision was just recorded: start the next one clean
        st.session_state[text_key] = ""
        st.session_state[f"_keep_{text_key}"] = ""
    if gos is None and ai_state == "VALID":
        draft_ctx = sk.case_context_for(alert, txns)
        draft_saved = sk.saved_draft_available(draft_ctx, assessment)
        want_live = st.button("Draft with AI (optional). You must edit it.", key=f"draft_{selected}")
        want_saved = False
        if draft_saved:
            want_saved = st.button(T.SAVED_DRAFT_BUTTON, key=f"saved_draft_{selected}")
            st.caption(T.SAVED_AVAILABLE.format(when=_when(draft_saved["captured_at"]), model=md_safe(draft_saved["model"])))
        if want_live or want_saved:
            _screen = sk.screen_request("Draft Ground of Suspicion narrative")
            if not _screen["allowed"]:
                st.error(f"Request refused: {_screen['reason']}")
            else:
                ctx = draft_ctx
                _t0 = time.monotonic()
                try:
                    if want_saved:
                        with sk.replaying():
                            result = sk.ground_of_suspicion_writer(ctx, assessment)
                    else:
                        with st.spinner("The AI is drafting, then checking its own draft… typically 60–100 s. Your rationale below is not changed until it finishes."):
                            result = sk.ground_of_suspicion_writer(ctx, assessment)
                except Exception as err:  # noqa: BLE001
                    _model_wait_add(selected, time.monotonic() - _t0)
                    st.error(T.SAVED_UNAVAILABLE if isinstance(err, SavedResponseUnavailable) else explained(err, "The AI draft"))
                else:
                    _model_wait_add(selected, time.monotonic() - _t0)
                    result["checked_sha"] = _sha(result["narrative"])
                    st.session_state["gos_result"], st.session_state["gos_alert"] = result, selected
                    st.session_state[text_key] = result["narrative"]
                    st.session_state[f"_keep_{text_key}"] = result["narrative"]
                    st.session_state[f"ai_draft_{selected}"] = result["narrative"]   # original draft, for the near-verbatim overlap at record time
                    st.rerun()
    elif ai_state == "INVALID":
        st.error("The AI assessment was invalid and has been withheld, so no draft can be made. Write your rationale yourself, or run the assessment again.")

    st.session_state.setdefault(text_key, st.session_state.get(f"_keep_{text_key}", ""))
    narrative = st.text_area(T.RATIONALE_LABEL, key=text_key, height=210, help=T.RATIONALE_HELP,
                             placeholder="Describe the specific basis for your decision, citing the transactions, the customer profile and what the evidence does and does not establish.")
    st.session_state[f"_keep_{text_key}"] = narrative
    ai_draft = (st.session_state.get(f"ai_draft_{selected}") or "").strip()      # the recorder strips the text it hashes; compare the same thing
    draft_unedited = bool(ai_draft) and _sha(narrative.strip()) == _sha(ai_draft)
    if draft_unedited:
        st.info(T.AI_DRAFT_BANNER)
    _narrative_references(narrative, txns, basis, selected)
    text_hash = _sha(narrative)

    # ── AI quality status for THIS exact text ────────────────────────────────
    if gos is None:
        status = "NOT_CHECKED"
    elif gos.get("checked_sha") != text_hash:
        status = "STALE"
    else:
        status = gos["status"]
    st.markdown(f"AI quality check: {_status_pill(status)}" + (f"  &nbsp; score **{md_safe(gos['quality_score'])}/10**" if gos and status not in ("STALE", "NOT_CHECKED") else "")
                + (f"  &nbsp; <span style='color:#777;font-size:0.85em'>draft by {esc(gos.get('model_used'))}"
                   + (f" (saved response, captured {esc(_when(gos.get('output_captured_at')))})" if gos.get("output_source") == SOURCE_SAVED else "") + "</span>"
                   if gos and gos.get("model_used") else ""),
                unsafe_allow_html=True)
    if gos is not None and not gos.get("ai_output_valid", False):
        st.error("The AI quality check gave an unusable answer, so this text cannot be marked READY. Check it yourself and re-check, or record why you are proceeding.")
    if status == "STALE":
        st.warning(T.STALE_QUALITY)
    if gos is not None and gos.get("quality_failures") and status not in ("STALE",):
        with st.expander(f"{len(gos['quality_failures'])} quality issue(s) to fix"):
            for item in gos["quality_failures"]:
                st.markdown(f"- {md_safe(item)}")
    if narrative.strip() and st.button("Re-check my text with the AI quality check", key=f"recheck_{selected}"):
        ctx = sk.case_context_for(alert, txns)
        with st.spinner("The AI is checking your text… typically 40–60 s."):
            q = sk.str_quality_checker(narrative, ctx)
        prev = gos or {}
        st.session_state["gos_result"] = {**prev, "narrative": narrative, "quality_score": q["quality_score"],
                                          "quality_failures": q["failures"], "hard_gate_passed": q["hard_gate_passed"],
                                          "ai_output_valid": q["ai_output_valid"], "ai_output_error": q["ai_output_error"],
                                          "status": q["status"], "checked_sha": text_hash,
                                          "model_used": prev.get("model_used") or sk.last_model_used}
        st.session_state["gos_alert"] = selected
        st.rerun()

    # ── who, and when ────────────────────────────────────────────────────────
    now_ist = datetime.now(IST).replace(second=0, microsecond=0)
    d_key, t_key = f"susp_date_{selected}", f"susp_time_{selected}"
    session_user = _session_user_id()
    po_shadow = _sticky("po_id", session_user)
    supplied = _feed_suspicion_ist(alert)                  # the case feed's time, if it gave one: the officer confirms or changes it
    d_shadow = _sticky(d_key, (supplied or now_ist).date())
    t_shadow = _sticky(t_key, (supplied or now_ist).time().replace(second=0, microsecond=0))
    if session_user:           # Snowflake supplied an authenticated session identity: it is shown, not typed, and it is what gets recorded
        st.text_input("Principal Officer ID", value=session_user, disabled=True, key="po_id_session")
        po_id = session_user
        st.caption(T.ID_SESSION.format(who=md_safe(session_user)))
    else:
        po_id = st.text_input("Principal Officer ID", key="po_id")
        st.caption(T.ID_TYPED)
    identity = ident.resolve(session_user, po_id)
    c_date, c_time = st.columns(2)
    susp_date = c_date.date_input("Suspicion formed", key=d_key, max_value=now_ist.date(), help="The 7-working-day STR clock runs from this point.")
    susp_time = c_time.time_input("Time (IST)", key=t_key, step=300)
    st.session_state[po_shadow] = po_id
    st.session_state[d_shadow], st.session_state[t_shadow] = susp_date, susp_time
    suspicion_ts = datetime.combine(susp_date, susp_time, tzinfo=IST).astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    ctx = sk.case_context_for(alert, txns, suspicion_ts, txn_owners=owners)
    ev = sk.validate_gos_evidence(narrative, txns, profile_text=ctx["customer_kyc"], context_dates=ctx["context_dates"],
                                  alert_narrative=ctx["alert_narrative"]) if narrative.strip() else None
    _render_gate(ev)

    # ── the decision ─────────────────────────────────────────────────────────
    labels = dict(T.DECISIONS)
    st.markdown(f"##### {T.DECISION_PROMPT}")
    gen = st.session_state.get("form_gen", 0)           # bumped after a recording: fresh widgets, nothing stale can be submitted twice
    choice_key = f"decision_{selected}_{gen}"
    try:
        choice = st.radio(T.DECISION_PROMPT, [d for d, _ in T.DECISIONS], format_func=labels.get, index=None, horizontal=True,
                          key=choice_key, label_visibility="collapsed")
    except TypeError:                                  # an older Streamlit without index=None: an explicit "choose" option instead
        choice = st.radio(T.DECISION_PROMPT, [None] + [d for d, _ in T.DECISIONS], format_func=lambda d: "— choose —" if d is None else labels[d],
                          horizontal=True, key=choice_key, label_visibility="collapsed")
    if choice is None:
        st.info(T.DECISION_NONE)
        return

    quality = {"status": status, "quality_score": (gos or {}).get("quality_score"),
               "hard_gate_passed": (gos or {}).get("hard_gate_passed"), "ai_output_valid": (gos or {}).get("ai_output_valid")}
    ack_key, assumed_key, override_key = f"ack_{selected}_{gen}", f"assumed_ack_{selected}_{gen}", f"override_{selected}_{gen}"
    eq_ack_key, reason_key = f"eq_ack_{selected}_{gen}", f"closure_reason_{selected}_{gen}_{choice}"       # per decision: Close and Defer offer different codes
    supersede_key = f"supersede_{selected}_{gen}"
    draft_ack_key = f"draft_ack_{selected}_{gen}"

    def make_gate():
        return sk.decision_gate(disposition=choice, rationale_text=narrative, case_context=ctx, gos_quality=quality, ai_recommendation=rec,
                                regulatory_basis=basis, override_reason=(st.session_state.get(override_key) or "").strip() or None,
                                unverified_claims_acknowledged=bool(st.session_state.get(ack_key)),
                                assumed_basis_acknowledged=bool(st.session_state.get(assumed_key)), suspicion_formed_at=suspicion_ts,
                                evidence_gate=ev, decision_maker_id=po_id, evidence_quality=eq.gate_summary(record_quality),
                                evidence_quality_acknowledged=bool(st.session_state.get(eq_ack_key)), identity=ident.clean(identity),
                                closure_reason_stated=(bool(st.session_state.get(reason_key)) if choice in ("NOT_FILE", "ESCALATE") else None),
                                prior_decisions=prior, supersede_reason=(st.session_state.get(supersede_key) or "").strip() or None,
                                ai_draft_adopted_verbatim=draft_unedited, ai_draft_adoption_acknowledged=bool(st.session_state.get(draft_ack_key)))

    gate = make_gate()
    codes = {c["code"] for c in gate["conditions"]}
    # Only what THIS decision needs is asked for — nothing else.
    if codes & {"ASSUMED_RULES_IN_FILING_BASIS", "ASSUMED_RULES_IN_CLOSURE_BASIS"}:
        tpl = T.ACK_ASSUMED_FILE if choice == "FILE" else T.ACK_ASSUMED_CLOSE
        st.checkbox(tpl.format(rules=label_safe(", ".join(basis["assumed_rule_ids"]))), key=assumed_key)
    if "UNVERIFIED_ASSERTIONS_IN_NARRATIVE" in codes:
        st.checkbox(T.ACK_UNVERIFIED, key=ack_key)
    if "EVIDENCE_QUALITY_ACK_REQUIRED" in codes and record_quality:
        st.checkbox(T.ACK_EVIDENCE_QUALITY.format(titles=label_safe("; ".join(f["title"] for f in record_quality["findings"] if f["effect"] == eq.REQUIRES_ACKNOWLEDGEMENT))), key=eq_ack_key)
    if codes & {"GOS_NOT_READY", "DECISION_DIFFERS_FROM_AI", "EVIDENCE_QUALITY_MANUAL_REVIEW"}:
        st.text_area(T.OVERRIDE_LABEL.format(n=MIN_OVERRIDE_REASON_CHARS), key=override_key, height=80, help=T.OVERRIDE_HELP)
    if "AI_DRAFT_ADOPTED_VERBATIM" in codes:
        st.checkbox(T.ACK_AI_DRAFT, key=draft_ack_key)
    if "REPEAT_DECISION_NEEDS_REASON" in codes:
        st.text_area(T.SUPERSEDE_LABEL.format(n=MIN_OVERRIDE_REASON_CHARS), key=supersede_key, height=80, help=T.SUPERSEDE_HELP)
    reason_code = None
    if choice in fbk.REASONS_BY_DISPOSITION:
        reasons = fbk.reasons_for(choice)
        reason_code = st.selectbox(T.FB_REASON_LABEL, [None] + list(reasons), format_func=lambda c: reasons.get(c, T.FB_REASON_NONE), key=reason_key, help=T.FB_REASON_HELP)
    str_ref = st.text_input("FINGate STR reference", placeholder="FINGATEREF-XXXX", key=f"str_ref_input_{gen}") if choice == "FILE" else None
    gate = make_gate()

    brief = signal_brief(txns) if txns else {}
    cp = checkpoint(gate, disposition=choice, ai_state=ai_state, ai_recommendation=rec, transaction_count=len(txns or []), window=brief.get("window"),
                    basis=basis, sla_days_remaining=sla_days_remaining(suspicion_ts, datetime.now(timezone.utc)))
    with bordered():
        st.markdown("#### Decision review sheet")
        st.caption("Review the seven checks, then the exact record below. Changing your text or choices re-evaluates the same decision gate.")
        _render_checkpoint(cp)
        _render_record_summary(alert, cp, po_id, suspicion_ts, rec, basis, narrative, st.session_state.get(override_key), identity=identity,
                               supersede_text=(st.session_state.get(supersede_key) or "").strip() if "REPEAT_DECISION_NEEDS_REASON" in codes else None)

    human_review_payload, hr_incomplete = None, False
    if hr.enabled():
        human_review_payload, hr_incomplete = _reconciliation(sk, selected, alert, choice, rec, ai_state, assessment, txns, terr, basis, gen)

    if st.button("Record decision to file" if choice == "FILE" else T.RECORD_BUTTON.format(label=labels[choice]), type="primary", use_container_width=True,
                 disabled=(not gate["can_record"]) or hr_incomplete or prior is None, key=f"record_{selected}",
                 help="Enabled only when the checkpoint has nothing that blocks or needs you."):
        _record_disposition(sk, selected, alert, txns, ctx, narrative, choice, po_id.strip(), suspicion_ts,
                            (str_ref or "PENDING-FINGATEREF") if choice == "FILE" else None, assessment or [], rec, status, gos,
                            (st.session_state.get(override_key) or "").strip(), bool(st.session_state.get(ack_key)), bool(st.session_state.get(assumed_key)),
                            human_review=human_review_payload, transactions_readable=not bool(terr),
                            supersede_reason=(st.session_state.get(supersede_key) or "").strip() if prior else None,
                            ai_draft_adoption_acknowledged=bool(st.session_state.get(draft_ack_key)),
                            evidence_quality_acknowledged=bool(st.session_state.get(eq_ack_key)), identity=ident.clean(identity),
                            feedback={"reason_code": reason_code, "ai_draft_generated": bool(st.session_state.get(f"ai_draft_{selected}")),
                                      "ai_draft_sha256": _sha((st.session_state.get(f"ai_draft_{selected}") or "").strip())}, txn_owners=owners)


CP_STYLE = {"PASS": ("#2e7d32", "✓"), "NA": ("#78909c", "–"), "NOTE": ("#546e7a", "i"), "NEEDS_YOU": ("#e65100", "!"), "BLOCK": ("#c62828", "✕")}


def _render_checkpoint(cp: dict):
    """The decision checkpoint: seven rows, one status each — glyph + words + colour, never colour alone."""
    st.markdown(f"##### {T.CHECKPOINT_TITLE.format(label=cp['label'])}")
    rows = []
    for r in cp["rows"]:
        color, glyph = CP_STYLE[r["status"]]
        rows.append(
            f'<div style="display:flex;flex-wrap:wrap;gap:4px 14px;padding:6px 0;border-bottom:1px solid rgba(128,128,128,.25)">'
            f'<div style="min-width:175px;font-weight:700;color:{color}">{glyph}&nbsp; {esc(r["status_label"])}</div>'
            f'<div style="flex:1;min-width:240px"><div style="font-weight:600">{esc(r["label"])}</div><div style="opacity:.9">{esc(r["detail"])}</div></div></div>')
    html_md("".join(rows))
    color = "#2e7d32" if cp["ready"] else "#c62828"
    html_md(f'<div style="border-left:5px solid {color};padding:6px 12px;margin:8px 0;font-weight:700">{esc(cp["summary"])}</div>')
    with st.expander("What the statuses mean"):
        for k, label in T.STATUS_LABEL.items():
            st.markdown(f"- **{label}** — {T.STATUS_MEANING[k]}")
    st.markdown(f"**{T.RESPONSIBILITY_TITLE}**")
    for line in cp["responsibility"]:
        st.markdown(f"- {md_safe(line)}")


def _render_record_summary(alert, cp, po_id, suspicion_ts, rec, basis, narrative, override_text, identity=None, supersede_text=None):
    """Exactly what will become the permanent record (design/CASE_WORKSPACE_SPEC.md §4.5)."""
    labels = dict(T.DECISIONS)
    nb = lambda k: len((basis or {}).get(k) or [])  # noqa: E731
    with bordered():
        st.markdown(f"**{T.RECORD_SUMMARY_TITLE}**")
        st.markdown(f"- **Decision:** {md_safe(cp['label'])} — alert {md_safe(alert['ALERT_ID'])}, customer {md_safe(alert['CUSTOMER_REF'])}")
        try:
            formed = datetime.strptime(suspicion_ts, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc).astimezone(IST).strftime("%-d %b %Y, %H:%M IST")
        except ValueError:
            formed = suspicion_ts
        st.markdown(f"- **By:** {md_safe(po_id.strip() or '(enter your Principal Officer ID)')} · suspicion formed {md_safe(formed)}")
        if identity is not None:
            st.markdown("- **Identity:** " + ("Snowflake session identity (authenticated)" if identity.get("authenticated") else "typed, not authenticated") + " · " + md_safe(T.ID_RECORDED_NOTE))
        st.markdown(f"- **AI said:** {md_safe((rec or 'not used').replace('_', ' '))} → **you decided:** {md_safe(cp['label'])}"
                    + (f" · your reason: “{md_safe((override_text or '').strip()[:160])}”" if (override_text or '').strip() else ""))
        st.markdown(f"- **Regulatory basis:** corpus v{md_safe((basis or {}).get('corpus_version', 'unknown'))} · {nb('proven_rule_ids')} PROVEN · {nb('assumed_rule_ids')} ASSUMED")
        st.markdown("**Your rationale:** exact text to be recorded")
        st.text(narrative)
        if override_text:
            st.markdown("**Override reason — exact text:**")
            st.text(override_text)
        if supersede_text:
            st.markdown("**Why the earlier decision no longer stands — exact text:**")
            st.text(supersede_text)
        st.caption("Recording FILE stores your decision to file; it does not submit an STR. Submission through FINGate is a separate manual step." if cp["disposition"] == "FILE" else
                   "This stores the selected decision and rationale in the append-only ledger; it does not submit an STR.")
        st.caption(T.RECORD_SUMMARY_FOOTER)


def _narrative_references(narrative, txns, basis, selected):
    """Read-only source inspector beside the note; never a claim-to-source verification."""
    import re
    st.markdown("##### Narrative references")
    st.caption("Open a cited source without leaving your note. An ID match confirms only that the source exists, not that it supports the sentence. Unrecognised citations may be missed.")
    mentions = lambda value: bool(value and re.search(r"(?<![\w-])" + re.escape(str(value)) + r"(?![\w-])", narrative, re.I))
    entries = []
    for row in txns:
        if mentions(row.get("txn_id")):
            entries.append(("Transaction · " + str(row["txn_id"]), row, "transaction"))
    for rule in (basis or {}).get("rules", []):
        if mentions(rule.get("rule_id")):
            entries.append(("Rule · " + str(rule["rule_id"]), rule, "rule"))
    if not entries:
        st.caption("No supplied transaction or case-basis rule IDs matched this note. Use the evidence pane for the full record and regulatory lookup.")
        return
    # Case-scoped key; discard a selection that no longer exists after an edit.
    key = f"narrative_reference_{selected}"
    labels = [e[0] for e in entries]
    if st.session_state.get(key) not in labels:
        st.session_state.pop(key, None)
    picked = st.selectbox("Open cited source", labels, key=key, format_func=label_safe)
    _, row, kind = next(e for e in entries if e[0] == picked)
    with bordered():
        if kind == "transaction":
            st.text(f"{row.get('txn_id')} · {row.get('type')} · ₹{float(row.get('amount_inr') or 0):,.0f}")
            st.text(f"Recorded date: {row.get('date')} · Channel: {row.get('channel')}")
            st.text(f"Counterparty: {row.get('counterparty') or 'Not supplied'}")
            st.caption("Stored row only; may be an aggregate. No transfer-to-sentence relationship has been verified.")
        else:
            st.text(f"{row.get('rule_id')} · {row.get('evidence_level')} · {row.get('source_authority') or 'Authority not supplied'}")
            st.text(f"Review: {row.get('review_status') or 'Not supplied'}")
            st.caption("Counts as a case basis" if row.get("usable_as_basis") else "Does not count as a case basis")
            st.caption("This is case-basis metadata, not verified legal advice. Use the in-case rule lookup for available source text and qualifications.")


def _render_gate(gate):
    """Live feedback on the text as it stands: do its facts match the record, and what can the checks not verify."""
    if gate is None:
        return
    st.caption("Evidence gate · Deterministic grounding before filing. A passing result is limited to the listed pattern checks and does not approve a conclusion.")
    coverage = gate.get("fact_coverage") or {}
    st.caption(f"Pattern checks on the current text: {coverage.get('amounts_checked', 0)} amount(s), "
               f"{coverage.get('dates_checked', 0)} date(s), {coverage.get('txn_ids_checked', 0)} transaction ID(s). "
               "Counts describe detected patterns, not verified sentences.")
    if gate["passed"]:
        st.success("**Facts check: PASS.** No unsupported facts were detected by the existing pattern checks. This is not sentence-level verification or approval of your conclusion.")
    else:
        lines = [f"- **{k.replace('_', ' ')}:** " + ", ".join(f"`{code_safe(v)}`" for v in vals) for k, vals in gate["unsupported_claims_by_type"].items()]
        st.error("**Facts check: BLOCKED.** Your text states facts that are NOT in the case record:  \n" + "  \n".join(lines))
    misattributed = [a for a in gate["unverified_assertions"] if a.get("type") == "attribution_mismatch"]
    unverifiable = [a for a in gate["unverified_assertions"] if a.get("type") != "attribution_mismatch"]
    if misattributed:
        st.warning(T.ATTRIBUTION_WARNING + "  \n" + "  \n".join(f"- `{code_safe(a['text'])}` — {md_safe(a['why'])}" for a in misattributed))
    if unverifiable:
        st.warning("**Unverified statements.** These cannot be checked against the record. Label them as your inference; do not present them as fact:  \n" +
                   "  \n".join(f"- `{code_safe(a['text'])}` — {md_safe(a['why'])}" for a in unverifiable))
    st.caption("Outside checker coverage: intent, causal links and the meaning of a whole sentence are not established by matching values or IDs. A passing check does not prove the narrative true.")
    with st.expander("What the facts check did and did not verify", expanded=True):
        scope = gate["verification_scope"]
        st.markdown("**Pattern classes checked (not a list of verified claims):** " + md_safe("; ".join(scope.get("verified", []))))
        st.markdown("**NOT verified (a passing check is not full verification):**\n" + "\n".join(f"- {md_safe(x)}" for x in scope.get("not_verified", [])))
        if scope.get("not_checkable_now"):
            st.markdown("**Not checkable for this case:** " + md_safe("; ".join(scope["not_checkable_now"])))


def _when(iso) -> str:
    """The date part of a stored capture time, e.g. '5 Oct 2026 (UTC)'; never raises."""
    try:
        return datetime.fromisoformat(str(iso)).strftime("%-d %b %Y") + " (UTC)"
    except (TypeError, ValueError):
        return "an earlier date"


def _saved_output_args(alert_id: str, ai_rec) -> dict:
    """Keyword arguments for the recorder when any AI output behind this decision was a SAVED response (none for a live or absent AI)."""
    if not ai_rec:
        return {}
    gos = st.session_state.get("gos_result") if st.session_state.get("gos_alert") == alert_id else None
    assessed = st.session_state.get("assessed_alert") == alert_id
    parts = [name for name, src, when in (("assessment", st.session_state.get("assessment_source") if assessed else None, st.session_state.get("assessment_captured_at")),
                                          ("draft", (gos or {}).get("output_source"), (gos or {}).get("output_captured_at"))) if src == SOURCE_SAVED]
    if not parts:
        return {}
    when = (st.session_state.get("assessment_captured_at") if "assessment" in parts else (gos or {}).get("output_captured_at"))
    return {"ai_output_source": SOURCE_SAVED, "ai_output_captured_at": when, "ai_output_parts": parts}


def _desk_open(alert_id: str):
    """Note, once per session, when this case was first shown on the Investigation desk (the start of the desk-session proxy)."""
    st.session_state.setdefault(f"_desk_opened_{alert_id}", time.time())


def _model_wait_add(alert_id: str, seconds: float):
    key = f"_model_wait_{alert_id}"
    st.session_state[key] = float(st.session_state.get(key, 0.0)) + max(0.0, float(seconds))


def _desk_session_args(alert_id: str) -> dict:
    opened = st.session_state.get(f"_desk_opened_{alert_id}")
    if not opened:
        return {}
    return {"desk_session": {"opened_at_utc": datetime.fromtimestamp(opened, timezone.utc).isoformat(timespec="seconds"), "desk_seconds": time.time() - opened,
                             "model_wait_seconds": st.session_state.get(f"_model_wait_{alert_id}", 0.0)}}


def _record_disposition(sk, alert_id, alert, txns, ctx, rationale, disposition, po_id, suspicion_ts, str_ref,
                        poe_assessment, ai_rec, gos_status, gos, override_reason, ack, assumed_ack=False, human_review=None,
                        transactions_readable=True, evidence_quality_acknowledged=None, identity=None, feedback=None, txn_owners=None,
                        supersede_reason=None, ai_draft_adoption_acknowledged=None):
    from skills.ledger import LedgerBlocked, LedgerWriteError
    rules = json.loads(str(alert.get("RULES_CITED") or "[]"))
    rfis = json.loads(str(alert.get("RFI_TRIGGERS") or "[]"))
    quality = {"status": gos_status, "quality_score": (gos or {}).get("quality_score"),
               "hard_gate_passed": (gos or {}).get("hard_gate_passed"), "ai_output_valid": (gos or {}).get("ai_output_valid")}
    try:
        with st.spinner("Recording your decision and sealing it with a hash…"):
            result = sk.alert_disposition_recorder(
                alert_id=alert_id, customer_ref=alert["CUSTOMER_REF"], disposition=disposition, rationale_text=rationale,
                rules_cited=rules, rfi_triggers=rfis, poe_assessment=poe_assessment, decision_maker_id=po_id,
                suspicion_formed_at=suspicion_ts, str_reference=str_ref, ai_recommendation=ai_rec,
                override_reason=(override_reason or "").strip() or None, model_name=sk.last_model_used if ai_rec else None,
                case_context=ctx, gos_quality=quality, unverified_claims_acknowledged=bool(ack),
                assumed_basis_acknowledged=bool(assumed_ack), human_review=human_review,
                transactions_readable=transactions_readable, evidence_quality_acknowledged=evidence_quality_acknowledged,
                identity=identity, feedback=feedback, supersede_reason=(supersede_reason or "").strip() or None,
                ai_draft_adoption_acknowledged=ai_draft_adoption_acknowledged, **_saved_output_args(alert_id, ai_rec), **_desk_session_args(alert_id))
    except LedgerBlocked as err:
        st.warning(f"**Not recorded.** {md_safe(err)}")
        return
    except (LedgerWriteError, Exception) as err:  # noqa: BLE001
        from skills.errors import explain
        st.error("**Your decision was NOT recorded and nothing was saved.** " + explain(err, "The ledger")["message"] + " Your text is still here: try again.")
        return
    st.session_state.pop(f"_desk_opened_{alert_id}", None)             # the next decision on this alert starts a new desk session
    st.session_state.pop(f"_model_wait_{alert_id}", None)
    provenance = result.get("provenance") if isinstance(result, dict) else {}
    provenance = provenance if isinstance(provenance, dict) else {}
    stored_basis = provenance.get("regulatory_basis") or {}
    acknowledgements = provenance.get("acknowledgements") or {}
    st.session_state["last_decision"] = {
        "decision_id": result["decision_id"], "alert_id": alert_id, "disposition": disposition,
        "sla_days_remaining": result["sla_days_remaining"], "po_id": po_id,
        "recorded_at": datetime.now(IST).strftime("%-d %b %Y, %H:%M IST"),
        "evidence_txn_ids": list(provenance.get("evidence_txn_ids") or []),
        "proven_rule_ids": list(stored_basis.get("proven_rule_ids") or []),
        "assumed_rule_ids": list(stored_basis.get("assumed_rule_ids") or []),
        "assumed_basis_acknowledged": acknowledgements.get("assumed_basis"),
    }
    for key in ("poe_assessment", "assessed_alert", "gos_result", "gos_alert", "assessment_source", "assessment_captured_at"):
        st.session_state.pop(key, None)
    for key in (f"ai_failed_{alert_id}", f"ai_draft_{alert_id}", _provisional_key(alert_id)):
        st.session_state.pop(key, None)
    st.session_state["form_gen"] = st.session_state.get("form_gen", 0) + 1
    st.session_state["_clear_text_for"] = alert_id        # applied BEFORE the text widget exists on the next run
    st.cache_data.clear()
    st.rerun()


def _render_reconstruction(decision_id: str, heading: str = "Decision reconstruction"):
    """Reconstruct a stored decision: first WHAT was decided and why (what the PO saw, said and acknowledged), then the integrity replay."""
    try:
        rc = get_skills().reconstruct_decision(decision_id)
    except Exception as err:  # noqa: BLE001
        st.error(explained(err, "The reconstruction"))
        return
    if not rc["found"]:
        st.warning("This decision is no longer in the ledger. Tell your system owner.")
        return
    d, meta = rc["decision"], rc["provenance"] or {}
    from skills.governance import basis_by_level
    st.markdown(f"**{heading}**")
    st.caption("Decision dossier · recorded provenance below; current-data replay is separately labelled. A hash is an integrity check, not proof that the original evidence was true.")
    st.markdown(f"**Decision:** `{code_safe(meta.get('human_decision', d.get('DISPOSITION')))}` by `{code_safe(d.get('DECISION_MAKER_ID'))}` · "
                f"recorded {md_safe(str(d.get('DECISION_MADE_AT') or '—')[:19])} · {md_safe(d.get('SLA_DAYS_REMAINING'))} working day(s) were left")
    st.markdown("#### Evidence at decision time")
    st.caption("The ledger retains evidence references and a fingerprint, not a complete historical copy of every transaction. Current records must not be treated as the original snapshot.")
    st.text("Recorded evidence references: " + ", ".join(map(str, meta.get("evidence_txn_ids") or [])))
    st.text("Recorded evidence fingerprint: " + str(meta.get("evidence_snapshot_sha256") or "Not recorded"))
    with st.expander("Assessment stored with this decision"):
        if meta.get("poe_assessment"):
            st.json(meta["poe_assessment"])
        else:
            st.caption("No factor assessment recorded. This is not a newly generated assessment.")
    st.markdown("#### Officer reasoning and recorded outcome")
    st.markdown("**Their reason, in their words:**")
    st.text(d.get("RATIONALE_TEXT") or "—")
    c1, c2 = st.columns(2)
    with c1:
        st.markdown("**What they saw**")
        st.markdown(f"- The AI said: `{code_safe(meta.get('ai_recommendation', '—'))}` (model `{code_safe(meta.get('model_name', '—'))}`)  \n"
                    f"- They decided: `{code_safe(meta.get('human_decision', d.get('DISPOSITION')))}`" + (f" — override reason: “{md_safe(meta.get('override_reason'))}”" if meta.get("override") else ""))
        out = meta.get("ai_output")
        if isinstance(out, dict) and out.get("source") == SOURCE_SAVED:
            st.markdown("- " + T.SAVED_RECORDED.format(when=md_safe(_when(out.get("captured_at"))), model=md_safe(out.get("model", "UNKNOWN")),
                                                        parts=md_safe(" and ".join(out.get("parts") or []) or "AI output")))
        sup = meta.get("supersession")
        if isinstance(sup, dict) and sup.get("prior_count"):
            st.markdown(f"- This decision came after {md_safe(sup.get('prior_count'))} earlier decision(s) on the alert, most recently `{code_safe(sup.get('supersedes_decision_id'))}`"
                        f" — reason: “{md_safe(str(sup.get('reason') or '')[:300])}”")
        basis = basis_by_level(meta.get("regulatory_basis"))
        st.markdown(f"- Regulatory basis: corpus v{md_safe(meta.get('corpus_version', '—'))} · {len(basis.get('PROVEN', []))} PROVEN · {len(basis.get('ASSUMED', []))} ASSUMED"
                    f" · {len(basis.get('NEEDS-VERIFICATION', []))} internal tag(s)")
        g = meta.get("defensibility_gate") or {}
        if g.get("status"):
            st.markdown(f"- Checkpoint result: `{code_safe(g['status'])}`")
    with c2:
        st.markdown("**What they acknowledged**")
        ack = meta.get("acknowledgements") or {}
        lines = []
        if ack.get("assumed_basis") is True:
            lines.append(f"ASSUMED rules ({md_safe(', '.join(ack.get('assumed_rule_ids') or []))})")
        if ack.get("unverified_claims") is True:
            lines.append(f"{md_safe(ack.get('unverified_assertion_count', 0))} unverified statement(s)")
        if ack.get("override_reason_recorded"):
            lines.append("an override reason was recorded")
        st.markdown("\n".join(f"- {x}" for x in lines) if lines else "- Nothing needed acknowledging.")
        ch = meta.get("challenge") or {}
        st.markdown("**What argued against it**")
        if ch.get("counter_evidence"):
            for c in ch["counter_evidence"][:6]:
                st.markdown(f"- {md_safe(c.get('detail'))}")
            if ch.get("counter_evidence_total", 0) > 6:
                st.caption(f"+{ch['counter_evidence_total'] - 6} more in the stored record.")
        else:
            st.markdown("- " + (T.CHALLENGE_NONE if ch else "Not recorded for this decision."))
    eqs, ids, fbo = meta.get("evidence_quality"), meta.get("decision_identity"), meta.get("feedback")
    if isinstance(eqs, dict) or isinstance(ids, dict) or isinstance(fbo, dict):
        st.markdown("#### Record quality, attribution and feedback")
        if isinstance(eqs, dict):
            counts = eqs.get("counts") or {}
            st.markdown(f"- Evidence sufficiency when decided: **{md_safe(eqs.get('sufficiency_pct'))}%** · issues: "
                        + md_safe(", ".join(f"{n} {eq.EFFECT_LABEL.get(k, k).lower()}" for k, n in counts.items() if n) or "none"))
            for fnd in (eqs.get("findings") or [])[:8]:
                st.markdown(f"  - {md_safe(fnd.get('title'))} ({md_safe(eq.EFFECT_LABEL.get(fnd.get('effect'), fnd.get('effect')))})")
        if isinstance(ids, dict):
            st.markdown("- Decision-maker identity: " + ("a Snowflake session identity (authenticated)" if ids.get("authenticated") else "typed by the officer, **not authenticated**"))
        if isinstance(fbo, dict):
            st.markdown(f"- AI recommendation response: `{code_safe(fbo.get('ai_response'))}` · structured reason: `{code_safe(fbo.get('reason_code') or 'not stated')}`")
            st.caption("Feedback is used for monitoring and future calibration only.")
    hrv = meta.get("human_review")
    if isinstance(hrv, dict):
        prov, air, fr = hrv.get("provisional") or {}, hrv.get("ai_reveal") or {}, hrv.get("final_reconciliation") or {}
        st.markdown(f"#### {T.HR_RECON_SECTION}")
        st.markdown("- " + md_safe(T.HR_RECON_PROVISIONAL.format(
            view=T.HR_VIEWS.get(prov.get("view"), prov.get("view") or "—"),
            refs=", ".join(prov.get("evidence_refs") or []) or "—", q=prov.get("unanswered_question") or "—")))
        st.markdown("- " + md_safe(T.HR_RECON_AI.format(used="yes" if air.get("assessment_used") else "no", rec=(air.get("recommendation") or "—"))))
        st.markdown("- " + md_safe(T.HR_RECON_FINAL.format(decision=fr.get("final_decision") or "—", changed=fr.get("changed_since_provisional"))))
        if fr.get("material_counter_evidence"):
            st.markdown("- Response to the most material counter-point: " + md_safe(fr.get("material_counter_evidence")))
        if fr.get("ai_draft_overlap_pct") is not None:
            st.caption(f"Near-verbatim AI-draft overlap at record time: {md_safe(fr.get('ai_draft_overlap_pct'))}% (descriptive only — shared facts make overlap expected).")
        st.caption(T.HR_RECON_ENFORCEMENT)
    st.markdown("**Checks replayed now**")
    st.caption("These checks run now. Evidence comparisons and grounding replay use the current case data; stored hash/provenance checks inspect the recorded decision. Missing or changed evidence is not silently replaced.")
    icon = {True: "✅", False: "❌", None: "⚪"}
    for name, chk in rc["checks"].items():
        st.markdown(f"{icon[chk['ok']]} **{name.replace('_', ' ')}** — {md_safe(chk['detail'])}")
    with st.expander("Full stored record (METADATA_JSON)"):
        st.json(meta)
    st.caption(f"Written by role `{code_safe(meta.get('written_by_role', '—'))}`" + (f" as database user `{code_safe(meta.get('written_by_user'))}`" if meta.get("written_by_user") else "")
               + f" · evidence fingerprint `{code_safe(str(meta.get('evidence_snapshot_sha256', ''))[:16])}…` "
               f"· row hash `{code_safe(str(d.get('ROW_HASH') or '—')[:16])}…`")
    _inspection_pack(rc, decision_id)


def _inspection_pack(rc: dict, decision_id: str):
    """The decision as a file for an inspector or a case-management record, checkable offline (skills/dossier.py, scripts/verify_dossier.py).
    Built only when asked: it reads the alert and its transactions once more, and the officer should see what it contains before it leaves the application."""
    from skills import dossier as DS
    decision_id = str(decision_id)
    packs = st.session_state.setdefault("_inspection_packs", {})
    st.markdown("#### Inspection pack")
    st.caption("A file of this decision: the rationale as recorded, the stored provenance, the regulatory basis and what the officer acknowledged, with the case record "
               "and the checks that can be replayed from the file alone. It does not file anything. Contains the customer reference and the alert data shown here.")
    if decision_id not in packs:
        if st.button("Prepare inspection pack", key=f"pack_{decision_id}"):
            try:
                sk = get_skills()
                d_alert = sk.load_alert(rc["decision"]["ALERT_ID"])
                d_txns = sk.load_transactions(rc["decision"]["ALERT_ID"])
                dossier = DS.build(rc, d_alert, d_txns, generated_at=datetime.now(timezone.utc), app_version=PACK_APP_VERSION)
                verdict = DS.verify(dossier)
                packs[decision_id] = {"json": json.dumps(dossier, indent=1, ensure_ascii=False, default=str), "html": DS.render_html(dossier, verdict), "verdict": verdict["verdict"],
                                      "failed": verdict.get("failed") or []}
            except Exception as err:  # noqa: BLE001
                st.error(explained(err, "The inspection pack"))
                return
            st.rerun()
        return
    pack = packs[decision_id]
    if pack["failed"]:
        st.error("The pack was built but fails its own offline checks: " + ", ".join(label_safe(x.replace("_", " ")) for x in pack["failed"]) + ". Tell your system owner before using it.")
    else:
        st.caption(f"Offline verification of this pack: **{label_safe(pack['verdict'])}** (INCOMPLETE means some checks cannot be run on this decision, for example the row predates a control).")
    c1, c2 = st.columns(2)
    c1.download_button("Download pack (JSON)", pack["json"], file_name=f"decision-{decision_id[:8]}.json", mime="application/json", key=f"dlj_{decision_id}")
    c2.download_button("Download printable page (HTML)", pack["html"], file_name=f"decision-{decision_id[:8]}.html", mime="text/html", key=f"dlh_{decision_id}")
    st.caption("Check it without this application: `python scripts/verify_dossier.py decision-….json`")


# ── the zones ────────────────────────────────────────────────────────────────
def _facts_zone(sk, selected, alert, txns, terr):
    """SOURCE FACTS: everything here is read from, or computed over, the case record. No model output appears in this zone."""
    _zone("facts")
    with bordered():
        st.markdown(f"> {md_safe(alert['ALERT_NARRATIVE'])}")
        st.caption("This text comes from the detection system and is not verified. Everything below it is computed from the transaction rows.")
        _signal_brief(alert, txns, terr)
        try:
            rfi_list = json.loads(str(alert.get("RFI_TRIGGERS") or "[]"))
        except ValueError:
            rfi_list = []
        if rfi_list:
            st.markdown("**Detector tags:** " + "  ·  ".join(f"`{code_safe(r)}`" for r in rfi_list) +
                        "  \n_These are internal tags, not verified regulatory citations._")
    if selected in DEMO_PAIR:
        other = DEMO_PAIR[1] if selected == DEMO_PAIR[0] else DEMO_PAIR[0]
        with st.expander(f"{T.PAIR_TITLE} — compare with {other}", expanded=True):
            st.caption(T.PAIR_THESIS)
            try:
                o = sk.load_alert(other)
            except Exception:  # noqa: BLE001
                o = None
            if o:
                a, b = (alert, o) if selected == DEMO_PAIR[0] else (o, alert)
                _twin_table(a, b)
                _pair_explanation(a, b)
            else:
                st.warning(T.PAIR_UNAVAILABLE)


def _signal_brief(alert, txns, terr):
    case_id = hashlib.sha256(str(alert["ALERT_ID"]).encode()).hexdigest()[:12]
    html_md(f'<div class="case-anchor" id="money-{case_id}"></div>')
    st.markdown("#### Money movement")
    if terr:
        st.error(terr)
        return
    if not txns:
        st.warning(T.NO_TRANSACTIONS)
        return
    from skills.evidence import signal_brief, movement_records
    b = signal_brief(txns)
    movement = movement_records(txns)
    if movement["has_summaries"]:
        st.warning("Aggregated records present — individual transfers are unavailable for: " +
                   md_safe(", ".join(movement["summary_ids"])) + ". Counts below are stored rows, not underlying transfer counts.")
    st.caption("Amounts and directions are from the supplied rows. Arrows do not link particular credits to debits or establish timing or account balance.")
    def node(title, amount, count):
        return (f'<div class="money-node"><small>{title}</small><strong>{amount}</strong>'
                f'<small>{count}</small></div>')
    html_md('<div class="money-flow">' +
            node("Credits recorded", f"₹{b['total_credit']:,.0f}" if b["credit_count"] else "No credit rows", f"{b['credit_count']} stored rows") +
            '<span class="money-arrow" aria-hidden="true">→</span>' +
            node("Customer record", esc(alert.get("CUSTOMER_REF") or "Not supplied"), "Balance not established") +
            '<span class="money-arrow" aria-hidden="true">→</span>' +
            node("Debits recorded", f"₹{b['total_debit']:,.0f}" if b["debit_count"] else "No debit rows", f"{b['debit_count']} stored rows") + '</div>')
    st.caption(f"{b['txn_count']} stored rows · {len(b['flagged_counterparties'])} flagged counterparties" +
               (f" · debit/credit ratio {b['onward_ratio_pct']}%" if b["onward_ratio_pct"] is not None else ""))
    st.caption("Summary labels are detected from the feed text; other rows' granularity is not independently verified.")
    if b["window"]:
        st.caption(f"Observed window {b['window'][0]} → {b['window'][1]}  ·  {len(b['counterparties'])} counterparties  ·  channels: {md_safe(', '.join(b['channels']) or '—')}")
    if b["flagged_counterparties"]:
        st.caption("Flagged counterparties: " + md_safe(", ".join(b["flagged_counterparties"])))
    if b["documented_counterparties"]:
        st.caption("Documentation noted in record (documents not independently checked): " + md_safe(", ".join(b["documented_counterparties"])))
    direction = st.radio("Transaction rows to inspect", ["All records", "Credits", "Debits"], horizontal=True,
                         key=f"movement_direction_{alert['ALERT_ID']}")
    visible = txns if direction == "All records" else movement["groups"]["CREDIT" if direction == "Credits" else "DEBIT"]
    st.caption("This filter changes the evidence view only; assessment and decision checks always use the complete case record.")
    import pandas as pd
    if not visible:
        st.info("No rows for this direction in the supplied record. This does not establish that no transfers occurred.")
        return
    st.dataframe(pd.DataFrame(visible).rename(columns={"txn_id": "TXN", "date": "Date", "type": "Type", "amount_inr": "₹",
                                                    "channel": "Channel", "counterparty": "Counterparty", "is_flagged": "Flagged"}),
                 hide_index=True, use_container_width=True)
    row_index = st.selectbox("Inspect a transaction row", range(len(visible)),
                            format_func=lambda i: label_safe(visible[i].get("txn_id") or f"Row {i + 1}"),
                            key=f"movement_row_{alert['ALERT_ID']}_{direction}")
    row = visible[row_index]
    with bordered():
        st.markdown(f"**{md_safe(row.get('txn_id') or 'Unidentified row')}** · {md_safe(row.get('type'))} · ₹{float(row.get('amount_inr') or 0):,.0f}")
        st.text(f"Counterparty: {row.get('counterparty') or 'Not supplied'}")
        st.text(f"Recorded date: {row.get('date') or 'Not supplied'} · Channel: {row.get('channel') or 'Not supplied'}")
        st.caption("Flag recorded" if row.get("is_flagged") else "No flag recorded — not a clearance finding")


def _case_rules(alert) -> list[str]:
    try:
        return [r for r in json.loads(str(alert.get("RULES_CITED") or "[]")) if isinstance(r, str)]
    except ValueError:
        return []


def _basis_zone(sk, alert):
    """REGULATORY BASIS: what the corpus says, how sure it is, how it was reviewed, and whether it still applies — or an abstention."""
    _zone("basis")
    st.caption("Cortex Search · Governed regulatory lookup. Returned corpus entries retain their PROVEN, ASSUMED or excluded status; this is not independently verified legal advice.")
    basis = None
    with bordered():
        rules = _case_rules(alert)
        try:
            basis = cached_rule_basis(tuple(rules))
        except Exception as err:  # noqa: BLE001
            _abstain(T.ABSTAIN_UNAVAILABLE_BODY, T.ABSTAIN_UNAVAILABLE_TITLE)
            st.caption(explained(err, "The regulatory basis"))
        if basis is not None:
            _render_basis(basis)
        with st.expander("Look up a rule (Cortex Search)", expanded=False):
            _lookup_widget(sk, key="inline_rule", limit=3)
    return basis


def _render_basis(basis: dict):
    """What each cited rule is, how strong (PROVEN / ASSUMED), who said it, how it was reviewed, whether it still applies."""
    from skills.governance import GRADE_NO_SUPPORTED_BASIS, GRADE_UNAVAILABLE
    import pandas as pd
    grade = basis.get("grade")
    if grade == GRADE_UNAVAILABLE:
        _abstain(T.ABSTAIN_UNAVAILABLE_BODY, T.ABSTAIN_UNAVAILABLE_TITLE)
        return
    if not basis.get("rules"):
        _abstain(T.ABSTAIN_BASIS_BODY, T.ABSTAIN_NO_RULES_TITLE, T.ABSTAIN_BASIS_FILE, T.ABSTAIN_BASIS_OTHER)
        return
    st.caption(T.BASIS_HEADER.format(version=md_safe(basis.get("corpus_version")), snapshot=md_safe(basis.get("snapshot_date"))))
    if grade == GRADE_NO_SUPPORTED_BASIS:
        _abstain(T.ABSTAIN_BASIS_BODY, T.ABSTAIN_BASIS_TITLE, T.ABSTAIN_BASIS_FILE, T.ABSTAIN_BASIS_OTHER)
    elif basis.get("requires_assumed_acknowledgement"):
        st.warning(T.BASIS_GRADE["INCLUDES_ASSUMED"])
    else:
        st.info(T.BASIS_GRADE["PROVEN_ONLY"])
    table = []
    order = {"PROVEN": 0, "ASSUMED": 1}
    for e in sorted(basis["rules"], key=lambda e: (order.get(e.get("evidence_level"), 2), e["rule_id"])):          # strongest first
        reason = e.get("unusable_reason")
        status = T.RULE_STATUS["counts"] if e.get("usable_as_basis") else T.RULE_STATUS.get(reason, "Does not count").format(successor=e.get("superseded_by") or "?")
        table.append({T.BASIS_TABLE_COLUMNS[0]: e["rule_id"], T.BASIS_TABLE_COLUMNS[1]: e.get("evidence_level"),
                      T.BASIS_TABLE_COLUMNS[2]: T.AUTHORITY_LABEL.get(e.get("source_authority"), e.get("source_authority") or "—"),
                      T.BASIS_TABLE_COLUMNS[3]: T.REVIEW_LABEL.get(e.get("review_status"), e.get("review_status") or "—"),
                      T.BASIS_TABLE_COLUMNS[4]: status})
    st.dataframe(pd.DataFrame(table), hide_index=True, use_container_width=True)
    present = {e.get("evidence_level") for e in basis["rules"]}
    for level in ("PROVEN", "ASSUMED", "NEEDS-VERIFICATION"):
        if level in present:
            st.caption(T.WEIGHT_LEGEND[level])
    usable = len(basis.get("proven_rule_ids") or []) + len(basis.get("assumed_rule_ids") or [])
    if usable:
        st.caption(T.VERIFIED_LINE.format(verified=basis.get("independently_verified_count", 0), usable=usable))
    for e in basis.get("excluded", []):
        if e.get("reason") == "SUPERSEDED":
            st.warning(T.SUPERSEDED_NOTE.format(rule=md_safe(e["rule_id"]), successor=md_safe(e.get("superseded_by"))))
        elif e.get("reason") == "NOT_IN_CORPUS":
            st.warning(T.NOT_IN_CORPUS_NOTE.format(rule=md_safe(e["rule_id"])))


def _lookup_widget(sk, key: str, limit: int):
    q = st.text_input("Regulatory question", key=f"{key}_q", placeholder="e.g. What is the STR filing deadline?")
    if st.button("Search", key=f"{key}_btn") and q.strip():
        _screen = sk.screen_request(q.strip())
        if not _screen["allowed"]:
            st.error(f"Request refused: {_screen['reason']}")
            return
        try:
            with st.spinner("Cortex Search: looking up the corpus…"):
                res = sk.regulatory_lookup_with_basis(q.strip(), limit=limit)
        except Exception as err:  # noqa: BLE001
            st.error(explained(err, "Regulatory lookup"))
            return
        _render_lookup(res)


def _render_lookup(res: dict):
    if res.get("mode") == "keyword_fallback":
        st.warning("Regulatory search did not answer, so these results come from plain keyword matching. They are not ranked by meaning.")
    for qual in res["qualifications"]:
        st.warning("⚠ **Superseded instrument:** " + md_safe(qual["message"]))
    for s in res["superseded"]:
        st.info(f"Withheld superseded rule **{md_safe(s['rule_id'])}** — replaced by {md_safe(s.get('superseded_by'))}.")
    scope_block = res.get("scope") or {}
    if scope_block.get("status") == "OUT_OF_PERIMETER":
        # label and redirect are fixed strings from skills/scope_guard.py, never the officer's own words
        _abstain(T.ABSTAIN_SCOPE_BODY.format(subject=md_safe(scope_block.get("label") or "that subject"),
                                              redirect=md_safe(scope_block.get("redirect") or "")), T.ABSTAIN_SCOPE_TITLE)
        return
    if scope_block.get("status") == "WEAK_MATCH":
        _abstain(T.ABSTAIN_WEAK_BODY, T.ABSTAIN_WEAK_TITLE)
        if scope_block.get("considered_rule_ids"):
            st.caption(T.ABSTAIN_WEAK_CONSIDERED.format(rules=", ".join(label_safe(i) for i in scope_block["considered_rule_ids"])))
        return
    if not res["rules"]:
        _abstain(T.ABSTAIN_SUPERSEDED_BODY if res.get("superseded") else T.ABSTAIN_LOOKUP_BODY, T.ABSTAIN_LOOKUP_TITLE)
        return
    basis = res["basis"]
    if basis["grade"] == "PROVEN_ONLY":
        st.success("All returned rules are PROVEN (a primary source is cited).")
    else:
        st.warning(md_safe(basis["warning"]))
    if basis.get("unverified_note"):
        st.caption(md_safe(basis["unverified_note"]))
    st.caption(T.LOOKUP_SCOPE_CAPTION)
    for r in res["rules"]:
        ev = r.get("evidence_level", "UNKNOWN")
        icon = EVIDENCE_BADGE.get(ev, ("⚪",))[0]
        with st.expander(f"{icon} {label_safe(r['rule_id'])} — {label_safe(r.get('category', ''))}  [{label_safe(ev)}]", expanded=True):
            review = r.get("review", {})
            html_md(evidence_badge(ev) + "  " + badge((r.get("review_status") or "—"), "#eceff1", "#37474f") + f"  &nbsp; **{esc(r['rule_id'])}**"
                    + (f"  &nbsp; {badge('successor of ' + str(r['surfaced_as_successor_of']), '#e3f2fd', '#0d47a1')}" if r.get("surfaced_as_successor_of") else ""))
            st.markdown(f"**Rule:**  \n{md_safe(r['rule_text'])}")
            if r.get("my_synthesis"):
                st.markdown(f"**PO-lens synthesis (not source text):**  \n_{md_safe(r['my_synthesis'])}_")
            cols = st.columns(4)
            cols[0].markdown(f"**Authority:** {md_safe(r.get('source_authority') or '—')}")
            cols[1].markdown(f"**Source:** {md_safe(r.get('source_document') or '—')}")
            cols[2].markdown(f"**Corpus v{md_safe(r.get('corpus_version') or '—')}** · as of {md_safe(r.get('snapshot_date') or '—')}")
            link = safe_url(r.get("source_url"))
            cols[3].markdown(f"[Primary source link]({link})" if link else ("Source link not shown (not a plain http(s) address)" if r.get("source_url") else "—"))
            st.caption(f"Review: {md_safe(review.get('reason', '—'))} · owner: {md_safe(r.get('owner') or '—')} · URL verified: {'yes' if r.get('source_url_verified') else 'no'}")


def _ai_inference_panel(sk, selected, alert, txns, locked=False):
    with bordered():
        st.caption("Cortex Complete · Labelled suspicion assessment. Optional model output is a proposal, not a fact or the Principal Officer's decision.")
        assessment = _current_assessment(selected)
        if assessment is None:
            if locked:
                st.info(T.HR_AI_LOCKED)
                return
            st.caption("Optional. The model weighs the alert against 11 suspicion factors and each factor's evidence is then checked against the transaction record. "
                       "It usually takes 40–60 seconds.")
            if not txns:
                st.info("The assessment is off: there is no transaction record to check it against.")
                return
            ctx = sk.case_context_for(alert, txns)
            saved_hit = sk.saved_assessment_available(ctx)
            run_live = st.button("Run 11-Factor Assessment", type="primary")
            load_saved = False
            if saved_hit:
                load_saved = st.button(T.SAVED_ASSESSMENT_BUTTON, key=f"saved_assessment_{selected}")
                st.caption(T.SAVED_AVAILABLE.format(when=_when(saved_hit["captured_at"]), model=md_safe(saved_hit["model"])))
            if run_live or load_saved:
                _t0 = time.monotonic()
                try:
                    if load_saved:
                        with sk.replaying():
                            result = sk.suspicion_evaluator(ctx)
                    else:
                        with st.spinner("The AI is weighing 11 factors… usually 40–60 seconds."):
                            result = sk.suspicion_evaluator(ctx)
                except Exception as err:  # noqa: BLE001
                    _model_wait_add(selected, time.monotonic() - _t0)
                    st.session_state[f"ai_failed_{selected}"] = True
                    st.error(T.SAVED_UNAVAILABLE if isinstance(err, SavedResponseUnavailable) else explained(err, "The AI assessment"))
                    return
                _model_wait_add(selected, time.monotonic() - _t0)
                st.session_state.pop(f"ai_failed_{selected}", None)
                st.session_state.update({"poe_assessment": result, "assessed_alert": selected, "case_ctx": ctx,
                                         "assessment_model": sk.last_model_used, "assessment_source": sk.output_source,
                                         "assessment_captured_at": sk.output_captured_at})
                st.rerun()
            if st.session_state.get(f"ai_failed_{selected}"):
                st.caption("The AI was unavailable. You can still decide: it will be recorded as fully human.")
            return

        validity = sk.assessment_validity(assessment)
        if st.button("↻ Re-run", key="rerun_assessment"):
            for key in ("poe_assessment", "assessed_alert", "gos_result", "gos_alert", "assessment_source", "assessment_captured_at"):
                st.session_state.pop(key, None)
            st.rerun()
        if not validity["valid"]:
            st.error("**The AI output was invalid, so its recommendation is withheld.** Nothing from it is shown as a finding. "
                     "Run it again, or decide from the source facts.")
            st.caption(f"What was wrong: {md_safe(validity['error'])}")
            return
        model = st.session_state.get("assessment_model")
        if st.session_state.get("assessment_source") == SOURCE_SAVED:
            st.info(T.SAVED_NOTICE.format(when=_when(st.session_state.get("assessment_captured_at")), model=md_safe(model or "UNKNOWN")))
        elif model:
            st.caption(f"Assessed by `{code_safe(model)}`" + (" — the fallback model, because the primary one failed or timed out." if model != "llama3.3-70b" else "."))

        triggered = [f for f in assessment if f["assessment"] == "triggered"]
        clear = [f for f in assessment if f["assessment"] == "clear"]
        insuff = [f for f in assessment if f["assessment"] == "insufficient_data"]
        summ = sk.evidence_sufficiency_summary(assessment, txns)
        tab_a, tab_g, tab_p = st.tabs(["Assessment", f"Evidence Gaps ({len(insuff)})", "Investigation Plan"])

        with tab_a:
            m1, m2, m3, m4 = st.columns(4)
            m1.metric("Triggered", len(triggered))
            m2.metric("of which grounded", sum(1 for f in triggered if f.get("grounded")))
            m3.metric("Clear", len(clear))
            m4.metric("Insufficient", len(insuff))
            for fac in assessment:
                asmt = fac["assessment"]
                icon = "🔴" if asmt == "triggered" else ("🟢" if asmt == "clear" else "⚪")
                ground = "" if asmt == "insufficient_data" else (" ✅ grounded" if fac.get("grounded") else " ⚠ ungrounded")
                with st.expander(f"{icon} {label_safe(fac['factor_id'])} — {label_safe(fac['factor_name'])}{ground}", expanded=(asmt == "triggered")):
                    st.markdown(f"**Assessment (AI):** `{code_safe(asmt)}`" + (f"  _(downgraded from `{code_safe(fac['normalised_from'])}`: no evidence given)_" if fac.get("normalised_from") else ""))
                    st.markdown(f"**Evidence (AI):** {md_safe(fac['evidence'])}")
                    if fac.get("evidence_txn_ids"):
                        st.markdown("**Verified transaction IDs:** " + ", ".join(f"`{code_safe(i)}`" for i in fac["evidence_txn_ids"]))
                    if fac.get("grounding_issues"):
                        st.warning("Not verifiable in the case record: " + md_safe("; ".join(f"{k}: {v}" for k, v in fac["grounding_issues"].items())))
                    if fac.get("rules_cited"):
                        st.markdown("**Rules cited by the AI:** " + ", ".join(f"`{code_safe(r)}`" for r in fac["rules_cited"]))

            rec = summ["recommendation"]
            rec_bg = {"FILE": ("#ffebee", "#c62828", "FILE"), "REVIEW": ("#fff8e1", "#e65100", "REVIEW — further evidence needed"),
                      "INSUFFICIENT_EVIDENCE": ("#e8eaf6", "#283593", "INSUFFICIENT EVIDENCE — cannot recommend"),
                      "NOT_FILE": ("#e8f5e9", "#2e7d32", "NOT FILE")}.get(rec, ("#f5f5f5", "#333", rec))
            ungrounded = len(summ.get("ungrounded_triggered", []))
            html_md(f'<div style="background:{rec_bg[0]};border-left:4px solid {rec_bg[1]};padding:12px 16px;border-radius:4px;margin:8px 0">'
                    f'<span style="color:{rec_bg[1]};font-weight:700;font-size:1.05em">AI Recommendation: {esc(rec_bg[2])}</span><br>'
                    f'<span style="font-size:0.85em;color:#555">Based on {int(summ["triggered_count"])} triggered factor(s) '
                    f'({ungrounded} ungrounded, not counted for FILE) and {int(summ["insufficient_count"])} gap(s). '
                    f'The Principal Officer must form an independent view.</span></div>')
            for dn in summ.get("discounted_nexus_factors") or []:
                st.caption(f"Not counted toward FILE · {label_safe(dn['factor_id'])} {label_safe(dn.get('factor_name') or '')}: the model triggered it, but the case record "
                           f"does not back it ({md_safe(dn['reason'])}). Product policy, not a regulatory rule.")
            with st.expander("What would change this recommendation?"):
                if rec == "FILE":
                    st.markdown("Would change to **REVIEW** / **NOT FILE** if: documented proof of source of funds explains the pattern; "
                                "the beneficiary is removed from the I4C Suspect Registry; prior similar transactions have legitimate explanations on file; "
                                "or KYC shows a declared activity consistent with the credits.")
                elif rec == "INSUFFICIENT_EVIDENCE":
                    st.markdown("Would change to **FILE** / **NOT FILE** once the evidence gaps are resolved (KYC obtained, source of funds documented).")
                else:
                    st.markdown("Would change to **FILE** if: a similar pattern is found across linked accounts; the beneficiary appears on a watchlist; "
                                "or new information contradicts the documented explanation.")

        with tab_g:
            if not insuff:
                st.success("Every factor had enough data to assess.")
            else:
                if summ["recommendation"] == "INSUFFICIENT_EVIDENCE":
                    st.warning(f"{len(insuff)} factor(s) lack the data needed to form a defensible view. Obtain it before deciding.")
                for gap in summ["gaps"]:
                    st.markdown(f"- **{md_safe(gap['factor_id'])} ({md_safe(gap['factor_name'])}):** {md_safe(gap['evidence'])}")

        with tab_p:
            st.caption("Deterministic investigative steps derived from the triggered factors. The PO conducts each step and forms their own view.")
            t_ids, i_ids = {f["factor_id"] for f in triggered}, {f["factor_id"] for f in insuff}
            plan = []
            if t_ids & {"POE-002", "POE-005"}:
                plan.append("Verify declared occupation/income against payroll records or tax filings.")
            if "POE-003" in t_ids:
                plan.append("Pull 12-month account statement; identify prior similar high-velocity periods.")
            if "POE-006" in t_ids:
                plan.append("Request documentary proof of source of funds (invoice, contract, bank confirmation) for each credit.")
            if "POE-007" in t_ids:
                plan.append("Run beneficiary counterparties through the I4C Suspect Registry and internal watchlists.")
            if "POE-008" in t_ids:
                plan.append("Check whether the same burst-frequency pattern appears in prior periods or linked accounts.")
            if "POE-011" in t_ids:
                plan.append("Verify the SWIFT correspondent chain; check FATF grey/black-list status of intermediaries.")
            if "POE-012" in i_ids:
                plan.append("Obtain current KYC: re-verify identity documents, address and Aadhaar linkage before filing.")
            for item in plan or ["No specific investigative steps required for the current triggered factors."]:
                st.markdown(f"- {md_safe(item)}")


# ── page: Decision Ledger ─────────────────────────────────────────────────────
def page_ledger():
    st.header("Decision archive")
    st.markdown("Append-only audit trail", help="Enforced by the database: the app role has INSERT+SELECT only "
                "(deploy/03_grants.sql, proven by deploy/04_verify_ledger_rbac.sql). Each row carries a SHA-256 ROW_HASH.")
    rows, err = query("""
        SELECT d.DECISION_ID, d.ALERT_ID, d.CUSTOMER_REF, d.DISPOSITION, d.DECISION_MAKER_ID, d.SUSPICION_FORMED_AT,
               d.DECISION_MADE_AT, d.SLA_DAYS_REMAINING, d.STR_REFERENCE, d.RATIONALE_TEXT, i.INTEGRITY_STATUS,
               a.ALERT_TYPE, a.CUSTOMER_PROFILE, a.ALERT_AMOUNT_INR
        FROM FIU_COPILOT.AML.DECISION_LEDGER d
        LEFT JOIN FIU_COPILOT.AML.DECISION_LEDGER_INTEGRITY_V i ON i.DECISION_ID = d.DECISION_ID
        LEFT JOIN FIU_COPILOT.AML.ALERTS_CURRENT a ON d.ALERT_ID = a.ALERT_ID
        ORDER BY d.DECISION_MADE_AT DESC
    """, area="The decision ledger")
    if err:
        db_error(err)
        return
    if not rows:
        st.info(T.EMPTY_LEDGER)
        return

    filed = sum(1 for r in rows if r["DISPOSITION"] == "FILE")
    no_file = sum(1 for r in rows if r["DISPOSITION"] == "NOT_FILE")
    overdue = sum(1 for r in rows if (r["SLA_DAYS_REMAINING"] if r["SLA_DAYS_REMAINING"] is not None else 99) < 0)
    ratio = round(filed * 100 / (filed + no_file), 1) if (filed + no_file) else 0.0
    integ = {}
    for r in rows:
        integ[r["INTEGRITY_STATUS"] or "UNKNOWN"] = integ.get(r["INTEGRITY_STATUS"] or "UNKNOWN", 0) + 1
    c1, c2, c3, c4, c5 = st.columns(5)
    c1.metric("Total decisions", len(rows))
    c2.metric("FILE", filed)
    c3.metric("NOT_FILE", no_file)
    c4.metric("Alert-to-STR ratio", f"{ratio}%", help="Internal governance metric; no FIU-IND benchmark published (DG-04).")
    c5.metric("Overdue (SLA < 0)", overdue, delta=f"-{overdue}" if overdue else None, delta_color="inverse")
    if integ.get("TAMPERED"):
        st.error(T.INTEGRITY_TAMPERED.format(n=integ["TAMPERED"]))
    else:
        st.success(f"Ledger integrity: {integ.get('INTACT', 0)} row(s) hash-verified INTACT · 0 TAMPERED"
                   + (" · " + T.INTEGRITY_LEGACY.format(n=integ["LEGACY_UNHASHED"]) if integ.get("LEGACY_UNHASHED") else ""))
    _render_reconciliation()
    st.divider()

    target_reconstruction = st.session_state.pop("reconstruct_decision_id", None)
    for r in rows:
        sla = r["SLA_DAYS_REMAINING"]
        integrity = r["INTEGRITY_STATUS"] or "UNKNOWN"
        open_target = target_reconstruction == r["DECISION_ID"]
        with st.expander(f"{label_safe(r['ALERT_ID'])} [{label_safe(r['DISPOSITION'])}] · {label_safe(r['DECISION_MAKER_ID'])} · "
                         f"{label_safe(str(r['DECISION_MADE_AT'])[:16])} · {label_safe(integrity)}", expanded=open_target):
            html_md(disp_badge(r["DISPOSITION"]) + "  " + badge(integrity, {"INTACT": "#e8f5e9", "TAMPERED": "#ffebee"}.get(integrity, "#eceff1"),
                                                             {"INTACT": "#2e7d32", "TAMPERED": "#c62828"}.get(integrity, "#455a64")))
            col1, col2, col3 = st.columns(3)
            with col1:
                st.markdown(f"**Decision ID:** `{code_safe(r['DECISION_ID'])}`  \n**Customer:** `{code_safe(r['CUSTOMER_REF'])}`  \n"
                            f"**STR reference:** `{code_safe(r.get('STR_REFERENCE') or '—')}`")
            with col2:
                st.markdown(f"**Suspicion formed:** {md_safe(str(r.get('SUSPICION_FORMED_AT') or '—')[:19])}  \n"
                            f"**Decision made:** {md_safe(str(r.get('DECISION_MADE_AT') or '—')[:19])}  \n**SLA days remaining at decision:** {md_safe(sla)}")
            with col3:
                st.caption("Current alert context — not a historical snapshot")
                amt = r.get("ALERT_AMOUNT_INR")
                st.markdown(f"**Alert type:** {md_safe(r.get('ALERT_TYPE') or '—')}  \n" + (f"**Amount:** ₹{float(amt):,.0f}  \n" if amt else "")
                            + f"**Customer profile:** {md_safe(str(r.get('CUSTOMER_PROFILE') or '—')[:100])}")
            st.markdown("**Rationale text (as recorded):**")
            st.text(r.get("RATIONALE_TEXT") or "—")
            if open_target:
                st.success("Opened from the decision-record completion summary.")
                _render_reconstruction(r["DECISION_ID"])
            elif toggle("Reconstruct this decision", key=f"rc_{r['DECISION_ID']}"):
                _render_reconstruction(r["DECISION_ID"])


def _render_export_protection(st_: dict):
    """Is audit-export protection provisioned and current, and is there an independent write-once copy? Never says the ledger is immutable."""
    label = {aud.STATUS_NOT_PROVISIONED: "NOT PROVISIONED", aud.STATUS_BEHIND: "BEHIND", aud.STATUS_CURRENT: "CURRENT", aud.STATUS_CHAIN_BROKEN: "CHAIN BROKEN"}[st_["level"]]
    box = {aud.STATUS_CHAIN_BROKEN: st.error, aud.STATUS_NOT_PROVISIONED: st.warning, aud.STATUS_BEHIND: st.warning, aud.STATUS_CURRENT: st.success}[st_["level"]]
    box(f"**Audit-export protection: {label}.** {md_safe(st_['headline'])} {md_safe(st_['detail'])}")
    st.caption(f"External write-once copy: **{md_safe(st_['external'].replace('_', ' ').lower())}**. {md_safe(st_['external_detail'])}")
    with st.expander("Residual risk, and what a write-once copy requires", expanded=False):
        st.markdown(md_safe(st_["residual_risk"]))
        for req in st_["worm_requirements"]:
            st.markdown(f"- {md_safe(req)}")


def _render_reconciliation():
    """Read-only reconciliation of the whole ledger (and of the audit export, when one exists) — see skills/audit.py."""
    try:
        rep = get_skills().ledger_reconciliation()
    except Exception as err:  # noqa: BLE001
        st.warning(explained(err, "The ledger check"))
        return
    counts = ", ".join(f"{n} {k}" for k, n in sorted(rep["by_integrity"].items()))
    msg = f"**Ledger reconciliation: {md_safe(rep['verdict'])}** — {rep['ledger_rows']} row(s): {md_safe(counts or 'none')}"
    {"COMPROMISED": st.error, "ATTENTION": st.warning, "CONSISTENT": st.success}.get(rep["verdict"], st.info)(msg)
    for f in rep["findings"]:
        st.markdown(f"- `{code_safe(f['code'])}` × {f['count']} — {md_safe(f['detail'])}")
    _render_export_protection(aud.export_protection_status(rep, now=datetime.now(timezone.utc)))
    a = rep["anchor"]
    if a["present"]:
        st.caption(f"Audit export: {a['records']} record(s), chain {'valid' if a['chain_valid'] else 'BROKEN'} — deletion of exported rows is detectable.")
    else:
        st.caption(f"Audit export: none ({md_safe(a.get('reason'))}). **Deletion of ledger rows by the owner role would NOT be detected** — see DEPLOY.md, audit export.")
    with st.expander("What this check can and cannot show"):
        for limit in rep["limits"]:
            st.markdown(f"- {md_safe(limit)}")


# ── page: Dashboard ───────────────────────────────────────────────────────────
def _review_monitoring_panel():
    """Phase 5 — a READ-ONLY, programme-level view of independent-review health for second-line / model-risk review.
    Flag-gated; not a default frontline dashboard. Never a per-officer scorecard (skills/review_monitor.py)."""
    st.divider()
    st.subheader("Independent-review monitoring · second-line")
    st.caption(rvm.DISCLAIMER)
    rows, err = query("SELECT DISPOSITION, TO_JSON(METADATA_JSON) AS META_TEXT FROM FIU_COPILOT.AML.DECISION_LEDGER", area="Review monitoring")
    if err:
        db_error(err)
        return
    if not rows:
        st.info(T.EMPTY_LEDGER)
        return
    out = rvm.summarise_reviews(rows)
    g, labels = out["groups"]["all"], out["metric_labels"]
    st.markdown(f"**{g['total_decisions']} recorded decision(s).** Read each figure with its caveat; drift is a prompt to sample and review by hand, not a conclusion.")

    def _line(key):
        m = g[key]
        val = "—" if m.get("rate") is None else f"{m['rate'] * 100:.0f}% ({m['numerator']}/{m['denominator']})"
        html_md(f"<div style='padding:4px 0'><b>{esc(labels[key])}:</b> {esc(val)}"
                f"<div style='opacity:.7;font-size:.85em'>{esc(m['caveat'])}</div></div>")

    for key in ("with_review_rate", "reconciliation_completion_rate", "differ_from_ai_rate", "provisional_to_final_revision_rate",
                "flagged_transaction_closure_rate", "accepted_innocent_explanation_rate", "unsupported_closure_rate",
                "unsupported_filing_rate", "unresolved_gap_rate", "missing_review_provenance_rate"):
        _line(key)
    nv = g["near_verbatim_adoption"]
    nv_val = f"{nv['mean_overlap_pct']}% over {nv['measured']} measured, {nv['deferred']} deferred" if nv["measured"] else f"none measured, {nv['deferred']} deferred"
    html_md(f"<div style='padding:4px 0'><b>{esc(labels['near_verbatim_adoption'])}:</b> {esc(nv_val)}"
            f"<div style='opacity:.7;font-size:.85em'>{esc(nv['caveat'])}</div></div>")


def page_dashboard():
    st.header("Inspection Readiness Dashboard")
    st.caption("Key metrics FIU-IND inspectors focus on")

    alerts_rows, err = query("SELECT ALERT_STATUS, ALERT_TYPE, SIGNAL_SOURCE, ALERT_AMOUNT_INR::FLOAT AS ALERT_AMOUNT_INR FROM FIU_COPILOT.AML.ALERTS_CURRENT", area="The dashboard figures")
    ledger_rows, err2 = query("SELECT DISPOSITION, SLA_DAYS_REMAINING, DECISION_MADE_AT FROM FIU_COPILOT.AML.DECISION_LEDGER", area="The dashboard figures")
    if err or err2:
        db_error(err or err2)
    else:
        open_a = sum(1 for r in alerts_rows if r["ALERT_STATUS"] in ("OPEN", "DEFERRED"))
        reviewed = sum(1 for r in alerts_rows if r["ALERT_STATUS"] == "REVIEWED")
        filed = sum(1 for r in ledger_rows if r["DISPOSITION"] == "FILE")
        not_filed = sum(1 for r in ledger_rows if r["DISPOSITION"] == "NOT_FILE")
        deferred = sum(1 for r in ledger_rows if r["DISPOSITION"] == "DEFERRED")
        overdue = sum(1 for r in ledger_rows if (r["SLA_DAYS_REMAINING"] if r["SLA_DAYS_REMAINING"] is not None else 99) < 0)
        ratio = round(filed * 100 / (filed + not_filed), 1) if (filed + not_filed) else None

        st.subheader("Alert Pipeline")
        c1, c2, c3, c4 = st.columns(4)
        c1.metric("Open / deferred", open_a)
        c2.metric("Reviewed", reviewed)
        c3.metric("Filed (STR)", filed)
        c4.metric("Not Filed", not_filed)
        st.subheader("Key FIU-IND Inspection Metrics")
        m1, m2, m3 = st.columns(3)
        m1.metric("Alert-to-STR Ratio", f"{ratio}%" if ratio is not None else "—",
                  help="Internal governance metric (no FIU-IND benchmark published — Gap DG-04). Too low = suppression risk; too high = over-filing.")
        m2.metric("SLA Breaches (>7 WD)", overdue, delta=f"{overdue} overdue" if overdue else None, delta_color="inverse")
        m3.metric("Deferred / Pending Info", deferred)
        st.divider()
        st.subheader("Alert Breakdown by Type")
        type_counts: dict[str, int] = {}
        for r in alerts_rows:
            t = r["ALERT_TYPE"].replace("_", " ").title()
            type_counts[t] = type_counts.get(t, 0) + 1
        if type_counts:
            st.bar_chart(data=dict(sorted(type_counts.items(), key=lambda x: -x[1])), use_container_width=True, height=300)
        st.subheader("Signal Source Mix")
        src: dict[str, int] = {}
        for r in alerts_rows:
            src[r.get("SIGNAL_SOURCE") or "UNKNOWN"] = src.get(r.get("SIGNAL_SOURCE") or "UNKNOWN", 0) + 1
        for name, cnt in sorted(src.items(), key=lambda x: -x[1]):
            st.markdown(f"`{code_safe(name)}` — {cnt} alerts ({cnt * 100 // len(alerts_rows) if alerts_rows else 0}%)")

    if hr.enabled():
        _review_monitoring_panel()

    st.divider()
    st.subheader("Ask the data (Cortex Analyst)")
    st.caption("Plain-English questions about the alerts, the recorded decisions and the transactions. Cortex Analyst turns the question into a query, which runs "
               "read-only under this app's role. The query is available to inspect under each answer.")
    analyst_q = st.text_input("Type a question about the alert pipeline", placeholder="How many alerts were filed as STR this quarter?", key="analyst_question")
    if st.button("Ask", key="analyst_ask") and analyst_q.strip():
        _screen = get_skills().screen_request(analyst_q.strip())
        if not _screen["allowed"]:
            st.error(f"Request refused: {_screen['reason']}")
        else:
            with st.spinner("Cortex Analyst: generating SQL…"):
                result = get_analyst().ask(analyst_q.strip())
            if not result.get("available"):
                st.error(explained(RuntimeError((result.get("warnings") or ["no detail"])[0]), "Ask the data") +
                         " The figures above are computed directly from the tables and are not affected.")
            else:
                if result.get("interpretation"):
                    st.markdown(md_safe(result["interpretation"]))
                if result.get("generated_sql"):
                    with st.expander("Generated SQL", expanded=False):
                        st.code(result["generated_sql"], language="sql")
                if result.get("rows") is not None:
                    if result["rows"]:
                        import pandas as pd
                        st.dataframe(pd.DataFrame(result["rows"]), use_container_width=True)
                    else:
                        st.info("Query returned no rows.")
                elif result.get("generated_sql"):
                    st.info("SQL generated but not executed (see warnings).")
                for w in result.get("warnings", []):
                    st.warning(md_safe(w))
                notes = result.get("analyst_notes") or []
                if notes:
                    with st.expander(f"Analyst notes about the semantic model ({len(notes)})", expanded=False):
                        st.caption("Advisories from Cortex Analyst about how the semantic model is written — not about your question or this result.")
                        for note in notes:
                            st.text(note)
    st.divider()
    st.caption("Alert-to-STR ratio is an internal governance metric. No official FIU-IND benchmark has been publicly confirmed (Gap DG-04).")


# ── page: Regulatory Reference ────────────────────────────────────────────────
def page_regulatory():
    st.header("Regulatory Reference")
    st.caption("Cortex Search over the FIU-IND AML corpus — PROVEN + ASSUMED only, PROVEN first, superseded rules handled deterministically")
    sk = get_skills()
    summary = cached_corpus_summary()
    if summary.get("error"):
        st.error("The regulatory corpus is unavailable. The copilot abstains from regulatory guidance until it is back. Tell your administrator.")
        return
    if not summary["total"]:
        st.info(T.EMPTY_CORPUS)
        return
    st.info(f"Corpus **v{md_safe(summary['version'])}** · snapshot {md_safe(summary['snapshot_date'])} · {md_safe(summary['proven'])} PROVEN · "
            f"{md_safe(summary['assumed'])} ASSUMED · {md_safe(summary['needs_verification'])} NEEDS-VERIFICATION (excluded) · "
            f"**{md_safe(summary['verified'])} independently verified** — "
            "PROVEN means a primary source is cited by the corpus author, not that it was re-checked.")
    query_text = st.text_input("Ask a regulatory question", placeholder="e.g. What is the STR filing deadline? / What are the CTR obligations?")
    limit = st.number_input("Max results", min_value=1, max_value=10, value=5)
    if query_text:
        _screen = sk.screen_request(query_text)
        if not _screen["allowed"]:
            st.error(f"Request refused: {_screen['reason']}")
        else:
            try:
                with st.spinner("Cortex Search: looking up the corpus…"):
                    res = sk.regulatory_lookup_with_basis(query_text, limit=int(limit))
            except Exception as err:  # noqa: BLE001
                st.error(explained(err, "Regulatory lookup"))
            else:
                _render_lookup(res)

    st.divider()
    st.subheader("Key rules quick-reference")
    quick, err = query("""
        SELECT RULE_ID, SUBCATEGORY, LEFT(RULE_TEXT, 100) AS RULE_PREVIEW, EVIDENCE_LEVEL, REVIEW_STATUS
        FROM FIU_COPILOT.AML.REGULATORY_CORPUS
        WHERE RULE_ID IN ('STR-001','STR-002','CTR-001','INS-001','INS-003','SB-002') AND SUPERSEDED_BY IS NULL
        ORDER BY EVIDENCE_LEVEL, RULE_ID
    """, area="The quick reference")
    if err:
        db_error(err)
    for r in quick:
        html_md(f"{EVIDENCE_BADGE.get(r['EVIDENCE_LEVEL'], ('⚪',))[0]} **{esc(r['RULE_ID'])}** — {esc(r['SUBCATEGORY'])}  <br>"
                f"{esc(r['RULE_PREVIEW'])}…  {evidence_badge(r['EVIDENCE_LEVEL'])} {badge(r.get('REVIEW_STATUS') or '—', '#eceff1', '#37474f')}")
        st.markdown("")


# ── page: Corpus governance ───────────────────────────────────────────────────
def _items_df(items: list[dict], columns: list[tuple[str, str]]):
    import pandas as pd
    return pd.DataFrame([{label: (i.get(key) if i.get(key) is not None else "—") for label, key in columns} for i in items])


def page_corpus_governance():
    st.header("Corpus governance")
    st.caption("The lifecycle of every regulatory rule: source, authority, effective date, last review, last independent verification, owner, review SLA, supersession and approval. "
               "Read-only. It reports what the data proves; it never edits a rule.")
    try:
        rows, info = get_skills().corpus_lifecycle_rows()
    except Exception as err:  # noqa: BLE001
        db_error(explained(err, "The corpus governance report"))
        return
    if not rows:
        st.info(T.EMPTY_CORPUS)
        return
    rep = cl.governance_report(rows, datetime.now(IST).date())
    c = rep["counts"]
    st.info(md_safe(rep["statement"]) + " " + md_safe(rep["exclusion_statement"]))
    if not info["lifecycle_columns"]:
        st.warning("The lifecycle columns (last reviewed, review SLA, approval) are not in the live table yet, so they read as not provisioned: every rule shows as never reviewed "
                   "and unapproved. Apply the migration in domain/corpus/export/ddl/regulatory_corpus.sql (DEPLOY.md).")
    m = st.columns(5)
    m[0].metric("Rules", rep["total"])
    m[1].metric("Independently verified", c["independently_verified"], help="Declared VERIFIED, with a date, a named verifier who is not the rule's owner, within the review SLA.")
    m[2].metric("Requiring review", c["requiring_review"])
    m[3].metric("Superseded", c["superseded"])
    m[4].metric("Excluded from conclusions", c["excluded_from_conclusions"], help="NEEDS-VERIFICATION and superseded rules never bear a legal or regulatory conclusion.")
    m2 = st.columns(5)
    m2[0].metric("Never reviewed", c["never_reviewed"])
    m2[1].metric("Review overdue", c["review_overdue"])
    m2[2].metric("Source URL not verified", c["source_url_not_verified"])
    m2[3].metric("Stale verification", c["stale_verification"])
    m2[4].metric("Approved", c["approved"], help="Approval needs approved_by and approved_on.")
    tabs = st.tabs([f"Requiring review ({len(rep['requiring_review'])})", f"Superseded ({len(rep['superseded'])})", f"Unverified sources ({len(rep['unverified_sources'])})",
                    f"Stale ({len(rep['stale'])})", f"Excluded ({len(rep['excluded'])})", "All rules", "Lifecycle fields"])
    cols_review = [("Rule", "rule_id"), ("Weight", "evidence_level"), ("Why", "reason"), ("Due on", "due_on"), ("Owner", "owner")]
    with tabs[0]:
        st.caption("Never reviewed, overdue or due within 30 days. Rules that are NEEDS-VERIFICATION are listed first: they are excluded until someone verifies them.")
        st.dataframe(_items_df(rep["requiring_review"], cols_review), hide_index=True, use_container_width=True) if rep["requiring_review"] else st.success("No rule requires review.")
    with tabs[1]:
        st.caption("A superseded rule is never returned as current and never counts as a basis; its successor is pinned.")
        st.dataframe(_items_df(rep["superseded"], [("Rule", "rule_id"), ("Superseded by", "superseded_by"), ("Weight", "evidence_level")]), hide_index=True, use_container_width=True) if rep["superseded"] else st.info("No rule is superseded in this corpus.")
        if rep["replacing"]:
            st.markdown("**Rules that replace an instrument**")
            st.dataframe(_items_df(rep["replacing"], [("Rule", "rule_id"), ("Replaces", "replaces")]), hide_index=True, use_container_width=True)
    with tabs[2]:
        st.caption("A source is unverified when its URL was never confirmed live, or the rule was never independently verified.")
        st.dataframe(_items_df(rep["unverified_sources"], cols_review), hide_index=True, use_container_width=True) if rep["unverified_sources"] else st.success("Every source is verified.")
    with tabs[3]:
        st.dataframe(_items_df(rep["stale"], cols_review), hide_index=True, use_container_width=True) if rep["stale"] else st.info("No rule is past its review SLA or carries an out-of-date verification.")
    with tabs[4]:
        st.caption(md_safe(rep["exclusion_statement"]))
        st.dataframe(pd_excluded(rep["excluded"]), hide_index=True, use_container_width=True) if rep["excluded"] else st.info("No rule is excluded.")
    with tabs[5]:
        st.dataframe(_items_df(rep["rules"], [("Rule", "rule_id"), ("Weight", "evidence_level"), ("Authority", "source_authority"), ("Source URL", "source_url"), ("URL verified", "source_url_verified"),
                                              ("Effective", "effective_date"), ("As of", "snapshot_date"), ("Last reviewed", "last_reviewed"), ("Last verified", "last_verified"),
                                              ("Verified by", "verified_by"), ("Owner", "owner"), ("Review SLA (days)", "review_sla_days"), ("Review due", "review_due_on"),
                                              ("Review", "review_state"), ("Verification", "verification"), ("Approval", "approval_status"), ("Superseded by", "superseded_by"),
                                              ("Replaces", "replaces"), ("Usable for a conclusion", "usable_for_conclusion")]), hide_index=True, use_container_width=True)
    with tabs[6]:
        import pandas as pd
        st.dataframe(pd.DataFrame([{"Field": k, "Available in this table": "yes" if v["provisioned"] else "NO — column not present", "Rules with a value": v["populated"]}
                                   for k, v in rep["field_coverage"].items()]), hide_index=True, use_container_width=True)


def pd_excluded(excluded: list[dict]):
    import pandas as pd
    return pd.DataFrame([{"Rule": e["rule_id"], "Why excluded": ", ".join(e["reasons"])} for e in excluded])


# ── page: Model quality ───────────────────────────────────────────────────────
def page_model_quality():
    st.header("Model quality and feedback")
    st.info(fbk.CALIBRATION_POLICY)
    st.caption(fbk.DISCLAIMER)
    rows, err = query("SELECT DISPOSITION, ALERT_ID, DECISION_MADE_AT, TO_JSON(METADATA_JSON) AS META_TEXT FROM FIU_COPILOT.AML.DECISION_LEDGER", area="The feedback figures")
    if err:
        db_error(err)
        return
    if not rows:
        st.info(T.EMPTY_LEDGER)
        return
    try:
        outcomes = sql(fbk.OUTCOMES_SQL)
    except Exception:  # noqa: BLE001 - the outcome feed is opt-in; its absence is a stated state, not an error
        outcomes = None
    out = fbk.summarise_feedback(rows, outcomes)
    g, labels = out["groups"]["all"], out["metric_labels"]
    st.markdown(f"**{g['total_decisions']} recorded decision(s)**" + (f", {g['decisions_without_provenance']} without provenance (older rows; excluded from AI figures)." if g["decisions_without_provenance"] else "."))

    def _line(key):
        m = g[key]
        val = "—" if m.get("rate") is None else f"{m['rate'] * 100:.0f}% ({m['numerator']}/{m['denominator']})"
        html_md(f"<div style='padding:4px 0'><b>{esc(labels[key])}{' (proxy)' if m.get('is_proxy') else ''}:</b> {esc(val)}<div style='opacity:.7;font-size:.85em'>{esc(m['caveat'])}</div></div>")
    for key in ("ai_agreement_rate", "override_rate", "unsupported_claim_rate_officer", "unsupported_claim_rate_ai", "false_positive_proxy_rate", "rework_rate", "closure_reason_stated_rate"):
        _line(key)
    st.markdown("**Recurring evidence gaps**")
    gaps = g["recurring_evidence_gaps"]
    for item in gaps["ai_factor_gaps"]:
        st.markdown(f"- AI factor gap `{code_safe(item['factor_id'])}` — in {item['decisions']} decision(s)")
    for item in gaps["record_quality_findings"]:
        st.markdown(f"- Record issue `{code_safe(item['code'])}` — in {item['decisions']} decision(s)")
    if not gaps["ai_factor_gaps"] and not gaps["record_quality_findings"]:
        st.caption("No recurring gap is recorded yet.")
    st.caption(gaps["caveat"])
    if g["closure_reason_mix"]:
        st.markdown("**Closure and deferral reasons (structured)**")
        for code, n in g["closure_reason_mix"].items():
            st.markdown(f"- `{code_safe(code)}` — {n}")
    o = g["outcomes"]
    st.markdown("**Downstream outcomes**")
    if not o["available"]:
        st.caption(md_safe(o["reason"]))
    else:
        st.markdown(f"{o['decisions_with_outcome']} decision(s) have an outcome: " + md_safe(", ".join(f"{k} × {v}" for k, v in o["by_type"].items()) or "none"))
        for key in ("outcome_rework", "qa_confirmed_closure_rate"):
            m = o[key]
            st.caption(f"{key.replace('_', ' ')}: {'—' if m['rate'] is None else str(round(m['rate'] * 100)) + '% (' + str(m['numerator']) + '/' + str(m['denominator']) + ')'} — {md_safe(m['caveat'])}")


# ── page: Business value ──────────────────────────────────────────────────────
def page_business_value():
    import pandas as pd
    st.header("Business value and KPIs")
    st.warning(kpi.CLAIMS_POLICY)
    ledger_rows, err = query("SELECT DISPOSITION, ALERT_ID, DECISION_MADE_AT, SUSPICION_FORMED_AT, SLA_DAYS_REMAINING, TO_JSON(METADATA_JSON) AS META_TEXT "
                             "FROM FIU_COPILOT.AML.DECISION_LEDGER", area="The KPI figures")
    alert_rows, err2 = query("SELECT ALERT_ID, ALERT_DATE, ALERT_STATUS, ALERT_TYPE, SIGNAL_SOURCE, ALERT_AMOUNT_INR, CUSTOMER_REF, CUSTOMER_PROFILE, ALERT_NARRATIVE, ACCOUNT_TYPE "
                             "FROM FIU_COPILOT.AML.ALERTS_CURRENT", area="The KPI figures")
    if err or err2:
        db_error(err or err2)
        return
    (all_txns, all_owners), txn_err = load_all_txns()
    open_quality = None if txn_err else [eq.assess(a, all_txns.get(a["ALERT_ID"], []), now=datetime.now(timezone.utc), txn_owners=all_owners.get(a["ALERT_ID"]))
                                         for a in alert_rows if a.get("ALERT_STATUS") != "REVIEWED"]
    try:
        outcomes = sql(fbk.OUTCOMES_SQL)
    except Exception:  # noqa: BLE001
        outcomes = None
    rep = kpi.compute_kpis(ledger_rows, alert_rows, outcomes=outcomes, open_case_quality=open_quality)
    st.caption("Every figure carries its status. A KPI that cannot be measured says what it needs; nothing is estimated to fill the gap.")
    for status in (kpi.MEASURED, kpi.PROXY, kpi.SYNTHETIC_LABELS, kpi.NOT_MEASURED):
        items = [k for k in rep["kpis"] if k["status"] == status]
        if not items:
            continue
        st.markdown(f"##### {status.replace('_', ' ').title()} ({len(items)})")
        st.caption(kpi.STATUS_MEANING[status])
        st.dataframe(pd.DataFrame([{"KPI": k["name"], "Value": k["display"], "n": str(k["n"]) if k["n"] is not None else "—", "Definition": k["definition"], "Source": k["source"],
                                    "Caveat": k["caveat"], "Needs": k["needs"] or "—"} for k in items]), hide_index=True, use_container_width=True)
    st.divider()
    st.subheader("Simulated illustration")
    st.caption("Off by default. These are not measurements; they show the shape of the dashboard once hands-on timing and adjudicated labels exist.")
    if toggle("Show a simulated illustration (not data)", key="kpi_sim"):
        sim = kpi.simulated_cohort()
        st.error(sim["notice"])
        st.dataframe(pd.DataFrame([{"KPI": k["name"], "Value": k["display"], "Status": k["status"]} for k in sim["kpis"]]), hide_index=True, use_container_width=True)


# ── page: Architecture and readiness ──────────────────────────────────────────
TIER_STYLE = {rdy.IMPLEMENTED: ("#2e7d32", "IMPLEMENTED"), rdy.SIMULATED: ("#9a600a", "SIMULATION"), rdy.PRODUCTION: ("#546e7a", "PRODUCTION REQUIREMENT")}


def page_architecture():
    import pandas as pd
    st.header("Architecture and readiness")
    st.info(T.POSITIONING_IS)
    st.caption(T.POSITIONING_IS_NOT)
    st.caption(T.POSITIONING_FLOW)
    sm = rdy.summary()
    cols = st.columns(3)
    for col, tier in zip(cols, rdy.TIERS):
        col.metric(rdy.TIER_LABEL[tier], sm["capabilities"][tier] + sm["checklist"][tier] + sm["architecture"][tier], help=rdy.TIER_MEANING[tier])
    tabs = st.tabs(["Reference architecture", "Implemented · simulated · production", "Security and privacy readiness", "Scale", "Known limitations and roadmap"])
    with tabs[0]:
        st.caption("Low-latency deterministic stages are separated from the slow, on-demand AI stage. A stage marked PRODUCTION REQUIREMENT or SIMULATION is not built as shown.")
        for stage in rdy.ARCHITECTURE_STAGES:
            color, label = TIER_STYLE[stage["status"]]
            html_md(f'<div class="arch-stage" style="border-left-color:{color}"><strong>{stage["n"]}. {esc(stage["name"])}</strong> &nbsp; {badge(label, color + "22", color)}'
                    f'<small><b>Latency class:</b> {esc(stage["latency"])}</small><small><b>In this prototype:</b> {esc(stage["prototype"])}</small>'
                    f'<small><b>In production:</b> {esc(stage["production"])}</small></div>')
        st.caption("Deterministic alerting and scoring answer in milliseconds to seconds. AI investigation is on demand, takes tens of seconds to minutes, and is optional: the officer can decide without it.")
    with tabs[1]:
        show = st.radio("Show", ["All"] + [rdy.TIER_LABEL[t] for t in rdy.TIERS], horizontal=True, key="arch_tier")
        items = [c for c in rdy.CAPABILITIES if show == "All" or rdy.TIER_LABEL[c["status"]] == show]
        st.dataframe(pd.DataFrame([{"ID": c["id"], "Area": c["area"], "Capability": c["capability"], "Status": rdy.TIER_LABEL[c["status"]], "Evidence": c["evidence"] or "—", "Where": c["where"] or "—",
                                    "Simulated by": c["simulated_by"] or "—", "Production needs": c["production"] or "—", "Limits": c["limits"] or "—"} for c in items]),
                     hide_index=True, use_container_width=True)
    with tabs[2]:
        st.warning("Production requirements. None of these is an account control this repository can enforce; the right-hand column is what a deployment needs before any real data (SECURITY.md §8).")
        st.dataframe(pd.DataFrame([{"Control": c["control"], "Status": rdy.TIER_LABEL[c["status"]], "Today": c["today"], "Production needs": c["production"], "Evidence": c["evidence"] or "—"} for c in rdy.PRODUCTION_CHECKLIST]),
                     hide_index=True, use_container_width=True)
    with tabs[3]:
        st.dataframe(pd.DataFrame([{"Topic": x["topic"], "Prototype": x["prototype"], "At scale": x["approach"]} for x in rdy.SCALABILITY]), hide_index=True, use_container_width=True)
    with tabs[4]:
        st.markdown("**Known limitations**")
        for line in rdy.KNOWN_LIMITATIONS:
            st.markdown(f"- {md_safe(line)}")
        st.markdown("**Prioritised roadmap of what is intentionally not built**")
        st.dataframe(pd.DataFrame([{"Priority": r["priority"], "Item": r["item"], "Why": r["why"]} for r in rdy.ROADMAP]), hide_index=True, use_container_width=True)


# ── main shell ────────────────────────────────────────────────────────────────
def main():
    st.set_page_config(page_title="EvidenceDesk · FIU-IND AML", page_icon="🏦", layout="wide", initial_sidebar_state="expanded")
    apply_visual_foundation()

    try:
        get_conn()
    except Exception as err:  # noqa: BLE001 - config / connection problems get an actionable, secret-free message
        st.error(f"**Cannot connect to Snowflake.** {_short(err)}")
        st.markdown("Local runs need a `.env` (copy `.env.example`); inside Snowflake the app uses its owner role. See **DEPLOY.md**.")
        st.stop()

    with st.sidebar:
        html_md('<div class="desk-kicker">FIU-IND AML · CASEWORK</div><div class="desk-brand">EvidenceDesk</div>')
        st.caption("Evidence. Judgment. Decision record.")
        st.caption("AML decision-defensibility and investigation copilot · synthetic data")
        st.divider()
        pages = ["Alert Queue", "Disposition Panel", "Decision Ledger", "Dashboard", "Regulatory Reference", "Corpus Governance", "Model Quality", "Business Value", "Architecture"]
        # The radio is KEYED and never given a changing `index`. An unkeyed `radio(index=…)` changes widget identity every
        # time the page changes, so after one manual sidebar click a later "Review →" jump left the browser holding a stale
        # value; the next widget interaction sent it back and bounced the user to the queue (seen live, 2026-10-01).
        goto = st.session_state.pop("_goto", None)
        if goto in pages:
            st.session_state["nav_page"] = goto
        elif st.session_state.get("nav_page") not in pages:
            seed = st.session_state.get("page")
            st.session_state["nav_page"] = seed if seed in pages else pages[0]
        selected_page = st.radio("Navigate", pages, key="nav_page", format_func=PAGE_LABELS.get)
        st.session_state["page"] = selected_page
        st.divider()
        s = cached_corpus_summary()
        if s.get("error"):
            st.caption("Corpus: unavailable. The copilot abstains from regulatory guidance until it is back.")
        else:
            st.caption(f"Corpus v{md_safe(s['version'])} · snapshot {md_safe(s['snapshot_date'])}  \nPROVEN {md_safe(s['proven'])} · ASSUMED {md_safe(s['assumed'])}  \n"
                       f"NEEDS-VERIFICATION {md_safe(s['needs_verification'])} (excluded)  \nIndependently verified: {md_safe(s['verified'])}  \n"
                       "The 11 review factors are compiled by this product; they are not an official FIU-IND list")
        rows, _ = query("SELECT CURRENT_ROLE() AS R")
        if rows:
            st.caption(f"Running as role: `{code_safe(rows[0]['R'])}`")

    {"Alert Queue": page_alert_queue, "Disposition Panel": page_disposition, "Decision Ledger": page_ledger,
     "Dashboard": page_dashboard, "Regulatory Reference": page_regulatory, "Corpus Governance": page_corpus_governance,
     "Model Quality": page_model_quality, "Business Value": page_business_value, "Architecture": page_architecture}[selected_page]()


if __name__ == "__main__":
    main()
