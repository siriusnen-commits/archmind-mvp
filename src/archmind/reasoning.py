from __future__ import annotations

from typing import Optional

from archmind.providers.router import build_provider_router


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
