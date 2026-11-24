import pytest

from assistant.services.message_parts import split_message_into_parts


@pytest.mark.parametrize("message", [
    "What is my balance?",
    "what is my balance and withdrawals",
    "my transfer and my withdrawal",
    "How much is in my Roth IRA",
])
def test_a_message_with_one_request_stays_in_one_piece(message):
    assert split_message_into_parts(message) == [message]


@pytest.mark.parametrize("message, parts", [
    ("Can I withdraw 2500, and how long would it take?", ["Can I withdraw 2500", "how long would it take?"]),
    ("whats the weather in boston and what is my balance?", ["whats the weather in boston", "what is my balance?"]),
    ("What are the fees? How long does a transfer take?", ["What are the fees?", "How long does a transfer take?"]),
    ("show my pending transfers, also how long do transfers usually take", ["show my pending transfers", "how long do transfers usually take"]),
    ("did my transfer finish?? and what are your support hours", ["did my transfer finish??", "what are your support hours"]),
])
def test_joined_or_separate_requests_become_parts_in_the_order_asked(message, parts):
    assert split_message_into_parts(message) == parts


def test_an_empty_message_comes_back_as_it_is():
    assert split_message_into_parts("") == [""]
    assert split_message_into_parts("   ") == ["   "]
