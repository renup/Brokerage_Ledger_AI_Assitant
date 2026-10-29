# Domain errors: things that go wrong in OUR business logic, described without any web words.
# Services raise these; main.py translates them into HTTP responses in one place.
# That keeps services reusable (a CLI or a test can use them) and routers free of try/except.


# The thing asked for doesn't exist OR belongs to someone else. We deliberately use the
# same error for both, so a caller can't discover that another customer's data exists.
class NotFoundError(Exception):
    pass
