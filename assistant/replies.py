
# Every fixed reply the assistant sends from code, without asking the model. One place, so the wording is
# consistent and an exam can check it. Each name says WHEN the reply is sent.

# A lookup found nothing and the question was only about how things work (the help center had no answer)
REPLY_NOTHING_FOUND = "I'm sorry, I don't have that information. I can connect you with a person if you would like."

# A request we never help with, so no lookup and no model call happens: investment, tax or legal advice, a request
# for the assistant's own instructions, or anything unrelated to the brokerage. Offers a person, because the router
# can be wrong and a false decline must not be a dead end.
REPLY_CANNOT_HELP_WITH_THAT = (
    "I'm sorry, I can only help with your own brokerage accounts and how things work here. "
    "I can't give investment, tax or legal advice. If I've misunderstood, I can connect you with a person."
)

# A question about, or a change to, someone else's account, name or details
REPLY_ONLY_THEIR_OWN_ACCOUNT = (
    "I'm sorry, I can only help with your own accounts. For anything on someone else's account, "
    "that person will need to contact us themselves."
)

