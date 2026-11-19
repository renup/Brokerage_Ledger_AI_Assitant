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

# A number as written in text: 25,000 or 1200.50 or 7. The $ and % signs are looked at separately.
EVERY_NUMBER = re.compile(r"\d{1,3}(?:,\d{3})+(?:\.\d+)?|\d+(?:\.\d+)?")
# A code such as QUIET-FEE-0 or HO-4471: capital-letter pieces joined by hyphens. No IGNORECASE on purpose,
# so ordinary hyphenated words are not mistaken for codes.
CODE = re.compile(r"\b[A-Z][A-Z0-9]*(?:-[A-Z0-9]+)+\b")

# A length of time as written in an answer: "3 business days", "5 to 7 business days", "1-2 weeks", "24 hours".
# The lookbehind keeps the tail of a bigger number ("1,000 days") from being read as a duration. Words such as
# "business" or "working" between the number and the unit are allowed and then ignored.
DURATION = re.compile(
    r"(?<![\d,.$])(\d+)(?:\s*(?:to|-|–|or)\s*(\d+))?\s+(?:business\s+|working\s+|calendar\s+)?(minute|hour|day|week|month|year)s?\b",
    re.IGNORECASE,
)


# One way to write a number, so $25,000 and 25000 and 25,000.00 compare as equal
def normalise_number(written: str) -> str:
    return format(Decimal(written.replace(",", "")).normalize(), "f")


# One way to write a length of time, so "3 business days" and "3 days" compare as equal
def written_duration(first: int, last: int, unit: str) -> str:
    return f"{first}-{last} {unit}" if last != first else f"{first} {unit}"


# The lengths of time stated in a text, in that one written form
def durations_in(text: str) -> list[str]:
    return [written_duration(int(m.group(1)), int(m.group(2) or m.group(1)), m.group(3).lower()) for m in DURATION.finditer(text)]


# The lengths of time a trusted text backs: every one it states, and each end of a range ("5 to 7 business days"
# also backs "7 days"), so a fair paraphrase is not stopped
def durations_backed_by(text: str) -> set[str]:
    backed = set(durations_in(text))
    for m in DURATION.finditer(text):
        for end in (m.group(1), m.group(2)):
            if end:
                backed.add(written_duration(int(end), int(end), m.group(3).lower()))
    return backed


# Only some numbers are checked in an answer: money, percentages, numbers with a thousands comma and numbers of four
# or more digits. Other small plain numbers are NOT checked: they are everywhere in real answers. Lengths of time such as
# "3 business days" are checked separately, see DURATION.
def is_checked_number(sentence: str, number: re.Match) -> bool:
    written = number.group()
    before = sentence[: number.start()].rstrip()
    after = sentence[number.end():]
    return before.endswith("$") or after.startswith("%") or "," in written or len(written.split(".")[0]) >= 4


# The figures and codes in an answer sentence that must be backed by a trusted source. Lengths of time are included
# unless the answer rests on ledger data (the model may then work one out, such as "1 business day left").
def checked_figures_in(sentence: str, with_durations: bool = True) -> list[str]:
    numbers = [normalise_number(m.group()) for m in EVERY_NUMBER.finditer(sentence) if is_checked_number(sentence, m)]
    return numbers + CODE.findall(sentence) + (durations_in(sentence) if with_durations else [])


# Every number, code and length of time in a trusted text, small numbers too: a trusted source may back any figure it contains
def every_figure_in(text: str) -> set[str]:
    return {normalise_number(m.group()) for m in EVERY_NUMBER.finditer(text)} | set(CODE.findall(text)) | durations_backed_by(text)


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
        self._check_durations = True

    # Adds the figures in this text to what the answer may mention. Used for the customer's own words and for ledger
    # tool results; never for help passages.
    def trust_figures_in(self, text: str) -> None:
        self._trusted_figures |= every_figure_in(text)

    # Called when a ledger lookup backs this answer. The model may then work out a length of time ("1 business day
    # left" from "day 2 of 3") that no text states, so lengths of time are no longer checked for this answer.
    def stop_checking_durations_for_this_answer(self) -> None:
        self._check_durations = False

    # The first figure or code in the sentence that no trusted source backs, as a reason; None when all are backed
    def _find_unsupported_figure(self, sentence: str) -> str | None:
        for figure in checked_figures_in(sentence, self._check_durations):
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
        reason = find_unsafe_reason(sentence) or self._find_unsupported_figure(sentence)
        if reason is None:
            return sentence
        self.stopped_because = reason
        self._unchecked_words = ""
        logger.warning("Answer stopped by guard (%s): %r", reason, sentence[:200])
        return ANSWER_STOPPED_MESSAGE
