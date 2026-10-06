"""
Operational errors, written for a Principal Officer under a deadline.

`explain(err, area)` turns ANY exception into {category, reference, title, action, message}:

  * the message says what is unavailable and what the PO can do next — never why in database terms;
  * it NEVER contains SQL, object or schema names, stack traces, file paths, account or user names, or credentials: the original
    text is only classified, never echoed;
  * `reference` is a short code a PO can quote to an administrator: the Snowflake error number when there is one (SF-002003),
    otherwise a hash of the exception type (REF-3F2A9C10). The technical line is written to the server log (redacted), where an
    administrator can find it — not to the screen.

Pure apart from logging. Every sentence here is quoted in design/PO_WORKFLOW_SPEC.md (rendered by scripts/render_po_copy.py).
"""

from __future__ import annotations

import hashlib
import logging
import re

log = logging.getLogger("fiu.copilot")

# category → (title, action). The title says what is unavailable; the action says what the PO can do.
CATEGORIES: dict[str, tuple[str, str]] = {
    "ACCESS":   ("This app's role is not allowed to use this data. It has either not been set up, or access has not been granted.",
                 "Tell your administrator. Other pages still work."),
    "TIMEOUT":  ("The request took too long and was stopped.",
                 "Try again in a moment. You can carry on without it: the checks still apply."),
    "MODEL":    ("The AI model did not answer.",
                 "You can still decide: write your own rationale and the checks still apply."),
    "SEARCH":   ("Regulatory search did not answer.",
                 "Rules shown instead come from plain keyword matching and are not ranked by meaning."),
    "NETWORK":  ("Snowflake could not be reached.",
                 "Check your connection and try again."),
    "SIGNIN":   ("Signing in to Snowflake failed.",
                 "Check your sign-in details with your administrator."),
    "WAREHOUSE": ("The compute warehouse is unavailable.",
                  "Try again shortly. If it persists, tell your administrator."),
    "UNKNOWN":  ("Something went wrong loading this.",
                 "Try again. If it keeps happening, give your administrator the reference below."),
}

# order matters: the first match wins. Patterns are matched case-insensitively against the exception text, which is never shown.
_RULES: list[tuple[str, re.Pattern]] = [
    ("SIGNIN",    re.compile(r"incorrect user|incorrect username|invalid username|authenticat|password|mfa|multi-?factor|passcode|sso|token (?:has )?expired|invalid.*token", re.I)),
    ("TIMEOUT",   re.compile(r"timeout|timed out|time out|statement reached|exceeded the (?:statement|warehouse)|cancel(?:l)?ed", re.I)),
    ("WAREHOUSE", re.compile(r"warehouse.*(?:suspend|unavailable|not.*(?:running|resum))|resource monitor|quota|no active warehouse", re.I)),
    ("ACCESS",    re.compile(r"insufficient privileges|access control|not authorized|does not exist|object .* not found|permission denied|\b403\b|\b3001\b|002003|002043", re.I)),
    ("SEARCH",    re.compile(r"search_preview|cortex search|search service", re.I)),
    ("MODEL",     re.compile(r"cortex|model|complete|llm|legacy status|rate.?limit|\b429\b|\b5\d\d\b.*(?:analyst|cortex)", re.I)),
    ("NETWORK",   re.compile(r"connection|network|name resolution|unreachable|max retries|ssl|dns|refused|reset by peer|socket|broken pipe", re.I)),
]
_SF_CODE = re.compile(r"\b(\d{6})\b")


def classify(err) -> str:
    """The category of an exception (the text is only inspected, never returned)."""
    text = f"{type(err).__name__} {err}"
    for category, pattern in _RULES:
        if pattern.search(text):
            return category
    return "UNKNOWN"


def reference(err) -> str:
    """A short, safe reference: SF-<Snowflake error number> when present, else REF-<hash of the exception type and first 40 chars>."""
    m = _SF_CODE.search(str(err))
    if m:
        return f"SF-{m.group(1)}"
    seed = f"{type(err).__name__}:{str(err)[:40]}".encode("utf-8", "replace")
    return "REF-" + hashlib.sha256(seed).hexdigest()[:8].upper()


def explain(err, area: str = "This", *, log_it: bool = True) -> dict:
    """{category, reference, title, action, message} for any exception. `area` names what failed ("The alert queue")."""
    category = classify(err)
    title, action = CATEGORIES[category]
    ref = reference(err)
    if log_it:
        try:
            from skills.connection import redact
            detail = redact(" ".join(str(err).split()))[:300]
        except Exception:  # noqa: BLE001 - logging must never break the page
            detail = "(unavailable)"
        log.warning("%s | %s | %s | %s: %s", area, category, ref, type(err).__name__, detail)
    return {"category": category, "reference": ref, "title": title, "action": action, "area": area,
            "message": f"{area} is unavailable. {title} {action} Reference: {ref}."}


def message(err, area: str = "This") -> str:
    """Just the PO-facing sentence(s)."""
    return explain(err, area)["message"]
