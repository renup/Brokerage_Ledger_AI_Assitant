import json
import uuid

import gradio as gr
import httpx

# Where the two services live
LEDGER_CORE_URL = "http://localhost:8000"
ASSISTANT_URL = "http://localhost:8001"

# The suggested questions shown as clickable buttons. Each example is a list of three
# values: the message, plus one value for each hidden input below (token and session id).
# The hidden ones are None here because the page fills them in itself.
EXAMPLES = [
    ["Where is my withdrawal?", None, None],
    ["Why did my IRA transfer fail?", None, None],
    ["What is my cash balance?", None, None],
]


# Called when the "Log in" button is clicked. It returns TWO values, one for each
# output wired up below: (the token to remember, the message to show).
def login(email, password):
    try:
        # The same login call you made in Postman, now from code
        response = httpx.post(
            f"{LEDGER_CORE_URL}/auth/login",
            json={"email": email, "password": password},
            timeout=10,
        )
    except httpx.RequestError:
        # ledger-core isn't running or isn't reachable
        return None, "Could not reach ledger-core. Is it running on port 8000?"
    if response.status_code != 200:
        return None, "Wrong email or password"
    return response.json()["access_token"], f"Logged in as {email}"


# Called each time the customer sends a message. It's a generator (it uses "yield"):
# every yield replaces the bot's text on screen, which is how the words appear one by one.
# Gradio passes: the message, the earlier messages (history), then our two hidden inputs.
def chat(message, history, token, session_id):
    # Nobody has logged in yet
    if not token:
        yield "Please log in first, using the form above"
        return

    text = ""  # the reply as built so far
    sources = []  # filled in by "sources" events (Phase 6)

    try:
        # httpx.stream keeps the connection open and lets us read the SSE messages as they
        # arrive, instead of waiting for the end. timeout=None: never give up mid-stream.
        with httpx.stream(
            "POST",
            f"{ASSISTANT_URL}/chat",
            headers={"Authorization": f"Bearer {token}"},
            json={"session_id": session_id, "message": message},
            timeout=None,
        ) as response:
            if response.status_code == 401:
                yield "Your login has expired. Please log in again"
                return
            if response.status_code != 200:
                # The f before the quote is what puts the real number into {...}
                yield f"Something went wrong (error {response.status_code})"
                return

            # An SSE message arrives as two lines: "event: token" then "data: {...}".
            # We remember the event name from the first line, and use it on the second.
            event = None
            for line in response.iter_lines():
                if line.startswith("event:"):
                    # [len("event:"):] cuts off the label, .strip() removes the space
                    event = line[len("event:"):].strip()
                elif line.startswith("data:"):
                    # The data is JSON text; json.loads turns it into a Python dict
                    data = json.loads(line[len("data:"):])
                    # Everything below sits INSIDE this branch: it only makes sense
                    # once we have both the event name and its data.
                    if event == "token":
                        # Add the new word and show everything so far
                        text += data["text"]
                        yield text
                    elif event == "sources":
                        sources = data
                    elif event == "error":
                        yield text + f"\n\n (Error: {data['message']})"
                        return
    except httpx.RequestError:
        yield "Could not reach the assistant. Is it running on port 8001?"
        return

    # Nothing sends "sources" yet, so this does nothing for now. It will in Phase 6.
    # It shows the sources as a bullet list of links under the answer.
    if sources:
        links = "\n".join(f"- [{s['title']}]({s['url']})" for s in sources)
        yield f"{text}\n\n**Sources**\n{links}"


# gr.Blocks is the page. Everything inside the "with" goes on it, top to bottom.
with gr.Blocks(title="Ask Ledger") as demo:
    # Markdown needs a space after the # to make a heading
    gr.Markdown("# Ask Ledger")

    # gr.State holds a value for ONE browser tab, invisibly. Each tab gets its own copy,
    # so two people using the page can't mix up their logins.
    token = gr.State(None)
    # A function (lambda) so every tab gets a NEW random session id when it opens.
    # Without it, all tabs would share one id and one conversation.
    session_id = gr.State(lambda: str(uuid.uuid4()))

    # The login form. The boxes are pre-filled with Maya's demo login to save typing.
    with gr.Row():
        email = gr.Textbox(label="Email", value="maya.patel@example.com")
        password = gr.Textbox(label="Password", type="password", value="demo1234")
        login_button = gr.Button("Log in")
    status = gr.Markdown("Not logged in")
    # When the button is clicked: send email and password to login(), and put its two
    # results into the token State and the status text.
    login_button.click(login, inputs=[email, password], outputs=[token, status])

    # The chat box. fn is called for each message. additional_inputs hands our hidden
    # token and session id to chat(), after the message and history.
    gr.ChatInterface(
        fn=chat,
        additional_inputs=[token, session_id],
        examples=EXAMPLES,
    )

# Start the web server at http://localhost:7860, reachable only from this computer
demo.launch(server_port=7860)
