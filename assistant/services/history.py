from functools import lru_cache

from transformers import AutoTokenizer

from assistant.config import settings
from assistant.models import Message

# The chat template wraps every message in extra tokens (<|im_start|>role ... <|im_end|>).
# Step 4.1 measured 13 extra tokens for 2 messages, so 5 per message is a safe estimate.
TEMPLATE_OVERHEAD = 5


# Loads the tokenizer the first time it is needed, then reuses it (lru_cache remembers the result).
# Loading lazily keeps importing this file fast, which matters for tests and startup.
@lru_cache
def _tokenizer():
    return AutoTokenizer.from_pretrained(settings.llm_tokenizer)


# Tokens one message will cost: its text plus the template's wrapper
def count_tokens(text: str) -> int:
    return len(_tokenizer().encode(text)) + TEMPLATE_OVERHEAD


# A pure function: rows in, model messages out. No database, so it is easy to test.
# "newest_first" is the repository's order; we keep as many of the newest as fit in the
# budget, then return them oldest first, the order the model needs.
def trim_to_budget(newest_first: list[Message], budget: int) -> list[dict]:
    kept = []
    used = 0
    for message in newest_first:
        cost = count_tokens(message.text)
        # Stop once the next (older) message would go over the budget.
        # "kept and ..." means the newest message (the question just asked) is always included.
        if kept and used + cost > budget:
            break
        kept.append({"role": message.role, "content": message.text})
        used += cost
    kept.reverse()
    return kept
