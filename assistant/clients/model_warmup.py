import logging

import httpx

from assistant.config import settings

logger = logging.getLogger(__name__)


# Ollama's own address. Our chat client talks to its OpenAI-style "/v1" door, which has no keep-alive option;
# the warm-up needs the native door, which is the same address without "/v1".
def ollama_native_url() -> str:
    return settings.llm_base_url.removesuffix("/v1")


# Loads the chat model and the embedding model into memory and asks Ollama to keep them there, so the first
# customer after a quiet spell does not wait for a load (about 8 seconds for chat, more for the embedding model).
# Never raises: if Ollama is down the app still starts and the first questions are just slower.
async def load_models_into_memory() -> None:
    try:
        # A short limit to connect, but a long one to read: loading a model can take a while
        async with httpx.AsyncClient(base_url=ollama_native_url(), timeout=httpx.Timeout(10.0, read=120.0)) as client:
            # A generate request with no prompt loads the model and answers nothing
            chat = await client.post("/api/generate", json={"model": settings.llm_model, "keep_alive": settings.model_keep_alive})
            chat.raise_for_status()
            # An embed request with empty input does the same for the embedding model
            embedding = await client.post(
                "/api/embed", json={"model": settings.embedding_model, "input": "", "keep_alive": settings.model_keep_alive}
            )
            embedding.raise_for_status()
        logger.info("Chat and embedding models loaded: keeping them for %s", settings.model_keep_alive)
    except httpx.HTTPError:
        logger.warning("Could not warm the models (is Ollama running?); the first questions may be slow", exc_info=True)
