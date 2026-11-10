import hashlib
from collections.abc import Awaitable, Callable
from dataclasses import dataclass

from sqlmodel import Session

from assistant.config import settings
from assistant.knowledge.passages import Passage
from assistant.models import HelpPassage
from assistant.repositories.help_passages import HelpPassageRepository

# nomic-embed-text is trained with a short label in front of what it embeds: one for text that
# will be searched, another for the question that searches it. Skipping them makes matches worse.
DOCUMENT_LABEL = "search_document: "
QUESTION_LABEL = "search_query: "

# A passage farther than this (cosine distance) from the question is not about it, so it is not returned.
# Measured with `uv run python -m evals.run_retrieval_eval`: every real question's closest passage was within 0.384,
# every off-topic question's was beyond 0.404. 0.40 sits in that gap. Re-measure after adding articles or changing the model.
MAX_DISTANCE = 0.40

# The embedding function. A parameter, so tests can pass a fake and never need Ollama.
EmbedTexts = Callable[[list[str]], Awaitable[list[list[float]]]]


# What indexing did, for the command to print
@dataclass(frozen=True)
class IndexReport:
    added: int
    updated: int
    unchanged: int
    removed: int


# A passage that matched a question, with how far away it was
@dataclass(frozen=True)
class FoundPassage:
    article: str
    heading: str
    text: str
    source: str
    distance: float


# A fingerprint of a passage's words and the model that embeds them. If either changes the passage must be
# embedded again, which is exactly what a different fingerprint tells the indexing step.
def fingerprint_of(passage: Passage) -> str:
    return hashlib.sha256(f"{settings.embedding_model}|{passage.searchable_text()}".encode()).hexdigest()


class HelpCenterService:
    def __init__(self, db: Session, passages: HelpPassageRepository, embed: EmbedTexts):
        self.db = db
        self.passages = passages
        self.embed = embed

    # Brings the stored passages in line with the articles: new ones are added, changed ones re-embedded,
    # removed sections deleted, and unchanged ones left alone (embedding is the slow part).
    async def index_help_center_articles(self, articles: list[Passage]) -> IndexReport:
        stored = self.passages.stored_passages_by_location()
        current = {(passage.source, passage.heading): passage for passage in articles}

        # Only the passages that are new or whose fingerprint changed need embedding
        needs_embedding = []
        for location, passage in current.items():
            fingerprint = fingerprint_of(passage)
            if location not in stored or stored[location].text_hash != fingerprint:
                needs_embedding.append((passage, fingerprint))

        # One request for all of them. If it fails nothing has been written, so the table is never half-updated.
        vectors = []
        if needs_embedding:
            vectors = await self.embed([DOCUMENT_LABEL + passage.searchable_text() for passage, _ in needs_embedding])

        added = updated = 0
        for (passage, fingerprint), vector in zip(needs_embedding, vectors):
            row = stored.get((passage.source, passage.heading))
            if row is None:
                self.passages.add(
                    HelpPassage(
                        source=passage.source, article=passage.article, heading=passage.heading,
                        text=passage.text, text_hash=fingerprint, embedding=vector,
                    )
                )
                added += 1
            else:
                # An existing row is changed in place; the session saves the difference on commit
                row.article, row.text, row.text_hash, row.embedding = passage.article, passage.text, fingerprint, vector
                updated += 1

        removed = 0
        for location, row in stored.items():
            if location not in current:
                self.passages.remove(row)
                removed += 1

        self.db.commit()
        return IndexReport(added, updated, len(current) - len(needs_embedding), removed)

    # The passages nearest in meaning to the question, nearest first. Anything beyond MAX_DISTANCE is dropped.
    # "Nearby" is not yet "answers it": the passage judge (passage_judge.py) checks that afterwards.
    async def find_nearby_passages(self, question: str, limit: int = 3) -> list[FoundPassage]:
        [question_vector] = await self.embed([QUESTION_LABEL + question])
        return [
            FoundPassage(row.article, row.heading, row.text, row.source, distance)
            for row, distance in self.passages.closest_to(question_vector, limit)
            if distance <= MAX_DISTANCE
        ]
