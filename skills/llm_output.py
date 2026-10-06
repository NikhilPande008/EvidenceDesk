"""
Strict, FAIL-CLOSED handling of LLM output.

Rule: nothing a model returns is trusted until it parses AND matches the exact shape
the caller expects. Empty, malformed, truncated, wrongly-shaped or partial output
raises LLMOutputError; callers convert that into a non-passing result
(NEEDS_MANUAL_REVIEW) — never into a default "pass".

Pure Python, no Snowflake dependency, so every branch is unit-testable offline.
"""

from __future__ import annotations

import json
import re
from typing import Any

# Result vocabulary shared by the skills and the UI (single source of truth).
STATUS_READY               = "READY"
STATUS_NEEDS_REVISION      = "NEEDS_REVISION"
STATUS_REJECT              = "REJECT"
STATUS_NEEDS_MANUAL_REVIEW = "NEEDS_MANUAL_REVIEW"

ASSESSMENT_VALUES = ("triggered", "clear", "insufficient_data")

_FENCE = re.compile(r"```[ \t]*(?:json|JSON)?[ \t]*\r?\n?(.*?)```", re.DOTALL)
_OPEN_FENCE = re.compile(r"```[ \t]*(?:json|JSON)?[ \t]*\r?\n?(.*)$", re.DOTALL)


class LLMOutputError(ValueError):
    """Model output cannot be trusted. `code` is a stable machine-readable reason."""

    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code
        self.message = message

    def __str__(self) -> str:  # concise, safe to show in the UI
        return f"[{self.code}] {self.message}"


# ── JSON extraction ──────────────────────────────────────────────────────────

def extract_json(raw: Any) -> Any:
    """Return the JSON value in a model response, or raise LLMOutputError.

    Accepted (in order): bare JSON; JSON inside a ``` fence (fence may follow prose);
    JSON that starts after prose (first '[' or '{', decoded with raw_decode).
    Anything else — including None, "", whitespace, or fenced garbage — is rejected.
    """
    if raw is None:
        raise LLMOutputError("empty_output", "Model returned no output.")
    if not isinstance(raw, str):
        raise LLMOutputError("not_text", f"Model output was {type(raw).__name__}, expected text.")
    text = raw.strip()
    if not text:
        raise LLMOutputError("empty_output", "Model returned an empty response.")

    candidates: list[str] = []
    fenced = _FENCE.search(text)
    if fenced:
        candidates.append(fenced.group(1).strip())
    elif text.startswith("```") or "```" in text:
        # unterminated fence (truncated output) — try, but it will usually fail to parse
        m = _OPEN_FENCE.search(text)
        if m:
            candidates.append(m.group(1).strip())
    candidates.append(text)

    last_err: Exception | None = None
    for cand in candidates:
        if not cand:
            continue
        try:
            return json.loads(cand)
        except json.JSONDecodeError as e:
            last_err = e
        # prose before the JSON: decode from the first bracket
        starts = [i for i in (cand.find("["), cand.find("{")) if i >= 0]
        if starts:
            try:
                value, _ = json.JSONDecoder().raw_decode(cand[min(starts):])
                return value
            except json.JSONDecodeError as e:
                last_err = e
    raise LLMOutputError(
        "malformed_json",
        f"Model output is not valid JSON ({last_err.msg if isinstance(last_err, json.JSONDecodeError) else 'unparseable'}).",
    )


def parse_json_array(raw: Any, key: str | None = None) -> list:
    """extract_json + require a non-empty array.

    The array may be the whole reply, or the value of ONE key of a top-level object: Cortex structured outputs must be an object, so the
    assessment and the checklist arrive as {"assessments": [...]} / {"checklist": [...]}. With `key` that exact key is required; without it the
    object must hold exactly one list. Anything else (several lists, a scalar, a missing key) is still rejected."""
    value = extract_json(raw)
    if isinstance(value, dict):
        lists = [k for k, v in value.items() if isinstance(v, list)]
        if key is not None:
            if key not in value or not isinstance(value[key], list):
                raise LLMOutputError("wrong_shape", f"Expected an object with a list under {key!r}.")
            value = value[key]
        elif len(value) == 1 and len(lists) == 1:
            value = value[lists[0]]
        else:
            raise LLMOutputError("wrong_shape", "Expected a JSON array (or an object holding exactly one array).")
    if not isinstance(value, list):
        raise LLMOutputError(
            "wrong_shape", f"Expected a JSON array, got {type(value).__name__}."
        )
    if not value:
        raise LLMOutputError("empty_output", "Model returned an empty JSON array.")
    return value


# ── shape validators ─────────────────────────────────────────────────────────

def _str_list(value: Any, field: str, ident: str) -> list[str]:
    if value is None:
        return []
    if not isinstance(value, list) or not all(isinstance(v, str) for v in value):
        raise LLMOutputError("wrong_shape", f"{ident}: '{field}' must be a list of strings.")
    return [v for v in value if v.strip()]


