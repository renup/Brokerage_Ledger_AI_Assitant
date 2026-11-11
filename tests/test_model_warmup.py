import asyncio
import json
import logging

import httpx

from assistant.clients import model_warmup
from assistant.clients.model_warmup import load_models_into_memory, ollama_native_url
from assistant.config import settings


# Makes the warm-up talk to a fake server instead of Ollama. "handler" receives the request and returns the response.
def use_fake_server(monkeypatch, handler):
    real_client = httpx.AsyncClient
    monkeypatch.setattr(
        model_warmup.httpx, "AsyncClient", lambda **kwargs: real_client(transport=httpx.MockTransport(handler), **kwargs)
    )


def test_the_native_address_is_the_chat_address_without_v1(monkeypatch):
    monkeypatch.setattr(settings, "llm_base_url", "http://localhost:11434/v1")
    assert ollama_native_url() == "http://localhost:11434"


def test_both_models_are_loaded_and_asked_to_stay(monkeypatch):
    seen = []

    def handler(request):
        seen.append((request.url.path, json.loads(request.read())))
        return httpx.Response(200, json={})

    use_fake_server(monkeypatch, handler)
    asyncio.run(load_models_into_memory())

    assert seen == [
        ("/api/generate", {"model": settings.llm_model, "keep_alive": settings.model_keep_alive}),
        ("/api/embed", {"model": settings.embedding_model, "input": "", "keep_alive": settings.model_keep_alive}),
    ]


def test_an_unreachable_ollama_only_logs_a_warning(monkeypatch, caplog):
    def handler(request):
        raise httpx.ConnectError("refused")

    use_fake_server(monkeypatch, handler)
    with caplog.at_level(logging.WARNING):
        asyncio.run(load_models_into_memory())

    assert "Could not warm the models" in caplog.text


def test_a_model_that_is_not_pulled_only_logs_a_warning(monkeypatch, caplog):
    use_fake_server(monkeypatch, lambda request: httpx.Response(404, json={"error": "model not found"}))
    with caplog.at_level(logging.WARNING):
        asyncio.run(load_models_into_memory())

    assert "Could not warm the models" in caplog.text
