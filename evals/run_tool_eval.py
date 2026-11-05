"""Scores which tools the model chooses (and with what arguments) for a list of example questions.

Run from the repo root:   uv run python -m evals.run_tool_eval
It asks the REAL model each question in evals/tools.jsonl, but never runs the tools: we only
measure what the model DECIDES to do. Exit code 0 = good enough, 1 = score too low (for CI).
"""

import argparse
import asyncio
import hashlib
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

from assistant.config import settings
from assistant.llm import ToolCall, stream_turn
from assistant.models import Message
from assistant.services.chat_service import system_prompt
from assistant.services.history import trim_to_budget
from assistant.services.tool_router import ToolRouter, router_prompt
from assistant.tools import ALL_TOOLS
from assistant.tools.registry import ToolRegistry

# The same tool menu and the same system prompt the real app uses, so we test what customers get
REGISTRY = ToolRegistry(ALL_TOOLS)
# The same router the app uses, so evals measure routing and the model's tool choice together
ROUTER = ToolRouter()
TOOLS_BY_NAME = {tool.name: tool for tool in ALL_TOOLS}


# One JSON object per line: {"id", "category", "question", "expected_tools", "expected_args"},
# plus optional "history" and optional "alternatives": [{"tools": [...], "args": {...}}]
def load_cases(path: Path) -> list[dict]:
    with open(path, encoding="utf-8") as f:
        return [json.loads(line) for line in f if line.strip()]


# A fixed time stamped on the canned lookups, so the replayed "Looked up at" label reads like a real one
HISTORY_TIME = "2026-11-01T10:00:00+00:00"


# Turns a case into the messages the model receives, using the app's own history code
# (replay and token trimming), so we test exactly what a real follow-up looks like.
# A case with no "history" is a single question, as before.
def build_messages(case: dict) -> list[dict]:
    rows = []
    for turn in case.get("history", []):
        # The lookups the assistant is pretending to have made in that earlier turn
        records = [
            {
                "id": f"h{len(rows)}-{n}",
                "name": lookup["tool"],
                "arguments": json.dumps(lookup["arguments"]),
                "result": REGISTRY.data_result(lookup["tool"], lookup["data"]),
            }
            for n, lookup in enumerate(turn.get("lookups", []))
        ]
        trace = [{"records": records, "at": HISTORY_TIME}] if records else []
        rows.append(
            Message(
                message_id=str(len(rows)), session_id="eval", customer_id_hash="eval",
                role=turn["role"], text=turn["text"], tool_trace_json=json.dumps(trace),
            )
        )
    # The question being scored is the newest message
    rows.append(
        Message(message_id=str(len(rows)), session_id="eval", customer_id_hash="eval", role="user", text=case["question"])
    )

    rules = system_prompt().replace("{first_name}", "Maya")
    # trim_to_budget wants newest first, the order the repository returns them in
    history = trim_to_budget(list(reversed(rows)), settings.history_token_budget)
    return [{"role": "system", "content": rules}] + history


# Asks the model one question, the way the app does: first the router narrows the menu, then the
# model answers with only those tools on offer. Returns the tools it asked for (an empty list = it
# answered in words), what it said, and the names of the tools that were on offer.
async def ask_model(case: dict, use_router: bool = True) -> tuple[list[ToolCall], str, list[str]]:
    messages = build_messages(case)
    registry = await ROUTER.registry_for_message(messages, REGISTRY) if use_router else REGISTRY
    calls = []
    words = []
    async for item in stream_turn(messages, registry.definitions()):
        # Tool requests are what we score; the words are kept as evidence
        if isinstance(item, ToolCall):
            calls.append(item)
        else:
            # Keep the words too; they are the evidence when a case fails
            words.append(item)
    return calls, "".join(words), registry.tool_names()


# The arguments the model sent, cleaned up by the tool's own Pydantic class. That fills in
# defaults (an omitted "status" becomes "all"), so "left it out" and "said all" score the same.
# Returns None if the arguments were invalid.
def normalized_args(call: ToolCall) -> dict | None:
    try:
        return TOOLS_BY_NAME[call.name].args_model.model_validate(json.loads(call.arguments or "{}")).model_dump()
    except Exception:
        return None


# Checks one acceptable answer (a set of tools, and optionally the arguments each must have) against
# what the model did. Returns (choice_ok, args_ok); args_ok is None when no arguments are listed.
def check_expectation(expected_tools: list[str], expected_args: dict, called: dict[str, ToolCall]) -> tuple[bool, bool | None]:
    # Right tools means exactly the expected set: none missing, none extra
    choice_ok = set(called) == set(expected_tools)

    # Only answers that list expected_args are checked on arguments (None = not applicable)
    args_ok = None
    if expected_args:
        args_ok = choice_ok
        for name, expected in expected_args.items():
            actual = normalized_args(called[name]) if name in called else None
            # Every argument we listed must match; extra arguments the model added are ignored
            if actual is None or any(actual.get(key) != value for key, value in expected.items()):
                args_ok = False
    return choice_ok, args_ok


