import asyncio

import httpx
import pytest
from sqlalchemy import text
from sqlmodel import Session, select

from assistant.clients import embeddings
from assistant.clients.embeddings import EmbeddingUnavailableError, embed_texts_for_search
from assistant.config import settings
from assistant.database import engine
from assistant.models import HelpPassage


# Makes embed_texts_for_search talk to a fake server instead of Ollama. "handler" receives the request
# and returns the response.
def use_fake_server(monkeypatch, handler):
    real_client = httpx.AsyncClient
    monkeypatch.setattr(
        embeddings.httpx, "AsyncClient", lambda **kwargs: real_client(transport=httpx.MockTransport(handler), **kwargs)
    )


def test_texts_are_sent_in_one_request_and_come_back_in_the_order_sent(monkeypatch):
    seen = {}

    def handler(request):
        seen["url"], seen["body"] = str(request.url), request.read().decode()
        # Deliberately out of order: the client must sort by "index"
        return httpx.Response(
            200, json={"data": [{"index": 1, "embedding": [0.2]}, {"index": 0, "embedding": [0.1]}]}
        )

    use_fake_server(monkeypatch, handler)
    assert asyncio.run(embed_texts_for_search(["first", "second"])) == [[0.1], [0.2]]
    assert seen["url"].endswith("/embeddings")
    assert settings.embedding_model in seen["body"] and "first" in seen["body"] and "second" in seen["body"]


def test_an_unreachable_server_becomes_embedding_unavailable(monkeypatch):
    def handler(request):
        raise httpx.ConnectError("down")

    use_fake_server(monkeypatch, handler)
    with pytest.raises(EmbeddingUnavailableError):
        asyncio.run(embed_texts_for_search(["x"]))


def test_a_missing_model_is_an_error_not_silent(monkeypatch):
    use_fake_server(monkeypatch, lambda request: httpx.Response(404, json={"error": "model not found"}))
    with pytest.raises(httpx.HTTPStatusError):
        asyncio.run(embed_texts_for_search(["x"]))


# A vector with a 1 in one position and 0 elsewhere, so distances are easy to reason about
def unit_vector(position):
    vector = [0.0] * settings.embedding_dimensions
    vector[position] = 1.0
    return vector


def test_passages_are_stored_with_vectors_and_found_by_closeness():
    with Session(engine) as session:
        session.exec(text("TRUNCATE help_passages"))
        for position, heading in enumerate(["Cancelling", "Fees", "Taxes"]):
            session.add(
                HelpPassage(source="a.md", article="A", heading=heading, text=heading, text_hash="h", embedding=unit_vector(position))
            )
        session.commit()
        # Nearest to a query that points the same way as "Fees". cosine_distance is 0 for the same direction.
        nearest = session.exec(
            select(HelpPassage).order_by(HelpPassage.embedding.cosine_distance(unit_vector(1))).limit(1)
        ).one()
        assert nearest.heading == "Fees"
        session.exec(text("TRUNCATE help_passages"))
        session.commit()
