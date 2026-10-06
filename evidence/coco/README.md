# Cortex Code CLI sessions

**No Cortex Code CLI session is recorded in this folder. None is claimed.**

What exists is the skill files in [`.cortex/skills/`](../../.cortex/skills/): five `SKILL.md` directories that describe how to verify an inspection pack, reconcile the
ledger read-only, dry-run a feed, deploy into an isolated environment and measure honestly. `tests/test_cortex_skills.py` keeps them consistent with the scripts they
tell a reader to run (the scripts exist, the flags exist, no secret, no unasked write). That test checks the files; it does not show a session ever used them.

## How a session is recorded here, once one has happened

Only a session that really took place goes in this folder, unedited apart from redaction of anything secret.

1. In the repository root, start the Cortex Code CLI and run `/skill list`. The five `evidencedesk-*` skills should be listed. If they are not, the directory the CLI
   searched is not the one in this repository; say so in the note rather than moving files until it works and not saying.
2. Ask for one concrete task per skill. Suggested prompts, each against a file or command that exists in this repository:

   | Skill | Prompt |
   |---|---|
   | `evidencedesk-verify-pack` | `$evidencedesk-verify-pack Verify docs/sample/decision-pack-sample.json and tell me what the verdict does and does not show` (the sample was built by the real recorder against a stub database; a pack downloaded from the hosted app is the better test once you have one) |
   | `evidencedesk-audit-ledger` | `$evidencedesk-audit-ledger Give me the read-only reconciliation report` (needs credentials; it must not run any `--apply` step) |
   | `evidencedesk-load-feed` | `$evidencedesk-load-feed Dry-run domain/feeds/tm_export_alerts.csv and domain/feeds/tm_export_transactions.csv with domain/feeds/tm_export_mapping.json` (it must stop after the dry run) |
   | `evidencedesk-deploy-check` | `$evidencedesk-deploy-check Show me the plan for a clean-room deploy, and do not apply it` |
   | `evidencedesk-measure` | `$evidencedesk-measure Run the offline tests and report the counts, then explain which harnesses need credentials` |

3. Save the whole transcript as `evidence/coco/<date>-<skill>.md` with the CLI version (`cortex --version`), the date and the model the CLI reported, and
   add one line to the table below saying what the session did and what it did not.

| Date | Skill | CLI version | What it did | Transcript |
|---|---|---|---|---|
| (none recorded) | | | | |

## What a session would and would not show

- It would show that the skill files load in the CLI and that an agent following them runs the commands they name.
- It would not show anything about the application's accuracy, and it is not a substitute for the offline tests or the live suites.
- Code in this repository was written with an AI coding assistant (Claude Code). That is separate from, and not a substitute for, use of the Cortex Code CLI.
