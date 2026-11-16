import asyncio

from sqlmodel import Session

from assistant.clients.embeddings import embed_texts_for_search
from assistant.database import engine
from assistant.knowledge.passages import load_help_center_passages
from assistant.repositories.help_passages import HelpPassageRepository
from assistant.services.help_center_service import HelpCenterService, IndexReport
from assistant.services.passage_screening import QuarantinedPassage, screen_passages_before_indexing


# Screens every passage first, then stores only the clean ones. A quarantined passage that was stored earlier is
# deleted too, because the indexer removes every stored passage that is not in the list it is given.
async def screen_then_index(service: HelpCenterService) -> tuple[IndexReport, list[QuarantinedPassage]]:
    screening = await screen_passages_before_indexing(load_help_center_passages())
    report = await service.index_help_center_articles(screening.clean)
    return report, screening.quarantined


# Reads the articles and updates the search table. Safe to run again at any time: only changes are embedded.
#   uv run python -m assistant.index_help_center
# Exits with 1 when any passage was kept out, so a script (or CI later) notices.
def index_help_center_from_command_line() -> None:
    with Session(engine) as db:
        service = HelpCenterService(db, HelpPassageRepository(db), embed_texts_for_search)
        report, quarantined = asyncio.run(screen_then_index(service))
    print(
        f"Help center indexed: {report.added} added, {report.updated} updated, "
        f"{report.unchanged} unchanged, {report.removed} removed."
    )
    for stopped in quarantined:
        print(f"  NOT INDEXED {stopped.passage.source} / {stopped.passage.heading}: {'; '.join(stopped.reasons)}")
    if quarantined:
        raise SystemExit(1)


if __name__ == "__main__":
    index_help_center_from_command_line()
