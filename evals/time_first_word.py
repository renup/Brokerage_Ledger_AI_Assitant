import sys
import time
import uuid
import os

import httpx

BASE = "http://localhost:8001"
CORE = "http://localhost:8000"

# Time from sending the question to the first word of the reply, in seconds. Reads the server-sent events line by line
# and stops at the first "token" event (the first word the customer would see).
def seconds_to_first_word(token: str, question: str) -> float:
    started = time.perf_counter()
    body = {"session_id": str(uuid.uuid4()), "message": question}
    headers = {"Authorization": f"Bearer {token}"}
    with httpx.Client(timeout=120) as client, client.stream("POST", f"{BASE}/chat", headers=headers, json=body) as response:
        event = None
        for line in response.iter_lines():
            if line.startswith("event:"):
                event = line.split(":", 1)[1].strip()
            elif line.startswith("data:") and event == "token":
                return time.perf_counter() - started
    # No word ever arrived (an error event, for example)
    return float("nan")


if __name__ == "__main__":
    # Ask as another customer by setting ASK_AS, for example ASK_AS=raj.manwani@example.com
    email = os.environ.get("ASK_AS", "maya.patel@example.com")
    login = httpx.post(f"{CORE}/auth/login", json={"email": email, "password": "demo1234"}).json()    
    # One line per question given on the command line: seconds, then the question
    for question in sys.argv[1:]:
        print(f"{seconds_to_first_word(login['access_token'], question):6.2f}s  {question}")
