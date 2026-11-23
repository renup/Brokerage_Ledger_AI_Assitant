import asyncio
import json
import logging
import re
from functools import lru_cache
from pathlib import Path

from assistant import llm
from assistant.replies import REPLY_NOTHING_FOUND, REPLY_CANNOT_HELP_WITH_THAT, REPLY_ONLY_THEIR_OWN_ACCOUNT
from assistant.tools.base import ToolGroup
from assistant.tools.registry import ToolRegistry

logger = logging.getLogger(__name__)

# How many of the latest messages the router reads, and how much of each. A short look is enough
# to understand "cancel it", and keeps the extra model call fast.
ROUTER_CONTEXT_MESSAGES = 4
ROUTER_MESSAGE_CHARS = 300

# The router's answer when no tool is needed at all
NO_TOOLS_WORD = "none"

# How long the help center gets to answer before a declined request stays declined. Short on purpose: it only
# decides whether to rescue a request, and a decline is the safe side if the search is slow.
DECLINE_CHECK_SECONDS = 3

# The router answers that mean "we do not help with this". No tool belongs to them.
DECLINE_GROUPS = {ToolGroup.DECLINE_REQUEST, ToolGroup.THIRD_PARTY_REQUEST}

# Routes whose questions also depend on what the help articles say. Tax-form and fee questions go to "reference"
# (tools), but the facts around them (when forms are ready, what "pending" means) live in the articles. With no
# search the model answers those from memory and sometimes invents them.
ROUTES_THAT_ALSO_NEED_THE_HELP_ARTICLES = {ToolGroup.REFERENCE}

# Words that put a question about tax. "government" is included because customers ask "what do I pay the government".
TAX_WORDS = re.compile(r"\b(?:tax|taxes|taxed|taxable|irs|government)\b", re.IGNORECASE)

# Words that turn a tax question into a request for advice: what the customer owes, can deduct, or can save.
# A tax question without one of these ("when will my tax documents be ready?", "what is tax-advantaged?") is not advice.
OWING_OR_SAVING_WORDS = re.compile(
    r"\b(?:owe|owed|pay|paying|liable|liability|deduct\w*|write[- ]?offs?|lower|reduce|avoid|save)\b", re.IGNORECASE
)

# Advice questions that never say "tax": "am I liable for the gain", "can I write this loss off"
LIABLE_FOR_A_GAIN = re.compile(r"\b(?:liable|liability)\b.*\b(?:gains?|loss(?:es)?|income|earnings|dividends)\b", re.IGNORECASE)
WRITING_OFF_A_LOSS = re.compile(r"\bwrite\b.{0,25}\boff\b", re.IGNORECASE)
# "Can I deduct my IRA contribution?" has no tax word. Only the customer asking for permission counts: "the fee is deducted
# from my balance" is not a tax question.
ASKING_TO_DEDUCT = re.compile(r"\b(?:can|could|may|should)\s+i\s+deduct\b", re.IGNORECASE)


# Reads the router's instructions the first time they are needed, then reuses them
@lru_cache
def router_prompt() -> str:
    return (Path(__file__).parent.parent / "prompts" / "router.md").read_text()


# The last few things said, as plain text for the router. Only the customer's and the assistant's
# words: the system rules and the raw lookup results are left out.
def recent_conversation(messages: list[dict]) -> str:
    spoken = [m for m in messages if m["role"] in ("user", "assistant") and m.get("content")]
    return "\n".join(f"{m['role']}: {m['content'][:ROUTER_MESSAGE_CHARS]}" for m in spoken[-ROUTER_CONTEXT_MESSAGES:])


# Turns the router's reply ("account, reference") into a set of groups.
#   a set with groups  -> those groups
#   an empty set       -> the router said "none": no tools needed
#   None               -> the answer made no sense, so the caller should not trust it
def parse_groups(answer: str) -> set[ToolGroup] | None:
    words = set(re.findall(r"[a-z]+", answer.lower()))
    groups = {group for group in ToolGroup if group.value in words}
    # A request about someone else's account wins over every other word: acting on a third party's account is the
    # worse mistake, and a customer whose request was wrongly turned away can simply rephrase.
    if ToolGroup.THIRD_PARTY_REQUEST in groups:
        return {ToolGroup.THIRD_PARTY_REQUEST}
    # "decline" next to a real group means the router was unsure. The real group wins, so a real question
    # is never turned away.
    real_groups = groups - DECLINE_GROUPS
    if real_groups:
        groups = real_groups
    if groups:
        return groups
    if NO_TOOLS_WORD in words:
        return set()
    return None


# The latest thing the customer said, cut to the length the search tool accepts
def last_customer_message(messages: list[dict]) -> str:
    spoken = [m["content"] for m in messages if m["role"] == "user" and m.get("content")]
    return spoken[-1][:300] if spoken else ""


