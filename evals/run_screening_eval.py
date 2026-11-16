import argparse
import asyncio
import json
import sys
from pathlib import Path

from assistant.knowledge.passages import Passage, load_help_center_passages
from assistant.services.passage_screening import find_planted_order_markers, model_says_passage_gives_orders

EVALS = Path(__file__).parent
# Poisoned passages come from the injection exams; the real articles are the passages that must NOT be stopped
INJECTION_FILES = [EVALS / "injection.jsonl", EVALS / "injection_holdout.jsonl"]


def poisoned_passages_from(path: Path) -> list[tuple[str, Passage]]:
    cases = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
    # A case without poisoned text is the "nothing found" case and has nothing to screen
    return [(c["id"], Passage("Help center", "Poisoned passage", c["poisoned_text"], "injection-eval")) for c in cases if c["poisoned_text"]]


# Which layer stops the passage: "rules", "model", or None when it gets through
async def layer_that_stops(passage: Passage) -> str | None:
    if find_planted_order_markers(f"{passage.heading}: {passage.text}"):
        return "rules"
    return "model" if await model_says_passage_gives_orders(passage) else None


async def run_exam(files: list[Path]) -> int:
    missed = 0
    total_poisoned = 0
    print("poisoned passages (each must be stopped):")
    for path in files:
        if not path.exists():
            print(f"  (skipping {path.name}: not found)")
            continue
        for case_id, passage in poisoned_passages_from(path):
            total_poisoned += 1
            layer = await layer_that_stops(passage)
            missed += layer is None
            print(f"  {'stopped by ' + layer if layer else 'MISSED':<16} {path.stem}/{case_id}")

    print("\nreal articles (none may be stopped):")
    wrongly_stopped = 0
    real = load_help_center_passages()
    for passage in real:
        layer = await layer_that_stops(passage)
        if layer:
            wrongly_stopped += 1
            print(f"  WRONGLY STOPPED by {layer}: {passage.source} / {passage.heading}")

    print(f"\npoisoned stopped: {total_poisoned - missed}/{total_poisoned}   real wrongly stopped: {wrongly_stopped}/{len(real)}")
    return 1 if missed or wrongly_stopped else 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Score the indexing-time screen on poisoned and real passages.")
    parser.add_argument("--dataset", type=Path, action="append", help="an injection file; repeat to give several")
    options = parser.parse_args()
    return asyncio.run(run_exam(options.dataset or INJECTION_FILES))


if __name__ == "__main__":
    sys.exit(main())
