import asyncio
import json
from pathlib import Path

from sqlmodel import Session

from assistant.clients.embeddings import embed_texts_for_search
from assistant.database import engine
from assistant.repositories.help_passages import HelpPassageRepository
from assistant.services.help_center_service import MAX_DISTANCE, QUESTION_LABEL

DATASET = Path(__file__).parent / "help_center.jsonl"
# Cut-offs to compare, so MAX_DISTANCE is chosen from measurements and not guessed
CANDIDATE_CUTOFFS = [0.30, 0.35, 0.40, 0.45, 0.50, 0.55, 0.60]


# Finds, for each question, the three nearest passages and how far each is. Needs the help center to be indexed.
async def measure_retrieval() -> list[dict]:
    cases = [json.loads(line) for line in DATASET.read_text().splitlines() if line.strip()]
    vectors = await embed_texts_for_search([QUESTION_LABEL + case["question"] for case in cases])
    results = []
    with Session(engine) as db:
        repo = HelpPassageRepository(db)
        for case, vector in zip(cases, vectors):
            nearest = [((row.source, row.heading), distance) for row, distance in repo.closest_to(vector, 3)]
            results.append({**case, "nearest": nearest})
    return results


def report(results: list[dict]) -> None:
    in_scope = [r for r in results if r["expected_source"]]
    off_topic = [r for r in results if not r["expected_source"]]

    def rank_of_expected(r):
        wanted = (r["expected_source"], r["expected_heading"])
        places = [i for i, (location, _) in enumerate(r["nearest"]) if location == wanted]
        return places[0] if places else None

    # Ranking quality, before any cut-off is applied
    first = sum(rank_of_expected(r) == 0 for r in in_scope)
    top3 = sum(rank_of_expected(r) is not None for r in in_scope)
    print(f"in-scope questions: {len(in_scope)}   right passage first: {first}   within top 3: {top3}")
    for r in in_scope:
        if rank_of_expected(r) != 0:
            print(f"  MISS {r['id']} {r['question']!r} -> got {r['nearest'][0][0][1]!r} ({r['nearest'][0][1]:.3f}), rank of expected: {rank_of_expected(r)}")

    best_in = sorted(r["nearest"][0][1] for r in in_scope)
    best_off = sorted(r["nearest"][0][1] for r in off_topic)
    print(f"closest-passage distance, in-scope:  min {best_in[0]:.3f}  median {best_in[len(best_in)//2]:.3f}  max {best_in[-1]:.3f}")
    print(f"closest-passage distance, off-topic: min {best_off[0]:.3f}  median {best_off[len(best_off)//2]:.3f}  max {best_off[-1]:.3f}")

    # For each cut-off: how many real questions still get an answer, and how many off-topic ones are turned away
    print(f"\n{'cut-off':>8} {'kept in-scope':>14} {'rejected off-topic':>19}")
    for cutoff in CANDIDATE_CUTOFFS:
        kept = sum(r["nearest"][0][1] <= cutoff and rank_of_expected(r) == 0 for r in in_scope)
        rejected = sum(r["nearest"][0][1] > cutoff for r in off_topic)
        marker = "  <- current MAX_DISTANCE" if abs(cutoff - MAX_DISTANCE) < 1e-9 else ""
        print(f"{cutoff:>8.2f} {kept:>10}/{len(in_scope):<3} {rejected:>14}/{len(off_topic):<3}{marker}")


if __name__ == "__main__":
    report(asyncio.run(measure_retrieval()))
