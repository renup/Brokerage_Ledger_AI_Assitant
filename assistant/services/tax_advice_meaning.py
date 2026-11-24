import json
import math
from pathlib import Path
from typing import Awaitable, Callable

from assistant.services.help_center_service import QUESTION_LABEL

EmbedTexts = Callable[[list[str]], Awaitable[list[list[float]]]]

# The questions we know are tax advice, written in many ways. A customer question that means the same as one of
# these is tax advice, even when it shares none of their words.
TAX_ADVICE_QUESTIONS_FILE = Path(__file__).parent.parent / "knowledge" / "tax_advice_questions.jsonl"


# The reference questions as plain text, in file order
def load_tax_advice_questions() -> list[str]:
    lines = TAX_ADVICE_QUESTIONS_FILE.read_text().splitlines()
    return [json.loads(line)["question"] for line in lines if line.strip()]


# How far apart two meanings are: 0 means the same direction, larger means less alike. This is the same cosine distance
# the help-center search uses, so the numbers can be compared with MAX_DISTANCE there.
def distance_between_meanings(first: list[float], second: list[float]) -> float:
    dot = sum(a * b for a, b in zip(first, second))
    length = math.sqrt(sum(a * a for a in first)) * math.sqrt(sum(b * b for b in second))
    return 1.0 - dot / length


# Tells how close the meaning of a customer question is to the known tax-advice questions
class TaxAdviceMeaning:
    def __init__(self, embed: EmbedTexts):
        self.embed = embed
        # The reference questions' meanings. Worked out on first use, then kept: they never change while the app runs.
        self._reference_meanings: list[list[float]] | None = None

    # The distance to the nearest reference question: small means "this asks for tax advice"
    async def distance_to_nearest_tax_advice_question(self, question: str) -> float:
        if self._reference_meanings is None:
            # One request for all of them, with the same label the help search puts on questions
            self._reference_meanings = await self.embed([QUESTION_LABEL + q for q in load_tax_advice_questions()])
        [question_meaning] = await self.embed([QUESTION_LABEL + question])
        return min(distance_between_meanings(question_meaning, reference) for reference in self._reference_meanings)
