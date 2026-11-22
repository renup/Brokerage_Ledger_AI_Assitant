import logging
import re
from decimal import Decimal
from functools import lru_cache

from assistant.knowledge.passages import load_help_center_passages

logger = logging.getLogger(__name__)

# What the customer sees instead of an answer the guard stopped
ANSWER_STOPPED_MESSAGE = "I'm sorry, I can't finish that answer here. I can connect you with a person if you would like."

# A sentence ends at . ! or ? followed by a space, or at a new line. A dot inside a web address is not followed by
# a space, so an address stays in one piece.
SENTENCE_END = re.compile(r"[.!?]\s|\n")

# Things the assistant must never tell a customer, whatever the passages or the model said. The list is short on
# purpose: it names the harms (a link, an address, a request for a secret), not the ways an attacker can word them.
UNSAFE_ANSWER_PATTERNS = {
    "contains a web address": r"https?://|www\.|\b[\w-]+\.(com|net|org|io)\b",
    "contains an email address": r"[\w.+-]+@[\w-]+\.[\w.]+",
    "asks the customer for a secret": r"\b(enter|type|send|share|confirm|provide|submit|give|email)\b[^.!?\n]{0,60}\b(password|passcode|pin|ssn|social security|account number)\b",
}

# A sentence that warns ("never share your password") mentions a secret without asking for one
WARNING_WORDS = r"\b(never|do not|don't|won't|will not)\b"

# A sentence that says what the customer owes in tax, or must report: the assistant may not say this. General facts
# about how an account type is taxed are not matched here: the router and the system prompt handle those. The real help
# articles never do (a test checks that); the system prompt forbids it, and this makes it a rule in code.
TAX_LIABILITY_CLAIM = re.compile(
    r"\byou\s+(?:(?:do\s+not|don't|will\s+not|won't|never)\s+)?owe\b"
    r"|\bowe\s+(?:any\s+|no\s+)?tax"
    r"|\bno\s+tax(?:es)?\s+(?:is\s+|are\s+)?(?:due|owed)\b"
    r"|\bnothing\s+to\s+report\b"
    r"|\b(?:do\s+not|don't|no\s+need\s+to|not\s+required\s+to|need\s+not)\s+(?:have\s+to\s+)?report\b"
    r"|\b(?:must|need\s+to|have\s+to|required\s+to)\s+report\b",
    re.IGNORECASE,
)

# A sentence with one of these hedges or hands the question to a professional, so it is not a claim
TAX_HEDGE_WORDS = r"\b(whether|if|ask|speak to|talk to|consult|tax professional|tax adviser|tax advisor|cannot|can't)\b"

# A number as written in text: 25,000 or 1200.50 or 7. The $ and % signs are looked at separately.
EVERY_NUMBER = re.compile(r"\d{1,3}(?:,\d{3})+(?:\.\d+)?|\d+(?:\.\d+)?")
# A code such as QUIET-FEE-0 or HO-4471: capital-letter pieces joined by hyphens. No IGNORECASE on purpose,
# so ordinary hyphenated words are not mistaken for codes.
CODE = re.compile(r"\b[A-Z][A-Z0-9]*(?:-[A-Z0-9]+)+\b")

# A turnaround time: how long the assistant says something will take, as written in an answer: "3 business days", "5 to 7 business days", "1-2 weeks", "24 hours".
# The lookbehind keeps the tail of a bigger number ("1,000 days") from being read as a turnaround time. Words such as
# "business" or "working" between the number and the unit are allowed and then ignored.
TURNAROUND_TIME = re.compile(
    r"(?<![\d,.$])(\d+)(?:\s*(?:to|-|–|or)\s*(\d+))?\s+(?:business\s+|working\s+|calendar\s+)?(minute|hour|day|week|month|year)s?\b",
    re.IGNORECASE,
)


# One way to write a number, so $25,000 and 25000 and 25,000.00 compare as equal
def normalise_number(written: str) -> str:
    return format(Decimal(written.replace(",", "")).normalize(), "f")


# One way to write a length of time, so "3 business days" and "3 days" compare as equal
def written_turnaround(first: int, last: int, unit: str) -> str:
    return f"{first}-{last} {unit}" if last != first else f"{first} {unit}"


# The lengths of time stated in a text, in that one written form
def turnarounds_in(text: str) -> list[str]:
    return [written_turnaround(int(m.group(1)), int(m.group(2) or m.group(1)), m.group(3).lower()) for m in TURNAROUND_TIME.finditer(text)]


# The lengths of time a trusted text backs: every one it states, and each end of a range ("5 to 7 business days"
# also backs "7 days"), so a fair paraphrase is not stopped
def turnarounds_backed_by(text: str) -> set[str]:
    backed = set(turnarounds_in(text))
    for m in TURNAROUND_TIME.finditer(text):
        for end in (m.group(1), m.group(2)):
            if end:
                backed.add(written_turnaround(int(end), int(end), m.group(3).lower()))
    return backed


