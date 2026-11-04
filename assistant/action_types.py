from enum import StrEnum


# A StrEnum is a fixed list of allowed words. Each one is also an ordinary string ("proposed"),
# so it is stored as text, but a typo like ActionStatus.APROVED fails at once instead of
# silently saving a wrong word.


# What a proposal would do if approved
class ActionKind(StrEnum):
    RETRY_TRANSFER = "retry_transfer"
    CHANGE_NAME = "change_name"
    CANCEL_WITHDRAWAL = "cancel_withdrawal"


# Where a proposal is in its life. It only ever moves forward.
class ActionStatus(StrEnum):
    PROPOSED = "proposed"
    APPROVED = "approved"
    REJECTED = "rejected"
    EXPIRED = "expired"
    EXECUTED = "executed"
    FAILED = "failed"


# Who did something, for the audit log
class Actor(StrEnum):
    CUSTOMER = "customer"
    AGENT = "agent"
    GUARD = "guard"


# What happened, for the audit log. The study sheet lists the first eight; EXPIRED and FAILED are
# added because proposals can end those ways too.
class AuditAction(StrEnum):
    READ = "read"
    PROPOSED = "proposed"
    APPROVED = "approved"
    REJECTED = "rejected"
    EXECUTED = "executed"
    BLOCKED = "blocked"
    HANDOFF = "handoff"
    CRITIC_REVISE = "critic_revise"
    EXPIRED = "expired"
    FAILED = "failed"
