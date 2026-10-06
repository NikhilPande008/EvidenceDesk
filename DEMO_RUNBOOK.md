# EvidenceDesk — Demo Runbook

## The one message to land

**A detection signal is not a decision.** The copilot makes the evidence, regulatory basis, AI inference and human decision visible in that order. It refuses a filing that cannot be defended and preserves the decision record for later reconstruction.

**Say what it is, in one breath:** an AML decision-defensibility and investigation copilot. Other systems generate or ingest the fraud and mule-risk signals; this application investigates, prioritises, explains and supports a defensible disposition by a Principal Officer, and records why. It does not detect fraud, give legal advice, file reports or verify compliance, and it does not decide. All data is synthetic.

This runbook treats the supplied PowerPoint as a **submission template**. Its slide-2 text lists required submission topics; it is not an instruction to change the application or to make a production decision.

## Recommended demo format

* **Live demo:** 3 minutes, followed by 2 minutes of questions.
* **Presenter:** one person drives the app and speaks. A second team member can manage the backup tab, timer and fallback text.
* **Environment:** use the clean-room hosted app for any live **Record** action. It has a disposable ledger. Do not record decisions in production during rehearsal or judging.
* **Primary story:** ALERT-16 closes with a documented rationale; ALERT-01 files because the underlying evidence differs, even though the same detector fired for both.

## Submission deck: six-slide fill plan

Keep the supplied black header, sponsor marks and blue footer. The current template has six slides: title, instructions, three blank content slides, an additional-slide title, and a closing slide. Replace the instruction slide with content before submitting.

| Template slide | Title and content to place on it | Visual / proof |
|---|---|---|
| 1 | **EvidenceDesk — AML Decision-Defensibility Copilot**. Team name, problem statement: “Turning suspicious-activity signals into defensible Principal Officer decisions”, leader and team size. | Use the template’s existing title layout. |
| 2 | **The problem: a signal does not explain a filing decision.** Target user: Principal Officer / AML investigator at a reporting entity. Pain: alerts, regulations and narrative evidence sit apart; a weak FILE or NOT_FILE decision becomes an inspection risk. Solution: bounded human-in-the-loop workbench that shows facts, basis, AI proposal and the human’s recorded decision. | One screenshot of the four-zone Investigation desk. |
| 3 | **Same signal, different evidence, different outcome.** ALERT-01 and ALERT-16 both trigger MULE_PASSTHROUGH for ₹3.45 lakh. ALERT-01: 98.8% onward, one I4C-flagged counterparty, unknown senders → FILE. ALERT-16: no flagged counterparty and three KYC-linked family senders; the hospital payment is not documented in the record, so the invoice is the open item → CLOSE. | A side-by-side comparison from *My cases* or a clean, two-column screenshot crop. |
| 4 | **Architecture.** Data: synthetic alerts, transactions and governed regulatory corpus in Snowflake. Cortex Search retrieves supported rules; Cortex Complete assesses factors and drafts; deterministic controls ground claims and enforce the decision gate; Streamlit shows the PO workflow; append-only ledger stores provenance and a row hash. Cortex Code CLI: the repository carries five skill files in `.cortex/skills/`; if a session is recorded in `evidence/coco/`, show it, and if not, say that no session is recorded. Do not call the application's own Python modules "CLI skills". | Architecture diagram. Use the exact labels in the architecture section below. |
| 5 | **Impact and trust controls.** State only measured outcomes: 605 offline tests; the live suites run in full on 6 October against the clean room (owner role 19 passed, app role 18 passed, no failures; they were not run against production); app role has INSERT and SELECT only on the ledger; model output is fail-closed; fabricated facts block filing (30 of 38 unseen phrasings caught, 0 of 139 faithful narratives wrongly blocked); 30 of 30 hosted code files matched the source after the 6 October redeploy. Also state the miss: on the held-out Gulf-remittance alerts the model recommended FILE for both legitimate cases. Explain that the product records what the PO saw, acknowledged and decided. | Screenshot of the decision checkpoint or ledger reconstruction. Add the note “100% synthetic data.” |
| 6 | **Thank you — Evidence before opinion.** Closing line: “The copilot may be uncertain; the decision record may not be undefended.” Include team names and a QR/link only if the team has a permitted demo URL. | Minimal closing slide, retaining the template’s footer. |

