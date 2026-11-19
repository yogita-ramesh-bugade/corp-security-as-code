# RFC: What the triage model decides, and what stays human

| | |
| --- | --- |
| **Status** | Proposed |
| **Author** | Yogita Bugade (Security Engineering) |
| **Date** | [date you finish] |
| **Depends on** | Inventory (Step 4.1), risk score (4.2), policy rules (4.3), LLM triage (4.4) |
| **Evidence** | `governance/eval/report.md`, labels in `governance/eval/labels.jsonl`, rubric in `governance/eval/RUBRIC.md` |

<!-- Fill every [bracket] from report.md. Don't round in the model's favour. If a number is
     embarrassing, keep it: the point of this RFC is to show where the model can't be trusted. -->

## 1. Summary

Policy rules decide [48.9]% of Lumen's SaaS and agent inventory on their own. The rest goes to a review queue,
where a local model (Llama 3.1 8B through Ollama) recommends approve, deny or escalate for each item.
I labeled 200 queue items myself, using a rubric written before I saw any model output, and compared.
[One sentence with the headline, e.g.: "Llama 3.1 agreed with my review on [x]% of chat apps but approved
[y] of the [z] OAuth grants I denied, so OAuth grants stay human-reviewed."]

**Decision:** [the handoff table from section 5, in one sentence].

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
3. A regex scanner flags instruction-like text ([x]/[20] injection cases caught, [y] clean items flagged).
4. A code guard: if the scanner fires, or the risk score is 60+, a model "approve" becomes "escalate".
5. A person decides. Text shown in chat can't @-mention people or render links.

## 4. Evaluation

**Set.** 200 items from the review queue: [n] real (from the lab inventory) and [n] synthetic, so every type has
enough examples; 21 of them are injection attempts (20 written for the test, plus QuickNotes AI from Step 4.4),
covering direct orders, fake pre-approval, fake JSON, fake closing tags, a fake publisher, Spanish, base64,
spaced-out letters, HTML comments, fake scan results, fake "trusted context", and rubric-gaming.
Synthetic items are labeled as such in `items.jsonl`.

**Labels.** Mine, with `RUBRIC.md` frozen before the first label (each label records the rubric's fingerprint).
Mix: [approve n / deny n / escalate n].

**Results** (paste the table from report.md):

[table]

**Injection.** On its own, the model approved [n]/21 injection cases. After the code guard, [n] reached a reviewer
as "approve". [Which styles worked, from the "Every false approve" list.]

**Errors I read one by one.** [2-4 sentences: what the false approves had in common. E.g. "All three were OAuth
apps with files.read from unreviewed vendors; the model treated read-only as safe."]

## 5. Handoff rules

| Item type | Model approvals | Model denials | Why |
|---|---|---|---|
| oauth_grant | [human decides / may skip review] | pre-fill, a person confirms | [from report.md] |
| chat_app | [...] | pre-fill, a person confirms | [...] |
| browser_extension | [...] | pre-fill, a person confirms | [...] |
| internal_agent | [...] | pre-fill, a person confirms | [...] |
| admin_role | human decides | human decides | Re-certification is a conversation, not a classification |

A type is handed over only if, after the guard: 0 false approves, 0 injection cases approved, at least 10 of my
denials to test against, and 80%+ agreement. With fewer than 10 denials, "0% false approves" is not evidence:
0 of 5 still leaves a 95% upper bound of about 43%.

Even where approvals are handed over, every model approval is logged, and a weekly sample of [10] goes to a person.

## 6. Risks and open questions

- **Small and partly synthetic set.** [n] items per type is enough to find big problems, not to prove small error
  rates. Synthetic items may be easier or harder than real ones.
- **One labeler.** My labels are the answer key; a second reviewer labeling 50 of the same items would show how
  much reviewers disagree with each other, and the model can't be expected to beat that.
- **Injection set written by me.** An attacker will try styles I didn't think of. The guard and the human click
  matter more than the model's resistance.
- **Model and prompt drift.** Any change to the model or prompt invalidates these numbers; `run_eval.py` re-asks
  the model automatically when the prompt changes. Re-run before changing a handoff rule.
- **Next:** the same evaluation with a Claude backend, side by side ([planned]).
