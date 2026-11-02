from dataclasses import dataclass


# One entry in the catalog. frozen=True means it can't be changed after creation.
@dataclass(frozen=True)
class ErrorInfo:
    title: str  # a short name for the problem
    meaning: str  # what went wrong, in plain words
    what_to_do: str  # the next step for the customer


# The catalog: transfer error code -> explanation. These are written by us, not the model,
# so the explanation is always the same and always correct.
ERROR_CODES: dict[str, ErrorInfo] = {
    "214": ErrorInfo(
        title="Name mismatch",
        meaning="The name on the account at the other broker does not match the name on this account.",
        what_to_do="Check that the name is spelled the same at both brokers, fix it at the other broker if not, then start the transfer again.",
    ),
    "215": ErrorInfo(
        title="Account number mismatch",
        meaning="The account number given for the other broker was not found or did not match.",
        what_to_do="Check the account number on a recent statement from the other broker, then start the transfer again.",
    ),
    "220": ErrorInfo(
        title="Account type not accepted",
        meaning="The other broker cannot send this type of account to us.",
        what_to_do="Contact the other broker to ask which account types they can transfer out.",
    ),
    "230": ErrorInfo(
        title="Missing signature",
        meaning="The transfer form needs a signature that is missing or does not match.",
        what_to_do="Sign the transfer form again and send it in.",
    ),
    "240": ErrorInfo(
        title="Assets cannot be moved",
        meaning="Some holdings in the account cannot be transferred as they are.",
        what_to_do="Sell those holdings or ask the other broker how they can be moved, then try again.",
    ),
}

# The one function the rest of the app uses. Returns None for a code we have no entry for.
# Keeping the lookup behind this function means we can later swap the dict for a database
# table without touching the tool or the agent.
def explain_error(code: str) -> ErrorInfo | None:
    # Ignore stray spaces, so " 214 " still finds "214"
    return ERROR_CODES.get(code.strip())
