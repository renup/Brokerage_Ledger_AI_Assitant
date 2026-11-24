"""Measures whether the meaning check separates tax-advice questions from tax lookups it must still answer.

Each held-out question is compared with the known tax-advice questions and with the known tax-help questions.
It would be declined when it is closer to an advice question than to every help question (the rule decided before
looking at any numbers: no margin). The held-out file is for measuring only; nothing here is tuned against it.

    env -u VIRTUAL_ENV PYTHONPATH=. uv run python -m evals.run_tax_meaning_eval
"""
import asyncio
import json
from pathlib import Path

from assistant.clients.embeddings import embed_texts_for_search
from assistant.services.help_center_service import QUESTION_LABEL
from assistant.services.tax_advice_meaning import TAX_ADVICE_QUESTIONS_FILE, distance_between_meanings

TAX_HELP_QUESTIONS_FILE = TAX_ADVICE_QUESTIONS_FILE.with_name("tax_help_questions.jsonl")
HELD_OUT_FILE = Path(__file__).parent / "tax_meaning_heldout.jsonl"


def questions_in(file: Path) -> list[dict]:
    return [json.loads(line) for line in file.read_text().splitlines() if line.strip()]


def nearest_distance(meaning: list[float], references: list[list[float]]) -> float:
    return min(distance_between_meanings(meaning, reference) for reference in references)


async def measure_both_sides() -> None:
    advice, helps, held_out = (questions_in(f) for f in (TAX_ADVICE_QUESTIONS_FILE, TAX_HELP_QUESTIONS_FILE, HELD_OUT_FILE))
    texts = [r["question"] for r in advice + helps + held_out]
    meanings = await embed_texts_for_search([QUESTION_LABEL + t for t in texts])
    advice_meanings = meanings[: len(advice)]
    help_meanings = meanings[len(advice): len(advice) + len(helps)]
    held_out_meanings = meanings[len(advice) + len(helps):]

    wrongly_declined, caught, missed, answered_ok = [], [], [], []
    print("  to-advice  to-help   decision   label   question")
    for case, meaning in zip(held_out, held_out_meanings):
        to_advice, to_help = nearest_distance(meaning, advice_meanings), nearest_distance(meaning, help_meanings)
        declined = to_advice < to_help
        label = "ADVICE" if case["is_tax_advice"] else "keep"
        print(f"  {to_advice:.3f}     {to_help:.3f}    {'DECLINE' if declined else 'answer ':8}   {label:6}  {case['question']}")
        bucket = {(True, True): caught, (True, False): wrongly_declined, (False, True): missed, (False, False): answered_ok}
        bucket[(declined, case["is_tax_advice"])].append(case["id"])

    print(f"\nadvice declined: {len(caught)}/{len(caught) + len(missed)}   missed: {missed}")
    print(f"lookups wrongly declined: {len(wrongly_declined)}/{len(wrongly_declined) + len(answered_ok)}   {wrongly_declined}")


if __name__ == "__main__":
    asyncio.run(measure_both_sides())