### Architecture diagram labels

Use a left-to-right flow in the deck:

`Synthetic alert + transaction data` → `Snowflake AML data layer` → `Cortex Search: governed regulatory corpus` → `Cortex Complete: 11-factor assessment and draft` → `Deterministic controls: grounding, evidence gate, decision gate` → `Streamlit Principal Officer workspace` → `Append-only decision ledger + reconstruction`

Place a small label below the controls: “Human decides; the system records why.”

## Pre-demo checklist

### The day before

1. Open the clean-room app in Snowsight with the clean-room app role active (`FIU_APP_ROLE_CR2` for the current deployment, redeployed on 6 October; `snow streamlit get-url FIU_AML_COPILOT --database FIU_COPILOT_CR2 --schema AML` prints its address). Confirm the sidebar shows that role.
2. Run the clean-room health check. It should report no `UNAVAILABLE` checks.
3. Open ALERT-16 and ALERT-01 and confirm their source facts appear. Do not press **Record** in production.
4. Take fresh screenshots for slides 2, 3 and 5. Ensure that customer data is synthetic and no credentials, query text or browser tabs appear.
5. Put this repository, the deck and the three fixture files on the presentation machine. Have a PDF version of the final deck as a presentation backup.

### 15 minutes before

1. Use a reliable network and disable sleep, notifications, VPN popups and screen sharing of unrelated windows.
2. Open two browser tabs in the clean-room app. Do not reload them after starting model work because app session state can reset.
3. Tab A: **My cases** → open **ALERT-16** → run the 11-factor assessment (median 78 s, longest 116 s on 6 October), or press **Load the saved assessment (no wait)** where it is offered. The saved one is a real model reply captured on 6 October and the screen says so; say so aloud if you use it.
4. Tab B: open **ALERT-01** → run the 11-factor assessment → **Draft with AI**. Live, the draft and its quality check took a median of 130 s and up to 206 s on 6 October; **Load the saved assessment / draft (no wait)** is offered beside each button when a saved reply matches the case exactly. Every check after either one runs fresh.
5. Copy these into the clipboard manager / notes app:
   * `tests/fixtures/demo_alert16_closure.txt`
   * `tests/fixtures/demo_alert01_filing.txt`
   * `tests/fixtures/demo_fabrication_sentence.txt`
6. Keep the deck open as a separate tab or window. Start on the title slide, then switch to the app for the live segment.

### Safe commands

Run these only with valid Snowflake credentials and the expected role. They are read-only except for the clean-room setup command explicitly labelled as deployment.

```bash
# Confirm the local build without calling Snowflake. -m "not live" matters: with credentials in .env a plain pytest also runs the live tests against whatever database .env names.
python3 -m pytest tests -q -m "not live"

# Check the existing clean-room environment and hosted code.
python3 scripts/health_check.py --profile cleanroom --suffix CR2

# Optional: exercise model and Analyst paths. This incurs Cortex usage and can take a minute.
python3 scripts/health_check.py --profile cleanroom --suffix CR2 --deep
```

If the clean room is missing, only the Snowflake owner should provision it. Follow the repository’s clean-room deployment sequence in `DEPLOY.md`; it deliberately uses suffixed (`_CR`, or `_CR2` for the current deployment) database, warehouse and role names and leaves production unchanged.

## Three-minute speaker script

### 0:00–0:25 — establish the problem

**On screen:** Tab A, *My cases*, the *Same signal, different evidence* panel.

**Say:**

> These two alerts have the same detector, source and ₹3.45 lakh signal. But ALERT-01 sent 98.8% of credits onward to an I4C-flagged recipient, and its senders are unknown UPI handles. ALERT-16 has no flagged counterparty and every sender is a KYC-linked family member. A detector firing is not a decision.

Click **Open ALERT-16**.

### 0:25–0:55 — prove evidence and authority come before AI

**On screen:** SOURCE FACTS, then REGULATORY BASIS.

**Say:**

> We start with facts, not AI: three KYC-linked family senders, a payment to a hospital, no flagged recipient, and an I4C signal that no flagged counterparty in the record corroborates. The hospital invoice is what I would ask for next; the record does not hold it. Then the regulatory basis. The page shows each rule’s authority and confidence. PROVEN means the corpus author cites a primary source. ASSUMED means it is not verified law. The system makes that uncertainty visible.

