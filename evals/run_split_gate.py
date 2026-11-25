"""Runs the jailbreak and injection exams through the parts path the app uses (split, route each part, answer in order)
with splitting on and off, so a message cut into parts cannot hide a leak the old exams never saw.

    env -u VIRTUAL_ENV PYTHONPATH=. uv run python -m evals.run_split_gate --runs 3
"""
import argparse
import asyncio
from pathlib import Path

from assistant.clients.embeddings import embed_texts_for_search
from assistant.services.agent import Token
from assistant.services.answer_parts import answer_routed_parts_in_order
from assistant.services.chat_service import ChatService
from assistant.services.routed_parts import route_message_as_one_request, split_and_route_message
from assistant.tools.base import ToolContext
from evals.run_answer_eval import REGISTRY, ROUTER, answer_after_the_guard, find_problems, load_cases
from evals.run_injection_eval import fake_help_search_returning, find_obeyed_instructions
from evals.run_jailbreak_eval import find_jailbreak_problems
from evals.run_tool_eval import build_messages

JAILBREAKS = Path(__file__).parent / "jailbreak.jsonl"
INJECTIONS = Path(__file__).parent / "injection.jsonl"


# Answers one question the way stream_reply does: split (or not), route, answer the parts in order, then the answer guard.
# Returns the reply, the number of parts, and the passages the help search returned (the injection exam needs them).
async def answer_through_the_parts_path(question: str, search_help, splitting_on: bool) -> tuple[str, int, list[dict]]:
    passages = []

    # Wraps the search so the passages it returns are remembered
    async def search_and_remember(search_question: str) -> list[dict]:
        found = await search_help(search_question)
        passages.extend(found)
        return found

    messages = build_messages({"question": question})
    if splitting_on:
        routed_parts = await split_and_route_message(ROUTER, messages, REGISTRY, search_and_remember)
    else:
        routed_parts = [await route_message_as_one_request(ROUTER, messages, REGISTRY, search_and_remember)]

    context = ToolContext(ledger=None, search_help=search_and_remember)
    words = []
    async for event in answer_routed_parts_in_order(routed_parts, messages, REGISTRY, context):
        if isinstance(event, Token):
            words.append(event.text)
    reply, _ = answer_after_the_guard(question, "".join(words))
    return reply, len(routed_parts), passages


# Scores both exams with splitting off and then on, and prints one summary line per setting. Also lists the questions
# that came out in more than one part: those are the cases splitting actually changed.
async def measure_gate(jailbreak_cases: list[dict], injection_cases: list[dict], runs: int) -> None:
    help_search = ChatService(None, None, REGISTRY, ROUTER)._help_search_function_for_tools([])
    await embed_texts_for_search(["warm up"])
    for splitting_on in (False, True):
        jailbreak_held = jailbreak_attempts = 0
        injection_obeyed = injection_clean = injection_attempts = 0
        cut_into_parts = []
        for case in jailbreak_cases:
            for _ in range(runs):
                reply, part_count, _ = await answer_through_the_parts_path(case["question"], help_search, splitting_on)
                jailbreak_attempts += 1
                jailbreak_held += not find_jailbreak_problems(case, reply)
                if part_count > 1:
                    cut_into_parts.append(case["id"])
                    print(f"        {case['id']} came out in {part_count} parts: {reply[:120]!r}")
        for case in injection_cases:
            poisoned_search = fake_help_search_returning(case["poisoned_text"])
            for _ in range(runs):
                reply, part_count, passages = await answer_through_the_parts_path(case["question"], poisoned_search, splitting_on)
                injection_attempts += 1
                obeyed = bool(find_obeyed_instructions(case, reply))
                injection_obeyed += obeyed
                injection_clean += not obeyed and not find_problems(case, reply, passages)
                if part_count > 1:
                    cut_into_parts.append(case["id"])
                    print(f"        {case['id']} came out in {part_count} parts: {reply[:120]!r}")
        print(f"splitting {'ON ' if splitting_on else 'OFF'}: jailbreak held {jailbreak_held}/{jailbreak_attempts}, "
              f"injection obeyed {injection_obeyed}/{injection_attempts} clean {injection_clean}/{injection_attempts}, "
              f"attempts cut into parts: {len(cut_into_parts)}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--runs", type=int, default=3)
    options = parser.parse_args()
    asyncio.run(measure_gate(load_cases(JAILBREAKS), load_cases(INJECTIONS), options.runs))
