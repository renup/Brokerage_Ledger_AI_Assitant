import asyncio

from sqlmodel import Session

from assistant.clients.embeddings import embed_texts_for_search
from assistant.database import engine
from assistant.knowledge.passages import load_help_center_passages
from assistant.repositories.help_passages import HelpPassageRepository
from assistant.services.help_center_service import HelpCenterService


# Reads the articles and updates the search table. Safe to run again at any time: only changes are embedded.
#   uv run python -m assistant.index_help_center
def index_help_center_from_command_line() -> None:
    with Session(engine) as db:
        service = HelpCenterService(db, HelpPassageRepository(db), embed_texts_for_search)
        report = asyncio.run(service.index_help_center_articles(load_help_center_passages()))
    print(
        f"Help center indexed: {report.added} added, {report.updated} updated, "
        f"{report.unchanged} unchanged, {report.removed} removed."
    )


if __name__ == "__main__":
    index_help_center_from_command_line()
