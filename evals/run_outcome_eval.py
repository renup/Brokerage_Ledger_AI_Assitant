import argparse
import asyncio
import json
import sys
from pathlib import Path

from assistant.clients.embeddings import embed_texts_for_search
from assistant.services.agent import Token, ToolRound
from assistant.services.answer_parts import answer_routed_parts_in_order
from assistant.services.chat_service import ChatService
from assistant.services.routed_parts import route_message_as_one_request
from assistant.services.tool_router import ToolRouter
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


# Runs the whole conversation the way the app does, using the app's own functions so this exam cannot drift from it:
# routing, the forced help search where the route says so, every tool round and the final answer. Only the ledger is
# the demo one. Returns the answer and the names of the tools used, in order.
async def answer_end_to_end(question: str, search_help) -> tuple[str, list[str]]:
    messages = build_messages({"question": question})
    # One request, routed with all the code rules (decline, tax advice, help articles)
    routed_parts = [await route_message_as_one_request(ROUTER, messages, REGISTRY, search_help)]
    # What the tools may use: the demo ledger and the real help search
    context = ToolContext(DemoLedger(), search_help=search_help)
    words, tools_used = [], []
    async for event in answer_routed_parts_in_order(routed_parts, messages, REGISTRY, context):
        if isinstance(event, Token):
            words.append(event.text)
        elif isinstance(event, ToolRound):
            # A finished round of lookups: remember which tools ran
            tools_used += [record.name for record in event.records]
    return "".join(words), tools_used


def find_problems(case: dict, answer: str) -> list[str]:
    lowered = answer.lower()
    problems = [f"missing: {w[0]!r}" for w in case.get("must_state", []) if not any(x.lower() in lowered for x in w)]
    problems += [f"must not say: {w[0]!r}" for w in case.get("must_not_state", []) if any(x.lower() in lowered for x in w)]
    return problems


async def run(cases: list[dict], runs: int) -> list[dict]:
    # The app's own help search (real articles and judge), built once for all cases
    search_help = ChatService(None, None, REGISTRY, ROUTER)._help_search_function_for_tools([])
    # Loads the embedding model first, so the first case does not time out
    await embed_texts_for_search(["warm up"])
    results = []
    for case in cases:
        attempts = []
        for _ in range(runs):
            answer, tools_used = await answer_end_to_end(case["question"], search_help)
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
