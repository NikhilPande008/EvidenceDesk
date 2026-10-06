"""
Decision-maker identity — authenticated where Snowflake supplies it, honestly labelled where it does not.

A decision record is only as attributable as the identity on it. Until this module the Principal Officer's ID was a typed text field.
Now:

  SESSION   the identity Snowflake supplies to a Streamlit-in-Snowflake app for the signed-in viewer (`st.user` /
            `st.experimental_user`). The field is read-only and the decision-maker recorded is that identity.
  TYPED     there is no authenticated session identity (a local run, or a runtime that does not supply one). The officer types an ID,
            the screen says it is NOT authenticated, and the decision gate records a warning (IDENTITY_NOT_AUTHENTICATED).

Two things are true whichever applies:
  * The ledger INSERT also stamps the Snowflake USER and ROLE that wrote the row (`written_by_user`, `written_by_role`), computed by the
    database — not supplied by the client. That is the strongest attribution available without single sign-on.
  * An authenticated identity can never be overridden: if the ID being recorded differs from it, the gate BLOCKS
    (PO_ID_DIFFERS_FROM_SESSION_IDENTITY). A client that lies about being authenticated can still lie about it — which is why the
    database-stamped user sits next to it, and why SSO + MFA at the Snowflake layer is a PRODUCTION REQUIREMENT (skills/readiness.py).

What this does NOT do: verify that a typed ID belongs to the person typing it; enforce MFA; prove the viewer is the person on the record.
Pure functions; no database, no Streamlit.
"""

from __future__ import annotations

from typing import Any

SESSION, TYPED = "SESSION", "TYPED"
MAX_ID_CHARS = 200


def normalise(value: Any) -> str:
    return " ".join(("" if value is None else str(value)).split())[:MAX_ID_CHARS]


def resolve(session_user: Any, typed: Any = None) -> dict:
    """The identity to record. `session_user` is what the runtime supplied (None/'' if nothing); `typed` is the officer's text."""
    who = normalise(session_user)
    if who:
        return {"id": who, "source": SESSION, "authenticated": True, "editable": False}
    return {"id": normalise(typed), "source": TYPED, "authenticated": False, "editable": True}


def matches(decision_maker_id: Any, identity: dict | None) -> bool:
    """Does the ID being recorded equal the identity? (case-insensitive; surrounding space ignored.)"""
    if not isinstance(identity, dict):
        return True
    return normalise(decision_maker_id).casefold() == normalise(identity.get("id")).casefold()


def clean(identity: Any) -> dict | None:
    """The bounded shape the gate and the ledger accept (None = not evaluated). Never trusted beyond these three fields."""
    if not isinstance(identity, dict):
        return None
    source = identity.get("source") if identity.get("source") in (SESSION, TYPED) else TYPED
    return {"id": normalise(identity.get("id")), "source": source, "authenticated": bool(identity.get("authenticated")) and source == SESSION}


def stored(identity: dict | None, decision_maker_id: Any) -> dict | None:
    """What the ledger keeps in provenance (the ID itself is already the DECISION_MAKER_ID column)."""
    c = clean(identity)
    if c is None:
        return None
    return {"schema": "decision_identity/1", "source": c["source"], "authenticated": c["authenticated"],
            "matches_session_identity": matches(decision_maker_id, c) if c["authenticated"] else None,
            "database_stamp": "written_by_user and written_by_role are added by the INSERT (CURRENT_USER(), CURRENT_ROLE())"}
