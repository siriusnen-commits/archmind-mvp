from __future__ import annotations

import os

_PROVIDER_MODES = {"local", "cloud", "auto"}


def _read_env(name: str, default: str = "") -> str:
    return str(os.getenv(name, default) or "").strip()


def get_provider_mode(default: str = "local") -> str:
    mode = _read_env("ARCHMIND_PROVIDER_MODE", default).lower()
    if mode not in _PROVIDER_MODES:
        return str(default or "local").strip().lower() or "local"
    return mode


def get_local_base_url(default: str = "http://127.0.0.1:11434") -> str:
    return _read_env("ARCHMIND_LOCAL_BASE_URL", default) or default


def get_local_model(default: str = "llama3:latest") -> str:
    return _read_env("ARCHMIND_LOCAL_MODEL", default) or default


def get_openai_api_key(default: str = "") -> str:
    return _read_env("OPENAI_API_KEY", default)


def get_openai_model(default: str = "gpt-4.1-mini") -> str:
    return _read_env("OPENAI_MODEL", default) or default
