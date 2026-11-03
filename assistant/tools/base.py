from collections.abc import Awaitable, Callable
from dataclasses import dataclass

from pydantic import BaseModel, ConfigDict

from assistant.action_types import ActionKind
from assistant.clients.ledger import LedgerClient
from assistant.models import PendingAction


# Base class for every tool's arguments. extra="forbid" means any argument we did not
# declare is an error. So a model that tries to pass customer_id=2 is rejected outright.
class ToolArgs(BaseModel):
    model_config = ConfigDict(extra="forbid")


# For tools that need no input. Shared, so it lives here and not in any one tool's file.
class NoArgs(ToolArgs):
    pass


# Saves a proposal for the customer to approve: (kind, details, plain-words summary) -> the saved row.
# The tool never sees a database; it can only call this.
ProposalSaver = Callable[[ActionKind, dict, str], PendingAction]


# Everything a tool is allowed to use, built fresh for each customer message.
#   ledger:  reads this customer's data from ledger-core, with their own token
#   propose: saves a proposal. It is None where proposing makes no sense (e.g. in evals), and
#            only the propose tools use it.
@dataclass(frozen=True)
class ToolContext:
    ledger: LedgerClient
    propose: ProposalSaver | None = None


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