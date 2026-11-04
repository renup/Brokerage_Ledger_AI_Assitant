import json

from assistant.llm import ToolCall
from evals.run_tool_eval import score_case


def call(name, **arguments):
    return ToolCall(id="c", name=name, arguments=json.dumps(arguments))


CASE = {
    "id": "x", "category": "t", "question": "q",
    "expected_tools": ["get_transfer_status"], "expected_args": {"get_transfer_status": {"transfer_id": 7}},
    "alternatives": [{"tools": ["lookup_error_code"], "args": {"lookup_error_code": {"code": "214"}}}],
}


def test_main_answer_passes():
    assert score_case(CASE, [call("get_transfer_status", transfer_id=7)], "")["matched_answer"] == 0


def test_an_alternative_answer_passes():
    result = score_case(CASE, [call("lookup_error_code", code="214")], "")
    assert result["passed"] and result["matched_answer"] == 1


def test_an_alternative_with_wrong_arguments_fails():
    assert not score_case(CASE, [call("lookup_error_code", code="999")], "")["passed"]


def test_an_unlisted_answer_fails_and_is_reported_against_the_main_answer():
    result = score_case(CASE, [call("get_accounts")], "")
    assert not result["passed"] and result["matched_answer"] is None and result["choice_ok"] is False


def test_cases_without_alternatives_behave_as_before():
    case = {"id": "y", "category": "t", "question": "q", "expected_tools": [], "expected_args": {}}
    assert score_case(case, [], "words")["passed"]
    assert not score_case(case, [call("get_accounts")], "")["passed"]
