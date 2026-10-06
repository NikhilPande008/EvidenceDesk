# Validation Evidence

## Scope

This public repository contains synthetic scenarios, automated tests, implementation artifacts and scrubbed run records. The run records under `evidence/` and the screenshots under `docs/` come from synthetic-data runs; account, organisation, user and local-path identifiers are removed. It does not publish credentials, connection information, customer data, or production-operating evidence.

## Validation approach

The automated suite exercises the main prototype boundaries, including:

- fail-closed parsing of AI output;
- deterministic grounding of supported case facts;
- regulatory-basis and supersession handling;
- human-review and decision-gate paths;
- ledger provenance and integrity checks;
- role and security-boundary checks; and
- UI safety and hostile-input handling.

Run the public validation commands from [README.md](README.md). A passing automated suite demonstrates only the behaviour exercised by its tests; it is not a production certification, security attestation, legal opinion, or regulatory approval.

## Remaining unverified claims

No public claim is made that this prototype has been deployed to, tested against, or approved for a real financial institution. The included regulatory corpus is governed reference material, not independently verified legal advice. Production performance, detection quality, operational impact, and regulatory acceptance require institution-specific validation.

