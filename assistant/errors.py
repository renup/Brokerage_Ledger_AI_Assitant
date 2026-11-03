# Domain errors: things that go wrong in OUR business logic, described without any web words.
# Services raise these; main.py translates them into HTTP responses in one place.
# That keeps services reusable (a CLI or a test can use them) and routers free of try/except.


# The thing asked for doesn't exist OR belongs to someone else. We deliberately use the
# same error for both, so a caller can't discover that another customer's data exists.
class NotFoundError(Exception):
    pass

# The proposal's 24 hours have passed
class ActionExpiredError(Exception):
    pass


# The proposal was already approved, rejected, expired or finished (including: you lost a double tap)
class ActionAlreadyDecidedError(Exception):
    pass


# The customer approved, but the world changed since the proposal was made
# (e.g. the transfer is no longer failed), so doing it now would be wrong
class ActionNotPossibleError(Exception):
    pass
