from sqlmodel import Session, select

from assistant.models import Message


# Every database query for messages lives here and nowhere else. If we change databases
# or add caching, this is the only file that changes. Services never write SQL.
# One repository is created per request and holds that request's database session as "db".
class MessageRepository:
    def __init__(self, db: Session):
        self.db = db

    # True if this session_id is already used by a DIFFERENT customer
    def session_owned_by_someone_else(self, session_id: str, owner: str) -> bool:
        taken = self.db.exec(
            select(Message).where(Message.session_id == session_id, Message.customer_id_hash != owner)
        ).first()
        return taken is not None

    # Save one new message (user or assistant) and commit it
    def add(self, message: Message) -> None:
        self.db.add(message)
        self.db.commit()

    # This customer's messages in one chat session. Oldest first by default;
    # newest_first=True is for the history trimmer, which keeps the newest messages.
    def list_for_session(self, session_id: str, owner: str, newest_first: bool = False) -> list[Message]:
        order = Message.created_at.desc() if newest_first else Message.created_at
        return list(
            self.db.exec(
                select(Message)
                # Both conditions: the right session AND the right owner
                .where(Message.session_id == session_id, Message.customer_id_hash == owner)
                .order_by(order)
            ).all()
        )

    # The one assistant reply a customer is rating, or None if any condition fails
    # (wrong id, wrong session, someone else's message, or not an assistant message)
    def get_assistant_message(self, message_id: str, session_id: str, owner: str) -> Message | None:
        return self.db.exec(
            select(Message).where(
                Message.message_id == message_id,
                Message.session_id == session_id,
                Message.customer_id_hash == owner,
                Message.role == "assistant",
            )
        ).first()

    # Store a thumbs up/down on an existing message; rating again replaces the old one
    def set_rating(self, message: Message, rating: str) -> None:
        message.rating = rating
        self.add(message)
