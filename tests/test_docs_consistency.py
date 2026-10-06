"""Public documentation contract.

The public repository intentionally contains concise, non-environment-specific documentation.
Implementation behaviour is established by code, schemas, tests and approved deployment
configuration—not by historical deployment notes or live-account evidence.
"""

from __future__ import annotations

from _helpers import ROOT, Runner


REQUIRED = {
    "README.md": "# EvidenceDesk — AML Decision-Defensibility Copilot",
    "DEPLOY.md": "# Deployment Guide",
    "HANDOFF.md": "# Contributor Handoff",
    "EVIDENCE.md": "# Validation Evidence",
    "SECURITY.md": "# Security and Data-Use Boundary",
}


def test_required_public_docs_exist_with_expected_titles():
    missing_or_wrong = [
        name for name, title in REQUIRED.items()
        if not (ROOT / name).is_file() or not (ROOT / name).read_text(encoding="utf-8").startswith(title)
    ]
    assert not missing_or_wrong, missing_or_wrong


def test_readme_states_the_product_and_data_boundary():
    text = (ROOT / "README.md").read_text(encoding="utf-8").lower()
    for phrase in ("100% synthetic", "human", "does not autonomously", "not a production"):
        assert phrase in text


def test_public_docs_do_not_embed_live_environment_identifiers():
    text = "\n".join((ROOT / name).read_text(encoding="utf-8") for name in REQUIRED)
    forbidden = ("aws_ap_southeast", "accountadmin", "fiu_wh", "fiu_copilot.aml", "session id")
    found = [value for value in forbidden if value in text.lower()]
    assert not found, found


def test_security_doc_states_audit_limit_and_production_requirements():
    text = (ROOT / "SECURITY.md").read_text(encoding="utf-8")
    for phrase in ("not make owner-role deletion impossible", "NOT provisioned", "DELETED_RECORD", "MODIFIED_SINCE_EXPORT", "SSO", "MFA"):
        assert phrase in text


def test_evidence_doc_does_not_overclaim_production_validation():
    text = (ROOT / "EVIDENCE.md").read_text(encoding="utf-8").lower()
    assert "remaining unverified claims" in text
    assert "not a production certification" in text


def test_readme_has_no_unfilled_placeholders():
    import re
    left = re.findall(r"@@\w+@@", (ROOT / "README.md").read_text(encoding="utf-8"))
    assert not left, f"unfilled README placeholders: {left}"


def test_readme_links_resolve_to_files_that_are_published():
    """A link to a missing or git-ignored file is a dead link on the public repository."""
    import re
    import subprocess
    text = (ROOT / "README.md").read_text(encoding="utf-8")
    targets = {t.split("#")[0] for t in re.findall(r"\]\(([^)\s]+)\)", text) if not t.startswith(("http://", "https://", "#", "mailto:"))}
    missing = sorted(t for t in targets if t and not (ROOT / t).exists())
    assert not missing, f"README links to files that do not exist: {missing}"
    try:
        ignored = [t for t in sorted(targets) if t and subprocess.run(["git", "check-ignore", "-q", t], cwd=ROOT).returncode == 0]
    except (OSError, subprocess.SubprocessError):
        return                                   # no git available: the existence check above is all that can be said
    assert not ignored, f"README links to git-ignored files (dead on the public repository): {ignored}"


TESTS = [
    test_required_public_docs_exist_with_expected_titles,
    test_readme_states_the_product_and_data_boundary,
    test_public_docs_do_not_embed_live_environment_identifiers,
    test_security_doc_states_audit_limit_and_production_requirements,
    test_evidence_doc_does_not_overclaim_production_validation,
    test_readme_has_no_unfilled_placeholders,
    test_readme_links_resolve_to_files_that_are_published,
]


if __name__ == "__main__":
    raise SystemExit(Runner("Public documentation contract").run(TESTS))