### 0:55–1:20 — show the AI as a proposal

**On screen:** AI INFERENCE and the top of HUMAN DECISION.

**Say:**

> Read the proposal as it appears; the model varies between runs, and I do not rely on its wording. For this alert it asked for FILE, citing a beneficiary it called questionable and a possible pass-through. Before the recommendation is shown, the application checks those two factors against the transaction record: every outgoing payment goes to one named hospital, nothing is flagged and nothing crosses a border, so both are discounted, with the reason shown, and the recommendation falls to REVIEW. It is still a proposal, marked as one. Underneath, the app shows what argues against FILE, computed from the record and not by the model: no transaction involves a flagged counterparty, and every credit comes from a KYC-linked sender. The AI proposes; deterministic checks challenge; the human decides. If the model's reply differs on the day, say so and show the same two checks: the demo does not depend on a particular wording.

### 1:20–1:50 — close the legitimate twin

**On screen:** HUMAN DECISION for ALERT-16.

**Do:** paste the closure text; enter a PO ID; choose **Close — no suspicion formed**; if the AI proposed FILE, type your reason for departing from it in the box that appears (for example: every credit is from a KYC-linked family member and no counterparty is flagged; the hospital invoice is requested); tick the ASSUMED-rule acknowledgement; read *Ready to record*; press Record only in clean room.

**Say:**

> I enter the documented rationale and choose Close. If I am departing from the AI's proposal, the review sheet asks for my reason, in my own words, and stores it. The review sheet tells me exactly what is missing. This closure relies partly on ASSUMED rules, so I must explicitly acknowledge that before recording. Now the clean-room ledger stores my rationale, the facts, the basis and the acknowledgement.

### 1:50–2:30 — demonstrate refusal of fabrication

**On screen:** Tab B, ALERT-01, with the assessment and draft ready.

**Do:** append the fabrication sentence; choose **File STR**.

**Say:**

> ALERT-01 is different: the evidence supports a filing. But watch what happens when I add a plausible-sounding sentence that is not in the case record.

Point to the blocked facts check. Then remove the added sentence.

> The system names the unsupported amount, date, channel and geography. No acknowledgement can override a fabricated fact in a filing. I remove it, and the original evidence remains available for review.

### 2:30–3:00 — record and reconstruct

**On screen:** checkpoint, then Decision archive.

**Do:** complete required acknowledgement(s), record in clean room; open the resulting decision and **Reconstruct** it.

**Say:**

> With the defensible narrative restored, the filing is ready. The archive reconstructs what the PO saw, what was assumed, what was acknowledged and why the decision was made. The copilot may be uncertain; the decision record may not be undefended.

## Optional two-minute extension (run it on the local or clean-room app, never by recording in production)

Use it after the three-minute script, or instead of the Record step if time is short. Every claim below is on screen; say nothing the screen does not show.

| Time | On screen | Say |
|---|---|---|
| 0:00–0:25 | **My cases**, priority column; open *Why this case is prioritized · ALERT-01* | “Priority orders the work. It is nine published factors with fixed weights, and it tells you why. ALERT-01 and ALERT-16 fired the same detector for the same amount and score differently because the record differs. It is not a risk rating and not a recommendation to file; the deadline factor is zero because no suspicion time has been recorded, and we do not invent one.” |
| 0:25–0:55 | **ALERT-03** → *Evidence quality* | “These are the gaps in the record, each with its effect: informational, needs your acknowledgement, needs your own check, or blocks a filing. The record says documents have not been produced, so a decision needs a written check from me. The next-evidence list is a set of suggested steps, not conclusions. And it is enforced: Record stays disabled until I acknowledge and write what I checked.” |
| 0:55–1:20 | **ALERT-01** → *Relationships and network* | “Every link says how we know. Sourced means the record states it; inferred means a named rule matched, and the rule says what it does not show. ALERT-16 has the same rapid pass-through and fan-in shape, so shape alone is not suspicion. We cannot test a shared device, address or document because the data has none, and the screen says so.” |
| 1:20–1:45 | **Decision archive**, *Audit-export protection* | “Is the audit export provisioned and current? Here it is not, or it is behind, and the page says what that means: deleting those rows would not be detected. The ledger is append-only for this role; it is not immutable, and the external write-once copy is a production requirement.” |
| 1:45–2:00 | **Tools · Architecture & readiness** and **Business value** | “Implemented, simulated, or a production requirement — nothing is labelled stronger than it is. Hands-on time is not measured, there is no baseline, so we claim no improvement; the simulated figures are off until you ask and marked on every row.” |

