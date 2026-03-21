from __future__ import annotations

from typing import Any, Optional

from archmind.config import (
    get_local_base_url,
    get_local_model,
    get_openai_api_key,
    get_openai_model,
    get_provider_mode,
)
from archmind.providers.base import ProviderError, ReasoningProvider
from archmind.providers.cloud_provider import CloudProvider
from archmind.providers.local_provider import LocalProvider


class ProviderRouter(ReasoningProvider):
    def __init__(
        self,
        *,
        mode: str,
        local_provider: Optional[ReasoningProvider] = None,
        cloud_provider: Optional[ReasoningProvider] = None,
    ) -> None:
        selected_mode = str(mode or "local").strip().lower() or "local"
        if selected_mode not in {"local", "cloud", "auto"}:
            selected_mode = "local"
        self.mode = selected_mode
        self.local_provider = local_provider
        self.cloud_provider = cloud_provider

    def generate(self, prompt: str, **kwargs: Any) -> str:
        if self.mode == "local":
            if self.local_provider is None:
                raise ProviderError("local provider is not configured")
            return self.local_provider.generate(prompt, **kwargs)
        if self.mode == "cloud":
            if self.cloud_provider is None:
                raise ProviderError("cloud provider is not configured")
            return self.cloud_provider.generate(prompt, **kwargs)

        # auto mode
        if self.local_provider is not None:
            try:
                return self.local_provider.generate(prompt, **kwargs)
            except ProviderError:
                pass
        if self.cloud_provider is None:
            raise ProviderError("auto provider fallback failed: cloud provider is not configured")
        return self.cloud_provider.generate(prompt, **kwargs)


def build_provider_router(
    mode: Optional[str] = None,
    *,
    local_base_url: Optional[str] = None,
    local_model: Optional[str] = None,
    openai_api_key: Optional[str] = None,
    openai_model: Optional[str] = None,
    timeout_s: int = 240,
) -> ProviderRouter:
    selected_mode = str(mode or get_provider_mode("local")).strip().lower() or "local"
    if selected_mode not in {"local", "cloud", "auto"}:
        selected_mode = "local"

    local_provider: Optional[ReasoningProvider] = None
    cloud_provider: Optional[ReasoningProvider] = None

    if selected_mode in {"local", "auto"}:
        local_provider = LocalProvider(
            base_url=str(local_base_url or get_local_base_url()),
            model=str(local_model or get_local_model()),
            timeout_s=timeout_s,
        )
    if selected_mode in {"cloud", "auto"}:
        key = str(openai_api_key if openai_api_key is not None else get_openai_api_key()).strip()
        model_name = str(openai_model or get_openai_model()).strip()
        if selected_mode == "cloud":
            cloud_provider = CloudProvider(api_key=key, model=model_name, timeout_s=timeout_s)
        elif key:
            cloud_provider = CloudProvider(api_key=key, model=model_name, timeout_s=timeout_s)

    return ProviderRouter(mode=selected_mode, local_provider=local_provider, cloud_provider=cloud_provider)
