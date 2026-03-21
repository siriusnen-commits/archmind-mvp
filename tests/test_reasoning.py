from __future__ import annotations

from archmind.reasoning import generate_reasoning_text


def test_generate_reasoning_text_uses_provider_router(monkeypatch) -> None:
    captured: dict[str, object] = {}

    class DummyRouter:
        def generate(self, prompt: str, **kwargs):  # type: ignore[no-untyped-def]
            captured["prompt"] = prompt
            captured["kwargs"] = kwargs
            return "ok"

    monkeypatch.setattr("archmind.reasoning.build_provider_router", lambda **_kwargs: DummyRouter())
    out = generate_reasoning_text("hello", mode="local", format_json=True, temperature=0.0)

    assert out == "ok"
    assert captured["prompt"] == "hello"
    kwargs = captured["kwargs"]
    assert isinstance(kwargs, dict)
    assert kwargs.get("format_json") is True

