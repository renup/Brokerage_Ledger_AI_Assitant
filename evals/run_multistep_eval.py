"""Measures whether the router sends a question that needs several areas to ALL of them.

Today the router returns one set of groups for the whole message. A multi-step question passes when every area the
case lists is among them. This is the baseline the multi-agent design must beat; nothing here changes the app.

    env -u VIRTUAL_ENV PYTHONPATH=. uv run python -m evals.run_multistep_eval --runs 3
    env -u VIRTUAL_ENV PYTHONPATH=. uv run python -m evals.run_multistep_eval --runs 3 --by-parts

With --by-parts the message is split into parts first and each part is routed on its own; the routes of all the
parts together are what is compared with the areas the case lists.
"""
import argparse
import asyncio
from pathlib import Path

from assistant.clients.embeddings import embed_texts_for_search
from assistant.services.chat_service import ChatService
from assistant.services.routed_parts import split_and_route_message
from assistant.tools.base import ToolGroup
from evals.run_answer_eval import REGISTRY, ROUTER, load_cases, route_like_the_app
from evals.run_tool_eval import build_messages

DATASET = Path(__file__).parent / "multistep.jsonl"


# The groups that satisfy one expected area. Help is satisfied by a reference route too, because the app adds the
# help articles to every reference route.
def groups_that_cover(area: str) -> set[ToolGroup]:
    covering = {ToolGroup(area)} if area != "help" else {ToolGroup.HELP_CENTER, ToolGroup.REFERENCE}
    return covering


# The areas the case lists that the route does not cover
def areas_missing_from(route: set[ToolGroup] | None, areas: list[str]) -> list[str]:
    # None means every tool was offered, so no area is missing (but nothing was routed either)
    if route is None:
        return []
    return [area for area in areas if not (groups_that_cover(area) & route)]


# The groups the app would choose for each part of the message, all parts together, taken from the app's own function
# (split_and_route_message), so this exam measures the code the app will run. A message of one part is routed exactly
# as before. The parts are routed one after another.
async def route_message_by_parts(question: str, search_help) -> set[ToolGroup] | None:
    routed_parts = await split_and_route_message(ROUTER, build_messages({"question": question}), REGISTRY, search_help)
    groups_of_each_part = [routed_part.groups for routed_part in routed_parts]
    # A part the router could not route (None) means every tool was offered, so the whole message is unrouted
    if any(groups is None for groups in groups_of_each_part):
        return None
    return set().union(*groups_of_each_part)


async def measure_route_coverage(cases: list[dict], runs: int, by_parts: bool) -> None:
    search_help = ChatService(None, None, REGISTRY, ROUTER)._help_search_function_for_tools([])
    await embed_texts_for_search(["warm up"])
    covered_runs = total_runs = fully_covered_cases = 0
    for case in cases:
        results = []
        for _ in range(runs):
            if by_parts:
                groups = await route_message_by_parts(case["question"], search_help)
            else:
                _, groups = await route_like_the_app(build_messages({"question": case["question"]}), search_help)
            results.append((groups, areas_missing_from(groups, case["areas"])))
        covered = sum(not missing for _, missing in results)
        covered_runs, total_runs, fully_covered_cases = covered_runs + covered, total_runs + runs, fully_covered_cases + (covered == runs)
        shown = ",".join(sorted(g.value for g in results[0][0])) if results[0][0] is not None else "all"
        print(f"{'COVERED' if covered == runs else 'MISSING' if covered == 0 else 'FLAKY  '} {covered}/{runs}  {case['id']}  wanted={case['areas']}  route={shown}  missing={results[0][1]}")
    print(f"\nevery wanted area covered: {covered_runs}/{total_runs} runs, {fully_covered_cases}/{len(cases)} cases fully")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--dataset", type=Path, default=DATASET)
    parser.add_argument("--runs", type=int, default=3)
    parser.add_argument("--by-parts", action="store_true", help="split each message into parts and route every part")
    options = parser.parse_args()
    asyncio.run(measure_route_coverage(load_cases(options.dataset), options.runs, options.by_parts))