# Lookups our code runs BEFORE the model speaks, because the route says the answer must come from them.
# Today: a question about how things work always searches the help center. A small model told to "search first"
# sometimes skips it and invents an answer with a made-up source, so the search is not left to the model's choice.
def required_calls_for(groups: set[ToolGroup] | None, messages: list[dict]) -> list[llm.ToolCall]:
    if not groups or ToolGroup.HELP_CENTER not in groups:
        return []
    question = json.dumps({"question": last_customer_message(messages)})
    return [llm.ToolCall(id="required-help-search", name="search_help_center", arguments=question)]


# The reply our code sends INSTEAD of any lookup or model call, because the router said this is a request we do not
# help with. None for every other route.
def declined_reply_for(groups: set[ToolGroup] | None) -> str | None:
    # None, an empty set ("none") and any real group all mean the model still answers
    if not groups or not groups <= DECLINE_GROUPS:
        return None
    return REPLY_ONLY_THEIR_OWN_ACCOUNT if ToolGroup.THIRD_PARTY_REQUEST in groups else REPLY_CANNOT_HELP_WITH_THAT


# True when the customer asks what they owe, can deduct or can save in tax. Wording rules only, so a new way of asking can
# slip past; the answer guard (find_tax_liability_claim) is the net behind it.
def question_asks_for_tax_advice(question: str) -> bool:
    return bool(
        (TAX_WORDS.search(question) and OWING_OR_SAVING_WORDS.search(question))
        or LIABLE_FOR_A_GAIN.search(question)
        or WRITING_OFF_A_LOSS.search(question)
        or ASKING_TO_DEDUCT.search(question)
    )


# The router often sends tax-advice questions to the tax-form lookup because the word "tax" is in them. When the
# question asks for tax advice, the route becomes "decline". A change request or another person's account keeps its own
# route, so a message that also asks for something real is not turned away as a whole. Run this AFTER the help check:
# a question the wording rules call tax advice is never rescued as help (a help passage on 1099 forms must not answer "do I owe tax").
def groups_after_tax_advice_check(groups: set[ToolGroup] | None, question: str) -> set[ToolGroup] | None:
    if groups is None or groups & {ToolGroup.CHANGES, ToolGroup.THIRD_PARTY_REQUEST} or groups == {ToolGroup.DECLINE_REQUEST}:
        return groups
    return {ToolGroup.DECLINE_REQUEST} if question_asks_for_tax_advice(question) else groups


# The router can be wrong when it says "decline". Before a customer is turned away, ask the help center: if it has
# an answer to this very question, it was a real question, so it is answered as a help question instead.
# Returns the groups to use. Anything other than a pure decline is returned unchanged.
async def groups_after_decline_check(groups: set[ToolGroup] | None, question: str, search_help) -> set[ToolGroup] | None:
    if groups != {ToolGroup.DECLINE_REQUEST}:
        return groups
    try:
        # The same search the help tool uses: the passages the relevance judge kept for this question
        passages = await asyncio.wait_for(search_help(question), DECLINE_CHECK_SECONDS)
    except Exception:
        # Too slow or broken: the decline stands (refusing is the safe side for advice and other people's accounts)
        return groups
    return {ToolGroup.HELP_CENTER} if passages else groups


# Adds the help center to a route that needs the articles as well as its tools, so the required help search runs
# for it. Any other route is returned unchanged.
def groups_with_help_articles(groups: set[ToolGroup] | None) -> set[ToolGroup] | None:
    if groups and groups & ROUTES_THAT_ALSO_NEED_THE_HELP_ARTICLES:
        return groups | {ToolGroup.HELP_CENTER}
    return groups


# The reply our code sends if the required help search finds nothing, or None when the model should still answer.
# Only a help-only route gets one: with another route as well (for example fees), the other lookup may still answer.
def fixed_reply_for(groups: set[ToolGroup] | None) -> str | None:
    return REPLY_NOTHING_FOUND if groups == {ToolGroup.HELP_CENTER} else None


# Decides which tools the model is offered for a message. Offering 3 to 6 tools instead of all of
# them keeps a small model steady as the menu grows.
class ToolRouter:
    # Asks the model one short question. Returns None when it cannot decide.
    async def choose_tool_groups(self, messages: list[dict]) -> set[ToolGroup] | None:
        question = [
            {"role": "system", "content": router_prompt()},
            {"role": "user", "content": recent_conversation(messages)},
        ]
        try:
            # Reuses the one place we talk to the model; this call offers no tools, so it answers in words
            answer = "".join([piece async for piece in llm.stream_turn(question) if isinstance(piece, str)])
        except Exception:
            # Routing is an optimisation. If it breaks, the customer still gets an answer.
            logger.exception("Tool routing failed; offering every tool")
            return None
        groups = parse_groups(answer)
        logger.info("Tool routing: %r -> %s", answer.strip(), groups)
        return groups

    # The registry for this message AND the groups behind it. If the router could not decide (groups is
    # None), every tool is offered, which is exactly how the app behaved before routing.
    async def choose_registry_and_groups(
        self, messages: list[dict], registry: ToolRegistry
    ) -> tuple[ToolRegistry, set[ToolGroup] | None]:
        groups = await self.choose_tool_groups(messages)
        return (registry if groups is None else registry.restricted_to(groups)), groups
