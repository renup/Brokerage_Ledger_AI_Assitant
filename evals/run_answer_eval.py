import argparse
import asyncio
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

from assistant.clients.embeddings import embed_texts_for_search
from assistant.config import settings
from assistant.llm import ToolCall, stream_turn, tool_request_message, tool_result_message
from assistant.services.chat_service import ChatService
from assistant.services.tool_router import ToolRouter, required_calls_for
from assistant.tools import ALL_TOOLS
from assistant.tools.base import ToolContext
from assistant.tools.registry import ToolRegistry
from evals.run_tool_eval import build_messages

DATASET = Path(__file__).parent / "answer_quality.jsonl"
ARTICLES_FOLDER = Path(__file__).parent.parent / "assistant" / "knowledge" / "help_center"
REGISTRY = ToolRegistry(ALL_TOOLS)
ROUTER = ToolRouter()

# Phrases that count as an honest "I don't know". The model words this differently each time.
ADMITS_IT_DOES_NOT_KNOW = [
    "don't have", "do not have", "doesn't say", "does not say", "not sure", "no information",
    "can't find", "cannot find", "unable to", "not able to", "can't help with", "cannot help with",
    "can only help", "only help with", "connect you", "speak to a person", "talk to a person",
]


# One JSON object per line: {"id", "question"} plus any of: "must_state" (a list of facts; each fact is a list
# of acceptable wordings), "must_say_unknown": true (the help center has nothing on it), "must_cite" (titles of
# the articles that must come back as sources) or "must_cite_nothing": true (no article should come back)
def load_cases(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


# The title of every article, e.g. "Moving money to your bank": the first line of each file without its "# "
def all_article_titles() -> list[str]:
    return [path.read_text(encoding="utf-8").splitlines()[0].lstrip("# ").strip() for path in ARTICLES_FOLDER.glob("*.md")]


# Numbers as plain digits ("$25,000." -> "25000"), so "25,000" in an answer matches "25,000" in a passage
def numbers_in(text: str) -> set[str]:
    return {found.replace(",", "").rstrip(".") for found in re.findall(r"\d[\d,]*\.?\d*", text)}


# Mirrors one chat turn: the router picks the route, the code runs the required help search, then the model
# writes the answer. Returns the answer, the passages the model was given, and the route words.
async def answer_like_the_app(question: str, search_help) -> tuple[str, list[dict], str]:
    messages = build_messages({"question": question})
    registry, groups = await ROUTER.choose_registry_and_groups(messages, REGISTRY)
    route = ",".join(sorted(g.value for g in groups)) if groups is not None else "all"
    context = ToolContext(ledger=None, search_help=search_help)

    passages = []
    required = required_calls_for(groups, messages)
    if required:
        results = [await registry.execute(context, call.name, call.arguments) for call in required]
        messages.append(tool_request_message((c.id, c.name, c.arguments) for c in required))
        for call, result in zip(required, results):
            messages.append(tool_result_message(call.id, result))
            # The registry wraps a successful result as {"tool", "note", "data": {...}}; the passages are inside "data"
            passages += json.loads(result).get("data", {}).get("passages", [])

    words = []
    async for item in stream_turn(messages, registry.definitions()):
        # A further tool request is not an answer; the empty answer then fails the case
        if not isinstance(item, ToolCall):
            words.append(item)
    return "".join(words), passages, route


# Checks one answer. Returns the list of problems (empty = good).
def find_problems(case: dict, answer: str, passages: list[dict]) -> list[str]:
    problems = []
    lowered = answer.lower()
    if not answer.strip():
        return ["no answer"]

    # The articles the search returned: exactly what the app announces to the customer as sources
    returned = {p["article"] for p in passages}

    for wordings in case.get("must_state", []):
        if not any(wording.lower() in lowered for wording in wordings):
            problems.append(f"missing fact: {wordings[0]!r}")

    if case.get("must_say_unknown") and not any(phrase in lowered for phrase in ADMITS_IT_DOES_NOT_KNOW):
        problems.append("did not admit it has no information")

    # Sources: every article the case names must be among the ones returned (retrieval found the right place)
    for title in case.get("must_cite", []):
        if title not in returned:
            problems.append(f"sources missing article: {title!r}")

    # For a question the help center cannot answer, the app must have nothing to cite
    if case.get("must_cite_nothing") and returned:
        problems.append(f"sources should be empty but were: {sorted(returned)}")

    # Every number in the answer must come from the question or a passage; anything else was invented
    allowed = numbers_in(case["question"]) | numbers_in(" ".join(p["text"] for p in passages))
    invented = numbers_in(answer) - allowed
    if invented:
        problems.append(f"numbers not in the passages: {sorted(invented)}")

    # An article may be named only if the search returned it
    for title in all_article_titles():
        if title.lower() in lowered and title not in returned:
            problems.append(f"named an article it was not given: {title!r}")
    return problems


async def run(cases: list[dict], runs: int) -> list[dict]:
    # The app's own search function, so the eval retrieves exactly as a real chat does (real Ollama, indexed dev database)
    search_help = ChatService(None, None, REGISTRY, ROUTER)._help_search_function_for_tools([])
    # The first embedding after Ollama has been idle loads the embedding model (about 20 seconds), far longer than the
    # search tool's 2-second limit. Load it once now so the cases measure answers, not that cold start.
    await embed_texts_for_search(["warm up"])
    results = []
    for case in cases:
        attempts = []
        for _ in range(runs):
            answer, passages, route = await answer_like_the_app(case["question"], search_help)
            attempts.append({"route": route, "answer": answer, "problems": find_problems(case, answer, passages)})
        results.append({"id": case["id"], "question": case["question"], "attempts": attempts})

        passed = sum(not a["problems"] for a in attempts)
        label = "PASS " if passed == runs else "FAIL " if passed == 0 else "FLAKY"
        print(f"{label} {passed}/{runs}  {case['id']:<6} {case['question'][:48]:<48} route={attempts[0]['route']}")
        for attempt in attempts:
            if attempt["problems"]:
                print(f"        {attempt['problems']}  answer: {attempt['answer'][:110]!r}")
    return results


def main() -> int:
    parser = argparse.ArgumentParser(description="Score whether help-center answers stay inside the passages.")
    parser.add_argument("--dataset", type=Path, default=DATASET)
    parser.add_argument("--runs", type=int, default=2, help="how many times to ask each question")
    parser.add_argument("--min-score", type=float, default=80.0)
    options = parser.parse_args()

    results = asyncio.run(run(load_cases(options.dataset), options.runs))
    attempts = [a for r in results for a in r["attempts"]]
    score = round(100 * sum(not a["problems"] for a in attempts) / len(attempts), 1)
    print(f"\nanswer quality {score}")

    results_dir = Path(__file__).parent / "results"
    results_dir.mkdir(exist_ok=True)
    report = {"ran_at": datetime.now(timezone.utc).isoformat(timespec="seconds"), "model": settings.llm_model, "score": score, "cases": results}
    (results_dir / "answers_latest.json").write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
    return 0 if score >= options.min_score else 1


if __name__ == "__main__":
    sys.exit(main())
