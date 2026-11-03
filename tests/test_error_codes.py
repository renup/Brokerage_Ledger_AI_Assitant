import asyncio
import json

from assistant.knowledge.error_codes import explain_error
from assistant.tools import ALL_TOOLS
from assistant.tools.registry import ToolRegistry


def test_known_code_is_explained():
    assert explain_error("214").title == "Name mismatch"


def test_stray_spaces_are_ignored():
    assert explain_error(" 214 ") is not None


def test_unknown_code_returns_none():
    assert explain_error("999") is None


# Runs the tool the way the agent does: through the registrd, so None.
def run_tool(code: str) -> dict:
    registry = ToolRegistry(ALL_TOOLS)
    raw = asyncio.run(registry.execute(None, "lookup_error_code", json.dumps({"code": code})))
    return json.loads(raw)["data"]


def test_tool_explains_known_code():
    assert run_tool("214")["found"] is True


def test_tool_admits_unknown_code():
    assert run_tool("999")["found"] is False