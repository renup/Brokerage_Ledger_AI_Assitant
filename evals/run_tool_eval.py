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
from assistant.services.chat_service import system_prompt
from assistant.tools.read import READ_TOOLS
from assistant.tools.registry import ToolRegistry

# The same tool menu and the same system prompt the real app uses, so we test what customers get
REGISTRY = ToolRegistry(READ_TOOLS)
TOOLS_BY_NAME = {tool.name: tool for tool in READ_TOOLS}


# One JSON object per line: {"id", "category", "question", "expected_tools", "expected_args"}
def load_cases(path: Path) -> list[dict]:
    with open(path, encoding="utf-8") as f:
        return [json.loads(line) for line in f if line.strip()]


# Asks the model one question and returns the tools it asked for (an empty list = it answered in words)
async def ask_model(question: str) -> list[ToolCall]:
    rules = system_prompt().replace("{first_name}", "Maya")
    messages = [{"role": "system", "content": rules}, {"role": "user", "content": question}]
    calls = []
    async for item in stream_turn(messages, REGISTRY.definitions()):
        # Words are ignored; we only care about the tool requests
        if isinstance(item, ToolCall):
            calls.append(item)
    return calls


# The arguments the model sent, cleaned up by the tool's own Pydantic class. That fills in
# defaults (an omitted "status" becomes "all"), so "left it out" and "said all" score the same.
# Returns None if the arguments were invalid.
def normalized_args(call: ToolCall) -> dict | None:
    try:
        return TOOLS_BY_NAME[call.name].args_model.model_validate(json.loads(call.arguments or "{}")).model_dump()
    except Exception:
        return None


# Compares what the model did with what we expected, for one question
def score_case(case: dict, calls: list[ToolCall]) -> dict:
    called = {call.name: call for call in calls}
    # Right tools means exactly the expected set: none missing, none extra
    choice_ok = set(called) == set(case["expected_tools"])

    # Only questions that list expected_args are checked on arguments (None = not applicable)
    args_ok = None
    if case["expected_args"]:
        args_ok = choice_ok
        for name, expected in case["expected_args"].items():
            actual = normalized_args(called[name]) if name in called else None
            # Every argument we listed must match; extra arguments the model added are ignored
            if actual is None or any(actual.get(key) != value for key, value in expected.items()):
                args_ok = False

    return {
        "id": case["id"],
        "category": case["category"],
        "question": case["question"],
        "expected_tools": case["expected_tools"],
        "called_tools": sorted(called),
        "called_args": {name: normalized_args(call) for name, call in called.items()},
        "choice_ok": choice_ok,
        "args_ok": args_ok,
        "passed": choice_ok and args_ok is not False,
    }


# "7 of 8" as a percentage; an empty group counts as 100 so it can't drag the score down
def percent(hits: int, total: int) -> float:
    return round(100 * hits / total, 1) if total else 100.0


def summarize(results: list[dict]) -> dict:
    no_tool = [r for r in results if not r["expected_tools"]]
    with_args = [r for r in results if r["args_ok"] is not None]
    return {
        "cases": len(results),
        # A case passes only if the tools AND their arguments were right
        "overall": percent(sum(r["passed"] for r in results), len(results)),
        "tool_choice": percent(sum(r["choice_ok"] for r in results), len(results)),
        "arguments": percent(sum(r["args_ok"] for r in with_args), len(with_args)),
        # "How long does an IRA transfer take?" must NOT trigger an account lookup
        "no_tool_when_not_needed": percent(sum(r["choice_ok"] for r in no_tool), len(no_tool)),
    }


# A short code that changes whenever the system prompt or the tool menu changes, saved in the report
# so a score can always be traced back to exactly what was tested
def fingerprint() -> str:
    text = system_prompt() + json.dumps(REGISTRY.definitions(), sort_keys=True)
    return hashlib.sha256(text.encode()).hexdigest()[:12]


# One question at a time (a local model handles one request at a time anyway)
async def run(cases: list[dict]) -> list[dict]:
    results = []
    for case in cases:
        results.append(score_case(case, await ask_model(case["question"])))
        mark = "PASS" if results[-1]["passed"] else "FAIL"
        print(f"{mark}  {case['id']:<9} {case['question'][:48]:<48} expected={case['expected_tools']} got={results[-1]['called_tools']}")
    return results


def main() -> int:
    parser = argparse.ArgumentParser(description="Score the model's tool choices.")
    parser.add_argument("--dataset", type=Path, default=Path(__file__).parent / "tools.jsonl")
    parser.add_argument("--min-score", type=float, default=80.0, help="fail (exit 1) if the overall score is lower")
    parser.add_argument("--limit", type=int, help="run only the first N cases")
    options = parser.parse_args()

    # [: None] keeps everything, so --limit is optional
    cases = load_cases(options.dataset)[: options.limit]
    results = asyncio.run(run(cases))
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
