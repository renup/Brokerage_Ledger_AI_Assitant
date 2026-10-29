import json


# Formats one Server-Sent Event: "event: <name>", "data: <json>", then a BLANK line to end it
def sse(event: str, data: dict) -> str:
    return f"event: {event}\ndata: {json.dumps(data)}\n\n"
