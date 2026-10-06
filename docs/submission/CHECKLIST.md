# Pre-submit checklist

Items marked **YOU** need a decision or an action that only the team lead can take. Items marked **DONE** were checked on 2026-10-06 and say how.

## Deadline (verify first)

- [ ] **YOU.** Exact submission deadline: date, time and **timezone**. It is not in the repository. The 5 October note said about 48 hours from that day. Confirm it on the portal, convert it to your own timezone, and write it here: `____________`
- [ ] **YOU.** Submit at least a few hours before it. A submission one minute late in the wrong timezone is a zero.

## Repository

- [x] **DONE.** A fresh clone of the latest commit compiles and passes: 603 passed, 20 skipped; all 46 standalone suites exit 0.
- [x] **DONE.** No credential-shaped string in any of the 30 commits outside test fixtures (those hold fake sentinels); `.env` is ignored; `.env.example` holds placeholders only.
- [ ] **YOU.** The work is on `hardening-2026-10-05`. Judges see the default branch. Merge it (`git switch main && git merge --ff-only hardening-2026-10-05`) and push, or tell me to. Nothing has been pushed.
- [ ] **YOU.** Repository is **public**, or accessible to the judges, and the URL below opens when logged out: `____________`
- [x] **DONE.** **License.** MIT, added on 2026-10-06 (`LICENSE`, copyright 2026 Nikhil Pande) and noted in the README. Check the hackathon's rules do not require a different one.
- [ ] **YOU.** The commit history carries your name and email address. Confirm you are happy for it to be public, or rewrite the author with your platform's no-reply address before the first push.
- [ ] **YOU.** Rotate `SNOWFLAKE_TOKEN`. Its value appeared once in an earlier tool output in this working session. It is not in git, but the transcript may be shared.
- [ ] `.claude/launch.json` carries a local, uncommitted edit. Leave it uncommitted (`git status` should show only that file).

## Claims

- [x] **DONE.** Every headline claim is labelled in `CLAIM_AUDIT.md` (17 PROVEN, 8 STUBBED, 3 ASSUMED, 7 never claimed). Wording defects found by the audit are fixed.
- [ ] **YOU.** The README and the writeup say the code was written with an AI coding assistant (Claude Code). Confirm you want that disclosed (the hackathon's rules may also ask).
- [ ] **YOU.** The README and the writeup say no Cortex Code CLI session is recorded. See "Cortex Code CLI" below: this is the largest gap for a CoCo CLI hackathon.
- [ ] Re-read the writeup's numbers against `evidence/` once more if any run changes them.

## Rules to check against the repository's history

- [ ] **YOU.** The first commit is 2026-10-04 00:12 IST and the history is 30+ commits. Check the hackathon's rules on a build window and on pre-existing code, and be ready to say what existed before the window.
- [ ] A jargon sweep of the pages the red-team did not walk (Decision archive, Tools pages) is still open (`REDTEAM.md`).

## Cortex Code CLI (the biggest gap)

- [ ] **YOU.** Run the CLI in the repository root. `/skill list` should show five `evidencedesk-*` skills. If it does not, say so in `evidence/coco/README.md` rather than moving files until it works.
- [ ] **YOU.** Run one task per skill (prompts are in `evidence/coco/README.md`), save each transcript as `evidence/coco/<date>-<skill>.md` with the CLI version, and add a row to the table in that README. Only a session that happened goes in.
- [ ] If no session is recorded, leave the "Cortex Code CLI" statements as they are. Do not edit them to imply use.

## Demo video

- [ ] **YOU.** Video length limit and format from the portal: `____________`. The script has a 90-second and a 3-minute cut (`DEMO_SCRIPT.md`).
- [ ] Record on the **clean-room** app, not production. Do not show credentials, the account identifier or the connection tab.
- [ ] Open on the working result. Use the saved assessment button; do not wait on a live call on camera.
- [ ] If a decision is recorded on camera it is a permanent row in the clean room (append-only). Do it once, last.
- [ ] Link is viewable by the judges (unlisted or public as the portal requires): `____________`

## Deck

- [ ] **YOU.** Paste the corrected text for slides 3, 4 and 5 from `DECK_COPY.md` into the hackathon template. Slides 2 and 6 stay.
- [ ] Export a PDF as the presentation backup and as the upload if the portal asks for one.

## Portal fields

- [ ] **YOU.** Platform: the template shows the YourStory, Snowflake and H2S marks, so the portal is probably Hack2Skill. Confirm the fields it asks for, and map them from `WRITEUP.md` (problem, solution, tech stack, track, links).
- [ ] Team name, size and lead as in the deck: Daksha EvidenceDesk, team of one, lead Nikhil Pande. Check the track is **Risk, Fraud and Regulatory Intelligence Copilot**.
- [ ] Repository URL, video URL, deck upload, and a hosted-app link **only if** judges can open it. The clean-room app is private to the Snowflake account; if they cannot, say "screenshots and video" and do not claim a live URL.
- [ ] Fill in the three link placeholders at the end of `WRITEUP.md`.

## Environment

- [ ] **YOU.** Keep the clean-room environment up until judging ends, or accept that the hosted app disappears. Do not tear down the earlier clean room without deciding that on purpose.
- [ ] Production `FIU_COPILOT` has not been touched by any run in this session.

## Last 10 minutes

```bash
git status --short                      # only .claude/launch.json
git log --oneline | head -3             # the commit you intend to submit
python -m pytest tests -q -p no:cacheprovider
python scripts/render_readiness_docs.py --check
```

Open the repository URL in a private window and click the README's evidence links.
