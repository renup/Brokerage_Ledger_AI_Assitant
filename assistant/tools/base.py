from collections.abc import Awaitable, Callable
from dataclasses import dataclass

from pydantic import BaseModel, ConfigDict

from assistant.clients.ledger import LedgerClient


# Base class for every tool's arguments. extra="forbid" means any argument we did not
# declare is an error. So a model that tries to pass customer_id=2 is rejected outright.
class ToolArgs(BaseModel):
    model_config = ConfigDict(extra="forbid")

# One tool the model may use. "frozen" means it can't be changed after creation.
@dataclass(frozen=True)
class Tool:
    name: str
    # The model decides when to call the tool from this text alone, so write it for the model
    description: str
    # The Pydantic class describing the arguments
    args_model: type[ToolArgs]
    # Our code that does the work: receives the caller's LedgerClient and the validated arguments
    run: Callable[[LedgerClient, ToolArgs], Awaitable[object]]

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