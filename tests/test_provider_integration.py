from __future__ import annotations

from typing import Any

import pytest

from archmind.generator import call_ollama_chat
from archmind.providers.base import ProviderError
from archmind.reasoning import generate_reasoning_text


def test_generate_reasoning_text_local_mode_uses_local_provider(monkeypatch) -> None:
    calls: list[str] = []

    def fake_local(self, prompt: str, **kwargs: Any) -> str:  # type: ignore[no-untyped-def]
        calls.append(f"local:{prompt}")
        return "local-ok"

    def fake_cloud(self, prompt: str, **kwargs: Any) -> str:  # type: ignore[no-untyped-def]
        calls.append(f"cloud:{prompt}")
        return "cloud-ok"

    monkeypatch.setattr("archmind.providers.local_provider.LocalProvider.generate", fake_local)
    monkeypatch.setattr("archmind.providers.cloud_provider.CloudProvider.generate", fake_cloud)

    out = generate_reasoning_text("hello", mode="local")
    assert out == "local-ok"
    assert calls == ["local:hello"]


def test_generate_reasoning_text_cloud_mode_uses_cloud_provider(monkeypatch) -> None:
    calls: list[str] = []

    def fake_local(self, prompt: str, **kwargs: Any) -> str:  # type: ignore[no-untyped-def]
        calls.append(f"local:{prompt}")
        return "local-ok"

    def fake_cloud(self, prompt: str, **kwargs: Any) -> str:  # type: ignore[no-untyped-def]
        calls.append(f"cloud:{prompt}")
        return "cloud-ok"

    monkeypatch.setattr("archmind.providers.local_provider.LocalProvider.generate", fake_local)
    monkeypatch.setattr("archmind.providers.cloud_provider.CloudProvider.generate", fake_cloud)

    out = generate_reasoning_text("hello", mode="cloud", openai_api_key="sk-test", openai_model="gpt-4.1-mini")
    assert out == "cloud-ok"
    assert calls == ["cloud:hello"]


def test_generate_reasoning_text_auto_mode_falls_back_to_cloud(monkeypatch) -> None:
    calls: list[str] = []

    def fake_local(self, prompt: str, **kwargs: Any) -> str:  # type: ignore[no-untyped-def]
        calls.append(f"local:{prompt}")
        raise ProviderError("local down")

    def fake_cloud(self, prompt: str, **kwargs: Any) -> str:  # type: ignore[no-untyped-def]
        calls.append(f"cloud:{prompt}")
        return "cloud-ok"

    monkeypatch.setattr("archmind.providers.local_provider.LocalProvider.generate", fake_local)
    monkeypatch.setattr("archmind.providers.cloud_provider.CloudProvider.generate", fake_cloud)

    out = generate_reasoning_text("hello", mode="auto", openai_api_key="sk-test", openai_model="gpt-4.1-mini")
    assert out == "cloud-ok"
    assert calls == ["local:hello", "cloud:hello"]


def test_generate_reasoning_text_auto_mode_raises_when_both_fail(monkeypatch) -> None:
    def fake_local(self, prompt: str, **kwargs: Any) -> str:  # type: ignore[no-untyped-def]
        raise ProviderError("local down")

    def fake_cloud(self, prompt: str, **kwargs: Any) -> str:  # type: ignore[no-untyped-def]
        raise ProviderError("cloud down")

    monkeypatch.setattr("archmind.providers.local_provider.LocalProvider.generate", fake_local)
    monkeypatch.setattr("archmind.providers.cloud_provider.CloudProvider.generate", fake_cloud)

    with pytest.raises(ProviderError):
        generate_reasoning_text("hello", mode="auto", openai_api_key="sk-test", openai_model="gpt-4.1-mini")


def test_generator_uses_reasoning_facade(monkeypatch) -> None:
    captured: dict[str, Any] = {}

    def fake_generate_reasoning_text(
        prompt: str,
        **kwargs: Any,
    ) -> str:
        captured["prompt"] = prompt
        captured["kwargs"] = kwargs
        return '{"ok":true}'

    monkeypatch.setattr("archmind.generator.generate_reasoning_text", fake_generate_reasoning_text)
    out = call_ollama_chat("make spec", model="llama3:latest", base_url="http://127.0.0.1:11434", timeout_s=20)
    assert out == '{"ok":true}'
    assert captured["prompt"] == "make spec"
    assert captured["kwargs"]["mode"] == "local"


def test_spec_suggester_uses_reasoning_facade_output(monkeypatch) -> None:
    from archmind.spec_suggester import suggest_project_spec

    monkeypatch.setattr(
        "archmind.spec_suggester.try_generate_reasoning_json",
        lambda *_a, **_k: {
            "entities": [{"name": "Note", "fields": [{"name": "title", "type": "string"}]}],
            "api_endpoints": ["GET /notes"],
            "frontend_pages": ["notes/list"],
        },
    )
    out = suggest_project_spec("note app", {"domains": [], "frontend_needed": True})
    assert out["entities"][0]["name"] == "Note"
    assert "GET /notes" in out["api_endpoints"]
    assert "notes/list" in out["frontend_pages"]


def test_plan_suggester_uses_reasoning_facade_output(monkeypatch) -> None:
    from archmind.plan_suggester import build_plan_from_project_spec

    monkeypatch.setattr(
        "archmind.plan_suggester.try_generate_reasoning_json",
        lambda *_a, **_k: {"phases": [{"title": "Custom", "steps": ["/inspect"]}]},
    )
    out = build_plan_from_project_spec({"shape": "backend", "entities": [], "api_endpoints": [], "frontend_pages": []})
    assert out == {"phases": [{"title": "Custom", "steps": ["/inspect"]}]}


def test_design_suggester_uses_reasoning_facade_output(monkeypatch) -> None:
    from archmind.design_suggester import build_architecture_design

    monkeypatch.setattr(
        "archmind.design_suggester.try_generate_reasoning_json",
        lambda *_a, **_k: {
            "shape": "fullstack",
            "template": "fullstack-ddd",
            "entities": [{"name": "Note", "fields": [{"name": "title", "type": "string"}]}],
            "api_endpoints": ["GET /notes"],
            "frontend_pages": ["notes/list"],
        },
    )
    out = build_architecture_design(
        "note app",
        {"app_shape": "backend", "recommended_template": "fastapi", "modules": [], "domains": [], "reason_summary": ""},
        {"entities": [], "api_endpoints": [], "frontend_pages": []},
    )
    assert out["shape"] == "fullstack"
    assert out["template"] == "fullstack-ddd"
    assert out["api_endpoints"] == ["GET /notes"]
