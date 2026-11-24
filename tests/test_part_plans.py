import asyncio

from assistant.replies import REPLY_CANNOT_HELP_WITH_THAT, REPLY_ONLY_THEIR_OWN_ACCOUNT
from assistant.services.part_plans import plan_replies_for_each_part
from assistant.services.tool_router import last_customer_message
from assistant.tools import ALL_TOOLS
from assistant.tools.base import ToolGroup
from assistant.tools.registry import ToolRegistry

registry = ToolRegistry(ALL_TOOLS)


# Stands in for the model-based router: decides by a word in the part, and remembers what each part looked like to it.
# The tax part is sent to the tax-form lookup on purpose, as the real router often does: the code rule must turn it into a decline.
class RouterThatRemembersWhatItWasAsked:
    def __init__(self):
        self.last_customer_messages_seen = []
        self.message_counts_seen = []

    async def choose_registry_and_groups(self, messages, full_registry):
        question = last_customer_message(messages)
        self.last_customer_messages_seen.append(question)
        self.message_counts_seen.append(len(messages))
        if "friend" in question:
            groups = {ToolGroup.THIRD_PARTY_REQUEST}
        elif "tax" in question:
            groups = {ToolGroup.REFERENCE}
        else:
            groups = {ToolGroup.ACCOUNT_DATA}
        return full_registry.restricted_to(groups), groups


# The help center never has an answer, so a decline is never rescued as a help question
async def help_search_that_finds_nothing(question):
    return []


def plan(router, text, earlier_messages=()):
    messages = [*earlier_messages, {"role": "user", "content": text}]
    return asyncio.run(plan_replies_for_each_part(router, messages, registry, help_search_that_finds_nothing))


def test_a_message_with_one_request_gets_one_plan_that_the_model_answers():
    plans = plan(RouterThatRemembersWhatItWasAsked(), "what is my balance")

    assert [p.text for p in plans] == ["what is my balance"]
    assert plans[0].groups == {ToolGroup.ACCOUNT_DATA}
    assert plans[0].fixed_sentence is None


def test_a_tax_advice_part_becomes_a_fixed_decline_even_when_the_router_sent_it_to_a_lookup():
    plans = plan(RouterThatRemembersWhatItWasAsked(), "what is my balance and do I owe tax on my gain")

    assert [p.text for p in plans] == ["what is my balance", "do I owe tax on my gain"]
    assert plans[0].fixed_sentence is None
    assert plans[1].groups == {ToolGroup.DECLINE_REQUEST}
    assert plans[1].fixed_sentence == REPLY_CANNOT_HELP_WITH_THAT


def test_a_part_about_someone_elses_account_gets_the_fixed_sentence_for_that():
    plans = plan(RouterThatRemembersWhatItWasAsked(), "what is my balance and send money from my friend's account")

    assert plans[0].fixed_sentence is None
    assert plans[1].fixed_sentence == REPLY_ONLY_THEIR_OWN_ACCOUNT


# Each part is routed on its own: the router must see ONE request as the customer's last message, and the earlier
# conversation must still be there for "cancel it" style follow-ups
def test_each_part_is_routed_alone_and_the_earlier_conversation_is_kept():
    router = RouterThatRemembersWhatItWasAsked()
    earlier = [{"role": "user", "content": "hi"}, {"role": "assistant", "content": "Hello!"}]

    plan(router, "what is my balance and do I owe tax on my gain", earlier)

    assert router.last_customer_messages_seen == ["what is my balance", "do I owe tax on my gain"]
    # Two earlier messages plus the part itself, every time: the part replaces the full message, it is not added to it
    assert router.message_counts_seen == [3, 3]