# Only some numbers are checked in an answer: money, percentages, numbers with a thousands comma and numbers of four
# or more digits. Other small plain numbers are NOT checked: they are everywhere in real answers. Lengths of time such as
# "3 business days" are checked separately, see TURNAROUND_TIME.
def is_checked_number(sentence: str, number: re.Match) -> bool:
    written = number.group()
    before = sentence[: number.start()].rstrip()
    after = sentence[number.end():]
    return before.endswith("$") or after.startswith("%") or "," in written or len(written.split(".")[0]) >= 4


# The figures and codes in an answer sentence that must be backed by a trusted source. Lengths of time are included
# unless the answer rests on ledger data (the model may then work one out, such as "1 business day left").
def checked_figures_in(sentence: str, with_turnarounds: bool = True) -> list[str]:
    numbers = [normalise_number(m.group()) for m in EVERY_NUMBER.finditer(sentence) if is_checked_number(sentence, m)]
    return numbers + CODE.findall(sentence) + (turnarounds_in(sentence) if with_turnarounds else [])


# Every number, code and length of time in a trusted text, small numbers too: a trusted source may back any figure it contains
def every_figure_in(text: str) -> set[str]:
    return {normalise_number(m.group()) for m in EVERY_NUMBER.finditer(text)} | set(CODE.findall(text)) | turnarounds_backed_by(text)


# The figures in the real help articles on disk (the firm's own text), read once. The passages the search returns are
# NOT used: a poisoned passage must not be able to vouch for its own fake figure.
@lru_cache
def figures_in_the_real_help_articles() -> frozenset[str]:
    return frozenset(every_figure_in(" ".join(f"{p.heading} {p.text}" for p in load_help_center_passages())))


# The reason a sentence is unsafe to show a customer, or None when it is fine
def find_unsafe_reason(sentence: str) -> str | None:
    for reason, pattern in UNSAFE_ANSWER_PATTERNS.items():
        if re.search(pattern, sentence, flags=re.IGNORECASE):
            if reason == "asks the customer for a secret" and re.search(WARNING_WORDS, sentence, flags=re.IGNORECASE):
                continue
            return reason
    return None


# The reason a sentence is a tax claim the assistant may not make, or None when it is fine
def find_tax_liability_claim(sentence: str) -> str | None:
    if TAX_LIABILITY_CLAIM.search(sentence) and not re.search(TAX_HEDGE_WORDS, sentence, flags=re.IGNORECASE):
        return "says what the customer owes or must report in tax"
    return None


# Holds back the answer as the model writes it and lets each sentence through only after it has been checked.
# Once one sentence is unsafe, the rest of the answer is dropped and the customer gets ANSWER_STOPPED_MESSAGE.
class AnswerGuard:
    def __init__(self):
        # Words received that do not yet form a complete sentence
        self._unchecked_words = ""
        # Figures and codes an answer may mention: the real articles, plus whatever is added with trust_figures_in
        self._trusted_figures = set(figures_in_the_real_help_articles())
        self.stopped_because: str | None = None
        # Off when a ledger lookup backs the answer: the model may work out a length of time that no text states
        self._check_turnarounds = True

    # Adds the figures in this text to what the answer may mention. Used for the customer's own words and for ledger
    # tool results; never for help passages.
    def trust_figures_in(self, text: str) -> None:
        self._trusted_figures |= every_figure_in(text)

    # Called when a ledger lookup backs this answer. The model may then work out a length of time ("1 business day
    # left" from "day 2 of 3") that no text states, so turnaround times are no longer checked for this answer.
    def stop_checking_turnarounds_for_this_answer(self) -> None:
        self._check_turnarounds = False

    # The first figure or code in the sentence that no trusted source backs, as a reason; None when all are backed
    def _find_unsupported_figure(self, sentence: str) -> str | None:
        for figure in checked_figures_in(sentence, self._check_turnarounds):
            if figure not in self._trusted_figures:
                return f"contains a figure or code that no account data or help article backs ({figure})"
        return None

    # Takes the newest words from the model; returns the complete sentences that are safe to show now
    def release_completed_sentences(self, new_words: str) -> list[str]:
        if self.stopped_because:
            return []
        self._unchecked_words += new_words
        released = []
        while (end := SENTENCE_END.search(self._unchecked_words)) and not self.stopped_because:
            sentence = self._unchecked_words[: end.end()]
            self._unchecked_words = self._unchecked_words[end.end():]
            released.append(self._release_or_stop_the_answer(sentence))
        return released

    # Called when the model has finished: checks whatever is left after the last full stop
    def release_unfinished_sentence(self) -> list[str]:
        if self.stopped_because or not self._unchecked_words:
            return []
        sentence, self._unchecked_words = self._unchecked_words, ""
        return [self._release_or_stop_the_answer(sentence)]

    def _release_or_stop_the_answer(self, sentence: str) -> str:
        reason = find_unsafe_reason(sentence) or self._find_unsupported_figure(sentence) or find_tax_liability_claim(sentence)
        if reason is None:
            return sentence
        self.stopped_because = reason
        self._unchecked_words = ""
        logger.warning("Answer stopped by guard (%s): %r", reason, sentence[:200])
        return ANSWER_STOPPED_MESSAGE
