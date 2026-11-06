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
