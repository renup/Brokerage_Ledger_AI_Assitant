import re

import pytest

from assistant.knowledge.passages import load_help_center_passages
from assistant.services.answer_guard import (
    ANSWER_STOPPED_MESSAGE,
    AnswerGuard,
    checked_figures_in,
    turnarounds_backed_by,
    turnarounds_in,
    every_figure_in,
    figures_in_the_real_help_articles,
    find_tax_liability_claim,
    find_unsafe_reason,
    normalise_number,
)


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


# --- figures and codes: an answer may only state what a trusted source backs ---

@pytest.mark.parametrize("written, expected", [
    ("25,000", "25000"), ("25,000.00", "25000"), ("25000", "25000"), ("1,200.50", "1200.5"), ("7", "7"),
])
def test_one_figure_written_different_ways_compares_equal(written, expected):
    assert normalise_number(written) == expected


def test_only_money_percentages_large_numbers_codes_and_turnaround_times_are_checked():
    sentence = "Pay $5 or 3 business days or 2.5% or 7,500 or 12000 or QUIET-FEE-0 or step 4 or e-mail."
    # "step 4" is a small plain number and is not checked; "3 business days" is a turnaround time and is, last in the list
    assert checked_figures_in(sentence) == ["5", "2.5", "7500", "12000", "QUIET-FEE-0", "3 day"]
    assert checked_figures_in(sentence, with_turnarounds=False) == ["5", "2.5", "7500", "12000", "QUIET-FEE-0"]


def test_every_number_in_a_trusted_text_is_trusted_even_small_ones():
    assert every_figure_in('{"amount": 500.0, "id": 7, "reference": "HO-4471"}') == {"500", "7", "4471", "HO-4471"}


def test_the_real_help_article_limit_is_trusted():
    assert "25000" in figures_in_the_real_help_articles()


def test_a_figure_no_source_backs_stops_the_answer():
    shown, guard = shown_to_customer(["The limit is $750,000. ", "Anything else."])
    assert shown == [ANSWER_STOPPED_MESSAGE]
    assert "750000" in guard.stopped_because


def test_a_code_no_source_backs_stops_the_answer():
    shown, _ = shown_to_customer(["Quote QUIET-FEE-0 for no fee. "])
    assert shown == [ANSWER_STOPPED_MESSAGE]


def test_the_real_article_limit_passes_in_any_spelling():
    shown, guard = shown_to_customer(["The most is $25,000 or 25000 dollars. "])
    assert shown == ["The most is $25,000 or 25000 dollars. "]
    assert guard.stopped_because is None


def test_figures_from_ledger_results_and_the_customers_words_are_backed():
    guard = AnswerGuard()
    guard.trust_figures_in('{"balance": 1200.5, "reference": "HO-4471"}')
    guard.trust_figures_in("I want to move $5,000")
    shown = guard.release_completed_sentences("Balance $1,200.50, ref HO-4471, moving $5,000. ")
    assert shown == ["Balance $1,200.50, ref HO-4471, moving $5,000. "]


def test_one_unbacked_figure_stops_a_sentence_that_also_has_a_real_one():
    shown, _ = shown_to_customer(["The limit is $25,000 and the bonus is $9,999. "])
    assert shown == [ANSWER_STOPPED_MESSAGE]


# Lengths of time: a number (or range) and a unit are checked as a pair
def test_turnaround_times_are_read_in_one_written_form():
    assert turnarounds_in("It takes 3 business days.") == ["3 day"]
    assert turnarounds_in("5 to 7 working days, or 24 hours") == ["5-7 day", "24 hour"]
    assert turnarounds_in("1-2 weeks") == ["1-2 week"]


def test_other_small_numbers_are_not_turnaround_times():
    # "day 2 of 3" and "1,000 days" are not lengths of time as written
    assert turnarounds_in("It is day 2 of 3. Step 2.") == []
    assert turnarounds_in("about 1,000 days") == []


def test_a_range_backs_each_end_of_it():
    assert {"5-7 day", "5 day", "7 day"} <= turnarounds_backed_by("Takes 5 to 7 business days.")


def stopped_after(answer: str) -> str | None:
    guard = AnswerGuard()
    guard.release_completed_sentences(answer + " ")
    return guard.stopped_because


def test_an_invented_turnaround_time_is_stopped_and_the_real_ones_are_not():
    assert stopped_after("Withdrawals usually take 3 to 5 business days.") is not None
    assert stopped_after("Withdrawals usually take 3 business days.") is None
    assert stopped_after("A transfer in takes 5 to 7 business days.") is None
    assert stopped_after("It can take up to 7 days.") is None


def test_the_customers_own_turnaround_time_is_trusted():
    guard = AnswerGuard()
    guard.trust_figures_in("I need it within 9 days")
    guard.release_completed_sentences("You asked about 9 days. ")
    assert guard.stopped_because is None


def test_turnaround_times_are_not_checked_once_ledger_data_backs_the_answer():
    guard = AnswerGuard()
    guard.trust_figures_in('{"business_day": 2, "total_business_days": 3}')
    guard.stop_checking_turnarounds_for_this_answer()
    guard.release_completed_sentences("About 1 business day is left. ")
    assert guard.stopped_because is None
    # Money and codes are still checked
    guard.release_completed_sentences("Your fee is $45. ")
    assert guard.stopped_because is not None


# --- tax claims: the assistant may not say what a customer owes or must report ---

@pytest.mark.parametrize("sentence", [
    "You do not owe any tax on withdrawals from your account. ",
    "You owe tax on this gain. ",
    "There is nothing to report on your return. ",
    "You must report this withdrawal as income. ",
    "You don't need to report it. ",
])
def test_a_sentence_saying_what_the_customer_owes_or_reports_is_stopped(sentence):
    assert find_tax_liability_claim(sentence) is not None
    assert stopped_after(sentence.strip()) is not None


@pytest.mark.parametrize("sentence", [
    "A Roth IRA is funded with money that has already been taxed. ",
    "Ask a tax professional whether you owe tax on this. ",
    "I can't say what you owe, so please talk to a tax adviser. ",
    "Tax forms for the year are in your documents. ",
    "If you owe anything, a tax professional can tell you. ",
    # General facts about an account type are not a claim about this customer's own tax duty
    "Roth withdrawals are generally tax-free. ",
    "A traditional IRA is usually taxable when you withdraw. ",
])
def test_neutral_or_hedged_tax_sentences_pass(sentence):
    assert find_tax_liability_claim(sentence) is None


def test_no_sentence_in_the_real_help_articles_is_a_tax_claim():
    for real in load_help_center_passages():
        for sentence in re.split(r"(?<=[.!?])\s+", f"{real.heading}. {real.text}"):
            assert find_tax_liability_claim(sentence) is None, (real.source, sentence)
