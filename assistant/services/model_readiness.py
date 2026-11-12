import logging

from assistant import llm
from assistant.clients.model_warmup import load_models_into_memory
from assistant.services.chat_service import system_prompt
from assistant.services.help_center_service import FoundPassage
from assistant.services.passage_judge import keep_only_passages_that_answer
from assistant.services.tool_router import ToolRouter, required_calls_for
from assistant.tools import ALL_TOOLS
from assistant.tools.base import ToolGroup
from assistant.tools.registry import ToolRegistry

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


# The third prompt a help question uses: the chat rules, the help tool menu and the search result, which the model turns
# into the answer. The rules are the same for every customer except the last line (the name), so reading them now
# means the first real customer does not pay for it. One short answer is written and thrown away. It is built from
# the same pieces the chat uses, so it matches a real help question.
# Never raises: a failed practice only means the first customer is slower.
async def practice_writing_an_answer() -> None:
    messages = [
        {"role": "system", "content": system_prompt().replace("{first_name}", "there")},
        {"role": "user", "content": PRACTICE_QUESTION},
    ]
    calls = required_calls_for({ToolGroup.HELP_CENTER}, messages)
    practice_result = ToolRegistry.data_result(
        "search_help_center",
        {"passages": [{"article": "Moving money to your bank", "heading": "How long a withdrawal takes",
                       "text": "Withdrawals usually arrive within 3 business days.", "source": "practice"}]},
    )
    messages.append(llm.tool_request_message((c.id, c.name, c.arguments) for c in calls))
    messages.extend(llm.tool_result_message(c.id, practice_result) for c in calls)
    menu = ToolRegistry(ALL_TOOLS).restricted_to({ToolGroup.HELP_CENTER}).definitions()
    try:
        # Reading every piece is what makes the model write the whole answer; the words themselves are not used
        async for _ in llm.stream_turn(messages, menu):
            pass
    except Exception:
        logger.warning("Practice answer failed; the first answer may be slow", exc_info=True)


# Everything the assistant does in the background at start-up so the first customer gets a fast answer:
# load the models, then practice on them. Called once from the lifespan.
async def get_models_ready_for_first_customer() -> None:
    await load_models_into_memory()
    await practice_router_and_judge()
    await practice_writing_an_answer()
    logger.info("Models loaded and practiced")
