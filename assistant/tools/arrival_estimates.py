from datetime import date

from pydantic import Field

from assistant.knowledge.business_days import add_business_days
from assistant.tools.base import Tool, ToolArgs, ToolContext, ToolGroup


class EstimateArrivalArgs(ToolArgs):
    business_days: int = Field(ge=1, le=10, description="How many business days the money takes, from 1 to 10.")
    start_date: date | None = Field(default=None, description="The day it starts, as YYYY-MM-DD. Leave out for today.")


# Another tool with no call to ledger-core: the date math is done in code, never by the model
async def estimate_arrival(context: ToolContext, args: EstimateArrivalArgs):
    # No start date means today
    start = args.start_date or date.today()
    arrival = add_business_days(start, args.business_days)
    return {
        "start_date": start.isoformat(),
        "arrival_date": arrival.isoformat(),
        "arrival_weekday": arrival.strftime("%A"),
        "note": "Counts Monday to Friday only. Market holidays are not included, so it could be one day later.",
    }


TOOLS = [
    Tool(
        name="estimate_arrival",
        description="Work out the date money would arrive after a number of business days (Monday to Friday). "
        "Use for 'if I withdraw today, when will it arrive' style questions, never do date math yourself. "
        "For a withdrawal the customer already made, use get_withdrawals instead.",
        args_model=EstimateArrivalArgs,
        run=estimate_arrival,
        groups=frozenset({ToolGroup.ACCOUNT_DATA, ToolGroup.REFERENCE}),
    ),
]
