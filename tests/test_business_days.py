import asyncio
import json
from datetime import date

from assistant.knowledge.business_days import add_business_days
from assistant.tools.read import READ_TOOLS
from assistant.tools.registry import ToolRegistry


# 2026-10-30 is a Friday. Three business days later is Wednesday, skipping the weekend.
def test_weekend_is_skipped():
    assert add_business_days(date(2026, 10, 30), 3) == date(2026, 11, 4)


# Starting on a Sunday, one business day later is Monday
def test_start_on_weekend():
    assert add_business_days(date(2026, 11, 1), 1) == date(2026, 11, 2)


# Runs the tool the way the agent does: through the registry. The client is not needed, so None.
def run_tool(arguments: dict) -> dict:
    registry = ToolRegistry(READ_TOOLS)
    raw = asyncio.run(registry.execute(None, "estimate_arrival", json.dumps(arguments)))
    return json.loads(raw)


def test_tool_returns_arrival_date():
    result = run_tool({"business_days": 3, "start_date": "2026-10-30"})
    assert result["data"]["arrival_date"] == "2026-11-04"


# 0 is outside the allowed 1 to 10, so the registry answers with an error and does not crash
def test_tool_rejects_zero_days():
    assert "error" in run_tool({"business_days": 0})
