import asyncio

import pytest
from sqlalchemy import text
from sqlmodel import Session

from assistant.database import engine
from assistant.knowledge.passages import Passage
from assistant.repositories.help_passages import HelpPassageRepository
from assistant.services.help_center_service import DOCUMENT_LABEL, QUESTION_LABEL, HelpCenterService

DIMENSIONS = 768


@pytest.fixture(autouse=True)
def empty_table():
    with Session(engine) as session:
        session.exec(text("TRUNCATE help_passages"))
        session.commit()


# A stand-in embedder: each topic word points in its own direction, so a text about "fees" is close to a
# question about "fees" and far from one about "tax". It also records what it was asked to embed.
class FakeEmbedder:
    TOPICS = ["fees", "tax", "transfer"]

    def __init__(self):
        self.requests = []

    async def __call__(self, texts):
        self.requests.append(texts)
        vectors = []
        for text_ in texts:
            vector = [0.0] * DIMENSIONS
            for position, topic in enumerate(self.TOPICS):
                if topic in text_.lower():
                    vector[position] = 1.0
            # A text about no topic points somewhere unrelated to all of them
            if not any(vector):
                vector[DIMENSIONS - 1] = 1.0
            vectors.append(vector)
        return vectors


def passage(heading, words, source="a.md"):
    return Passage(article="Guide", heading=heading, text=words, source=source)


def make_service(db, embedder):
    return HelpCenterService(db, HelpPassageRepository(db), embedder)


@pytest.fixture
def db():
    with Session(engine) as session:
        yield session


ARTICLES = [passage("Fees", "what fees cost"), passage("Taxes", "tax forms"), passage("Moving", "transfer times")]


def test_first_indexing_adds_every_passage_with_the_document_label(db):
    embedder = FakeEmbedder()
    report = asyncio.run(make_service(db, embedder).index_help_center_articles(ARTICLES))
    assert (report.added, report.updated, report.unchanged, report.removed) == (3, 0, 0, 0)
    # One request for all three, each with the label the model expects
    assert len(embedder.requests) == 1 and len(embedder.requests[0]) == 3
    assert all(t.startswith(DOCUMENT_LABEL) for t in embedder.requests[0])


def test_indexing_again_changes_nothing_and_embeds_nothing(db):
    embedder = FakeEmbedder()
    service = make_service(db, embedder)
    asyncio.run(service.index_help_center_articles(ARTICLES))
    report = asyncio.run(service.index_help_center_articles(ARTICLES))
    assert (report.added, report.updated, report.unchanged, report.removed) == (0, 0, 3, 0)
    assert len(embedder.requests) == 1


def test_only_the_edited_passage_is_embedded_again_and_removed_sections_are_deleted(db):
    embedder = FakeEmbedder()
    service = make_service(db, embedder)
    asyncio.run(service.index_help_center_articles(ARTICLES))
    edited = [passage("Fees", "what fees cost, now different"), ARTICLES[1]]
    report = asyncio.run(service.index_help_center_articles(edited))
    assert (report.added, report.updated, report.unchanged, report.removed) == (0, 1, 1, 1)
    # Only the one changed passage went to the embedder the second time
    assert len(embedder.requests[1]) == 1
    stored = HelpPassageRepository(db).stored_passages_by_location()
    assert set(stored) == {("a.md", "Fees"), ("a.md", "Taxes")}
    assert stored[("a.md", "Fees")].text == "what fees cost, now different"


def test_a_failed_embedding_leaves_the_table_untouched(db):
    async def broken(texts):
        raise RuntimeError("model down")

    with pytest.raises(RuntimeError):
        asyncio.run(make_service(db, broken).index_help_center_articles(ARTICLES))
    assert HelpPassageRepository(db).stored_passages_by_location() == {}


def test_search_returns_the_matching_passage_first_with_the_question_label(db):
    embedder = FakeEmbedder()
    service = make_service(db, embedder)
    asyncio.run(service.index_help_center_articles(ARTICLES))
    found = asyncio.run(service.find_nearby_passages("How much do fees cost?"))
    assert embedder.requests[-1][0].startswith(QUESTION_LABEL)
    assert [f.heading for f in found] == ["Fees"]
    assert found[0].distance < 0.01 and found[0].source == "a.md"


def test_a_question_about_nothing_in_the_help_center_returns_nothing(db):
    service = make_service(db, FakeEmbedder())
    asyncio.run(service.index_help_center_articles(ARTICLES))
    assert asyncio.run(service.find_nearby_passages("What is the weather today?")) == []


def index_test_articles(db):
    asyncio.run(make_service(db, FakeEmbedder()).index_help_center_articles(ARTICLES))


def test_keyword_search_finds_the_passage_with_the_questions_words_best_first(db):
    index_test_articles(db)
    found = HelpPassageRepository(db).best_by_keywords("how much do fees cost", 3)
    assert [row.heading for row, _ in found] == ["Fees"]
    assert found[0][1] > 0


def test_keyword_search_matches_word_forms_not_just_exact_words(db):
    index_test_articles(db)
    # The passage says "forms"; the customer says "form"
    found = HelpPassageRepository(db).best_by_keywords("which tax form do I need", 3)
    assert found[0][0].heading == "Taxes"


def test_keyword_search_returns_nothing_for_filler_words_or_no_words(db):
    index_test_articles(db)
    repo = HelpPassageRepository(db)
    assert repo.best_by_keywords("what is it", 3) == []
    assert repo.best_by_keywords("?! & | ()", 3) == []


def test_keyword_search_cannot_be_broken_by_the_search_languages_own_symbols(db):
    index_test_articles(db)
    found = HelpPassageRepository(db).best_by_keywords("fees & | ! ( ) ' ; drop table", 3)
    assert found[0][0].heading == "Fees"


def test_keyword_search_respects_the_limit(db):
    index_test_articles(db)
    found = HelpPassageRepository(db).best_by_keywords("fees tax transfer", 2)
    assert len(found) == 2
