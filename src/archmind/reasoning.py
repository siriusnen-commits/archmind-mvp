from __future__ import annotations

import json
import os
from typing import Optional

from archmind.providers.base import ProviderError
from archmind.providers.router import build_provider_router


def provider_mode_is_explicitly_configured() -> bool:
    return bool(str(os.getenv("ARCHMIND_PROVIDER_MODE", "") or "").strip())


def should_use_provider(*, use_provider: Optional[bool] = None) -> bool:
    if use_provider is not None:
        return bool(use_provider)
    return provider_mode_is_explicitly_configured()


def generate_reasoning_text(
    prompt: str,
    *,
    mode: Optional[str] = None,
    local_model: Optional[str] = None,
    local_base_url: Optional[str] = None,
    openai_api_key: Optional[str] = None,
    openai_model: Optional[str] = None,
    timeout_s: int = 240,
    system_prompt: str = "You are ArchMind reasoning engine.",
    format_json: bool = False,
    temperature: float = 0.2,
) -> str:
    router = build_provider_router(
        mode=mode,
        local_base_url=local_base_url,
        local_model=local_model,
        openai_api_key=openai_api_key,
        openai_model=openai_model,
        timeout_s=timeout_s,
    )
    return router.generate(
        prompt,
        timeout_s=timeout_s,
        system_prompt=system_prompt,
        format_json=format_json,
        temperature=temperature,
    )


def try_generate_reasoning_json(
    prompt: str,
    *,
    use_provider: Optional[bool] = None,
    mode: Optional[str] = None,
    timeout_s: int = 120,
    system_prompt: str = "Return only valid JSON.",
    temperature: float = 0.1,
) -> Optional[dict]:
    if not should_use_provider(use_provider=use_provider):
        return None
    try:
        text = generate_reasoning_text(
            prompt,
            mode=mode,
            timeout_s=timeout_s,
            system_prompt=system_prompt,
            format_json=True,
            temperature=temperature,
        )
    except ProviderError:
        return None
    except Exception:
        return None
    try:
        payload = json.loads(text)
    except Exception:
        return None
    return payload if isinstance(payload, dict) else None
