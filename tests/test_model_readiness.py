import asyncio

from assistant import llm
from assistant.services import model_readiness
from assistant.services.model_readiness import (
    PRACTICE_QUESTION,
    get_models_ready_for_first_customer,
    practice_router_and_judge,
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

    monkeypatch.setattr(model_readiness, "load_models_into_memory", fake_load)
    monkeypatch.setattr(model_readiness, "practice_router_and_judge", fake_practice)
    asyncio.run(get_models_ready_for_first_customer())

    assert steps == ["load", "practice"]

