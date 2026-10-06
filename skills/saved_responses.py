"""
Saved model responses: real Cortex output captured earlier, replayed ONLY when the request is byte-identical.

Why it exists: a live assessment takes tens of seconds and depends on a model service that can be slow or unavailable. A reviewer who
wants to see the workflow, rather than wait for it, can ask for the saved response. It is never substituted silently: the officer chooses
it, the screen says it is a saved response and when it was captured, and the ledger row records `ai_output.source = saved_response`.

What it is not: a cache of conclusions. The saved text is the model's raw reply; everything after it (parsing, the 11-factor check, grounding
every cited transaction, the evidence gate over a draft, the defensibility gate) runs again, now, against the record as it stands. If the
record, the corpus or the prompt has changed, the prompt text differs, its hash differs, nothing matches, and only a live call is possible.

The data lives in skills/saved_responses_data.py, written by `python3 scripts/eval_live_replay.py --write-saved` from a real run; it is
never edited by hand. This module is pure: no Snowflake, no clock.
"""

from __future__ import annotations

import hashlib

SOURCE_LIVE = "live"
SOURCE_SAVED = "saved_response"


class SavedResponseUnavailable(RuntimeError):
    """Replay was asked for, but no saved response matches this exact request. Nothing was sent to any model."""


def prompt_key(prompt: str) -> str:
    return hashlib.sha256(prompt.encode("utf-8")).hexdigest()


def _table() -> dict:
    from skills import saved_responses_data
    return saved_responses_data.SAVED


def lookup(prompt: str, table: dict | None = None) -> dict | None:
    """The saved entry for exactly this prompt text, or None. An entry needs a model, a capture time and a non-empty raw reply to count."""
    entry = (table if table is not None else _table()).get(prompt_key(prompt))
    if not isinstance(entry, dict):
        return None
    if not (entry.get("model") and entry.get("captured_at") and isinstance(entry.get("raw_response"), str) and entry["raw_response"].strip()):
        return None
    return entry


def describe(entry: dict) -> dict:
    """What the screen and the ledger may say about an entry (never the reply itself)."""
    return {"model": entry["model"], "captured_at": entry["captured_at"]}


def provenance(source: str | None, captured_at: str | None, model: str | None = None, parts: list[str] | None = None) -> dict | None:
    """The `ai_output` object stored with a decision when any of its AI output was a saved response; None otherwise (the key is then absent).
    `parts` names which outputs were saved ("assessment", "draft"); the other, if any, was a live call."""
    if source != SOURCE_SAVED:
        return None
    return {"source": SOURCE_SAVED, "captured_at": captured_at or "UNKNOWN", "model": model or "UNKNOWN", "parts": sorted(set(parts or []))}
