import asyncio

from assistant import llm
from assistant.services import model_readiness
from assistant.services.model_readiness import (
    PRACTICE_QUESTION,
    get_models_ready_for_first_customer,
    practice_router_and_judge,
    practice_writing_an_answer,
)


# Makes the model answer every call with this text, and records what it was asked
def model_says(monkeypatch, reply, asked):
    async def fake_turn(messages, tools=None):
        asked.append(messages)
        yield reply

    monkeypatch.setattr(llm, "stream_turn", fake_turn)


def test_the_practice_sends_the_router_prompt_and_the_judge_prompt_to_the_model(monkeypatch):
    asked = []
    model_says(monkeypatch, "none", asked)
    asyncio.run(practice_router_and_judge())

    assert len(asked) == 2
    assert PRACTICE_QUESTION in asked[0][-1]["content"]
    # The judge is shown the practice passage, numbered
    assert "Withdrawals usually arrive" in asked[1][-1]["content"]


def test_a_model_that_fails_during_practice_does_not_raise(monkeypatch):
    async def broken_turn(messages, tools=None):
        raise RuntimeError("model down")
        yield

    monkeypatch.setattr(llm, "stream_turn", broken_turn)
    asyncio.run(practice_router_and_judge())


def test_models_are_loaded_first_and_then_practiced(monkeypatch):
    steps = []

    async def fake_load():
        steps.append("load")

    async def fake_practice():
        steps.append("practice")

    async def fake_answer_practice():
        steps.append("answer")

    monkeypatch.setattr(model_readiness, "load_models_into_memory", fake_load)
    monkeypatch.setattr(model_readiness, "practice_router_and_judge", fake_practice)
    monkeypatch.setattr(model_readiness, "practice_writing_an_answer", fake_answer_practice)
    asyncio.run(get_models_ready_for_first_customer())

    assert steps == ["load", "practice", "answer"]


def test_the_answer_practice_uses_the_chat_rules_the_help_menu_and_a_search_result(monkeypatch):
    seen = {}

    async def fake_turn(messages, tools=None):
        seen["messages"], seen["tools"] = messages, tools
        yield "ok"

    monkeypatch.setattr(llm, "stream_turn", fake_turn)
    asyncio.run(practice_writing_an_answer())

    assert seen["messages"][0]["role"] == "system" and "{first_name}" not in seen["messages"][0]["content"]
    assert [m["role"] for m in seen["messages"]] == ["system", "user", "assistant", "tool"]
    assert "Withdrawals usually arrive" in seen["messages"][-1]["content"]
    assert [tool["function"]["name"] for tool in seen["tools"]] == ["search_help_center"]


def test_a_model_that_fails_while_practising_an_answer_does_not_raise(monkeypatch):
    async def broken_turn(messages, tools=None):
        raise RuntimeError("model down")
        yield

    monkeypatch.setattr(llm, "stream_turn", broken_turn)
    asyncio.run(practice_writing_an_answer())


def test_the_system_prompt_shares_one_opening_between_customers():
    # The customer's name must come after everything shared, so Ollama can reuse its work for the next customer
    from assistant.services.chat_service import system_prompt

    prompt = system_prompt()
    assert prompt.count("{first_name}") == 1
    assert prompt.rstrip().splitlines()[-1].startswith("The customer's first name is {first_name}")
