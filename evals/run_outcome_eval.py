import argparse
import asyncio
import json
import sys
from pathlib import Path

from assistant.services.agent import Token, run_agent
from assistant.services.tool_router import ToolRouter, required_calls_for
from assistant.tools import ALL_TOOLS
from assistant.tools.base import ToolContext
from assistant.tools.registry import ToolRegistry
from evals.demo_ledger import DemoLedger
from evals.run_tool_eval import build_messages

DATASET = Path(__file__).parent / "outcomes.jsonl"
REGISTRY = ToolRegistry(ALL_TOOLS)
ROUTER = ToolRouter()


# One JSON object per line: {"id", "question"} plus "must_state" (facts that must appear; each fact is a list of
# acceptable wordings) and optionally "must_not_state" (wordings that must NOT appear). The facts are worked out from
# the numbers in evals/demo_ledger.py, so a case is only as right as that arithmetic.
def load_cases(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


# Runs the whole conversation (router, every tool round, final answer) against the demo ledger and returns the answer
# and the names of the tools used, in order.
async def answer_end_to_end(question: str) -> tuple[str, list[str]]:
    messages = build_messages({"question": question})
    registry, groups = await ROUTER.choose_registry_and_groups(messages, REGISTRY)
    words, tools_used = [], []
    async for event in run_agent(messages, registry, ToolContext(DemoLedger()), required_calls_for(groups, messages)):
        if isinstance(event, Token):
            words.append(event.text)
        elif hasattr(event, "records"):
            tools_used += [record.name for record in event.records]
    return "".join(words), tools_used


def find_problems(case: dict, answer: str) -> list[str]:
    lowered = answer.lower()
    problems = [f"missing: {w[0]!r}" for w in case.get("must_state", []) if not any(x.lower() in lowered for x in w)]
    problems += [f"must not say: {w[0]!r}" for w in case.get("must_not_state", []) if any(x.lower() in lowered for x in w)]
    return problems


async def run(cases: list[dict], runs: int) -> list[dict]:
    results = []
    for case in cases:
        attempts = []
        for _ in range(runs):
            answer, tools_used = await answer_end_to_end(case["question"])
            attempts.append({"tools": tools_used, "answer": answer, "problems": find_problems(case, answer)})
        passed = sum(not a["problems"] for a in attempts)
        label = "PASS " if passed == runs else "FAIL " if passed == 0 else "FLAKY"
        print(f"{label} {passed}/{runs}  {case['id']:<7} {case['question'][:50]:<50} tools={[a['tools'] for a in attempts]}")
        for attempt in attempts:
            if attempt["problems"]:
                print(f"        {attempt['problems']}  answer: {attempt['answer'][:140]!r}")
        results.append({**case, "attempts": attempts})
    return results


def main() -> int:
    parser = argparse.ArgumentParser(description="Score the customer's final answer, not just the tools chosen.")
    parser.add_argument("--dataset", type=Path, default=DATASET)
    parser.add_argument("--runs", type=int, default=2)
    parser.add_argument("--min-score", type=float, default=80.0)
    options = parser.parse_args()
    results = asyncio.run(run(load_cases(options.dataset), options.runs))
    attempts = [a for r in results for a in r["attempts"]]
    score = round(100 * sum(not a["problems"] for a in attempts) / len(attempts), 1)
    print(f"\nend-to-end outcome {score}")
    return 0 if score >= options.min_score else 1


if __name__ == "__main__":
    sys.exit(main())
