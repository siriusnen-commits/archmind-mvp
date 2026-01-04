from __future__ import annotations
from pathlib import Path
import os
import json
import requests
from typing import Optional, Dict, Any

PROMPT_PATH = Path("docs/architecture_prompt.md")
INPUT_PATH = Path("examples/sample_input.txt")
OUTPUT_PATH = Path("examples/sample_output.md")

# ---- Config ----
DEFAULT_MODEL = os.getenv("ARCHMIND_MODEL", "llama3")
# OpenAI-compatible base url (text-generation-webui/openwebui/lm-studio/etc.)
OPENAI_BASE_URL = os.getenv("ARCHMIND_OPENAI_BASE_URL", "http://localhost:8000")
OPENAI_API_KEY = os.getenv("ARCHMIND_OPENAI_API_KEY", "sk-local")  # often ignored by local servers
# Ollama base url
OLLAMA_BASE_URL = os.getenv("ARCHMIND_OLLAMA_BASE_URL", "http://localhost:11434")

TIMEOUT = 120


def build_user_message(prompt: str, idea: str) -> str:
    return f"{prompt}\n\n---\n\nPRODUCT IDEA:\n{idea}\n"


def call_openai_compat(model: str, user_message: str) -> Optional[str]:
    url = f"{OPENAI_BASE_URL.rstrip('/')}/v1/chat/completions"
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {OPENAI_API_KEY}",
    }
    payload = {
        "model": model,
        "messages": [
            {"role": "system", "content": "You are a senior software architect."},
            {"role": "user", "content": user_message},
        ],
        "temperature": 0.2,
    }

    try:
        r = requests.post(url, headers=headers, json=payload, timeout=TIMEOUT)
        if r.status_code >= 400:
            return None
        data = r.json()
        return data["choices"][0]["message"]["content"]
    except Exception:
        return None


def call_ollama(model: str, user_message: str) -> Optional[str]:
    url = f"{OLLAMA_BASE_URL.rstrip('/')}/api/generate"
    payload = {
        "model": model,
        "prompt": user_message,
        "stream": False,
        "options": {"temperature": 0.2},
    }
    try:
        r = requests.post(url, json=payload, timeout=TIMEOUT)
        if r.status_code >= 400:
            return None
        data = r.json()
        return data.get("response")
    except Exception:
        return None


def main():
    prompt = PROMPT_PATH.read_text(encoding="utf-8")
    idea = INPUT_PATH.read_text(encoding="utf-8")
    user_message = build_user_message(prompt, idea)

    # 1) Try OpenAI-compatible first (usually best structured output)
    out = call_openai_compat(DEFAULT_MODEL, user_message)

    # 2) Fallback to Ollama
    if not out:
        out = call_ollama(DEFAULT_MODEL, user_message)

    if not out:
        raise RuntimeError(
            "Failed to call local LLM.\n"
            f"- Tried OpenAI-compatible: {OPENAI_BASE_URL}/v1/chat/completions\n"
            f"- Tried Ollama: {OLLAMA_BASE_URL}/api/generate\n"
            "Check which endpoint is running, base URLs, model name, and server logs."
        )

    OUTPUT_PATH.write_text(out.strip() + "\n", encoding="utf-8")
    print(f"[OK] Wrote architecture to: {OUTPUT_PATH}")


if __name__ == "__main__":
    main()