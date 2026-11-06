# Writing evals: a guide for the person who owns them

An eval is an exam for the assistant. You write questions, say what a correct response looks like, and a runner scores the real model against them. The scores tell you whether a change made the assistant better or worse. If the person who fixes the assistant also writes the exam, the exam gets easy without anyone noticing, which is why you own this one.

## The job in one loop

1. Write cases the assistant has never seen (below).
2. Run them, read every failure.
3. For each failure, decide whose fault it is **before** touching anything:

| Symptom in the report | Likely cause | Where the fix goes |
|---|---|---|
| `router_menu_ok` is low for that case | The router sent the message to the wrong group | `assistant/prompts/router.md` |
| Right menu, wrong tool or wrong arguments | Tool description or system prompt | `assistant/tools/<tool>.py`, `system.md` |
| Right tool, wrong or invented answer | Retrieval or the answering prompt | `help_center_service.py`, the search note |
| The case itself is ambiguous or wrong | The exam | Fix the case, and say why |

4. Change **one** thing, re-run **all** the sets (a change to one prompt shifts the others), compare.
5. Keep a line in your notes: what failed, what you thought, what you changed, what moved.

## What makes a good case

- **One clear right answer.** If two tools would be fine, list the second as an `alternatives` entry rather than guessing.
- **Wording a customer would really use.** Typos, short messages, "hey", "ok and..." are all fair. Do not copy the phrasing from the router examples or from the other eval files.
- **It must be able to fail.** If you cannot imagine the model getting it wrong, it teaches nothing.
- **Never edit a case to make it pass.** Edit it only if the case was wrong, and write down why.
- **Do not tune on your sealed set.** Look at its score, but do not copy its phrasing into prompts. Once you have fixed things using a case, it is "burned" and you write a replacement.

## The format (one JSON object per line)

```json
{"id": "sealed-01", "category": "fees", "question": "what does it cost to leave for another broker", "expected_tools": ["get_fees"], "expected_args": {}}
```

- `expected_tools`: the tools the model should call. `[]` means it should answer in words, with no lookup.
- `expected_args`: arguments that must match, keyed by tool name, for example `{"get_transfer_status": {"transfer_id": 7}}`. Use `{}` to skip the check.
- `alternatives`: other equally correct answers, for example `[{"tools": ["search_help_center"], "args": {}}]`.
- `history`: for follow-ups, earlier turns with their `lookups` (look at `evals/tools_multiturn.jsonl` for the shape).

## What to cover: 20 cases

The tools that the existing sets test least are listed first, so spend more cases there.

| Area | Cases | Ideas |
|---|---|---|
| Fees (`get_fees`) vs help (`search_help_center`) | 3 | "what does X cost" vs "how does X work". The boundary is where models slip. |
| Tax documents and `estimate_arrival` | 3 | Where is my form vs what is a form; when does money arrive. |
| Propose tools (retry, cancel, name change) | 4 | Clear requests, and vague ones ("fix it") where the right answer is to ask. |
| Eligibility and human hand-off | 3 | "can I take out 30k", "get me a person", a complaint. |
| Follow-ups with history | 4 | "that one", "and the other one", a number said in words. |
| Should do nothing | 3 | Thanks, small talk, a stock tip request, someone else's account. |

At least 5 of the 20 should be hard in a way you can explain: a message that sounds like one tool but needs another.

## Rules of engagement

- Save your cases as `evals/tools_sealed.jsonl`. I will not open it unless you ask.
- Run it yourself: `uv run python -m evals.run_tool_eval --dataset evals/tools_sealed.jsonl --runs 2`
- Paste me only what you want help with (usually the failing lines). I will ask what you think the cause is first.
- Before running, write down your **guess** of the score. Comparing guess to result is how your sense for the model's weak spots develops.

## Words you will hear

- **Held-out / sealed set**: questions nobody tunes against, so the score stays honest.
- **Burned case**: a case you used to fix something, so it no longer measures anything fresh.
- **Regression**: a case that used to pass and now fails after a change.
- **Flaky**: passes some runs and fails others; one run proves nothing.
- **Baseline**: the last accepted scores, which a CI gate later compares against (phase 12).
