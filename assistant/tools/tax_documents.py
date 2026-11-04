from pydantic import Field

from assistant.tools.base import Tool, ToolArgs, ToolContext, ToolGroup


class TaxDocumentsArgs(ToolArgs):
    year: int | None = Field(default=None, ge=2000, le=2100, description="The tax year, for example 2025. Leave out for every year.")


async def get_tax_documents(context: ToolContext, args: TaxDocumentsArgs):
    return await context.ledger.tax_documents(args.year)


TOOLS = [
    Tool(
        name="get_tax_documents",
        description="List the customer's own tax forms (such as 1099 or 5498) with the tax year, status "
        "and where to download them. Use for questions about whether a form is ready, which forms they have, "
        "or where to find one. Do not use for general tax advice or how to file.",
        args_model=TaxDocumentsArgs,
        run=get_tax_documents,
        groups=frozenset({ToolGroup.REFERENCE}),
    ),
]
