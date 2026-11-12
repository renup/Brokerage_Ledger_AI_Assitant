import sys
import httpx

from assistant.clients.model_warmup import ollama_native_url
from assistant.config import settings
from assistant.services.chat_service import system_prompt
from assistant.tools import ALL_TOOLS
from assistant.tools.base import ToolGroup
from assistant.tools.registry import ToolRegistry

QUESTION = "How long does a withdrawal usually take?"

def ask_ollama(first_name: str) -> dict:
    menu = ToolRegistry(ALL_TOOLS).restricted_to({ToolGroup.HELP_CENTER}).definitions()
    body = {
        "model": settings.llm_model,
        "messages": [
            {"role": "system", "content": system_prompt().replace("{first_name}", first_name)},
            {"role": "user", "content": QUESTION},
        ],
        "tools": menu,
        "stream": False,
        "options": {"num_predict": 1},
    }
    return httpx.post(f"{ollama_native_url()}/api/chat", json=body, timeout=120).json()

def report(label: str, result: dict) -> None:
    tokens = result.get("prompt_eval_count", 0)
    prompt_seconds = result.get("prompt_eval_duration", 0) / 1e9
    total_seconds = result["total_duration"] / 1e9
    print(f"{label:<10} prompt tokens processed: {tokens:>5}   prompt time: {prompt_seconds:5.2f}s   whole request: {total_seconds:5.2f}s")

if __name__ == "__main__":
    for first_name in sys.argv[1:]:
        report(first_name, ask_ollama(first_name))
