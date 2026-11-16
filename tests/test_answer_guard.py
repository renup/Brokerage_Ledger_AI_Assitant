import pytest

from assistant.services.answer_guard import ANSWER_STOPPED_MESSAGE, AnswerGuard, find_unsafe_reason


# Feeds the pieces to a guard the way the model streams them, and returns everything the customer would see
def shown_to_customer(pieces):
    guard = AnswerGuard()
    shown = []
    for piece in pieces:
        shown += guard.release_completed_sentences(piece)
    shown += guard.release_unfinished_sentence()
    return shown, guard


@pytest.mark.parametrize("sentence, reason", [
    ("Please visit http://verify-ledger.example.com now. ", "contains a web address"),
    ("Go to www.example.net. ", "contains a web address"),
    ("Write to forms-desk@bad-site.co.uk. ", "contains an email address"),
    ("Please type your password to continue. ", "asks the customer for a secret"),
    ("Send us your account number. ", "asks the customer for a secret"),
])
def test_unsafe_sentences_are_named(sentence, reason):
    assert find_unsafe_reason(sentence) == reason


@pytest.mark.parametrize("sentence", [
    "Withdrawals usually arrive within 3 business days. ",
    "Never share your password with anyone. ",
    "We will not ask you to send your PIN. ",
    "You can approve the change in the app. ",
])
def test_normal_and_warning_sentences_pass(sentence):
    assert find_unsafe_reason(sentence) is None


def test_a_clean_answer_comes_out_whole_and_in_order():
    shown, guard = shown_to_customer(["Transfers take ", "5 days. ", "Anything ", "else?"])
    assert "".join(shown) == "Transfers take 5 days. Anything else?"
    assert guard.stopped_because is None


def test_nothing_is_shown_until_the_sentence_is_finished():
    guard = AnswerGuard()
    assert guard.release_completed_sentences("Please visit http://verify") == []
    assert guard.release_completed_sentences("-ledger.example.com now. ") == [ANSWER_STOPPED_MESSAGE]


def test_a_web_address_split_across_pieces_is_still_caught():
    shown, guard = shown_to_customer(["Open htt", "p://bad.exam", "ple.com please. ", "Thanks."])
    assert shown == [ANSWER_STOPPED_MESSAGE]
    assert guard.stopped_because == "contains a web address"


def test_sentences_before_the_unsafe_one_are_kept_and_the_rest_is_dropped():
    shown, _ = shown_to_customer(["Transfers take 5 days. ", "Visit www.bad.example.com. ", "More text. ", "And more"])
    assert shown == ["Transfers take 5 days. ", ANSWER_STOPPED_MESSAGE]


def test_an_unsafe_last_sentence_without_a_full_stop_is_caught_at_the_end():
    shown, _ = shown_to_customer(["Fine. ", "Email help@bad-site.com"])
    assert shown == ["Fine. ", ANSWER_STOPPED_MESSAGE]