def validate_factor_assessments(items: list, expected: list[tuple[str, str]]) -> list[dict]:
    """Validate a suspicion-evaluator response against the expected POE factor set.

    Every expected factor must appear exactly once with a valid `assessment`. Missing,
    duplicate, unknown or mistyped factors make the WHOLE response invalid — a partial
    assessment must never be presented as a complete one. The single tolerance: a factor with
    no `evidence` text is downgraded to insufficient_data (recorded in `normalised_from`).
    Returns normalised dicts (canonical factor_name; model-supplied name is ignored).
    """
    names = dict(expected)
    seen: dict[str, dict] = {}
    for i, item in enumerate(items):
        if not isinstance(item, dict):
            raise LLMOutputError("wrong_shape", f"Factor #{i + 1} is {type(item).__name__}, expected an object.")
        fid = item.get("factor_id")
        if not isinstance(fid, str) or fid not in names:
            raise LLMOutputError("unknown_factor", f"Factor #{i + 1} has unexpected factor_id {fid!r}.")
        if fid in seen:
            raise LLMOutputError("duplicate_factor", f"Factor {fid} appears more than once.")
        asmt = item.get("assessment")
        asmt = asmt.strip().lower() if isinstance(asmt, str) else asmt
        if asmt not in ASSESSMENT_VALUES:
            raise LLMOutputError("bad_assessment", f"{fid}: assessment {item.get('assessment')!r} is not one of {ASSESSMENT_VALUES}.")
        evidence = item.get("evidence")
        if evidence is not None and not isinstance(evidence, str):
            raise LLMOutputError("wrong_shape", f"{fid}: 'evidence' must be a string, got {type(evidence).__name__}.")
        normalised_from = None
        if not (evidence or "").strip():
            # A factor with NO stated evidence cannot support "triggered" and must not be trusted as
            # "clear". Downgrade toward LESS certainty only — never toward clear / triggered.
            if asmt != "insufficient_data":
                normalised_from = asmt
            asmt = "insufficient_data"
            evidence = "The model gave no evidence for this factor" + (
                f" (it asserted '{normalised_from}'); treated as insufficient_data." if normalised_from else ".")
        seen[fid] = {
            "factor_id":        fid,
            "factor_name":      names[fid],
            "assessment":       asmt,
            "evidence":         evidence.strip(),
            "evidence_txn_ids": _str_list(item.get("evidence_txn_ids"), "evidence_txn_ids", fid),
            "rules_cited":      _str_list(item.get("rules_cited"), "rules_cited", fid),
            **({"normalised_from": normalised_from} if normalised_from else {}),
        }
    missing = [fid for fid, _ in expected if fid not in seen]
    if missing:
        raise LLMOutputError("incomplete_output", f"Missing factor(s): {', '.join(missing)}.")
    return [seen[fid] for fid, _ in expected]


def validate_checklist_results(items: list, n_items: int) -> dict[int, dict]:
    """Validate a str_quality_checker response: exactly items 1..n, each with a boolean
    `applies`. Returns {item_number: {"applies": bool, "note": str}}.

    `applies` must be a real JSON boolean — the strings "false"/"no" are rejected, so a
    sloppy model can never be read as a pass by truthiness accident.
    """
    out: dict[int, dict] = {}
    for i, item in enumerate(items):
        if not isinstance(item, dict):
            raise LLMOutputError("wrong_shape", f"Checklist entry #{i + 1} is {type(item).__name__}, expected an object.")
        num = item.get("item_number")
        if isinstance(num, bool) or not isinstance(num, int) or not (1 <= num <= n_items):
            raise LLMOutputError("bad_item_number", f"Checklist entry #{i + 1} has invalid item_number {num!r}.")
        if num in out:
            raise LLMOutputError("duplicate_item", f"Checklist item {num} appears more than once.")
        applies = item.get("applies")
        if not isinstance(applies, bool):
            raise LLMOutputError("bad_applies", f"Checklist item {num}: 'applies' must be true or false, got {applies!r}.")
        note = item.get("note", "")
        out[num] = {"applies": applies, "note": note if isinstance(note, str) else str(note)}
    missing = [n for n in range(1, n_items + 1) if n not in out]
    if missing:
        raise LLMOutputError("incomplete_output", f"Checklist is missing item(s): {', '.join(map(str, missing))}.")
    return out


# ── central readiness decision ───────────────────────────────────────────────

def gos_readiness(quality: dict | None) -> str:
    """The ONLY place that decides whether a Ground-of-Suspicion may be READY.

    Fail-closed: any missing / non-True `ai_output_valid` or `hard_gate_passed`, or a
    non-integer score, can never yield READY.
    """
    if not isinstance(quality, dict):
        return STATUS_NEEDS_MANUAL_REVIEW
    if quality.get("ai_output_valid") is not True:
        return STATUS_NEEDS_MANUAL_REVIEW
    if quality.get("hard_gate_passed") is not True:
        return STATUS_REJECT
    score = quality.get("quality_score")
    if isinstance(score, bool) or not isinstance(score, int):
        return STATUS_NEEDS_MANUAL_REVIEW
    if score >= 8:
        return STATUS_READY
    if score >= 5:
        return STATUS_NEEDS_REVISION
    return STATUS_REJECT
