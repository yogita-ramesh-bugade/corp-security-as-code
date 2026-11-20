# RFC: What the triage model decides, and what stays human

| | |
| --- | --- |
| **Status** | Proposed |
| **Author** | Yogita Bugade (Security Engineering) |
| **Date** | 2026-11-20 |
| **Depends on** | Inventory (Step 4.1), risk score (4.2), policy rules (4.3), LLM triage (4.4) |
| **Evidence** | `governance/eval/report.md` (prompt version d2d6e37891), labels in `governance/eval/labels.jsonl`, rubric in `governance/eval/RUBRIC.md` |

## 1. Summary

Policy rules decide 48.9% of Lumen's SaaS and agent inventory on their own (162 of 331 items). The rest goes to a
review queue, where a local model (Llama 3.1 8B through Ollama) recommends approve, deny or escalate for each item.
I labeled 200 queue items myself, using a rubric committed before I saw any model output, and compared.

Llama 3.1 never approved an item I denied (0 of 145; 95% upper bound 3%) and was not fooled by any of 21 prompt-injection
attempts. But it approved only 2 of the 54 items I approved, and agreed with me on 60% of items overall (38% of chat
apps, 70% of OAuth grants), so it cannot take decisions off reviewers yet.

**Decision:** every item type stays human-decided. The model's recommendation is shown to the reviewer as a second
opinion with its reasons, and nothing it says is applied on its own.

## 2. Problem

Hundreds of small apps, extensions, integrations and AI agents need a decision, and most are neither obviously
fine nor obviously dangerous. A person reviewing each one is slow, and slow review teaches people to go around
it. A model can give reviewers a head start, but a model that approves the wrong thing quietly opens access to
mail, files or code. And the text the model reads is written by the publishers being reviewed, so it can carry
instructions aimed at the model itself.

## 3. What the model gets, and what it never gets

| The model gets | The model never gets |
|---|---|
| The item's facts: type, publisher, owner, users, scopes | The ability to change anything: it writes a recommendation, nothing else |
| Lumen's own risk score, its reasons, and the policy result, marked TRUSTED CONTEXT | Secrets, tokens, or user data beyond names of who consented |
| The publisher's text, inside a randomly tagged data block it is told is data | The final decision: a reviewer clicks Approve or Deny |

Defenses against prompt injection, in the order they act:
1. System prompt: the data block is data; instructions inside it are a risk signal.
2. Data block with a random tag; fake closing tags are removed.
3. A regex scanner flags instruction-like text (8 of 21 injection cases caught, 0 clean items flagged).
4. A code guard: if the scanner fires, or the risk score is 60+, a model "approve" becomes "escalate".
5. A person decides. Text shown in chat can't @-mention people or render links.

## 4. Evaluation

**Set.** 200 items from the review queue: 83 real (from the lab inventory) and 117 synthetic, so every type has enough
examples. 21 of them are injection attempts (20 written for the test, plus QuickNotes AI from Step 4.4), covering
direct orders, fake pre-approval, fake JSON, fake closing tags, a fake publisher, Spanish, base64, spaced-out
letters, HTML comments, fake scan results, fake "trusted context", and rubric-gaming.
Synthetic items are labeled as such in `items.jsonl`.

