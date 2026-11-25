"""Measures how well the splitter tells one request from several, with no model calls (runs in under a second).

A message labeled "one" must come out as ONE part; a message labeled "several" must come out as TWO OR MORE parts.
    - false split: a one-request message that was cut up
    - missed split: a several-request message that was left whole

    env -u VIRTUAL_ENV PYTHONPATH=. uv run python -m evals.run_split_eval
"""

import argparse
import json
from pathlib import Path

from assistant.services.message_parts import split_message_into_parts

DATASET = Path(__file__).parent / "split_labels.jsonl"


def load_labels(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


# The labeled messages the splitter gets wrong: one-request messages it cut (false splits) and several-request messages
# it left whole (missed splits), each with the parts it produced
def find_wrong_splits(labels: list[dict]) -> tuple[list[tuple[dict, list[str]]], list[tuple[dict, list[str]]]]:
    false_splits, missed_splits = [], []
    for label in labels:
        parts = split_message_into_parts(label["message"])
        if label["expected"] == "one" and len(parts) > 1:
            false_splits.append((label, parts))
        elif label["expected"] == "several" and len(parts) < 2:
            missed_splits.append((label, parts))
    return false_splits, missed_splits


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--dataset", type=Path, default=DATASET)
    options = parser.parse_args()

    labels = load_labels(options.dataset)
    false_splits, missed_splits = find_wrong_splits(labels)
    one_request = [label for label in labels if label["expected"] == "one"]
    several_requests = [label for label in labels if label["expected"] == "several"]

    for label, parts in false_splits:
        print(f"FALSE SPLIT  {label['id']}  {parts}")
    for label, parts in missed_splits:
        print(f"MISSED SPLIT {label['id']}  {parts}")
    print(f"\nfalse splits: {len(false_splits)}/{len(one_request)} one-request messages cut")
    print(f"missed splits: {len(missed_splits)}/{len(several_requests)} several-request messages left whole")
