from __future__ import annotations

from typing import Any

import pytest

from archmind.providers.base import ProviderError, ReasoningProvider
from archmind.providers.cloud_provider import CloudProvider
from archmind.providers.local_provider import LocalProvider
from archmind.providers.router import ProviderRouter, build_provider_router


class _DummyResponse:
    def __init__(self, *, payload: dict[str, Any], status_code: int = 200) -> None:
        self._payload = payload
        self.status_code = status_code

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            raise RuntimeError(f"http {self.status_code}")

    def json(self) -> dict[str, Any]:
        return self._payload


def test_local_provider_success(monkeypatch) -> None:
    captured: dict[str, Any] = {}

    def fake_post(url: str, *, json: dict[str, Any], timeout: int):  # type: ignore[no-untyped-def]
        captured["url"] = url
        captured["json"] = json
        captured["timeout"] = timeout
        return _DummyResponse(payload={"message": {"content": "local-ok"}})

    monkeypatch.setattr("archmind.providers.local_provider.requests.post", fake_post)
    provider = LocalProvider(base_url="http://127.0.0.1:11434", model="llama3:latest", timeout_s=12)
    out = provider.generate("hello", system_prompt="sys", format_json=True, temperature=0.0)

    assert out == "local-ok"
    assert captured["url"].endswith("/api/chat")
    assert captured["json"]["model"] == "llama3:latest"
    assert captured["json"]["format"] == "json"
    assert captured["timeout"] == 12


def test_local_provider_failure(monkeypatch) -> None:
    def fake_post(*_a, **_k):  # type: ignore[no-untyped-def]
        raise RuntimeError("connect failed")

    monkeypatch.setattr("archmind.providers.local_provider.requests.post", fake_post)
    provider = LocalProvider(base_url="http://127.0.0.1:11434", model="llama3:latest")
    with pytest.raises(ProviderError, match="local provider request failed"):
        provider.generate("hello")


def test_cloud_provider_success(monkeypatch) -> None:
    captured: dict[str, Any] = {}

    def fake_post(url: str, *, headers: dict[str, str], json: dict[str, Any], timeout: int):  # type: ignore[no-untyped-def]
        captured["url"] = url
        captured["headers"] = headers
        captured["json"] = json
        captured["timeout"] = timeout
        return _DummyResponse(payload={"output_text": "cloud-ok"})

    monkeypatch.setattr("archmind.providers.cloud_provider.requests.post", fake_post)
    provider = CloudProvider(api_key="sk-test", model="gpt-4.1-mini", timeout_s=8)
    out = provider.generate("hello", system_prompt="sys")

    assert out == "cloud-ok"
    assert captured["url"] == "https://api.openai.com/v1/responses"
    assert captured["headers"]["Authorization"].startswith("Bearer ")
    assert captured["json"]["model"] == "gpt-4.1-mini"
    assert captured["timeout"] == 8


def test_cloud_provider_missing_api_key() -> None:
    with pytest.raises(ProviderError, match="OPENAI_API_KEY"):
        CloudProvider(api_key="", model="gpt-4.1-mini")


class _EchoProvider(ReasoningProvider):
    def __init__(self, value: str, *, fail: bool = False) -> None:
        self.value = value
        self.fail = fail

    def generate(self, prompt: str, **kwargs) -> str:  # type: ignore[no-untyped-def]
        if self.fail:
            raise ProviderError(f"{self.value} failed")
        return f"{self.value}:{prompt}"


def test_provider_router_local_mode() -> None:
    router = ProviderRouter(mode="local", local_provider=_EchoProvider("local"))
    assert router.generate("p") == "local:p"


def test_provider_router_cloud_mode() -> None:
    router = ProviderRouter(mode="cloud", cloud_provider=_EchoProvider("cloud"))
    assert router.generate("p") == "cloud:p"


def test_provider_router_auto_fallback_local_to_cloud() -> None:
    router = ProviderRouter(
        mode="auto",
        local_provider=_EchoProvider("local", fail=True),
        cloud_provider=_EchoProvider("cloud"),
    )
    assert router.generate("p") == "cloud:p"


def test_build_provider_router_mode_local_uses_local_provider(monkeypatch) -> None:
    monkeypatch.setenv("ARCHMIND_PROVIDER_MODE", "local")
    router = build_provider_router(mode=None)
    assert router.mode == "local"
    assert router.local_provider is not None

