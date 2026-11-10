import re

from sqlalchemy import func
from sqlmodel import Session, select

from assistant.models import HelpPassage


# All SQL for the help_passages table. Like the other repositories it never commits: the service decides.
class HelpPassageRepository:
    def __init__(self, db: Session):
        self.db = db

    # Everything stored now, found by (article file, section heading). The indexing step compares these
    # against the current articles to see what is new, changed or gone.
    def stored_passages_by_location(self) -> dict[tuple[str, str], HelpPassage]:
        return {(row.source, row.heading): row for row in self.db.exec(select(HelpPassage)).all()}

    def add(self, passage: HelpPassage) -> None:
        self.db.add(passage)

    # For a passage whose section no longer exists in the articles
    def remove(self, passage: HelpPassage) -> None:
        self.db.delete(passage)

    # The passages whose meaning is closest to the question, nearest first, each with its distance.
    # Cosine distance: 0 means the same direction (same meaning), 1 unrelated, 2 opposite.
    def closest_to(self, question_vector: list[float], limit: int) -> list[tuple[HelpPassage, float]]:
        distance = HelpPassage.embedding.cosine_distance(question_vector)
        rows = self.db.exec(select(HelpPassage, distance).order_by(distance).limit(limit)).all()
        return [(row, float(far)) for row, far in rows]

    # The passages that contain the most of the question's words, best first, each with its keyword score.
    # The question's words are joined with "|" (OR), so a passage needs only SOME of them: customers write
    # sentences, not search terms. Postgres drops filler words ("what", "is") and stems the rest ("charged" ->
    # "charg"). The score (ts_rank_cd) is higher when more of the words appear, and closer together.
    def best_by_keywords(self, question: str, limit: int) -> list[tuple[HelpPassage, float]]:
        # Only letters and digits are kept, so nothing a customer types can change the shape of the
        # search expression (it has its own symbols, such as & and |)
        words = re.findall(r"[A-Za-z0-9]+", question)
        if not words:
            return []
        query = func.to_tsquery("english", " | ".join(words))
        score = func.ts_rank_cd(HelpPassage.search_vector, query)
        # "@@" is Postgres' "this text matches this query"; it uses the GIN index
        rows = self.db.exec(
            select(HelpPassage, score).where(HelpPassage.search_vector.op("@@")(query)).order_by(score.desc()).limit(limit)
        ).all()
        return [(row, float(points)) for row, points in rows]
