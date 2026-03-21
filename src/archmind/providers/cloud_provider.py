from __future__ import annotations

from typing import Any

import requests

from archmind.providers.base import ProviderError, ReasoningProvider


class CloudProvider(ReasoningProvider):
    def __init__(self, *, api_key: str, model: str, timeout_s: int = 120) -> None:
        self.api_key = str(api_key or "").strip()
        self.model = str(model or "gpt-4.1-mini").strip() or "gpt-4.1-mini"
        self.timeout_s = int(timeout_s)
        if not self.api_key:
            raise ProviderError("cloud provider requires OPENAI_API_KEY")

    def generate(self, prompt: str, **kwargs: Any) -> str:
        if not str(prompt or "").strip():
            raise ProviderError("cloud provider prompt is empty")

        timeout_s = int(kwargs.get("timeout_s") or self.timeout_s)
        temperature = float(kwargs.get("temperature", 0.2))
        system_prompt = str(kwargs.get("system_prompt") or "You are ArchMind cloud reasoning provider.").strip()

        payload = {
            "model": self.model,
            "input": [
                {"role": "system", "content": [{"type": "input_text", "text": system_prompt}]},
                {"role": "user", "content": [{"type": "input_text", "text": str(prompt)}]},
            ],
            "temperature": temperature,
        }

        try:
            response = requests.post(
                "https://api.openai.com/v1/responses",
                headers={
                    "Authorization": f"Bearer {self.api_key}",
                    "Content-Type": "application/json",
                },
                json=payload,
                timeout=timeout_s,
            )
            response.raise_for_status()
            body = response.json()
        except Exception as exc:
            raise ProviderError(f"cloud provider request failed: {exc}") from exc

        text = self._extract_text(body)
        if not text:
            raise ProviderError("cloud provider returned empty text")
        return text

    @staticmethod
    def _extract_text(body: Any) -> str:
        if not isinstance(body, dict):
            return ""
        output_text = str(body.get("output_text") or "").strip()
        if output_text:
            return output_text

        output = body.get("output")
        if isinstance(output, list):
            for item in output:
                if not isinstance(item, dict):
                    continue
                content = item.get("content")
                if not isinstance(content, list):
                    continue
                for block in content:
                    if not isinstance(block, dict):
                        continue
                    text = str(block.get("text") or "").strip()
                    if text:
                        return text
        return ""
