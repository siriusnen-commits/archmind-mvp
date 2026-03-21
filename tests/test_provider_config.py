from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass, field
from pathlib import Path

import archmind.telegram_bot as telegram_bot
from archmind.reasoning import generate_reasoning_text, resolve_provider_mode
from archmind.state import load_state, set_provider_mode, write_state
from archmind.telegram_bot import command_inspect, command_provider, set_current_project


@dataclass
class DummyMessage:
    text: str = ""
    sent: list[str] = field(default_factory=list)

    async def reply_text(self, text: str, **kwargs):  # type: ignore[no-untyped-def]
        del kwargs
        self.sent.append(str(text))


@dataclass
class DummyChat:
    id: int = 1


@dataclass
class DummyUpdate:
    message: DummyMessage
    effective_chat: DummyChat = field(default_factory=DummyChat)


@dataclass
class DummyContext:
    args: list[str] = field(default_factory=list)


def test_resolve_provider_mode_uses_env_fallback(monkeypatch) -> None:
    monkeypatch.delenv("ARCHMIND_PROVIDER_MODE", raising=False)
    assert resolve_provider_mode() == "local"
    monkeypatch.setenv("ARCHMIND_PROVIDER_MODE", "cloud")
    assert resolve_provider_mode() == "cloud"


def test_provider_command_updates_state_and_reads_current_mode(tmp_path: Path) -> None:
    project_dir = tmp_path / "provider_project"
    project_dir.mkdir(parents=True, exist_ok=True)
    set_current_project(project_dir)

    msg_set = DummyMessage()
    asyncio.run(command_provider(DummyUpdate(message=msg_set), DummyContext(args=["cloud"])))
    assert msg_set.sent
    assert msg_set.sent[-1] == "Provider updated to: cloud"

    state_payload = load_state(project_dir) or {}
    provider = state_payload.get("provider") if isinstance(state_payload.get("provider"), dict) else {}
    assert provider.get("mode") == "cloud"

    msg_get = DummyMessage()
    asyncio.run(command_provider(DummyUpdate(message=msg_get), DummyContext(args=[])))
    assert msg_get.sent
    assert msg_get.sent[-1] == "Current provider: cloud"


def test_generate_reasoning_text_uses_state_provider_mode(monkeypatch, tmp_path: Path) -> None:
    project_dir = tmp_path / "provider_mode_state_project"
    project_dir.mkdir(parents=True, exist_ok=True)
    payload = {"provider": {"mode": "auto"}}
    set_provider_mode(payload, "auto")
    write_state(project_dir, payload)

    captured: dict[str, str] = {}

    class DummyRouter:
        def generate(self, prompt: str, **kwargs):  # type: ignore[no-untyped-def]
            del prompt, kwargs
            return "ok"

    def fake_build_provider_router(*, mode=None, **kwargs):  # type: ignore[no-untyped-def]
        del kwargs
        captured["mode"] = str(mode)
        return DummyRouter()

    monkeypatch.setattr("archmind.reasoning.build_provider_router", fake_build_provider_router)
    out = generate_reasoning_text("hello", project_dir=project_dir)
    assert out == "ok"
    assert captured.get("mode") == "auto"


def test_provider_command_invalid_mode_returns_error(tmp_path: Path) -> None:
    project_dir = tmp_path / "provider_invalid_project"
    project_dir.mkdir(parents=True, exist_ok=True)
    set_current_project(project_dir)
    msg = DummyMessage()
    asyncio.run(command_provider(DummyUpdate(message=msg), DummyContext(args=["invalid"])))
    assert msg.sent
    assert msg.sent[-1] == "Invalid provider mode. Use: /provider local|cloud|auto"


def test_inspect_includes_provider_mode(tmp_path: Path, monkeypatch) -> None:
    project_dir = tmp_path / "inspect_provider_project"
    archmind_dir = project_dir / ".archmind"
    archmind_dir.mkdir(parents=True, exist_ok=True)
    (archmind_dir / "project_spec.json").write_text(
        json.dumps(
            {
                "shape": "backend",
                "template": "fastapi",
                "domains": [],
                "modules": [],
                "entities": [],
                "api_endpoints": [],
                "frontend_pages": [],
                "evolution": {"version": 1, "history": []},
            }
        ),
        encoding="utf-8",
    )
    write_state(project_dir, {"provider": {"mode": "auto"}})
    set_current_project(project_dir)

    monkeypatch.setattr(
        telegram_bot,
        "_resolve_target_project",
        lambda: project_dir,
    )
    msg = DummyMessage()
    asyncio.run(command_inspect(DummyUpdate(message=msg), DummyContext()))
    assert msg.sent
    out = msg.sent[-1]
    assert "Provider:" in out
    assert "- Mode: auto" in out