# Compares what the model did with what we expected, for one question.
# A case has one main answer ("expected_tools") and, optionally, "alternatives": other answers that
# are just as correct (for example looking up an error code directly instead of the whole transfer).
# The model passes if it matches ANY of them.
def score_case(case: dict, calls: list[ToolCall], words: str, offered: list[str] | None = None) -> dict:
    called = {call.name: call for call in calls}

    main = {"tools": case["expected_tools"], "args": case["expected_args"]}
    acceptable = [main] + case.get("alternatives", [])
    checks = [check_expectation(a["tools"], a.get("args", {}), called) for a in acceptable]
    # The first answer it fully matches; if none, report against the main answer
    matched = next((i for i, (choice_ok, args_ok) in enumerate(checks) if choice_ok and args_ok is not False), None)
    choice_ok, args_ok = checks[matched if matched is not None else 0]
    # Was the right answer even possible? True when some acceptable answer used only tools that were on
    # offer. A False here means the ROUTER left a needed tool out; a False "passed" with a True here
    # means the MODEL chose badly. (None when no menu was recorded.)
    menu_ok = None if offered is None else any(set(a["tools"]) <= set(offered) for a in acceptable)

    return {
        "id": case["id"],
        "category": case["category"],
        "question": case["question"],
        "expected_tools": case["expected_tools"],
        "called_tools": sorted(called),
        "called_args": {name: normalized_args(call) for name, call in called.items()},
        "choice_ok": choice_ok,
        "args_ok": args_ok,
        # 0 = the main answer, 1+ = an alternative, None = no match (shown in the saved report)
        "matched_answer": matched,
        "offered_tools": offered,
        "menu_ok": menu_ok,
        "passed": matched is not None,
        "reply_text": words[:300],  # the model's first 300 characters, to see WHY a case failed
    }


# "7 of 8" as a percentage; an empty group counts as 100 so it can't drag the score down
def percent(hits: int, total: int) -> float:
    return round(100 * hits / total, 1) if total else 100.0


def summarize(results: list[dict]) -> dict:
    no_tool = [r for r in results if not r["expected_tools"]]
    with_args = [r for r in results if r["args_ok"] is not None]
    # question id -> a True/False for each try. A question is flaky when some tries pass and some fail.
    outcomes = {}
    for r in results:
        outcomes.setdefault(r["id"], []).append(r["passed"])
    return {
        "cases": len(outcomes),
        "attempts": len(results),
        "flaky_cases": sum(0 < sum(tries) < len(tries) for tries in outcomes.values()),
        # A case passes only if the tools AND their arguments were right
        "overall": percent(sum(r["passed"] for r in results), len(results)),
        "tool_choice": percent(sum(r["choice_ok"] for r in results), len(results)),
        "arguments": percent(sum(r["args_ok"] for r in with_args), len(with_args)),
        # "How long does an IRA transfer take?" must NOT trigger an account lookup
        "no_tool_when_not_needed": percent(sum(r["choice_ok"] for r in no_tool), len(no_tool)),
        # How often the routed menu still contained what the case needed (100 when routing is off)
        "router_menu_ok": percent(sum(r["menu_ok"] is not False for r in results), len(results)),
    }


# A short code that changes whenever the system prompt or the tool menu changes, saved in the report
# so a score can always be traced back to exactly what was tested
def fingerprint() -> str:
    text = system_prompt() + router_prompt() + json.dumps(REGISTRY.definitions(), sort_keys=True)
    return hashlib.sha256(text.encode()).hexdigest()[:12]


# Asks the model one question once and scores what it did
async def one_try(case: dict, use_router: bool) -> dict:
    calls, words, offered = await ask_model(case, use_router)
    return score_case(case, calls, words, offered)


# Asks every question "runs" times. The model has some randomness, so one try proves little;
# several tries show how reliable it is.
async def run(cases: list[dict], runs: int, use_router: bool = True) -> list[dict]:
    results = []
    for case in cases:
        # One scored result per try (a list built with await inside it works in an async function)
        attempts = [await one_try(case, use_router) for _ in range(runs)]
        results.extend(attempts)

        passes = sum(a["passed"] for a in attempts)
        # All tries right = reliable. None right = broken. In between = flaky.
        label = "PASS " if passes == runs else "FAIL " if passes == 0 else "FLAKY"
        print(f"{label} {passes}/{runs}  {case['id']:<9} {case['question'][:44]:<44} expected={case['expected_tools']} got={[a['called_tools'] for a in attempts]}")
    return results


def main() -> int:
    parser = argparse.ArgumentParser(description="Score the model's tool choices.")
    parser.add_argument("--dataset", type=Path, default=Path(__file__).parent / "tools.jsonl")
    parser.add_argument("--min-score", type=float, default=80.0, help="fail (exit 1) if the overall score is lower")
    parser.add_argument("--limit", type=int, help="run only the first N cases")
    parser.add_argument("--no-router", action="store_true", help="offer every tool to the model, as before routing existed")
    parser.add_argument("--runs", type=int, default=3, help="how many times to ask each question")
    options = parser.parse_args()

    # [: None] keeps everything, so --limit is optional
    cases = load_cases(options.dataset)[: options.limit]
    results = asyncio.run(run(cases, options.runs, use_router=not options.no_router))
    scores = summarize(results)

    print("\n" + "\n".join(f"{name:<26}{value}" for name, value in scores.items()))

    # Save the full report (every case, what was expected, what happened) for inspecting failures
    results_dir = Path(__file__).parent / "results"
    results_dir.mkdir(exist_ok=True)
    report = {
        "ran_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "model": settings.llm_model,
        "fingerprint": fingerprint(),
        "scores": scores,
        "cases": results,
    }
    (results_dir / "latest.json").write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")

    # The exit code is what lets CI block a change that makes the assistant worse
    if scores["overall"] < options.min_score:
        print(f"\nFAILED: overall {scores['overall']} is below the minimum {options.min_score}")
        return 1
    print(f"\nOK: overall {scores['overall']} meets the minimum {options.min_score}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
