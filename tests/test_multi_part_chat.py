from fastapi.testclient import TestClient

from assistant import llm
from assistant.config import settings
from assistant.auth import get_current_user
from assistant.dependencies import get_ledger_client, get_tool_router
from assistant.main import app as assistant_app
from assistant.replies import REPLY_CANNOT_HELP_WITH_THAT
from assistant.services.chat_service import ChatService
from assistant.services.tool_router import last_customer_message
from assistant.tools.base import ToolGroup
from tests.test_action_service import FakeLedger
from tests.test_assistant import MAYA, parse_sse


# Stands in for the model-based router: a balance request goes to the account lookup; a tax request goes to the tax-form
# lookup on purpose, as the real router often does, so the code rule must turn it into a decline
class RouterForTwoPartMessages:
    async def choose_registry_and_groups(self, messages, registry):
        groups = {ToolGroup.REFERENCE} if "tax" in last_customer_message(messages) else {ToolGroup.ACCOUNT_DATA}
        return registry.restricted_to(groups), groups


def chat(monkeypatch, message, splitting_on):
    monkeypatch.setattr(settings, "split_multi_part_messages", splitting_on)
    async def finds_nothing(question):
        return []

    monkeypatch.setattr(ChatService, "_help_search_function_for_tools", lambda self, article_names: finds_nothing)
    questions_the_model_saw = []

    async def model(messages, tools=None):
        questions_the_model_saw.append(messages[-1]["content"])
        yield "Your balance is in the app."

    monkeypatch.setattr(llm, "stream_turn", model)
    assistant_app.dependency_overrides[get_current_user] = lambda: MAYA
    assistant_app.dependency_overrides[get_ledger_client] = lambda: FakeLedger()
    assistant_app.dependency_overrides[get_tool_router] = lambda: RouterForTwoPartMessages()
    try:
        response = TestClient(assistant_app).post("/chat", json={"session_id": "two-parts-1", "message": message})
    finally:
        assistant_app.dependency_overrides.clear()
    return parse_sse(response.text), questions_the_model_saw


# One message, two requests: the model answers the first, code declines the second, both come back in one stream
def test_a_two_part_message_gets_both_answers_in_one_reply(monkeypatch):
    events, questions_the_model_saw = chat(monkeypatch, "what is my balance and do I owe tax on my gain", splitting_on=True)

    # The declined part never reaches the model
    assert questions_the_model_saw == ["what is my balance"]
    words = "".join(data["text"] for name, data in events if name == "token")
    assert words == f"Your balance is in the app.\n\n{REPLY_CANNOT_HELP_WITH_THAT}"
    # One reply: a single "done" at the end
    assert [name for name, _ in events].count("done") == 1
    assert events[-1][0] == "done"


# The switch is off by default: the whole message is routed as ONE request, exactly as the app did before splitting existed.
# Here the tax words are in the message, so the whole message is declined and the model is never asked, not even for the balance.
def test_with_splitting_off_a_two_part_message_is_routed_as_one_request(monkeypatch):
    events, questions_the_model_saw = chat(monkeypatch, "what is my balance and do I owe tax on my gain", splitting_on=False)

    assert questions_the_model_saw == []
    words = "".join(data["text"] for name, data in events if name == "token")
    assert words == REPLY_CANNOT_HELP_WITH_THAT


def test_splitting_is_off_unless_someone_turns_it_on():
    # The default in the code, not the value in this machine's .env
    assert settings.model_fields["split_multi_part_messages"].default is False
