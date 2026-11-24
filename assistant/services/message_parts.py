import re

# Words that start a new request in a message: a question word, a polite opener, or a verb the customer uses to ask
# for something. A joining word ("and", "also", "then") only splits a message when one of these follows it, so
# "my balance and my withdrawals" stays in one piece but "what is my balance and how long does it take" splits.
NEW_REQUEST_STARTERS = (
    "how|what|whats|what's|when|where|why|who|which|can|could|do|does|did|is|are|am|will|would|should|please|help|"
    "tell|show|cancel|resend|retry|change|update|send|remind|explain|i|you"
)

# The place between two requests that are joined by "and", "also" or "then" (alone or together, with an optional
# comma before): the joining words are part of the match, so they are dropped from the parts
JOINING_WORDS = re.compile(
    rf"(?:,\s*|\s+)(?:(?:and|also|then)\s+)+(?=(?:{NEW_REQUEST_STARTERS})\b)",
    re.IGNORECASE,
)

# The place between two sentences: after a ?, ! or . when more text follows
SENTENCE_BREAK = re.compile(r"(?<=[?!.])\s+(?=\S)")

# A joining word left at the front of a part, when the break came from the sentence rule ("... ?? and what are...")
LEADING_JOINING_WORD = re.compile(r"^(?:(?:and|also|then)\s+)+", re.IGNORECASE)


# Cuts a customer message into the separate requests in it, in the order they were asked. A message with one request
# comes back as one part, unchanged. Plain rules, no model call, so it costs nothing and gives the same cut every time.
def split_message_into_parts(message: str) -> list[str]:
    parts = []
    for sentence in SENTENCE_BREAK.split(message.strip()):
        parts += JOINING_WORDS.split(sentence)
    cleaned = [LEADING_JOINING_WORD.sub("", part.strip(" ,")) for part in parts]
    # An empty piece is dropped; if nothing is left (an empty message) the message itself is returned as the one part
    return [part for part in cleaned if part] or [message]
