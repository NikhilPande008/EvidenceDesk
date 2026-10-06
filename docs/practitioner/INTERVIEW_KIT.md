# Practitioner interview kit and informal timing exercise

**Status: nothing in this kit has been run, and no result exists.** It is how to get evidence for three claims the repository currently labels ASSUMED or STUBBED: that a Principal Officer and a financial-crime operations team would recognise this workflow (A1), who would pay for it (A5), and whether it changes the time a decision takes (S5). Results go in `docs/practitioner/RESULTS.md`, which does not exist until a real conversation has taken place.

## Ground rules

1. **Ask about their practice before showing anything.** The first six questions come before the product. If they have seen the product first, they answer about the product.
2. **Do not ask whether it is useful.** Ask what they did the last time. People are polite about demos and specific about last Tuesday.
3. **Keep the negative answers.** A conversation where someone says the path is wrong is worth more than three that agree, and it goes in the record.
4. **Always report how many.** Write "three informal conversations", never "validated" and never a percentage.
5. **Synthetic data only, and no confidential detail.** Nobody is asked about a real customer, a real case or their institution's internal figures. General terms are enough.
6. **Say how you know them.** A friend or former colleague is a fine participant, and the record must say so.

Three levels of consent, written down before the conversation ends: may be quoted by name and organisation; may be quoted by role only; may not be quoted (the answer is used as a theme).

## Who to ask (any one is better than none)

1. Someone who has held or deputised the Principal Officer or compliance-officer role at a bank or financial institution in India.
2. Someone in a financial-crime operations team, at a bank or a global capability centre, who prepares alerts into decisions.
3. Someone from internal audit, QA or a regulatory inspection background who reads those decisions afterwards.

## The 15-minute conversation

**Opening (1 minute).** "I am testing whether a prototype fits how alerts are really decided. It uses only synthetic data. I would like to ask about your practice first and then show three minutes of it. May I write down what you say, and how may I quote it?"

**Part 1: their practice (6 minutes, before the demo).**

| # | Question | Informs |
|---|---|---|
| 1 | Think of the last alert you had to decide on, or review. What did you have in front of you? | A1 |
| 2 | Where does the reasoning get written down today, and who can read it a year later? | A1 |
| 3 | How do you know how long you have left to file, and who keeps track? | A1 |
| 4 | Who prepares the case and who decides? Are they always different people? | A1, gap 1 in `REAL_WORLD_FIT.md` |
| 5 | What tool or document do you use for this today? What do you dislike about it? | A1, A5 |
| 6 | Does the same team work alerts under more than one country's rules? How is that handled? | A1, gap 2 |

**Part 2: three minutes of the demo.** The comparison of ALERT-01 and ALERT-16, then the evidence gate refusing a planted fact. Nothing else.

**Part 3: their reaction (5 minutes).**

| # | Question | Informs |
|---|---|---|
| 7 | In what you saw, what looks wrong, or unlike how it works where you are? | A1 |
| 8 | Which screen would you use first, and which would you never open? | A1 |
| 9 | What is missing that you would need before using it on a real alert? | A1 |
| 10 | If you used it, what would you stop doing? | A1, S5 |
| 11 | Who would have to agree to use it, and who would pay? What would they ask first? | A5 |
| 12 | Which sentence in our description of the problem is not true where you work? | A1 |

**Close (1 minute).** "Who else should I ask, especially someone who would disagree?"

## Capture template (one per conversation, in `RESULTS.md`)

```
Date:                      Role (and organisation type, if they allow it):
How we know each other:    Consent level:
Q1-Q6, in their words:
Q7-Q12, in their words:
Where they said the path on REAL_WORLD_FIT.md is wrong:
What they asked for that the product does not have:
Anything they would not let us claim:
```

## What to do with the answers

- If anyone says a step on [REAL_WORLD_FIT.md](../REAL_WORLD_FIT.md) is wrong, fix the page before anything else.
- A1 becomes "reviewed by n practitioners (roles)", and stays ASSUMED for fit. "I would use it" is an opinion, not demand.
- A5 changes only if someone names a budget holder and a way it would be bought. Otherwise write what they said and leave it ASSUMED.
- If a requested feature came up more than once, it goes in "What is next" with the count. Do not build it for the submission.

## Informal timing exercise (two or three people, one hour each)

**What it can show:** an observation of how long two people took on a case with and without the workspace, and how many facts in what they wrote were not in the record. **What it cannot show:** that time is saved. Two or three people is not a measurement. [The pilot protocol](../PILOT_PROTOCOL.md) says how a real number would be produced.

**Participants:** people who did not write the cases, ideally the practitioners above. Never show them the labels.

**Cases:** ALERT-01 and ALERT-16, the same signal and amount with different evidence. After the first one a participant knows the pair; say so in the record.

**Two conditions, in a different order for each participant:**
- **Plain.** The alert text and the transaction rows, copied from the app's source-facts view into a blank document, plus the text of rules STR-001, STR-002 and RS-004 as a handout. No checks, no AI.
- **Workspace.** The same case in the app, using the saved assessment so no model wait is counted, or no assessment at all.

**Task, both conditions:** decide FILE or NOT_FILE and write the rationale in your own words.

**Measured:**
1. Minutes from the start to a written decision and rationale, on a stopwatch. Time spent asking the facilitator is subtracted.
2. Facts in the written rationale that the case record does not hold. For the plain condition, paste the text into the app's evidence gate afterwards and copy down what it names.
3. Their decision. Only record it; it is not an accuracy test.
4. One question at the end: which would you rather work in, and why?

**Report it like this:** a table of raw numbers, one row per participant and condition, with the order, the case and the facilitator's notes. No average, no percentage, no "time saved". The sentence in the writeup is "In an informal exercise with n people, ..." followed by what was seen, and S5 stays STUBBED.
