from typing import Literal

from pydantic import Field

from assistant.tools.base import Tool, ToolArgs, ToolContext, ToolGroup


# Notice: no customer id. The caller's token decides whose accounts are checked.
class WithdrawalEligibilityArgs(ToolArgs):
    # gt=0 makes validation reject zero and negatives before any request is made
    amount: float = Field(
        gt=0,
        description="The withdrawal amount in dollars, exactly as the customer said it. "
        "For example 500 for 'five hundred dollars'.",
    )
    # None means "check every account", which is right when the customer did not name one
    account_type: Literal["individual", "roth_ira", "traditional_ira"] | None = Field(
        default=None,
        description="Only set this if the customer names a type of account. Leave it out to check all their accounts.",
    )


# Read-only: asks ledger-core whether the withdrawal WOULD be allowed. Nothing is requested or changed.
async def check_withdrawal_eligibility(context: ToolContext, args: WithdrawalEligibilityArgs):
    return await context.ledger.withdrawal_eligibility(args.amount, args.account_type)


TOOLS = [
    Tool(
        name="check_withdrawal_eligibility",
        description="Check whether the customer could withdraw a SPECIFIC amount right now, per account, with the reasons "
        "if not and how much is available. Only use when the customer states an amount, such as 'can I withdraw $500'. "
        "For questions about balances or cash with no amount, use get_accounts instead. "
        "It only checks; it does not start a withdrawal. "
        "Each account in the result also shows its cash balance now and its balance after this withdrawal, "
        "so a question like 'can I withdraw $500 and what will I have left' needs only this tool.",
        args_model=WithdrawalEligibilityArgs,
        run=check_withdrawal_eligibility,
        groups=frozenset({ToolGroup.ACCOUNT_DATA}),
    ),
]
