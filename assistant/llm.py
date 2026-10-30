import json
from collections.abc import AsyncIterator
from dataclasses import dataclass

import httpx

from assistant.config import settings


# One tool the model asked us to run. "arguments" is the JSON text the model wrote.
@dataclass(frozen=True)
class ToolCall:
    id: str
    name: str
    arguments: str


# The one place we talk to the model. An async generator: each "yield" hands something to the
# caller immediately, instead of waiting for the whole reply. It yields two kinds of thing:
#   - a str: the next bit of the answer in words
#   - a ToolCall: the model is asking us to run a tool
# "messages" is the conversation as a list of {"role": ..., "content": ...} dicts (as in the
# tokenizer notebook). "tools" is the list of tool definitions the model may use; leave it out
# and the model can only answer in words.
async def stream_turn(messages: list[dict], tools: list[dict] | None = None) -> AsyncIterator[str | ToolCall]:
    # The request body in the OpenAI-style format that Ollama understands
    payload = {
        "model": settings.llm_model,
        "messages": messages,
        "temperature": settings.llm_temperature,
        # Cap on the reply length, in tokens (from 4.1)
        "max_tokens": settings.llm_max_tokens,
        # Ask the server to send the reply in pieces as they are generated
        "stream": True,
    }
    # Only offer tools when we pass some. Leaving the key out means "answer in words only".
    if tools:
        payload["tools"] = tools

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
            # The reply is SSE: one "data: {...}" line per piece
            async for line in response.aiter_lines():
                # Skip blank separator lines
                if not line.startswith("data: "):
                    continue
                data = line[len("data: "):]
                # The server sends "data: [DONE]" as its final line
                if data == "[DONE]":
                    break
                # Each chunk holds a small "delta": the next bit of text and/or tool calls
                delta = json.loads(data)["choices"][0]["delta"]
                # Some chunks (the first, the last) carry no text, so skip them
                if delta.get("content"):
                    yield delta["content"]
                # Ollama sends each tool call complete in one chunk. (Some other providers
                # stream the arguments in fragments; we would need to stitch those together.)
                for call in delta.get("tool_calls") or []:
                    function = call["function"]
                    yield ToolCall(id=call["id"], name=function["name"], arguments=function["arguments"])


# Words only, for callers that never use tools. A thin wrapper so the HTTP code above exists once.
# (Step 4b switches ChatService to the agent loop, and then this can be deleted.)
async def stream_chat(messages: list[dict]) -> AsyncIterator[str]:
    async for item in stream_turn(messages):
        if isinstance(item, str):
            yield item
