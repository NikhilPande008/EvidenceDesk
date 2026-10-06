# Demo script

Two cuts of the same walkthrough: **90 seconds** and **3 minutes**. Both open on the working result, run on the isolated clean-room app, and say only what the application does. Everything on screen is synthetic.

## Before recording

- Use the clean-room app, never production. Open two tabs: **A** the *My cases* page, **B** the investigation desk for ALERT-01 (`Open ALERT-01` from the queue).
- Have the fixture text ready to paste: `tests/fixtures/demo_fabrication_sentence.txt` (the planted sentence) and `tests/fixtures/demo_alert01_filing.txt` (the true filing text for ALERT-01).
- On the ALERT-16 and ALERT-01 desks the button **Load the saved assessment (no wait)** appears beside the live one. It serves a real model reply captured on 6 October, labelled with its date and model. A live assessment takes about 80 seconds; do not wait on camera.
- **Recording a decision writes a permanent row.** The ledger is append-only for the application role, so a row cannot be removed from the clean room. If the 3-minute cut records one, do it once, last, and note it.
- Check the screen against the claims: nothing may say or imply that the model is right, that anything was filed with FIU-IND, or that the data is real.

## 90-second cut

| Time | On screen | Do | Say |
|---|---|---|---|
| 0:00 to 0:10 | Tab A, the queue | Show the ranked list and one deadline | "A detector firing is not a decision. These are 19 synthetic alerts, ranked for a Principal Officer, with the seven-working-day clock where the feed supplies a time." |
| 0:10 to 0:25 | *Same signal, different evidence*, then **Open ALERT-16** | Point at the two columns | "ALERT-01 and ALERT-16 have the same detector, the same source and the same ₹3.45 lakh. In ALERT-01, 98.8% of the credits went onward to a flagged recipient. In ALERT-16, 87% went to a named hospital and nothing is flagged." |
| 0:25 to 0:45 | ALERT-16 desk, AI section | Click **Load the saved assessment (no wait)** | "The AI part is optional and labelled. This is a real model reply from earlier; the screen says when and by which model. It asked for a filing. The application checked its beneficiary and complexity claims against the record, discounted both and showed why, and the recommendation falls to REVIEW. The officer still decides." |
| 0:45 to 1:05 | Tab B, ALERT-01 filing text | Paste the true text, append the planted sentence, choose **File STR** | "Now I add a sentence the record does not support: a ₹25 lakh SWIFT transfer to Dubai. The gate names the amount, the date, the channel and the place, and nothing overrides it." |
| 1:05 to 1:20 | *Regulatory lookup* | Ask the UAE goAML question shown in `docs/screenshots/03-regulatory-scope-abstention.jpg` | "Only India is covered. A question about another regime is declined and routed, not guessed." |
| 1:20 to 1:30 | The first screen | None | "Synthetic data, nothing is filed. What it gets wrong, we measured and published." |

## 3-minute cut

| Time | On screen | Do | Say |
|---|---|---|---|
| 0:00 to 0:25 | *My cases*, the twin panel | As above | The problem and the twin pair, as in the 90-second cut. |
| 0:25 to 0:55 | ALERT-16 desk: SOURCE FACTS, then REGULATORY BASIS | Scroll once | "Facts first: three KYC-linked family senders, a payment to a hospital, no flagged recipient. The I4C signal is not corroborated by any flagged party in the record. The hospital invoice is what I would ask for next; the record does not hold it. Then the regulatory basis: each rule shows its authority and its grade. PROVEN means a source is cited by the corpus author, not that it was independently verified." |
| 0:55 to 1:20 | AI section | **Load the saved assessment (no wait)** | The same lines as the 90-second cut. Then: "Underneath, what argues against a filing is computed from the record, not by the model." |
| 1:20 to 1:50 | Tab B, ALERT-01 | Planted sentence, **File STR**, then remove it | "The gate checks every amount, date, id, channel, place and entity against the record. An unsupported fact blocks the filing. Facts that are real but attached to the wrong party are flagged for me to acknowledge." |
| 1:50 to 2:10 | *Regulatory lookup* | The UAE question | "India only, and it says so." |
| 2:10 to 2:35 | The ALERT-01 review sheet | Complete the acknowledgements and record in the clean room, then open the decision and **Reconstruct** it | "The decision gate runs again at write time, not just on the screen. The ledger row stores what I saw, what was assumed, what I acknowledged and why. It is append-only for the application role; it is not immutable, and the page says what a deletion would and would not reveal." |
| 2:35 to 3:00 | The *What it gets wrong* evidence (`README.md`, the held-out row) | Show the row | "On two legitimate Gulf-remittance alerts the model still recommended FILE. We wrote them after freezing our rule, predicted the weakness before running them, and did not change the rule afterwards. The fix needs a jurisdiction list we do not have. The copilot may be uncertain; the decision record may not be undefended." |

## If something goes wrong

| Problem | Say or do |
|---|---|
| A live call is slow or times out | "The model service is slow today; the application fails closed." Use the saved assessment and carry on |
| The tab resets | Reopen the case from the queue; the gate is deterministic and independent of the screen state |
| The saved-assessment button is missing | The case record or prompt changed. Say so, run the live assessment off camera, and re-record |
| Someone asks if the model is accurate | "We do not claim accuracy. We measured it on 19 synthetic alerts we wrote ourselves and published where it is wrong" |
