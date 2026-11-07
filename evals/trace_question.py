import argparse
import asyncio

from assistant.services.agent import Token, ToolRound, run_agent
from assistant.services.tool_router import ToolRouter, required_calls_for
from assistant.tools import ALL_TOOLS
from assistant.tools.base import ToolContext
from assistant.tools.registry import ToolRegistry
from evals.demo_ledger import DemoLedger
from evals.run_tool_eval import build_messages


# Runs ONE question through the same path as a real chat (router, forced help search if routed, agent loop)
# and prints every step: which tools were on offer, each round of lookups with its arguments, and the final answer.
# Usage: uv run python -m evals.trace_question "Can I pull out 2500 today and tell me my balance after?"
async def trace(question: str) -> None:
    registry = ToolRegistry(ALL_TOOLS)
    messages = build_messages({"question": question})
    offered, groups = await ToolRouter().choose_registry_and_groups(messages, registry)
    print(f"route: {sorted(g.value for g in groups) if groups is not None else 'all (router unsure)'}")
    print(f"tools on offer: {offered.tool_names()}\n")

    words = []
    required = required_calls_for(groups, messages)
    async for event in run_agent(messages, offered, ToolContext(DemoLedger()), required):
        if isinstance(event, ToolRound):
            for record in event.records:
                print(f"round: {record.name}({record.arguments})")
        elif isinstance(event, Token):
            words.append(event.text)
    print(f"\nanswer: {''.join(words)}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Show every step of one question: route, tool rounds, final answer.")
    parser.add_argument("question")
    asyncio.run(trace(parser.parse_args().question))
