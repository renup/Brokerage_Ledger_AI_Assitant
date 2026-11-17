from assistant.services.chat_service import customer_words_in


def test_only_what_the_customer_wrote_is_collected_in_order():
    messages = [
        {"role": "system", "content": "rules mention Maya Rose Patel"},
        {"role": "user", "content": "my name is wrong"},
        {"role": "assistant", "content": "What should it say? Maybe Jane Doe?"},
        {"role": "tool", "content": "Sam Smith"},
        {"role": "user", "content": "Maya Rose Patel"},
    ]
    assert customer_words_in(messages) == "my name is wrong\nMaya Rose Patel"


def test_a_message_with_no_text_is_skipped():
    assert customer_words_in([{"role": "user", "content": None}, {"role": "user", "content": "hi"}]) == "hi"