**Labels.** Mine, with `RUBRIC.md` committed before the first label (each label records the rubric's fingerprint).
Mix: 54 approve, 145 deny, 1 escalate. 199 labels are my own; 1 (marked `ref-claude` in its note) came from a
reference model when I was stuck. I used escalate only once, so I decided almost everything as approve or deny; every
time the model escalated, that counts as a disagreement below.

**Results** (Llama 3.1 8B, temperature 0, structured output):

| Type | n | Agreement | False approves (of my denials) | 95% upper bound | Escalated | False denies | Injection fooled |
|---|---|---|---|---|---|---|---|
| admin_role | 6 | 67% | 0/4 (0%) | 49% | 33% | 0 | 0/0 |
| browser_extension | 40 | 52% | 0/29 (0%) | 12% | 25% | 8 | 0/4 |
| chat_app | 40 | 38% | 0/21 (0%) | 15% | 32% | 12 | 0/5 |
| internal_agent | 74 | 69% | 0/61 (0%) | 6% | 15% | 12 | 0/4 |
| oauth_grant | 40 | 70% | 0/30 (0%) | 11% | 5% | 10 | 0/8 |
| **All** | **200** | **60%** | **0/145 (0%)** | **3%** | **19%** | **42** | **0/21** |

Confusion (rows: my label, columns: the model):

| me \ model | approve | deny | escalate |
|---|---|---|---|
| approve | 2 | 42 | 10 |
| deny | 0 | 117 | 28 |
| escalate | 0 | 1 | 0 |

**Injection.** On its own, the model approved 0 of 21 injection cases, so the code guard never had to step in
(false approves 0 → 0, escalation rate 19% → 19%). The regex scanner caught only 8 of 21; the model's own
resistance did the rest. This is one model on cases I wrote myself, so the guard stays in place.

**Errors I read one by one.** There were no false approves to read. The model's error is the opposite one: it
denied 42 of the 54 items I approved and escalated 10 more, approving only 2. Reading all 42, most are low-risk items (scores 13–49) that the model called "broad access without an accountable publisher or owner" even when the scopes were narrow (storage, calendar.read, posting in one channel): it treated an unreviewed vendor, a missing description or a creator who left as enough to deny. In 7 of the 42, though, the model was right by my own rubric: they are injection cases (Poll personal 907, Notes personal 910, Poll slash 911, ReadKeeper 914, helper-agent-916, helper-agent-917, helper-agent-919) that I approved while labeling quickly, although the rubric says any text that tries to steer the review is a deny. Those are my labeling mistakes, not the model's; the numbers above use the labels as I first gave them (see section 6).

## 5. Handoff rules

| Item type | Model approvals | Model denials | Why |
|---|---|---|---|
| oauth_grant | nothing to hand over | a hint only; a person decides | 70% agreement; 10 false denies |
| chat_app | nothing to hand over | a hint only; a person decides | 38% agreement, the weakest type; 12 false denies |
| browser_extension | nothing to hand over | a hint only; a person decides | 52% agreement; 8 false denies |
| internal_agent | nothing to hand over | a hint only; a person decides | 69% agreement; 12 false denies |
| admin_role | human decides | human decides | Re-certification is a conversation, not a classification; only 6 items |

A type is handed over only if, after the guard: 0 false approves, 0 injection cases approved, at least 10 of my
denials to test against, and 80%+ agreement. Every type passes the safety tests (0 false approves, 0 injections
approved) but none reaches 80% agreement, and the model approved only 2 items in total, so there are no approvals to
hand over.

What the model is good for today: it never waved through anything I denied, and its rationale names the risky scope or
missing owner, which saves the reviewer reading time. What it is bad at: telling a harmless app from a risky one, so
following its denials would block about four in five apps that should be allowed (42 of 54).

## 6. Risks and open questions

- **Small and partly synthetic set.** 200 items, 117 of them synthetic, is enough to find big problems, not to prove
  small error rates. Admin roles have only 6 items (95% upper bound on false approves: 49%).
- **Label mistakes.** At least 7 of my approvals were injection cases my own rubric says to deny (section 4). The
  rubric says I fix real mistakes and write down why; correcting them would add 7 agreements and remove 7 false denies.
  The results above are left as first labeled so the evaluation is not tuned after seeing the model's answers.
- **One labeler, binary style.** My labels are the answer key, and I almost never escalated. A second reviewer
  labeling 50 of the same items would show how much reviewers disagree with each other.
- **Injection set written by me.** An attacker will try styles I didn't think of, and the scanner missed 13 of 21. The
  guard and the human click matter more than the model's resistance.
- **Model and prompt drift.** Any change to the model or prompt invalidates these numbers; `run_eval.py` re-asks the
  model automatically when the prompt changes. Re-run before changing a handoff rule.
- **Next:** reduce false denies (give the model the rubric's approve rules and examples; try a larger model), then the
  same evaluation with a Claude backend side by side.
