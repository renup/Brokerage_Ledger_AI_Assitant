import httpx

from assistant.config import settings


# The embedding model could not be reached (Ollama is down, or the model is not installed)
class EmbeddingUnavailableError(Exception):
    pass


# Turns texts into lists of numbers that capture their meaning, so that "cancel a withdrawal" ends up
# near "stop my payout" even though they share no words. Many texts go in one request.
# Like llm.py it uses the OpenAI-style API that Ollama serves, so a different provider later is a settings change.
async def embed_texts_for_search(texts: list[str]) -> list[list[float]]:
    headers = {"Authorization": f"Bearer {settings.llm_api_key}"}
    try:
        async with httpx.AsyncClient(timeout=httpx.Timeout(10.0, read=60.0)) as client:
            response = await client.post(
                f"{settings.llm_base_url}/embeddings",
                json={"model": settings.embedding_model, "input": texts},
                headers=headers,
            )
    except httpx.RequestError as exc:
        raise EmbeddingUnavailableError("Could not reach the embedding model") from exc
    # A 404 here usually means the model has not been pulled
    response.raise_for_status()
    # Each result says which input it belongs to; sorting by that keeps them in the order we sent
    items = sorted(response.json()["data"], key=lambda item: item["index"])
    return [item["embedding"] for item in items]
