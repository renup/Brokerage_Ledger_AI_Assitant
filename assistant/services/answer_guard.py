import logging
import re

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
        self.stopped_because: str | None = None

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
        reason = find_unsafe_reason(sentence)
        if reason is None:
            return sentence
        self.stopped_because = reason
        self._unchecked_words = ""
        logger.warning("Answer stopped by guard (%s): %r", reason, sentence[:200])
        return ANSWER_STOPPED_MESSAGE
