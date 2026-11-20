import asyncio

from sqlmodel import Session

from assistant.clients.embeddings import embed_texts_for_search
from assistant.database import engine
from assistant.knowledge.passages import load_help_center_passages
from assistant.repositories.help_passages import HelpPassageRepository
from assistant.services.help_center_service import HelpCenterService, IndexReport
from assistant.services.passage_screening import QuarantinedPassage, screen_passages_before_indexing


# Screens every passage first, then stores only the clean ones. A stopped passage that was stored earlier keeps its
# previous version (the indexer is told to leave it alone); the third value names those, so the report can say so.
async def screen_then_index(service: HelpCenterService) -> tuple[IndexReport, list[QuarantinedPassage], set[tuple[str, str]]]:
    screening = await screen_passages_before_indexing(load_help_center_passages())
    stopped_locations = frozenset((stopped.passage.source, stopped.passage.heading) for stopped in screening.quarantined)
    # Read before indexing: this is the set of stopped passages customers can still find
    still_live = set(stopped_locations) & service.stored_locations()
    report = await service.index_help_center_articles(screening.clean, keep_stored=stopped_locations)
    return report, screening.quarantined, still_live


# Reads the articles and updates the search table. Safe to run again at any time: only changes are embedded.
#   uv run python -m assistant.index_help_center
# Exits with 1 when any passage was kept out, so a script (or CI later) notices.
def index_help_center_from_command_line() -> None:
    with Session(engine) as db:
        service = HelpCenterService(db, HelpPassageRepository(db), embed_texts_for_search)
        report, quarantined, still_live = asyncio.run(screen_then_index(service))
    print(
        f"Help center indexed: {report.added} added, {report.updated} updated, "
        f"{report.unchanged} unchanged, {report.removed} removed."
    )
    if quarantined:
        print(f"\nATTENTION: {len(quarantined)} passages were stopped by screening and need a person to look at them.")
    for stopped in quarantined:
        location = (stopped.passage.source, stopped.passage.heading)
        print(f"  {stopped.passage.source} / {stopped.passage.heading}: {'; '.join(stopped.reasons)}")
        if location in still_live:
            print("    live help center: the previous version was KEPT. The new text is not live.")
        else:
            print("    live help center: this passage was never indexed, so customers do not see it.")
    if quarantined:
        print("\nWhat to do: read each passage. If it is real help, reword it so the rule does not match and run this again.")
        print("If it was planted, remove it from the article.")
        raise SystemExit(1)


if __name__ == "__main__":
    index_help_center_from_command_line()
