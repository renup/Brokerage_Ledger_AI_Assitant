import logging
import re
from functools import lru_cache
from pathlib import Path

from assistant import llm
from assistant.services.help_center_service import FoundPassage

logger = logging.getLogger(__name__)


# Reads the judge's instructions the first time they are needed, then reuses them
@lru_cache
def judge_prompt() -> str:
    return (Path(__file__).parent.parent / "prompts" / "passage_judge.md").read_text()


# The question and the passages as one block of text for the judge, each passage numbered from 1
def question_and_numbered_passages(question: str, passage_texts: list[str]) -> str:
    numbered = "\n".join(f"Passage {number}: {text}" for number, text in enumerate(passage_texts, start=1))
    return f"Question: {question}\n{numbered}"


# Turns the judge's reply ("1, 3" or "none") into the set of passage numbers it kept.
#   a set of numbers -> those passages answer the question
#   an empty set     -> the judge said "none"
#   None             -> the reply made no sense, so the caller should not trust it
def parse_kept_numbers(answer: str, passage_count: int) -> set[int] | None:
    numbers = {int(found) for found in re.findall(r"\d+", answer) if 1 <= int(found) <= passage_count}
    if numbers:
        return numbers
    if "none" in answer.lower():
        return set()
    return None


# Asks the model which of the nearby passages directly answer the question and returns only those. The vector
# search finds passages that are close in meaning; this checks that they actually say what was asked. It is an
# extra safeguard, like the router: if the model call breaks or the reply makes no sense, every passage is kept,
# so the customer gets today's behaviour and not an error.
async def keep_only_passages_that_answer(question: str, passages: list[FoundPassage]) -> list[FoundPassage]:
    if not passages:
        return passages
    # The heading is included because a short passage often only makes sense with it
    texts = [f"{passage.heading}: {passage.text}" for passage in passages]
    messages = [
        {"role": "system", "content": judge_prompt()},
        {"role": "user", "content": question_and_numbered_passages(question, texts)},
    ]
    try:
        answer = "".join([piece async for piece in llm.stream_turn(messages) if isinstance(piece, str)])
    except Exception:
        logger.exception("Passage judging failed; keeping every nearby passage")
        return passages
    kept = parse_kept_numbers(answer, len(passages))
    logger.info("Passage judge: %r -> %s", answer.strip(), kept)
    if kept is None:
        return passages
    return [passage for number, passage in enumerate(passages, start=1) if number in kept]