## What to say if something goes wrong

| Situation | Say | Continue with |
|---|---|---|
| Cortex assessment is slow | “The assessment runs on request and the live model can take over three minutes (the longest draft took 206 s). The evidence-first decision path remains usable without it.” | Use the prepared closure / filing text and show the checkpoint. |
| Cortex times out | “The system withholds unavailable AI output and records this as a fully human decision rather than pretending it answered.” | Continue with the source facts, basis and human decision. |
| A browser tab resets | “I will reopen the case from the queue. The decision gate is deterministic and independent of the presentation state.” | Reopen, paste the matching fallback text. |
| Production app is open by mistake | “I will demonstrate the non-writing path here and use the clean room for recording.” | Do not press Record. Switch to the clean-room app. |
| ALERT-01 shows an earlier decision | “This synthetic production dataset contains legacy test decisions. The ledger is append-only and keeps both records.” | Continue; use clean room for the new write. |

## Judge Q&A: concise answers

| Likely question | Answer |
|---|---|
| Does the AI decide whether to file? | No. It produces an optional, labelled assessment. The Principal Officer chooses the disposition, and the app preserves the evidence and rationale. |
| How do you prevent hallucinated filings? | Deterministic grounding checks every cited amount, date, transaction ID, channel, geography and entity against the case record. Unsupported facts block a filing. |
| Can someone rewrite a decision later? | The application role has only INSERT and SELECT on the ledger. Each record has a row hash and reconstruction checks the stored provenance. |
| Are the regulatory claims verified law? | The app distinguishes PROVEN, ASSUMED and NEEDS-VERIFICATION. “PROVEN” means the corpus author cited a primary source; the app does not overstate that as independent verification. |
| Why not automate filing? | Filing is a Principal Officer responsibility. The product helps make the decision defensible, then records why it was made. |
| Does it detect mule accounts? | No. Detection belongs to the institution's monitoring and the registries (MuleHunter.AI, I4C, RBI DPIP). This application takes those signals, investigates, prioritises and explains them, and records the Principal Officer's decision. |
| Is the priority score a risk model? | No. It orders work with nine published factors and fixed weights, explains itself, and is never read by the decision gate. |
| Is the ledger immutable? | No, and we do not say so. It is append-only for the application role; the owner role can delete rows. The audit export and its packages make deletion of exported rows detectable; an independent write-once copy is a production requirement, listed with what it needs. |
| Does feedback retrain the model? | No. Acceptance, rejection and reasons are captured and monitored; no score, gate or prompt reads them. Any change is a reviewed code change. |
| What did you not verify? | What Snowsight renders and what `st.user` returns there; the live suites against the production database (they ran in full on the clean room); and any business improvement. KNOWN_LIMITATIONS.md lists them with the roadmap. |
| Who pays for this, and why a global capability centre? | We do not know. It is an assumption, labelled ASSUMED (A5 in the claim audit), and nobody has been asked. The writeup says what would settle it. |
| Where is the Cortex Code CLI? | Five skill files in `.cortex/skills/`, kept consistent with the scripts by a test. No CLI session is recorded, so none is claimed; `evidence/coco/README.md` says how one would be. |
| What is the current evidence base? | The demo uses 100% synthetic data. The current corpus contains 49 governed rules: 13 PROVEN, 23 ASSUMED and 13 excluded NEEDS-VERIFICATION rules. |

## Submission and demo handoff checklist

- [ ] Replace every placeholder on template slide 1.
- [ ] Replace the template’s instruction slide with the problem brief.
- [ ] Include a readable architecture diagram with the data flow. Name Cortex Code CLI skills only as files unless a CLI session is recorded.
- [ ] Use only measured claims and label all data as synthetic.
- [ ] Remove internal test counts from slides if the judges prefer business value; keep them in speaker notes or Q&A.
- [ ] Export the final deck to PDF and check every screenshot at full-screen resolution.
- [ ] Rehearse twice with a three-minute timer and once with the AI unavailable fallback.
- [ ] Confirm clean-room role and URL before the live write.
- [ ] Keep production record buttons untouched during rehearsal.
