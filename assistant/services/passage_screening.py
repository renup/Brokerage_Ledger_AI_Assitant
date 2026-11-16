import logging
import re
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

from assistant import llm
from assistant.knowledge.passages import Passage

logger = logging.getLogger(__name__)

# What has no place in a help article. Real articles describe how the service works, so none of this appears in them.
# Each pattern has a label that is shown when a passage is stopped, so you can see why.
# These are only the sure things: the model check below catches rewordings the patterns cannot.
PLANTED_ORDER_PATTERNS = {
    "contains a web address": r"https?://|www\.|\b[\w-]+\.(com|net|org|io)\b",
    "contains an email address": r"[\w.+-]+@[\w-]+\.[\w.]+",
    "contains a phone number": r"\b\d{3}[-.\s]\d{3}[-.\s]\d{4}\b",
    "talks to the assistant": r"ignore (all |any )?(previous|prior|above)|disregard|new rule|note to (the )?assistant|^\s*system\s*:|you are now",
    "tells the assistant what to say to customers": r"\b(tell|ask) (the )?customers?\b|do not (tell|mention|reveal)",
    "asks for a secret": r"\b(password|passcode|pin|ssn|social security)\b",
}


# A passage that was not stored, and every reason it was stopped
@dataclass(frozen=True)
class QuarantinedPassage:
    passage: Passage
    reasons: list[str]


# What screening decided: the passages safe to store and the ones kept out
@dataclass(frozen=True)
class ScreeningResult:
    clean: list[Passage]
    quarantined: list[QuarantinedPassage]


# Reads the screening instructions the first time they are needed, then reuses them
@lru_cache
def screening_prompt() -> str:
    return (Path(__file__).parent.parent / "prompts" / "passage_screen.md").read_text()


# The labels of every pattern the text matches. Empty means the rules found nothing.
def find_planted_order_markers(passage_text: str) -> list[str]:
    return [
        label for label, pattern in PLANTED_ORDER_PATTERNS.items()
        if re.search(pattern, passage_text, flags=re.IGNORECASE | re.MULTILINE)
    ]


# Asks the model whether the passage gives orders or announces changes instead of describing how the service works.
# An unclear reply counts as "yes": text that could not be vetted is not stored. A model error is NOT caught here,
# so indexing stops, because nothing may be stored unscreened.
async def model_says_passage_gives_orders(passage: Passage) -> bool:
    messages = [
        {"role": "system", "content": screening_prompt()},
        {"role": "user", "content": f"{passage.heading}: {passage.text}"},
    ]
    reply = "".join([piece async for piece in llm.stream_turn(messages) if isinstance(piece, str)])
    logger.info("Passage screen: %s / %s -> %r", passage.source, passage.heading, reply.strip())
    return not reply.strip().lower().startswith("no")


# Splits the passages into the ones safe to store and the ones kept out. The rules run first and cost nothing; the
# model (about a second each) only looks at passages the rules let through.
async def screen_passages_before_indexing(passages: list[Passage]) -> ScreeningResult:
    clean, quarantined = [], []
    for passage in passages:
        reasons = find_planted_order_markers(f"{passage.heading}: {passage.text}")
        if not reasons and await model_says_passage_gives_orders(passage):
            reasons = ["a model judged that it gives orders or announces changes instead of describing how things work"]
        if reasons:
            quarantined.append(QuarantinedPassage(passage, reasons))
        else:
            clean.append(passage)
    return ScreeningResult(clean, quarantined)
