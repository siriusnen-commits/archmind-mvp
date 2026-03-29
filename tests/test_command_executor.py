from __future__ import annotations

from pathlib import Path

from archmind.command_executor import execute_command
from archmind.execution_history import load_recent_execution_events


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


def test_execute_command_single_evolution_triggers_repository_sync(monkeypatch) -> None:
    monkeypatch.setattr("archmind.command_executor._resolve_project_dir", lambda _name: Path("/tmp/demo"))

    def fake_add_api(project_dir: Path, method: str, path: str, auto_restart_backend: bool = True):  # type: ignore[no-untyped-def]
        assert project_dir == Path("/tmp/demo")
        assert method == "GET"
        assert path == "/tasks"
        assert auto_restart_backend is True
        return {"ok": True, "detail": "API added", "method": method, "path": path}

    sync_calls: list[str] = []

    def fake_sync(project_dir: Path, command_label: str):  # type: ignore[no-untyped-def]
        assert project_dir == Path("/tmp/demo")
        sync_calls.append(command_label)
        return {"status": "SYNCED", "reason": "", "last_commit_hash": "abc1234", "working_tree_state": "clean"}

    monkeypatch.setattr("archmind.telegram_bot.add_api_to_project", fake_add_api)
    monkeypatch.setattr("archmind.telegram_bot.sync_repo_after_evolution_command", fake_sync)
    out = execute_command("/add_api GET /tasks", "demo")
    assert out["ok"] is True
    assert sync_calls == ["/add_api GET /tasks"]
    assert out["repository_sync"]["status"] == "SYNCED"


def test_execute_command_add_api_patch_valid(monkeypatch) -> None:
    monkeypatch.setattr("archmind.command_executor._resolve_project_dir", lambda _name: Path("/tmp/demo"))

    def fake_add_api(project_dir: Path, method: str, path: str, auto_restart_backend: bool = True):  # type: ignore[no-untyped-def]
        assert project_dir == Path("/tmp/demo")
        assert method == "PATCH"
        assert path == "/tasks/{id}"
        assert auto_restart_backend is True
        return {"ok": True, "detail": "API patched", "method": method, "path": path}

    monkeypatch.setattr("archmind.telegram_bot.add_api_to_project", fake_add_api)
    out = execute_command("/add_api PATCH /tasks/{id}", "demo")
    assert out["ok"] is True
    assert out["message"] == "API patched"
    assert out["error"] is None


def test_execute_command_add_entity_valid(monkeypatch) -> None:
    monkeypatch.setattr("archmind.command_executor._resolve_project_dir", lambda _name: Path("/tmp/demo"))

    def fake_add_entity(project_dir: Path, entity_name: str, auto_restart_backend: bool = True):  # type: ignore[no-untyped-def]
        assert project_dir == Path("/tmp/demo")
        assert entity_name == "Task"
        assert auto_restart_backend is True
        return {"ok": True, "detail": "Entity added", "entity_name": entity_name}

    monkeypatch.setattr("archmind.telegram_bot.add_entity_to_project", fake_add_entity)
    out = execute_command("/add_entity Task", "demo")
    assert out["ok"] is True
    assert out["message"] == "Entity added"
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


def test_execute_command_success_creates_history_entry(tmp_path: Path, monkeypatch) -> None:
    project_dir = tmp_path / "demo"
    monkeypatch.setattr("archmind.command_executor._resolve_project_dir", lambda _name: project_dir)

    def fake_add_page(project_dir_arg: Path, page_path: str, auto_restart_backend: bool = True):  # type: ignore[no-untyped-def]
        assert project_dir_arg == project_dir
        assert page_path == "tasks/list"
        assert auto_restart_backend is True
        return {"ok": True, "detail": "Page added", "page_path": page_path}

    monkeypatch.setattr("archmind.telegram_bot.add_page_to_project", fake_add_page)
    out = execute_command("/add_page tasks/list", "demo", source="ui-next-run")
    assert out["ok"] is True
    events = load_recent_execution_events(project_dir, limit=5)
    assert len(events) == 1
    assert events[0]["source"] == "ui-next-run"
    assert events[0]["status"] == "ok"
    assert events[0]["command"] == "/add_page tasks/list"


def test_execute_command_failure_creates_history_entry(tmp_path: Path, monkeypatch) -> None:
    project_dir = tmp_path / "demo"
    monkeypatch.setattr("archmind.command_executor._resolve_project_dir", lambda _name: project_dir)

    def raise_error(*_args, **_kwargs):  # type: ignore[no-untyped-def]
        raise RuntimeError("boom")

    monkeypatch.setattr("archmind.telegram_bot.add_api_to_project", raise_error)
    out = execute_command("/add_api GET /tasks", "demo", source="telegram-auto", run_id="r1", step_no=2)
    assert out["ok"] is False
    events = load_recent_execution_events(project_dir, limit=5)
    assert len(events) == 1
    assert events[0]["source"] == "telegram-auto"
    assert events[0]["status"] == "fail"
    assert events[0]["command"] == "/add_api GET /tasks"
    assert events[0]["run_id"] == "r1"
    assert events[0]["step_no"] == 2


def test_execute_command_push_failure_does_not_fail_evolution(monkeypatch) -> None:
    monkeypatch.setattr("archmind.command_executor._resolve_project_dir", lambda _name: Path("/tmp/demo"))

    def fake_add_api(project_dir: Path, method: str, path: str, auto_restart_backend: bool = True):  # type: ignore[no-untyped-def]
        assert project_dir == Path("/tmp/demo")
        assert method == "GET"
        assert path == "/tasks"
        return {"ok": True, "detail": "API added", "method": method, "path": path}

    monkeypatch.setattr("archmind.telegram_bot.add_api_to_project", fake_add_api)
    monkeypatch.setattr(
        "archmind.telegram_bot.sync_repo_after_evolution_command",
        lambda *_args, **_kwargs: {
            "status": "PUSH_FAILED",
            "reason": "authentication failed",
            "last_commit_hash": "fff111",
            "working_tree_state": "clean",
        },
    )
    out = execute_command("/add_api GET /tasks", "demo")
    assert out["ok"] is True
    assert out["repository_sync"]["status"] == "PUSH_FAILED"
    assert "Repository sync: PUSH_FAILED (authentication failed)" in str(out["message_text"])
