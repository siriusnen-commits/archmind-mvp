from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Optional

from archmind.config import get_provider_mode
from archmind.providers.base import ProviderError
from archmind.providers.router import build_provider_router
from archmind.state import load_state, read_provider_mode

_PROVIDER_MODES = {"local", "cloud", "auto"}


def _normalized_provider_mode(value: str, default: str = "local") -> str:
    mode = str(value or "").strip().lower()
    if mode in _PROVIDER_MODES:
        return mode
    fallback = str(default or "local").strip().lower()
    return fallback if fallback in _PROVIDER_MODES else "local"


def _provider_mode_from_state(project_dir: Optional[Path]) -> str:
    if project_dir is None:
        return ""
    state = load_state(project_dir.expanduser().resolve())
    if not isinstance(state, dict):
        return ""
    return read_provider_mode(state)


def resolve_provider_mode(*, mode: Optional[str] = None, project_dir: Optional[Path] = None) -> str:
    if mode is not None:
        return _normalized_provider_mode(mode, "local")
    state_mode = _provider_mode_from_state(project_dir)
    if state_mode:
        return state_mode
    env_mode = str(os.getenv("ARCHMIND_PROVIDER_MODE", "") or "").strip().lower()
    if env_mode in _PROVIDER_MODES:
        return env_mode
    return _normalized_provider_mode(get_provider_mode("local"), "local")


def provider_mode_is_explicitly_configured(*, project_dir: Optional[Path] = None) -> bool:
    if _provider_mode_from_state(project_dir):
        return True
    return bool(str(os.getenv("ARCHMIND_PROVIDER_MODE", "") or "").strip())


def should_use_provider(
    *,
    use_provider: Optional[bool] = None,
    mode: Optional[str] = None,
    project_dir: Optional[Path] = None,
) -> bool:
    if use_provider is not None:
        return bool(use_provider)
    if mode is not None:
        return True
    return provider_mode_is_explicitly_configured(project_dir=project_dir)


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
    project_dir: Optional[Path] = None,
) -> str:
    selected_mode = resolve_provider_mode(mode=mode, project_dir=project_dir)
    router = build_provider_router(
        mode=selected_mode,
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
    project_dir: Optional[Path] = None,
) -> Optional[dict]:
    if not should_use_provider(use_provider=use_provider, mode=mode, project_dir=project_dir):
        return None
    try:
        text = generate_reasoning_text(
            prompt,
            mode=mode,
            timeout_s=timeout_s,
            system_prompt=system_prompt,
            format_json=True,
            temperature=temperature,
            project_dir=project_dir,
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
