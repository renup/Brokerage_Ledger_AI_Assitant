import argparse
import json
import sys
from pathlib import Path

from assistant.services.answer_guard import AnswerGuard

DATASET = Path(__file__).parent / "figure_guard.jsonl"


# Gives the guard what the real app gives it (the customer's words and the ledger results) and nothing else.
# "passages_shown" is deliberately NOT handed over: help passages are untrusted, which is the whole point of the exam.
def guard_answer_like_the_app(case: dict) -> str | None:
    guard = AnswerGuard()
    guard.trust_figures_in(case["question"])
    for ledger_result in case["ledger_results"]:
        guard.trust_figures_in(ledger_result)
        # As in the app: an answer resting on ledger data may work out a length of time
        guard.stop_checking_turnarounds_for_this_answer()
    guard.release_completed_sentences(case["answer"])
    guard.release_unfinished_sentence()
    return guard.stopped_because


def run_exam(dataset: Path) -> int:
    cases = [json.loads(line) for line in dataset.read_text(encoding="utf-8").splitlines() if line.strip()]
    wrong = 0
    for case in cases:
        stopped_because = guard_answer_like_the_app(case)
        stopped = stopped_because is not None
        right = stopped == case["should_stop"]
        wrong += not right
        verdict = "ok   " if right else "WRONG"
        print(f"{verdict} {case['id']:<6} should_stop={case['should_stop']!s:<5} stopped={stopped!s:<5} {case['why'][:50]}")
        if not right:
            print(f"        answer: {case['answer']!r}\n        guard said: {stopped_because}")
    print(f"\nright: {len(cases) - wrong}/{len(cases)}")
    return 1 if wrong else 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Score the answer guard's check of figures and codes.")
    parser.add_argument("--dataset", type=Path, default=DATASET)
    return run_exam(parser.parse_args().dataset)


if __name__ == "__main__":
    sys.exit(main())
