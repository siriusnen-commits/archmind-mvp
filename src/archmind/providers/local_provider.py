from __future__ import annotations

from typing import Any

import requests

from archmind.providers.base import ProviderError, ReasoningProvider


class LocalProvider(ReasoningProvider):
    def __init__(self, *, base_url: str, model: str, timeout_s: int = 240) -> None:
        self.base_url = str(base_url or "http://127.0.0.1:11434").rstrip("/")
        self.model = str(model or "llama3:latest").strip() or "llama3:latest"
        self.timeout_s = int(timeout_s)

    def generate(self, prompt: str, **kwargs: Any) -> str:
        if not str(prompt or "").strip():
            raise ProviderError("local provider prompt is empty")
        timeout_s = int(kwargs.get("timeout_s") or self.timeout_s)
        temperature = float(kwargs.get("temperature", 0.2))
        system_prompt = str(kwargs.get("system_prompt") or "You are ArchMind local reasoning provider.").strip()
        format_json = bool(kwargs.get("format_json", False))

        payload = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": str(prompt)},
            ],
            "stream": False,
            "options": {"temperature": temperature},
        }
        if format_json:
            payload["format"] = "json"

        url = f"{self.base_url}/api/chat"
        try:
            response = requests.post(url, json=payload, timeout=timeout_s)
            response.raise_for_status()
            body = response.json()
        except Exception as exc:
            raise ProviderError(f"local provider request failed: {exc}") from exc

        text = self._extract_text(body)
        if not text:
            raise ProviderError("local provider returned empty text")
        return text

    @staticmethod
    def _extract_text(body: Any) -> str:
        if not isinstance(body, dict):
            return ""
        message = body.get("message")
        if isinstance(message, dict):
            text = str(message.get("content") or "").strip()
            if text:
                return text
        text = str(body.get("response") or body.get("text") or "").strip()
        return text
