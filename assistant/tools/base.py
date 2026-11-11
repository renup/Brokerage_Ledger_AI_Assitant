from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from enum import StrEnum

from pydantic import BaseModel, ConfigDict

from assistant.action_types import ActionKind
from assistant.clients.ledger import LedgerClient
from assistant.schemas import ProposalOut


# Base class for every tool's arguments. extra="forbid" means any argument we did not
# declare is an error. So a model that tries to pass customer_id=2 is rejected outright.
class ToolArgs(BaseModel):
    model_config = ConfigDict(extra="forbid")


# For tools that need no input. Shared, so it lives here and not in any one tool's file.
class NoArgs(ToolArgs):
    pass


# Saves a proposal for the customer to approve: (kind, details, plain-words summary) -> its public
# form (id, summary, expiry). A plain object, not a database row, because the session that saved it is closed.
# The tool never sees a database; it can only call this.
ProposalSaver = Callable[[ActionKind, dict, str], ProposalOut]

# Records a hand-off to a human: (reason) -> a reference number. Like ProposalSaver, the tool never sees a database.
HandoffRecorder = Callable[[str], int]

# Searches the help center for a question and returns the matching passages as plain dictionaries
# (article, heading, text, source). Async because it has to embed the question first. The tool never sees a database.
HelpSearcher = Callable[[str], Awaitable[list[dict]]]


# Everything a tool is allowed to use, built fresh for each customer message.
#   ledger:  reads this customer's data from ledger-core, with their own token
#   propose: saves a proposal. It is None where proposing makes no sense (e.g. in evals), and
#            only the propose tools use it.
#   hand_off: records a hand-off to a human. None where it makes no sense (e.g. in evals).
#   search_help: finds help-center passages for a question. None where it makes no sense (e.g. in evals).
@dataclass(frozen=True)
class ToolContext:
    ledger: LedgerClient
    propose: ProposalSaver | None = None
    hand_off: HandoffRecorder | None = None
    search_help: HelpSearcher | None = None


# The kinds of help a customer message can need. The router picks the groups a message needs, and the
# model is offered only the tools in those groups. A tool can belong to several groups (for example a
# lookup that the "change" requests also need in order to find an id).
class ToolGroup(StrEnum):
    # Looking up the customer's own balances, withdrawals and transfers
    ACCOUNT_DATA = "account"
    # Fees, tax documents, what an error code means, how long something takes
    REFERENCE = "reference"
    # Asking for a change: retry a transfer, cancel a withdrawal, update the legal name
    CHANGES = "change"
    # The customer wants a person, or needs something no tool can do
    HUMAN_HELP = "human"
    # General questions about how things work here, answered from the help-center articles
    HELP_CENTER = "help"


# One tool the model may use. "frozen" means it can't be changed after creation.
@dataclass(frozen=True)
class Tool:
    name: str
    # The model decides when to call the tool from this text alone, so write it for the model
    description: str
    # The Pydantic class describing the arguments
    args_model: type[ToolArgs]
    # Our code that does the work: receives the ToolContext and the validated arguments
    run: Callable[[ToolContext, ToolArgs], Awaitable[object]]
    # Which kinds of help this tool belongs to. Required, so no tool can silently be left out of every menu.
    groups: frozenset[ToolGroup]
    # NEW: a longer limit for a tool that is slow by nature. None means "use the registry's limit" (2 seconds)
    timeout_seconds: float | None = None

    # The tool as the model sees it, in the standard "function" format that Ollama accepts.
    # The JSON schema is generated from the args model, so it can never drift from the validation.
    def definition(self) -> dict:
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": self.args_model.model_json_schema(),
            },
        }