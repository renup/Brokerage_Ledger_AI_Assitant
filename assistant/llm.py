import json
from collections.abc import AsyncIterator

import httpx
from assistant.config import settings


# An async generator: each "yield" hands one piece of text to the caller
# immediately, instead of waiting for the whole reply.
# "messages" is the conversation as a list of {"role": ..., "content": ...} dicts,
# the same shape you built in the tokenizer notebook.
async def stream_chat(messages: list[dict]) -> AsyncIterator[str]:
    # The request body in the OpenAI-style format that Ollama understands
    payload = {
        "model": settings.llm_model,
        "messages": messages,
        "temperature": settings.llm_temperature,
        # Cap on the reply length, in tokens (from 4.1)
        "max_tokens": settings.llm_max_tokens,
        # Ask the server to send the reply in pieces as they are generated
        "stream": True
    }

    # OpenAI-style APIs expect the key in this header. Ollama ignores the value.
    headers = {"Authorization": f"Bearer {settings.llm_api_key}"}

    # Timeout: wait up to 10s to connect, but up to 120s for data, because the first
    # token can be slow while the model loads into memory.
    async with httpx.AsyncClient(timeout=httpx.Timeout(10.0, read=120.0)) as client:
        # client.stream keeps the connection open and lets us read the body as it arrives
        async with client.stream(
            "POST", f"{settings.llm_base_url}/chat/completions", json=payload, headers=headers
        ) as response:
            # Turn an HTTP error (model not found, server error) into an exception
            response.raise_for_status()
            # The reply is SSE, the same format your own /chat sends: one "data: {...}" line per piece
            async for line in response.aiter_lines():
                # Skip blank separator lines
                if not line.startswith("data: "):
                    continue
                data = line[len("data: "):]
                # The server sends "data: [DONE]" as its final line
                if data == "[DONE]":
                    break
                # Each chunk holds a small "delta" with the next bit of text.
                # The key is "content" (it was mistyped "context" before, which always gave None).
                piece = json.loads(data)["choices"][0]["delta"].get("content")
                # Some chunks (the first, the last) carry no text, so skip them
                if piece:
                    yield piece
