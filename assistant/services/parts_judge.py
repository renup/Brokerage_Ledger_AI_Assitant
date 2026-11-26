import logging
import re
from functools import lru_cache
from pathlib import Path

from assistant import llm

logger = logging.getLogger(__name__)


# Reads the judge's instructions the first time they are needed, then reuses them
@lru_cache
def parts_judge_prompt() -> str:
    return (Path(__file__).parent.parent / "prompts" / "parts_judge.md").read_text()


# The pieces of the message as the numbered list the judge reads: "1. first piece" on one line, "2. ..." on the next
def numbered_parts(parts: list[str]) -> str:
    return "\n".join(f"{number}. {part}" for number, part in enumerate(parts, start=1))


# Asks the model whether the pieces of one customer message are separate requests (each needs its own answer or lookup)
# or one request told in several sentences. The splitter only cuts at sentence breaks and joining words; this decides
# whether the cut is real. Like the router and the passage judge it is an extra safeguard: if the model call breaks, or
# the answer is not exactly one of the two words, the message is treated as ONE request, which is how the app behaved
# before splitting existed. The customer's words go in the user message, never in the instructions.
async def parts_are_separate_requests(parts: list[str]) -> bool:
    messages = [
        {"role": "system", "content": parts_judge_prompt()},
        {"role": "user", "content": numbered_parts(parts)},
    ]
    try:
        answer = "".join([piece async for piece in llm.stream_turn(messages) if isinstance(piece, str)])
    except Exception:
        logger.exception("Judging the parts failed; treating the message as one request")
        return False
    # Whole words only, whatever the capital letters or punctuation: "Separate." counts, "someone" is not "one"
    words = set(re.findall(r"[a-z]+", answer.lower()))
    separate = "separate" in words and "one" not in words
    logger.info("Parts judge: %r -> %s", answer.strip(), "separate" if separate else "one")
    return separate
