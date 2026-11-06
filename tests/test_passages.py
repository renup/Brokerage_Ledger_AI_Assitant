from assistant.knowledge.passages import HELP_CENTER_FOLDER, load_help_center_passages, split_article_into_passages

ARTICLE = """# Fees

## Trades
Trades are free.

## Transfers out
An outgoing transfer costs $75.
"""


def test_an_article_splits_into_one_passage_per_heading():
    passages = split_article_into_passages("fees.md", ARTICLE)
    assert [(p.article, p.heading, p.text, p.source) for p in passages] == [
        ("Fees", "Trades", "Trades are free.", "fees.md"),
        ("Fees", "Transfers out", "An outgoing transfer costs $75.", "fees.md"),
    ]


def test_the_searchable_text_carries_the_title_and_heading():
    passage = split_article_into_passages("fees.md", ARTICLE)[1]
    assert passage.searchable_text() == "Fees: Transfers out\nAn outgoing transfer costs $75."


def test_an_article_with_no_sections_gives_no_passages():
    assert split_article_into_passages("empty.md", "# Just a title\n") == []


# Guards the real articles, so a badly formatted new article is caught before it is searched
def test_every_real_article_has_a_title_and_well_sized_passages():
    files = sorted(HELP_CENTER_FOLDER.glob("*.md"))
    assert len(files) >= 6
    passages = load_help_center_passages()
    assert {p.source for p in passages} == {f.name for f in files}
    for passage in passages:
        assert passage.article and passage.heading, passage
        # Short enough to be one clear answer, long enough to mean something
        assert 8 <= len(passage.text.split()) <= 200, (passage.source, passage.heading)
    # No two passages share a source and heading, or a citation could point at the wrong one
    assert len({(p.source, p.heading) for p in passages}) == len(passages)


def test_the_load_order_is_the_same_every_time():
    assert load_help_center_passages() == load_help_center_passages()
