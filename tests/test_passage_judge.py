import asyncio

from assistant import llm
from assistant.services import passage_judge
from assistant.services.help_center_service import FoundPassage
from assistant.services.passage_judge import keep_only_passages_that_answer, parse_kept_numbers, question_and_numbered_passages


def passage(heading, text="Some words."):
    return FoundPassage(article="Guide", heading=heading, text=text, source="guide.md", distance=0.3)


THREE = [passage("Fees"), passage("Taxes"), passage("Moving")]


# Makes the model answer with this exact text, and records what it was asked
def model_says(monkeypatch, reply, asked=None):
    async def fake_turn(messages, tools=None):
        if asked is not None:
            asked.append(messages)
        yield reply

    monkeypatch.setattr(llm, "stream_turn", fake_turn)


def test_the_numbers_in_the_reply_are_the_passages_kept():
    assert parse_kept_numbers("1, 3", 3) == {1, 3}
    assert parse_kept_numbers("Passage 2", 3) == {2}


def test_none_means_no_passage_answers_the_question():
    assert parse_kept_numbers("none", 3) == set()
    assert parse_kept_numbers("None.", 3) == set()


def test_a_reply_that_makes_no_sense_is_not_trusted():
    assert parse_kept_numbers("I think they are all fine", 3) is None
    # Numbers outside the list are ignored; with nothing left and no "none", the reply is not trusted
    assert parse_kept_numbers("7", 3) is None


def test_the_judge_sees_the_question_and_each_passage_numbered_from_one():
    text = question_and_numbered_passages("how much?", ["alpha", "beta"])
    assert text == "Question: how much?\nPassage 1: alpha\nPassage 2: beta"


def test_only_the_passages_the_judge_names_are_kept_in_their_original_order(monkeypatch):
    model_says(monkeypatch, "3, 1")
    kept = asyncio.run(keep_only_passages_that_answer("q", THREE))
    assert [p.heading for p in kept] == ["Fees", "Moving"]


def test_when_the_judge_says_none_nothing_is_kept(monkeypatch):
    model_says(monkeypatch, "none")
    assert asyncio.run(keep_only_passages_that_answer("q", THREE)) == []


def test_the_judge_is_given_each_passage_with_its_heading(monkeypatch):
    asked = []
    model_says(monkeypatch, "1", asked)
    asyncio.run(keep_only_passages_that_answer("q", [passage("Fees", "Trades are free.")]))
    assert "Passage 1: Fees: Trades are free." in asked[0][1]["content"]


def test_a_confusing_reply_keeps_every_passage(monkeypatch):
    model_says(monkeypatch, "hard to say")
    assert asyncio.run(keep_only_passages_that_answer("q", THREE)) == THREE


def test_a_failing_model_keeps_every_passage_instead_of_failing_the_search(monkeypatch):
    async def broken_turn(messages, tools=None):
        raise RuntimeError("model is down")
        yield  # makes this an async generator

    monkeypatch.setattr(llm, "stream_turn", broken_turn)
    assert asyncio.run(keep_only_passages_that_answer("q", THREE)) == THREE


def test_with_no_nearby_passages_the_model_is_not_asked_at_all(monkeypatch):
    asked = []
    model_says(monkeypatch, "1", asked)
    assert asyncio.run(keep_only_passages_that_answer("q", [])) == []
    assert asked == []
