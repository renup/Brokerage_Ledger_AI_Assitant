import json
from functools import lru_cache

from transformers import AutoTokenizer

from assistant.config import settings
from assistant.llm import tool_request_message, tool_result_message
from assistant.models import Message

# The chat template wraps every message in extra tokens (<|im_start|>role ... <|im_end|>).
# Step 4.1 measured 13 extra tokens for 2 messages, so 5 per message is a safe estimate.
TEMPLATE_OVERHEAD = 5
# How many of the newest assistant replies get their saved lookups replayed to the model.
# Older replies are sent as words only, to save tokens and avoid showing stale data.
REPLAYED_TURNS = 2


# Loads the tokenizer the first time it is needed, then reuses it (lru_cache remembers the result).
# Loading lazily keeps importing this file fast, which matters for tests and startup.
@lru_cache
def _tokenizer():
    return AutoTokenizer.from_pretrained(settings.llm_tokenizer)


# Tokens one message will cost: its text plus the template's wrapper
def count_tokens(text: str) -> int:
    return len(_tokenizer().encode(text)) + TEMPLATE_OVERHEAD


# Tokens one model message costs: its words, plus the tool names and arguments if it is a tool request
def message_cost(message: dict) -> int:
    cost = count_tokens(message.get("content") or "")
    for call in message.get("tool_calls", []):
        cost += count_tokens(call["function"]["name"] + call["function"]["arguments"])
    return cost


# Rebuilds what the model saw when it wrote this reply: for each round of lookups, the request
# and then the results, and finally the reply's own words.
def replay_reply(message: Message) -> list[dict]:
    replayed = []
    for round_ in json.loads(message.tool_trace_json):
        records = round_["records"]
        replayed.append(tool_request_message((r["id"], r["name"], r["arguments"]) for r in records))
        for r in records:
            # The label tells the model this is a snapshot, so it looks again for current status
            note = f"[Looked up at {round_['at']}. This may be out of date; look it up again for the current status.] "
            replayed.append(tool_result_message(r["id"], note + r["result"]))
    replayed.append({"role": "assistant", "content": message.text})
    return replayed


# A pure function: rows in, model messages out. No database, so it is easy to test.
# "newest_first" is the repository's order; we keep as many of the newest as fit in the
# budget, then return them oldest first, the order the model needs.
def trim_to_budget(newest_first: list[Message], budget: int) -> list[dict]:
    # One entry per saved row. A row may expand to several model messages (request, results, words),
    # and we keep or drop the whole group, so a request is never separated from its results.
    kept = []
    used = 0
    # How many assistant replies we have passed so far, newest first
    assistant_seen = 0
    for message in newest_first:
        # Only the newest REPLAYED_TURNS assistant replies get their lookups replayed
        replay = message.role == "assistant" and assistant_seen < REPLAYED_TURNS
        if message.role == "assistant":
            assistant_seen += 1
        group = replay_reply(message) if replay else [{"role": message.role, "content": message.text}]
        cost = sum(message_cost(m) for m in group)
        # Stop once the next (older) group would go over the budget.
        # "kept and ..." means the newest message (the question just asked) is always included.
        if kept and used + cost > budget:
            break
        kept.append(group)
        used += cost
    kept.reverse()
    # Flatten the groups into one list of messages
    return [m for group in kept for m in group]
