from __future__ import annotations

from pathlib import Path

from archmind.command_executor import execute_command


def test_execute_command_add_field_valid(monkeypatch) -> None:
    monkeypatch.setattr("archmind.command_executor._resolve_project_dir", lambda _name: Path("/tmp/demo"))

    def fake_add_field(project_dir: Path, entity: str, field: str, field_type: str, auto_restart_backend: bool = True):  # type: ignore[no-untyped-def]
        assert project_dir == Path("/tmp/demo")
        assert entity == "Task"
        assert field == "priority"
        assert field_type == "string"
        assert auto_restart_backend is True
        return {"ok": True, "detail": "Field added", "entity_name": entity, "field_name": field, "field_type": field_type}

    monkeypatch.setattr("archmind.telegram_bot.add_field_to_project", fake_add_field)
    out = execute_command("/add_field Task priority:string", "demo")
    assert out["ok"] is True
    assert out["command"] == "/add_field Task priority:string"
    assert out["project_name"] == "demo"
    assert out["message"] == "Field added"
    assert out["error"] is None


def test_execute_command_add_api_valid(monkeypatch) -> None:
    monkeypatch.setattr("archmind.command_executor._resolve_project_dir", lambda _name: Path("/tmp/demo"))

    def fake_add_api(project_dir: Path, method: str, path: str, auto_restart_backend: bool = True):  # type: ignore[no-untyped-def]
        assert project_dir == Path("/tmp/demo")
        assert method == "GET"
        assert path == "/tasks"
        assert auto_restart_backend is True
        return {"ok": True, "detail": "API added", "method": method, "path": path}

    monkeypatch.setattr("archmind.telegram_bot.add_api_to_project", fake_add_api)
    out = execute_command("/add_api GET /tasks", "demo")
    assert out["ok"] is True
    assert out["message"] == "API added"
    assert out["error"] is None


def test_execute_command_add_page_valid(monkeypatch) -> None:
    monkeypatch.setattr("archmind.command_executor._resolve_project_dir", lambda _name: Path("/tmp/demo"))

    def fake_add_page(project_dir: Path, page_path: str, auto_restart_backend: bool = True):  # type: ignore[no-untyped-def]
        assert project_dir == Path("/tmp/demo")
        assert page_path == "tasks/list"
        assert auto_restart_backend is True
        return {"ok": True, "detail": "Page added", "page_path": page_path}

    monkeypatch.setattr("archmind.telegram_bot.add_page_to_project", fake_add_page)
    out = execute_command("/add_page tasks/list", "demo")
    assert out["ok"] is True
    assert out["message"] == "Page added"
    assert out["error"] is None


def test_execute_command_implement_page_valid(monkeypatch) -> None:
    monkeypatch.setattr("archmind.command_executor._resolve_project_dir", lambda _name: Path("/tmp/demo"))

    def fake_implement_page(project_dir: Path, page_path: str, auto_restart_backend: bool = True):  # type: ignore[no-untyped-def]
        assert project_dir == Path("/tmp/demo")
        assert page_path == "tasks/list"
        assert auto_restart_backend is True
        return {"ok": True, "detail": "Implemented page: tasks/list", "page_path": page_path}

    monkeypatch.setattr("archmind.telegram_bot.implement_page_in_project", fake_implement_page)
    out = execute_command("/implement_page tasks/list", "demo")
    assert out["ok"] is True
    assert out["message"] == "Implemented page: tasks/list"
    assert out["error"] is None


def test_execute_command_invalid_command(monkeypatch) -> None:
    monkeypatch.setattr("archmind.command_executor._resolve_project_dir", lambda _name: Path("/tmp/demo"))
    out = execute_command("/unknown foo", "demo")
    assert out["ok"] is False
    assert "Unsupported command" in str(out["error"])


def test_execute_command_malformed_command(monkeypatch) -> None:
    monkeypatch.setattr("archmind.command_executor._resolve_project_dir", lambda _name: Path("/tmp/demo"))
    out = execute_command("/add_field Task priority", "demo")
    assert out["ok"] is False
    assert "Unsupported command" in str(out["error"])


def test_execute_command_missing_arguments(monkeypatch) -> None:
    monkeypatch.setattr("archmind.command_executor._resolve_project_dir", lambda _name: Path("/tmp/demo"))
    out = execute_command("/add_page ", "demo")
    assert out["ok"] is False
    assert "Unsupported command" in str(out["error"])


def test_execute_command_generator_failure(monkeypatch) -> None:
    monkeypatch.setattr("archmind.command_executor._resolve_project_dir", lambda _name: Path("/tmp/demo"))

    def raise_error(*_args, **_kwargs):  # type: ignore[no-untyped-def]
        raise RuntimeError("boom")

    monkeypatch.setattr("archmind.telegram_bot.add_api_to_project", raise_error)
    out = execute_command("/add_api GET /tasks", "demo")
    assert out["ok"] is False
    assert out["error"] == "boom"
