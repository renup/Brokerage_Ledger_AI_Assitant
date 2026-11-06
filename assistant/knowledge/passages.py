import re
from dataclasses import dataclass
from pathlib import Path

# Where the help-center articles are kept: one markdown file each
HELP_CENTER_FOLDER = Path(__file__).parent / "help_center"


# One searchable piece of the help center: a single section of an article. It keeps its article and heading
# so it can be understood on its own and shown to the customer as the source of an answer.
@dataclass(frozen=True)
class Passage:
    article: str
    heading: str
    text: str
    # The file it came from, e.g. "fees-and-charges.md"
    source: str

    # The words that get turned into numbers for searching. The title and heading are included because
    # they say what a short body is about.
    def searchable_text(self) -> str:
        return f"{self.article}: {self.heading}\n{self.text}"


# Splits one article into passages, one per "## heading" section.
def split_article_into_passages(source: str, markdown: str) -> list[Passage]:
    # The first line is "# Article title"; everything after it is split at each "## " heading
    title_line, _, body = markdown.partition("\n")
    article = title_line.removeprefix("# ").strip()

    passages = []
    # re.split leaves whatever came before the first "## " in position 0; it is blank, so [1:] skips it
    for section in re.split(r"^## ", body, flags=re.MULTILINE)[1:]:
        heading, _, text = section.partition("\n")
        passages.append(Passage(article, heading.strip(), text.strip(), source))
    return passages


# Reads every article in the folder and returns all their passages. Sorted by file name so the
# order is the same on every machine.
def load_help_center_passages(folder: Path = HELP_CENTER_FOLDER) -> list[Passage]:
    passages = []
    for path in sorted(folder.glob("*.md")):
        passages.extend(split_article_into_passages(path.name, path.read_text()))
    return passages