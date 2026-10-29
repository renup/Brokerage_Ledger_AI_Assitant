from sqlmodel import Session, select
from transformers import AutoTokenizer

from assistant.config import settings
from assistant.models import Message

# Load the tokenizer once at startup (the same one you used in the notebook)
_tokenizer = AutoTokenizer.from_pretrained(settings.llm_tokenizer)

# The chat template wraps every message in extra tokens (<|im_start|>role ... <|im_end|>).
# 4.1 measured 13 extra tokens for 2 messages, so 5 per message is a safe estimate.
TEMPLATE_OVERHEAD = 5


# Tokens one message will cost: its text plus the template's wrapper
def count_tokens(text: str) -> int:
    return len(_tokenizer.encode(text)) + TEMPLATE_OVERHEAD


# Returns this customer's messages for the session as [{"role", "content"}, ...],
# oldest first, keeping only as many of the newest as fit in the budget.
def load_history(session: Session, session_id: str, owner: str) -> list[dict]:
    rows = session.exec(
        select(Message)
        # Both conditions: the right session AND the right owner
        .where(Message.session_id == session_id, Message.customer_id_hash == owner)
        # Newest first, because the newest messages matter most when we must cut
        .order_by(Message.created_at.desc())
    ).all()

    kept = []
    used = 0

    for row in rows:
        cost = count_tokens(row.text)
        # Stop once the next (older) message would go over the budget.
        # "kept and ..." means the newest message (the question just asked) is always included.
        if kept and used + cost > settings.history_token_budget:
            break
        kept.append({"role": row.role, "content": row.text})
        used += cost

    # We collected newest-first; the model needs them in the order they happened
    kept.reverse()
    # This line was missing, so the function returned None
    return kept
