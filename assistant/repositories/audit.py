from sqlmodel import Session, select

from assistant.models import AuditEntry


# The audit log is append only. There is deliberately NO update and NO delete method here,
# so nothing in our code can rewrite history. Like ActionRepository, it never commits.
class AuditRepository:
    def __init__(self, db: Session):
        self.db = db

    def add(self, entry: AuditEntry) -> None:
        self.db.add(entry)

    # This customer's entries, newest first, for the Activity screen
    def list_for_customer(self, owner: str, limit: int = 50) -> list[AuditEntry]:
        return list(
            self.db.exec(
                select(AuditEntry)
                .where(AuditEntry.customer_id_hash == owner)
                .order_by(AuditEntry.ts.desc(), AuditEntry.id.desc())
                .limit(limit)
            ).all()
        )
