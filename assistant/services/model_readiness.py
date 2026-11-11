import logging

from assistant.clients.model_warmup import load_models_into_memory
from assistant.services.help_center_service import FoundPassage
from assistant.services.passage_judge import keep_only_passages_that_answer
from assistant.services.tool_router import ToolRouter

logger = logging.getLogger(__name__)

PRACTICE_QUESTION = "How long does a withdrawal usually take?"


# Even after a model is loaded, its first real use of a prompt is slow (about 4 seconds for the router, 2 for the
# judge). So a practice question goes through both, and the first customer does not pay for it. They are the same
# functions the chat uses, so this follows them when they change. Neither raises: the router falls back to "all tools"
# and the judge keeps every passage, so a failed practice is harmless.
async def practice_router_and_judge() -> None:
    await ToolRouter().choose_tool_groups([{"role": "user", "content": PRACTICE_QUESTION}])
    practice_passage = FoundPassage(
        article="Moving money to your bank",
        heading="How long it takes",
        text="Withdrawals usually arrive within 3 business days.",
        source="practice",
        distance=0.2,
    )
    await keep_only_passages_that_answer(PRACTICE_QUESTION, [practice_passage])


# Everything the assistant does in the background at start-up so the first customer gets a fast answer:
# load the models, then practice on them. Called once from the lifespan.
async def get_models_ready_for_first_customer() -> None:
    await load_models_into_memory()
    await practice_router_and_judge()
    logger.info("Models loaded and practiced")
