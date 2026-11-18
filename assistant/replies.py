
# Every fixed reply the assistant sends from code, without asking the model. One place, so the wording is
# consistent and an exam can check it. Each name says WHEN the reply is sent.

# A lookup found nothing and the question was only about how things work (the help center had no answer)
REPLY_NOTHING_FOUND = "I'm sorry, I don't have that information. I can connect you with a person if you would like."

# A request we never help with, so no lookup and no model call happens: investment, tax or legal advice,
# another person's account or details, or anything unrelated to the brokerage
REPLY_CANNOT_HELP_WITH_THAT = (
    "I'm sorry, I can only help with your own brokerage accounts and how things work here. "
    "I can't give investment, tax or legal advice, or help with other people's accounts."
)

