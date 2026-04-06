from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from archmind.command_executor import _execute_auto_command, execute_command
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


def test_execute_command_add_field_verification_marks_partial_when_runtime_reflection_missing(tmp_path: Path, monkeypatch) -> None:
    project_dir = tmp_path / "demo"
    (project_dir / ".archmind").mkdir(parents=True, exist_ok=True)
    (project_dir / "frontend" / "app" / "tasks" / "new").mkdir(parents=True, exist_ok=True)
    (project_dir / "frontend" / "app" / "tasks" / "new" / "page.tsx").write_text(
        '"use client";\nexport default function Page(){return <div>title only</div>;}\n',
        encoding="utf-8",
    )
    (project_dir / "app").mkdir(parents=True, exist_ok=True)
    (project_dir / "app" / "main.py").write_text("from fastapi import FastAPI\napp=FastAPI()\n", encoding="utf-8")
    spec_path = project_dir / ".archmind" / "project_spec.json"
    spec_path.write_text(
        json.dumps({"entities": [{"name": "Task", "fields": [{"name": "title", "type": "string"}]}]}, ensure_ascii=False),
        encoding="utf-8",
    )
    monkeypatch.setattr("archmind.command_executor._resolve_project_dir", lambda _name: project_dir)

    def fake_add_field(project_dir_arg: Path, entity: str, field: str, field_type: str, auto_restart_backend: bool = True):  # type: ignore[no-untyped-def]
        payload = {"entities": [{"name": entity, "fields": [{"name": "title", "type": "string"}, {"name": field, "type": field_type}]}]}
        spec_path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
        return {
            "ok": True,
            "detail": "Field added",
            "entity_name": entity,
            "field_name": field,
            "field_type": field_type,
            "runtime_recovery": {"attempted": False, "failed": False, "reason": "disabled"},
        }

    monkeypatch.setattr("archmind.telegram_bot.add_field_to_project", fake_add_field)
    out = execute_command("/add_field Task priority:string", "demo")
    verification = out.get("verification") if isinstance(out.get("verification"), dict) else {}
    assert str(verification.get("overall_status") or "") in {"PARTIAL", "FAILED"}
    assert str(verification.get("overall_status") or "") != "VERIFIED"


def test_execute_command_add_field_verification_is_verified_only_when_frontend_reflects_field(tmp_path: Path, monkeypatch) -> None:
    project_dir = tmp_path / "demo"
    (project_dir / ".archmind").mkdir(parents=True, exist_ok=True)
    (project_dir / "frontend" / "app" / "tasks" / "new").mkdir(parents=True, exist_ok=True)
    (project_dir / "frontend" / "app" / "_lib").mkdir(parents=True, exist_ok=True)
    (project_dir / "frontend" / "app" / "tasks" / "new" / "page.tsx").write_text(
        '"use client";\nexport default function Page(){return <div><label>priority</label><input name="priority" /></div>;}\n',
        encoding="utf-8",
    )
    (project_dir / "frontend" / "app" / "_lib" / "navigation.ts").write_text(
        'export const navigationItems = [{ href: "/", label: "Home" }, { href: "/tasks", label: "List" }, { href: "/tasks/new", label: "Create" }];\n',
        encoding="utf-8",
    )
    (project_dir / "frontend" / "app" / "_lib" / "AppNav.tsx").write_text(
        'export default function AppNav(){return null;}\n',
        encoding="utf-8",
    )
    (project_dir / "app").mkdir(parents=True, exist_ok=True)
    (project_dir / "app" / "main.py").write_text("from fastapi import FastAPI\napp=FastAPI()\n", encoding="utf-8")
    spec_path = project_dir / ".archmind" / "project_spec.json"
    spec_path.write_text(
        json.dumps({"entities": [{"name": "Task", "fields": [{"name": "title", "type": "string"}]}]}, ensure_ascii=False),
        encoding="utf-8",
    )
    monkeypatch.setattr("archmind.command_executor._resolve_project_dir", lambda _name: project_dir)

    def fake_add_field(project_dir_arg: Path, entity: str, field: str, field_type: str, auto_restart_backend: bool = True):  # type: ignore[no-untyped-def]
        payload = {"entities": [{"name": entity, "fields": [{"name": "title", "type": "string"}, {"name": field, "type": field_type}]}]}
        spec_path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
        return {
            "ok": True,
            "detail": "Field added",
            "entity_name": entity,
            "field_name": field,
            "field_type": field_type,
            "generated_files": ["frontend/app/tasks/new/page.tsx"],
            "runtime_recovery": {"attempted": True, "failed": False, "reason": ""},
        }

    monkeypatch.setattr("archmind.telegram_bot.add_field_to_project", fake_add_field)
    out = execute_command("/add_field Task priority:string", "demo")
    verification = out.get("verification") if isinstance(out.get("verification"), dict) else {}
    assert str(verification.get("overall_status") or "") == "VERIFIED"


def test_execute_command_auto_keeps_partial_status_when_verification_is_not_verified(monkeypatch) -> None:
    monkeypatch.setattr("archmind.command_executor._resolve_project_dir", lambda _name: Path("/tmp/demo"))

    def fake_auto_executor(project_dir: Path, *, project_name: str, source: str, run_id=None, auto_strategy=None):  # type: ignore[no-untyped-def]
        return {
            "ok": True,
            "project_name": project_name,
            "detail": "Auto completed",
            "message_text": "Auto evolution run",
            "auto_result": {"run_id": "auto-verify-1", "executed": 1, "commands": ["/add_field Task priority:string"]},
            "verification": {
                "overall_status": "PARTIAL",
                "issues": ["runtime reflection missing"],
                "runtime_reflection": "missing_restart",
                "drift_summary": "runtime reflection missing",
            },
        }

    monkeypatch.setattr("archmind.command_executor._execute_auto_via_plan_flow", fake_auto_executor)
    out = execute_command("/auto", "demo", source="ui-next-run")
    assert out["ok"] is True
    assert out["auto_result"]["verification"]["overall_status"] == "PARTIAL"


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
            "status": "COMMIT_ONLY",
            "reason": "github authentication not configured (fatal: could not read Username for 'https://github.com': Device not configured)",
            "hint": "configure git credentials or token for GitHub push from this environment",
            "last_commit_hash": "fff111",
            "working_tree_state": "clean",
        },
    )
    out = execute_command("/add_api GET /tasks", "demo")
    assert out["ok"] is True
    assert out["repository_sync"]["status"] == "COMMIT_ONLY"
    assert "Repository sync: COMMIT_ONLY (github authentication not configured" in str(out["message_text"])
    assert "Hint: configure git credentials or token for GitHub push from this environment" in str(out["message_text"])


def test_execute_command_auto_uses_flow_executor_and_skips_single_command_sync(monkeypatch) -> None:
    monkeypatch.setattr("archmind.command_executor._resolve_project_dir", lambda _name: Path("/tmp/demo"))
    sync_calls: list[str] = []

    def fake_auto_executor(project_dir: Path, *, project_name: str, source: str, run_id=None, auto_strategy=None):  # type: ignore[no-untyped-def]
        assert project_dir == Path("/tmp/demo")
        assert project_name == "demo"
        assert source == "ui-next-run"
        assert auto_strategy == "balanced"
        return {
            "ok": True,
            "project_name": project_name,
            "detail": "Auto completed",
            "message_text": "Auto evolution run",
            "repository_sync": {"status": "SYNCED"},
            "auto_result": {"run_id": "auto-1", "strategy": "balanced", "executed": 1, "commands": ["/add_api GET /boards/{id}/cards"]},
        }

    monkeypatch.setattr("archmind.command_executor._execute_auto_via_plan_flow", fake_auto_executor)
    monkeypatch.setattr("archmind.telegram_bot.sync_repo_after_evolution_command", lambda *_args, **_kwargs: sync_calls.append("called") or {"status": "SYNCED"})

    out = execute_command("/auto", "demo", source="ui-next-run")
    assert out["ok"] is True
    assert out["command"] == "/auto"
    assert out["auto_result"]["run_id"] == "auto-1"
    assert out["repository_sync"]["status"] == "SYNCED"
    assert sync_calls == []


def test_execute_command_auto_forwards_explicit_strategy(monkeypatch) -> None:
    monkeypatch.setattr("archmind.command_executor._resolve_project_dir", lambda _name: Path("/tmp/demo"))

    captured: dict[str, str] = {}

    def fake_auto_executor(project_dir: Path, *, project_name: str, source: str, run_id=None, auto_strategy=None):  # type: ignore[no-untyped-def]
        assert project_dir == Path("/tmp/demo")
        captured["strategy"] = str(auto_strategy or "")
        return {
            "ok": True,
            "project_name": project_name,
            "detail": "Auto completed",
            "message_text": "Auto evolution run",
            "repository_sync": {"status": "SYNCED"},
            "auto_result": {"run_id": "auto-2", "strategy": str(auto_strategy or "balanced"), "executed": 0, "commands": []},
        }

    monkeypatch.setattr("archmind.command_executor._execute_auto_via_plan_flow", fake_auto_executor)
    out = execute_command("/auto", "demo", source="ui-next-run", auto_strategy="safe")
    assert out["ok"] is True
    assert captured["strategy"] == "safe"
    assert out["auto_result"]["strategy"] == "safe"


def test_auto_triggers_plan_flow_execution_via_run_project_flow(monkeypatch, tmp_path: Path) -> None:
    project_dir = tmp_path / "demo"
    project_dir.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr("archmind.command_executor._resolve_project_dir", lambda _name: project_dir)

    class _Detail:
        plan = {
            "flows": [
                {
                    "name": "Flow A",
                    "steps": [{"id": "s1", "command": "/add_api GET /tasks"}],
                }
            ]
        }

    called: dict[str, Any] = {}

    monkeypatch.setattr("archmind.project_query.build_project_detail", lambda _project_dir: _Detail())

    def _fake_run_project_flow(project_dir_arg: Path, flow_name: str, *, sync: bool | None = None):  # type: ignore[no-untyped-def]
        called["project_dir"] = project_dir_arg
        called["flow_name"] = flow_name
        called["sync"] = sync
        return {
            "ok": True,
            "started": True,
            "detail": "Flow execution completed",
            "flow_execution": {
                "flow_name": flow_name,
                "status": "completed",
                "steps": [{"id": "s1", "status": "done", "command": "/add_api GET /tasks"}],
            },
        }

    monkeypatch.setattr("archmind.project_query.run_project_flow", _fake_run_project_flow)
    monkeypatch.setattr("archmind.state.load_state", lambda *_args, **_kwargs: {})
    monkeypatch.setattr("archmind.state.write_state", lambda *_args, **_kwargs: None)

    out = execute_command("/auto", "demo", source="ui-next-run")
    assert out["ok"] is True
    assert called["project_dir"] == project_dir
    assert called["flow_name"] == "Flow A"
    assert called["sync"] is True


def test_auto_selects_first_flow_when_multiple_flows_exist(monkeypatch, tmp_path: Path) -> None:
    project_dir = tmp_path / "demo"
    project_dir.mkdir(parents=True, exist_ok=True)

    class _Detail:
        plan = {
            "flows": [
                {"name": "First Flow", "steps": [{"id": "s1", "command": "/add_api GET /a"}]},
                {"name": "Second Flow", "steps": [{"id": "s2", "command": "/add_api GET /b"}]},
            ]
        }

    selected: dict[str, str] = {}
    monkeypatch.setattr("archmind.project_query.build_project_detail", lambda _project_dir: _Detail())
    monkeypatch.setattr("archmind.state.load_state", lambda *_args, **_kwargs: {})
    monkeypatch.setattr("archmind.state.write_state", lambda *_args, **_kwargs: None)

    def _fake_run_project_flow(_project_dir: Path, flow_name: str, *, sync: bool | None = None):  # type: ignore[no-untyped-def]
        selected["flow_name"] = flow_name
        return {"ok": True, "started": True, "detail": "done", "flow_execution": {"flow_name": flow_name, "status": "completed", "steps": []}}

    monkeypatch.setattr("archmind.project_query.run_project_flow", _fake_run_project_flow)
    monkeypatch.setattr("archmind.command_executor._resolve_project_dir", lambda _name: project_dir)
    out_exec = execute_command("/auto", "demo", source="ui-next-run")
    assert out_exec["ok"] is True
    assert selected["flow_name"] == "First Flow"


def test_auto_generates_plan_context_via_project_detail_when_missing(monkeypatch, tmp_path: Path) -> None:
    project_dir = tmp_path / "demo"
    project_dir.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr("archmind.command_executor._resolve_project_dir", lambda _name: project_dir)
    monkeypatch.setattr("archmind.state.load_state", lambda *_args, **_kwargs: {})
    monkeypatch.setattr("archmind.state.write_state", lambda *_args, **_kwargs: None)

    calls = {"detail": 0}

    class _Detail:
        plan = {"flows": [{"name": "Generated Flow", "steps": [{"id": "s1", "command": "/add_api GET /tasks"}]}]}

    def _fake_build_project_detail(_project_dir: Path):  # type: ignore[no-untyped-def]
        calls["detail"] += 1
        return _Detail()

    monkeypatch.setattr("archmind.project_query.build_project_detail", _fake_build_project_detail)
    monkeypatch.setattr(
        "archmind.project_query.run_project_flow",
        lambda _project_dir, flow_name, *, sync=None: {  # type: ignore[no-untyped-def]
            "ok": True,
            "started": True,
            "detail": "done",
            "flow_execution": {"flow_name": flow_name, "status": "completed", "steps": [{"id": "s1", "status": "done"}]},
        },
    )

    out = execute_command("/auto", "demo", source="ui-next-run")
    assert out["ok"] is True
    assert calls["detail"] >= 1
    assert out["auto_result"]["selected_flow"] == "Generated Flow"


def test_auto_reuses_flow_execution_state_and_stops_on_failure(monkeypatch, tmp_path: Path) -> None:
    project_dir = tmp_path / "demo"
    project_dir.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr("archmind.command_executor._resolve_project_dir", lambda _name: project_dir)
    monkeypatch.setattr("archmind.state.load_state", lambda *_args, **_kwargs: {})
    monkeypatch.setattr("archmind.state.write_state", lambda *_args, **_kwargs: None)

    class _Detail:
        plan = {
            "flows": [
                {
                    "name": "Failing Flow",
                    "steps": [
                        {"id": "s1", "command": "/add_api GET /tasks"},
                        {"id": "s2", "command": "/add_page tasks/list"},
                    ],
                }
            ]
        }

    monkeypatch.setattr("archmind.project_query.build_project_detail", lambda _project_dir: _Detail())
    monkeypatch.setattr(
        "archmind.project_query.run_project_flow",
        lambda _project_dir, flow_name, *, sync=None: {  # type: ignore[no-untyped-def]
            "ok": True,
            "started": True,
            "detail": "Flow execution completed",
            "flow_execution": {
                "flow_name": flow_name,
                "status": "failed",
                "current_step": "s2",
                "steps": [
                    {"id": "s1", "status": "done", "command": "/add_api GET /tasks"},
                    {"id": "s2", "status": "failed", "command": "/add_page tasks/list"},
                ],
            },
        },
    )

    out = execute_command("/auto", "demo", source="ui-next-run")
    assert out["ok"] is True
    assert out["auto_result"]["selected_flow"] == "Failing Flow"
    assert out["auto_result"]["stop_reason"] == "flow failed"
    assert out["auto_result"]["verification"]["overall_status"] == "FAILED"
    assert "s2" in str(out["auto_result"]["stop_explanation"])


def test_auto_strategy_safe_stops_before_medium_priority_action(monkeypatch, tmp_path: Path) -> None:
    project_dir = tmp_path / "demo"
    project_dir.mkdir(parents=True, exist_ok=True)

    analyses = [
        {
            "entities": ["Task"],
            "apis": [],
            "pages": [],
            "fields_by_entity": {"Task": [{"name": "title"}]},
            "placeholder_pages": [],
            "next_action": {"kind": "useful_field", "message": "Add description", "command": "/add_field Task description:string"},
            "next_action_explanation": {"reason_summary": "description improves usability", "expected_effect": "better task context"},
            "entity_crud_status": {"Task": {"missing_api": [], "missing_pages": []}},
        }
    ]
    call_idx = {"value": 0}

    monkeypatch.setattr("archmind.telegram_bot._build_project_analysis", lambda *_args, **_kwargs: analyses[min(call_idx["value"], len(analyses) - 1)])
    monkeypatch.setattr("archmind.telegram_bot._compute_auto_iteration_budget", lambda *_args, **_kwargs: (3, ["base=3"]))
    monkeypatch.setattr("archmind.telegram_bot.classify_auto_action_priority", lambda *_args, **_kwargs: "medium")
    monkeypatch.setattr("archmind.telegram_bot._normalize_recommended_command", lambda command: command)
    monkeypatch.setattr("archmind.telegram_bot._parse_command_string", lambda command: ("/add_field", ["Task", "description:string"]))
    monkeypatch.setattr("archmind.telegram_bot._analysis_progress_signature", lambda analysis: ("sig",))
    monkeypatch.setattr("archmind.telegram_bot._auto_progress_snapshot", lambda *_args, **_kwargs: {"entities": 1, "apis": 0, "pages": 0, "relation_pages": 0, "relation_apis": 0, "placeholders": 0})
    monkeypatch.setattr("archmind.telegram_bot._auto_is_good_enough_mvp", lambda *_args, **_kwargs: False)
    monkeypatch.setattr("archmind.telegram_bot._auto_stop_explanation", lambda reason, _analysis: f"base:{reason}")
    monkeypatch.setattr("archmind.telegram_bot._auto_command_already_satisfied", lambda *_args, **_kwargs: False)
    monkeypatch.setattr("archmind.telegram_bot._auto_is_multi_entity", lambda *_args, **_kwargs: False)
    monkeypatch.setattr("archmind.telegram_bot._auto_analysis_brief", lambda *_args, **_kwargs: "entities=1, apis=0, pages=0")
    monkeypatch.setattr("archmind.telegram_bot._auto_runtime_state_lines", lambda *_args, **_kwargs: [])
    monkeypatch.setattr("archmind.telegram_bot.auto_progress_delta", lambda *_args, **_kwargs: {"score": 0, "material": False})
    monkeypatch.setattr("archmind.telegram_bot.sync_repo_after_auto_batch", lambda *_args, **_kwargs: {"status": "NOT_ATTEMPTED"})
    monkeypatch.setattr("archmind.state.load_state", lambda *_args, **_kwargs: {})
    monkeypatch.setattr("archmind.state.write_state", lambda *_args, **_kwargs: None)
    monkeypatch.setattr("archmind.command_executor.execute_command", lambda *_args, **_kwargs: {"ok": False, "error": "should not execute"})

    out = _execute_auto_command(project_dir, project_name="demo", source="ui-next-run", auto_strategy="safe")
    assert out["ok"] is True
    assert out["auto_result"]["strategy"] == "safe"
    assert out["auto_result"]["executed"] == 0
    assert "strategy guard" in str(out["auto_result"]["stop_reason"]).lower()
    assert "safe strategy allows only high-priority actions" in str(out["auto_result"]["stop_explanation"]).lower()


def test_auto_strategy_aggressive_can_execute_medium_priority_action(monkeypatch, tmp_path: Path) -> None:
    project_dir = tmp_path / "demo"
    project_dir.mkdir(parents=True, exist_ok=True)

    analysis_before = {
        "entities": ["Task"],
        "apis": [],
        "pages": [],
        "fields_by_entity": {"Task": [{"name": "title"}]},
        "placeholder_pages": [],
        "next_action": {"kind": "useful_field", "message": "Add description", "command": "/add_field Task description:string"},
        "next_action_explanation": {"reason_summary": "description improves usability", "expected_effect": "better task context"},
        "entity_crud_status": {"Task": {"missing_api": [], "missing_pages": []}},
    }
    analysis_after = {
        "entities": ["Task"],
        "apis": [],
        "pages": [],
        "fields_by_entity": {"Task": [{"name": "title"}, {"name": "description"}]},
        "placeholder_pages": [],
        "next_action": {"kind": "none", "message": "No immediate suggestions.", "command": ""},
        "next_action_explanation": {},
        "entity_crud_status": {"Task": {"missing_api": [], "missing_pages": []}},
    }
    calls = {"count": 0}

    def fake_build_analysis(*_args, **_kwargs):  # type: ignore[no-untyped-def]
        calls["count"] += 1
        return analysis_before if calls["count"] <= 1 else analysis_after

    monkeypatch.setattr("archmind.telegram_bot._build_project_analysis", fake_build_analysis)
    monkeypatch.setattr("archmind.telegram_bot._compute_auto_iteration_budget", lambda *_args, **_kwargs: (3, ["base=3"]))
    monkeypatch.setattr("archmind.telegram_bot.classify_auto_action_priority", lambda row: "none" if str((row or {}).get("kind") or "").strip().lower() == "none" else "medium")
    monkeypatch.setattr("archmind.telegram_bot._normalize_recommended_command", lambda command: command)
    monkeypatch.setattr("archmind.telegram_bot._parse_command_string", lambda command: ("/add_field", ["Task", "description:string"]) if command else ("", []))
    monkeypatch.setattr("archmind.telegram_bot._analysis_progress_signature", lambda analysis: ("with-description",) if len((analysis.get("fields_by_entity") or {}).get("Task", [])) > 1 else ("base",))
    monkeypatch.setattr(
        "archmind.telegram_bot._auto_progress_snapshot",
        lambda analysis: {
            "entities": 1,
            "apis": 0,
            "pages": 0,
            "relation_pages": 0,
            "relation_apis": 0,
            "placeholders": 0,
            "useful_fields": len((analysis.get("fields_by_entity") or {}).get("Task", [])),
        },
    )
    monkeypatch.setattr("archmind.telegram_bot._auto_is_good_enough_mvp", lambda analysis: str((analysis.get("next_action") or {}).get("kind") or "").strip().lower() == "none")
    monkeypatch.setattr("archmind.telegram_bot._auto_stop_explanation", lambda reason, _analysis: f"base:{reason}")
    monkeypatch.setattr("archmind.telegram_bot._auto_command_already_satisfied", lambda *_args, **_kwargs: False)
    monkeypatch.setattr("archmind.telegram_bot._auto_is_multi_entity", lambda *_args, **_kwargs: True)
    monkeypatch.setattr("archmind.telegram_bot._auto_analysis_brief", lambda *_args, **_kwargs: "entities=1, apis=0, pages=0")
    monkeypatch.setattr("archmind.telegram_bot._auto_runtime_state_lines", lambda *_args, **_kwargs: [])
    monkeypatch.setattr("archmind.telegram_bot.auto_progress_delta", lambda *_args, **_kwargs: {"score": 3, "material": True})
    monkeypatch.setattr("archmind.telegram_bot.sync_repo_after_auto_batch", lambda *_args, **_kwargs: {"status": "SYNCED"})
    monkeypatch.setattr("archmind.state.load_state", lambda *_args, **_kwargs: {})
    monkeypatch.setattr("archmind.state.write_state", lambda *_args, **_kwargs: None)

    executed: list[str] = []

    def fake_execute(command: str, *_args, **_kwargs):  # type: ignore[no-untyped-def]
        executed.append(command)
        return {"ok": True, "detail": "ok"}

    monkeypatch.setattr("archmind.command_executor.execute_command", fake_execute)

    out = _execute_auto_command(project_dir, project_name="demo", source="ui-next-run", auto_strategy="aggressive")
    assert out["ok"] is True
    assert out["auto_result"]["strategy"] == "aggressive"
    assert out["auto_result"]["executed"] >= 1
    assert executed[0] == "/add_field Task description:string"


def test_auto_plan_relation_flow_orders_api_before_page_and_stops_when_goal_satisfied(monkeypatch, tmp_path: Path) -> None:
    project_dir = tmp_path / "demo-relation-plan"
    project_dir.mkdir(parents=True, exist_ok=True)

    analyses = [
        {
            "next_action": {
                "kind": "relation_page_behavior",
                "message": "Add cards by board page",
                "command": "/add_page cards/by_board",
            },
            "next_action_explanation": {
                "reason_summary": "Board->Card relation flow is incomplete",
                "expected_effect": "relation flow usable",
            },
            "suggestions": [
                {
                    "kind": "relation_scoped_api",
                    "message": "Add scoped relation API",
                    "command": "/add_api GET /boards/{id}/cards",
                }
            ],
            "entities": ["Board", "Card"],
            "fields_by_entity": {"Card": [{"name": "board_id"}]},
            "apis": [{"method": "GET", "path": "/boards"}, {"method": "GET", "path": "/cards"}],
            "pages": ["boards/list", "cards/list"],
            "placeholder_pages": [],
            "entity_crud_status": {"Board": {"missing_api": [], "missing_pages": []}, "Card": {"missing_api": [], "missing_pages": []}},
            "drift_warnings": ["Relation-scoped API GET /boards/{id}/cards is missing."],
        },
        {
            "next_action": {"kind": "none", "message": "No immediate suggestions.", "command": ""},
            "next_action_explanation": {},
            "suggestions": [],
            "entities": ["Board", "Card"],
            "fields_by_entity": {"Card": [{"name": "board_id"}]},
            "apis": [{"method": "GET", "path": "/boards"}, {"method": "GET", "path": "/cards"}, {"method": "GET", "path": "/boards/{id}/cards"}],
            "pages": ["boards/list", "cards/list", "cards/by_board"],
            "placeholder_pages": [],
            "entity_crud_status": {"Board": {"missing_api": [], "missing_pages": []}, "Card": {"missing_api": [], "missing_pages": []}},
            "drift_warnings": [],
        },
    ]
    call_idx = {"value": 0}

    def _fake_build_analysis(*_args, **_kwargs):  # type: ignore[no-untyped-def]
        idx = min(call_idx["value"], len(analyses) - 1)
        call_idx["value"] += 1
        return analyses[idx]

    monkeypatch.setattr("archmind.telegram_bot._build_project_analysis", _fake_build_analysis)
    monkeypatch.setattr("archmind.telegram_bot._compute_auto_iteration_budget", lambda *_args, **_kwargs: (3, ["base=3"]))
    monkeypatch.setattr("archmind.telegram_bot._auto_runtime_state_lines", lambda *_args, **_kwargs: [])
    monkeypatch.setattr("archmind.telegram_bot._auto_analysis_brief", lambda *_args, **_kwargs: "entities=2, apis=3, pages=3")
    monkeypatch.setattr("archmind.telegram_bot.sync_repo_after_auto_batch", lambda *_args, **_kwargs: {"status": "SYNCED"})
    monkeypatch.setattr("archmind.state.load_state", lambda *_args, **_kwargs: {})
    monkeypatch.setattr("archmind.state.write_state", lambda *_args, **_kwargs: None)

    executed: list[str] = []
    monkeypatch.setattr(
        "archmind.command_executor.execute_command",
        lambda command, *_args, **_kwargs: (executed.append(command) or {"ok": True, "detail": "ok"}),
    )

    out = _execute_auto_command(project_dir, project_name="demo", source="ui-next-run")
    assert out["ok"] is True
    assert executed == ["/add_api GET /boards/{id}/cards"]
    assert out["auto_result"]["plan_goal"] == "complete_relation_flow"
    assert out["auto_result"]["planned_steps"][0]["command"] == "/add_api GET /boards/{id}/cards"
    assert out["auto_result"]["goal_satisfied"] is True
    assert out["auto_result"]["stop_reason"] == "plan goal satisfied"


def test_auto_plan_complete_crud_gap_executes_expected_steps(monkeypatch, tmp_path: Path) -> None:
    project_dir = tmp_path / "demo-crud-plan"
    project_dir.mkdir(parents=True, exist_ok=True)

    analyses = [
        {
            "next_action": {"kind": "missing_page", "message": "Add tasks list page", "command": "/add_page tasks/list"},
            "next_action_explanation": {"reason_summary": "CRUD starter incomplete"},
            "suggestions": [
                {"kind": "missing_crud_api", "message": "Add tasks list API", "command": "/add_api GET /tasks"}
            ],
            "entities": ["Task"],
            "fields_by_entity": {"Task": [{"name": "title"}]},
            "apis": [],
            "pages": [],
            "placeholder_pages": [],
            "entity_crud_status": {"Task": {"missing_api": ["GET list"], "missing_pages": ["tasks/list"]}},
        },
        {
            "next_action": {"kind": "missing_page", "message": "Add tasks list page", "command": "/add_page tasks/list"},
            "next_action_explanation": {"reason_summary": "CRUD starter incomplete"},
            "suggestions": [],
            "entities": ["Task"],
            "fields_by_entity": {"Task": [{"name": "title"}]},
            "apis": [{"method": "GET", "path": "/tasks"}],
            "pages": [],
            "placeholder_pages": [],
            "entity_crud_status": {"Task": {"missing_api": [], "missing_pages": ["tasks/list"]}},
        },
        {
            "next_action": {"kind": "none", "message": "No immediate suggestions.", "command": ""},
            "next_action_explanation": {},
            "suggestions": [],
            "entities": ["Task"],
            "fields_by_entity": {"Task": [{"name": "title"}]},
            "apis": [{"method": "GET", "path": "/tasks"}],
            "pages": ["tasks/list"],
            "placeholder_pages": [],
            "entity_crud_status": {"Task": {"missing_api": [], "missing_pages": []}},
        },
    ]
    call_idx = {"value": 0}

    def _fake_build_analysis(*_args, **_kwargs):  # type: ignore[no-untyped-def]
        idx = min(call_idx["value"], len(analyses) - 1)
        call_idx["value"] += 1
        return analyses[idx]

    monkeypatch.setattr("archmind.telegram_bot._build_project_analysis", _fake_build_analysis)
    monkeypatch.setattr("archmind.telegram_bot._compute_auto_iteration_budget", lambda *_args, **_kwargs: (3, ["base=3"]))
    monkeypatch.setattr("archmind.telegram_bot._auto_runtime_state_lines", lambda *_args, **_kwargs: [])
    monkeypatch.setattr("archmind.telegram_bot._auto_analysis_brief", lambda *_args, **_kwargs: "entities=1, apis=1, pages=1")
    monkeypatch.setattr("archmind.telegram_bot.sync_repo_after_auto_batch", lambda *_args, **_kwargs: {"status": "SYNCED"})
    monkeypatch.setattr("archmind.state.load_state", lambda *_args, **_kwargs: {})
    monkeypatch.setattr("archmind.state.write_state", lambda *_args, **_kwargs: None)

    executed: list[str] = []
    monkeypatch.setattr(
        "archmind.command_executor.execute_command",
        lambda command, *_args, **_kwargs: (executed.append(command) or {"ok": True, "detail": "ok"}),
    )

    out = _execute_auto_command(project_dir, project_name="demo", source="ui-next-run")
    assert out["ok"] is True
    assert executed == ["/add_api GET /tasks", "/add_page tasks/list"]
    assert out["auto_result"]["plan_goal"] == "complete_crud_gap"
    assert out["auto_result"]["goal_satisfied"] is True
    assert out["auto_result"]["executed_steps"][0]["command"] == "/add_api GET /tasks"


def test_auto_plan_placeholder_goal_uses_implement_page(monkeypatch, tmp_path: Path) -> None:
    project_dir = tmp_path / "demo-placeholder-plan"
    project_dir.mkdir(parents=True, exist_ok=True)
    analyses = [
        {
            "next_action": {
                "kind": "placeholder_page",
                "message": "Implement placeholder page",
                "command": "/implement_page tasks/detail",
            },
            "next_action_explanation": {"reason_summary": "Page is still placeholder"},
            "suggestions": [],
            "entities": ["Task"],
            "fields_by_entity": {"Task": [{"name": "title"}]},
            "apis": [{"method": "GET", "path": "/tasks/{id}"}],
            "pages": ["tasks/detail"],
            "placeholder_pages": ["tasks/detail"],
            "entity_crud_status": {"Task": {"missing_api": [], "missing_pages": []}},
        },
        {
            "next_action": {"kind": "none", "message": "No immediate suggestions.", "command": ""},
            "next_action_explanation": {},
            "suggestions": [],
            "entities": ["Task"],
            "fields_by_entity": {"Task": [{"name": "title"}]},
            "apis": [{"method": "GET", "path": "/tasks/{id}"}],
            "pages": ["tasks/detail"],
            "placeholder_pages": [],
            "entity_crud_status": {"Task": {"missing_api": [], "missing_pages": []}},
        },
    ]
    call_idx = {"value": 0}
    monkeypatch.setattr(
        "archmind.telegram_bot._build_project_analysis",
        lambda *_args, **_kwargs: analyses[min(call_idx.__setitem__("value", call_idx["value"] + 1) or call_idx["value"] - 1, len(analyses) - 1)],
    )
    monkeypatch.setattr("archmind.telegram_bot._compute_auto_iteration_budget", lambda *_args, **_kwargs: (2, ["base=2"]))
    monkeypatch.setattr("archmind.telegram_bot._auto_runtime_state_lines", lambda *_args, **_kwargs: [])
    monkeypatch.setattr("archmind.telegram_bot._auto_analysis_brief", lambda *_args, **_kwargs: "entities=1, apis=1, pages=1")
    monkeypatch.setattr("archmind.telegram_bot.sync_repo_after_auto_batch", lambda *_args, **_kwargs: {"status": "SYNCED"})
    monkeypatch.setattr("archmind.state.load_state", lambda *_args, **_kwargs: {})
    monkeypatch.setattr("archmind.state.write_state", lambda *_args, **_kwargs: None)
    executed: list[str] = []
    monkeypatch.setattr(
        "archmind.command_executor.execute_command",
        lambda command, *_args, **_kwargs: (executed.append(command) or {"ok": True, "detail": "ok"}),
    )

    out = _execute_auto_command(project_dir, project_name="demo", source="ui-next-run")
    assert out["ok"] is True
    assert executed == ["/implement_page tasks/detail"]
    assert out["auto_result"]["plan_goal"] == "resolve_placeholder_or_incomplete_page"


def test_auto_plan_ignores_unsupported_add_entity_and_executes_supported_candidate(monkeypatch, tmp_path: Path) -> None:
    project_dir = tmp_path / "demo-unsupported-next-action"
    project_dir.mkdir(parents=True, exist_ok=True)
    analyses = [
        {
            "next_action": {"kind": "missing_entity", "message": "Add Task entity", "command": "/add_entity Task"},
            "next_action_explanation": {"reason_summary": "No entities found yet"},
            "suggestions": [
                {"kind": "missing_field", "message": "Add title field", "command": "/add_field Task title:string"},
                {"kind": "missing_entity", "message": "Add Task entity", "command": "/add_entity Task"},
            ],
            "entities": ["Task"],
            "fields_by_entity": {"Task": []},
            "apis": [],
            "pages": [],
            "placeholder_pages": [],
            "entity_crud_status": {"Task": {"missing_api": ["GET list"], "missing_pages": ["tasks/list"]}},
        },
        {
            "next_action": {"kind": "none", "message": "No immediate suggestions.", "command": ""},
            "next_action_explanation": {},
            "suggestions": [],
            "entities": ["Task"],
            "fields_by_entity": {"Task": [{"name": "title"}]},
            "apis": [],
            "pages": [],
            "placeholder_pages": [],
            "entity_crud_status": {"Task": {"missing_api": ["GET list"], "missing_pages": ["tasks/list"]}},
        },
    ]
    call_idx = {"value": 0}

    def _fake_build_analysis(*_args, **_kwargs):  # type: ignore[no-untyped-def]
        idx = min(call_idx["value"], len(analyses) - 1)
        call_idx["value"] += 1
        return analyses[idx]

    monkeypatch.setattr("archmind.telegram_bot._build_project_analysis", _fake_build_analysis)
    monkeypatch.setattr("archmind.telegram_bot._compute_auto_iteration_budget", lambda *_args, **_kwargs: (2, ["base=2"]))
    monkeypatch.setattr("archmind.telegram_bot._auto_runtime_state_lines", lambda *_args, **_kwargs: [])
    monkeypatch.setattr("archmind.telegram_bot._auto_analysis_brief", lambda *_args, **_kwargs: "entities=1, apis=0, pages=0")
    monkeypatch.setattr("archmind.telegram_bot.sync_repo_after_auto_batch", lambda *_args, **_kwargs: {"status": "SYNCED"})
    monkeypatch.setattr("archmind.state.load_state", lambda *_args, **_kwargs: {})
    monkeypatch.setattr("archmind.state.write_state", lambda *_args, **_kwargs: None)

    executed: list[str] = []
    monkeypatch.setattr(
        "archmind.command_executor.execute_command",
        lambda command, *_args, **_kwargs: (executed.append(command) or {"ok": True, "detail": "ok"}),
    )

    out = _execute_auto_command(project_dir, project_name="demo", source="ui-next-run")
    assert out["ok"] is True
    assert executed == ["/add_field Task title:string"]
    assert "/add_entity Task" not in out["auto_result"]["commands"]
    assert "unsupported command" not in str(out["auto_result"]["stop_reason"]).lower()


def test_auto_reports_no_supported_bootstrap_path_when_only_add_entity_is_available(monkeypatch, tmp_path: Path) -> None:
    project_dir = tmp_path / "demo-no-supported-bootstrap"
    project_dir.mkdir(parents=True, exist_ok=True)
    analyses = [
        {
            "next_action": {"kind": "missing_entity", "message": "Add Task entity", "command": "/add_entity Task"},
            "next_action_explanation": {"reason_summary": "No entities found yet"},
            "suggestions": [{"kind": "missing_entity", "message": "Add Task entity", "command": "/add_entity Task"}],
            "entities": [],
            "fields_by_entity": {},
            "apis": [],
            "pages": [],
            "placeholder_pages": [],
            "entity_crud_status": {},
        }
    ]
    monkeypatch.setattr("archmind.telegram_bot._build_project_analysis", lambda *_args, **_kwargs: analyses[0])
    monkeypatch.setattr("archmind.telegram_bot._compute_auto_iteration_budget", lambda *_args, **_kwargs: (1, ["base=1"]))
    monkeypatch.setattr("archmind.telegram_bot._auto_runtime_state_lines", lambda *_args, **_kwargs: [])
    monkeypatch.setattr("archmind.telegram_bot._auto_analysis_brief", lambda *_args, **_kwargs: "entities=0, apis=0, pages=0")
    monkeypatch.setattr("archmind.telegram_bot.sync_repo_after_auto_batch", lambda *_args, **_kwargs: {"status": "NOT_ATTEMPTED"})
    monkeypatch.setattr("archmind.state.load_state", lambda *_args, **_kwargs: {})
    monkeypatch.setattr("archmind.state.write_state", lambda *_args, **_kwargs: None)

    out = _execute_auto_command(project_dir, project_name="demo", source="ui-next-run")
    assert out["ok"] is True
    assert out["auto_result"]["executed"] == 0
    assert out["auto_result"]["commands"] == []
    assert "project not materialized / no supported bootstrap path" in str(out["auto_result"]["stop_reason"])


def test_auto_strategy_balanced_executes_medium_priority_plan_step(monkeypatch, tmp_path: Path) -> None:
    project_dir = tmp_path / "demo-balanced-medium"
    project_dir.mkdir(parents=True, exist_ok=True)
    analyses = [
        {
            "next_action": {"kind": "useful_field", "message": "Add description", "command": "/add_field Task description:string"},
            "next_action_explanation": {"reason_summary": "description improves usability"},
            "suggestions": [],
            "entities": ["Task"],
            "fields_by_entity": {"Task": [{"name": "title"}]},
            "apis": [{"method": "GET", "path": "/tasks"}],
            "pages": ["tasks/list"],
            "placeholder_pages": [],
            "entity_crud_status": {"Task": {"missing_api": [], "missing_pages": []}},
        },
        {
            "next_action": {"kind": "none", "message": "No immediate suggestions.", "command": ""},
            "next_action_explanation": {},
            "suggestions": [],
            "entities": ["Task"],
            "fields_by_entity": {"Task": [{"name": "title"}, {"name": "description"}]},
            "apis": [{"method": "GET", "path": "/tasks"}],
            "pages": ["tasks/list"],
            "placeholder_pages": [],
            "entity_crud_status": {"Task": {"missing_api": [], "missing_pages": []}},
        },
    ]
    call_idx = {"value": 0}

    def _fake_build_analysis(*_args, **_kwargs):  # type: ignore[no-untyped-def]
        idx = min(call_idx["value"], len(analyses) - 1)
        call_idx["value"] += 1
        return analyses[idx]

    monkeypatch.setattr("archmind.telegram_bot._build_project_analysis", _fake_build_analysis)
    monkeypatch.setattr("archmind.telegram_bot._compute_auto_iteration_budget", lambda *_args, **_kwargs: (3, ["base=3"]))
    monkeypatch.setattr("archmind.telegram_bot._auto_runtime_state_lines", lambda *_args, **_kwargs: [])
    monkeypatch.setattr("archmind.telegram_bot._auto_analysis_brief", lambda *_args, **_kwargs: "entities=1, apis=1, pages=1")
    monkeypatch.setattr("archmind.telegram_bot.sync_repo_after_auto_batch", lambda *_args, **_kwargs: {"status": "SYNCED"})
    monkeypatch.setattr("archmind.state.load_state", lambda *_args, **_kwargs: {})
    monkeypatch.setattr("archmind.state.write_state", lambda *_args, **_kwargs: None)
    executed: list[str] = []
    monkeypatch.setattr(
        "archmind.command_executor.execute_command",
        lambda command, *_args, **_kwargs: (executed.append(command) or {"ok": True, "detail": "ok"}),
    )

    out = _execute_auto_command(project_dir, project_name="demo", source="ui-next-run", auto_strategy="balanced")
    assert out["ok"] is True
    assert out["auto_result"]["strategy"] == "balanced"
    assert executed == ["/add_field Task description:string"]
    assert out["auto_result"]["executed"] == 1


def test_auto_plan_preserves_repeated_command_protection(monkeypatch, tmp_path: Path) -> None:
    project_dir = tmp_path / "demo-repeat-protection"
    project_dir.mkdir(parents=True, exist_ok=True)
    analyses = [
        {
            "next_action": {"kind": "missing_crud_api", "message": "Add detail API", "command": "/add_api GET /tasks/{id}"},
            "next_action_explanation": {"reason_summary": "CRUD gap"},
            "suggestions": [],
            "entities": ["Task"],
            "fields_by_entity": {"Task": [{"name": "title"}]},
            "apis": [{"method": "GET", "path": "/tasks"}],
            "pages": [],
            "placeholder_pages": [],
            "entity_crud_status": {"Task": {"missing_api": ["GET detail"], "missing_pages": []}},
        },
        {
            "next_action": {"kind": "missing_crud_api", "message": "Add detail API again", "command": "/add_api GET /tasks/{id}"},
            "next_action_explanation": {"reason_summary": "CRUD gap remains"},
            "suggestions": [],
            "entities": ["Task", "Board"],
            "fields_by_entity": {"Task": [{"name": "title"}]},
            "apis": [{"method": "GET", "path": "/tasks"}],
            "pages": [],
            "placeholder_pages": [],
            "entity_crud_status": {"Task": {"missing_api": ["GET detail"], "missing_pages": []}},
        },
    ]
    call_idx = {"value": 0}

    def _fake_build_analysis(*_args, **_kwargs):  # type: ignore[no-untyped-def]
        idx = min(call_idx["value"], len(analyses) - 1)
        call_idx["value"] += 1
        return analyses[idx]

    monkeypatch.setattr("archmind.telegram_bot._build_project_analysis", _fake_build_analysis)
    monkeypatch.setattr("archmind.telegram_bot._compute_auto_iteration_budget", lambda *_args, **_kwargs: (3, ["base=3"]))
    monkeypatch.setattr("archmind.telegram_bot._auto_runtime_state_lines", lambda *_args, **_kwargs: [])
    monkeypatch.setattr("archmind.telegram_bot._auto_analysis_brief", lambda *_args, **_kwargs: "entities=2, apis=1, pages=0")
    monkeypatch.setattr("archmind.telegram_bot.sync_repo_after_auto_batch", lambda *_args, **_kwargs: {"status": "SYNCED"})
    monkeypatch.setattr("archmind.state.load_state", lambda *_args, **_kwargs: {})
    monkeypatch.setattr("archmind.state.write_state", lambda *_args, **_kwargs: None)
    executed: list[str] = []
    monkeypatch.setattr(
        "archmind.command_executor.execute_command",
        lambda command, *_args, **_kwargs: (executed.append(command) or {"ok": True, "detail": "ok"}),
    )

    out = _execute_auto_command(project_dir, project_name="demo", source="ui-next-run")
    assert executed == ["/add_api GET /tasks/{id}"]
    assert "repeated command detected" in str(out["auto_result"]["stop_reason"])


def test_auto_strategy_safe_stops_when_only_medium_plan_step_remains(monkeypatch, tmp_path: Path) -> None:
    project_dir = tmp_path / "demo-safe-medium-remains"
    project_dir.mkdir(parents=True, exist_ok=True)
    analyses = [
        {
            "next_action": {"kind": "custom_high", "message": "Add initial list API", "command": "/add_api GET /tasks"},
            "next_action_explanation": {"reason_summary": "initial API baseline"},
            "suggestions": [],
            "entities": ["Task"],
            "fields_by_entity": {"Task": [{"name": "title"}]},
            "apis": [],
            "pages": [],
            "placeholder_pages": [],
            "entity_crud_status": {"Task": {"missing_api": [], "missing_pages": []}},
        },
        {
            "next_action": {"kind": "useful_field", "message": "Add description", "command": "/add_field Task description:string"},
            "next_action_explanation": {"reason_summary": "description improves readability"},
            "suggestions": [],
            "entities": ["Task"],
            "fields_by_entity": {"Task": [{"name": "title"}]},
            "apis": [{"method": "GET", "path": "/tasks"}],
            "pages": [],
            "placeholder_pages": [],
            "entity_crud_status": {"Task": {"missing_api": [], "missing_pages": []}},
        },
    ]
    call_idx = {"value": 0}

    def _fake_build_analysis(*_args, **_kwargs):  # type: ignore[no-untyped-def]
        idx = min(call_idx["value"], len(analyses) - 1)
        call_idx["value"] += 1
        return analyses[idx]

    monkeypatch.setattr("archmind.telegram_bot._build_project_analysis", _fake_build_analysis)
    monkeypatch.setattr("archmind.telegram_bot._compute_auto_iteration_budget", lambda *_args, **_kwargs: (3, ["base=3"]))
    monkeypatch.setattr("archmind.telegram_bot._auto_runtime_state_lines", lambda *_args, **_kwargs: [])
    monkeypatch.setattr("archmind.telegram_bot._auto_analysis_brief", lambda *_args, **_kwargs: "entities=1, apis=1, pages=0")
    monkeypatch.setattr("archmind.telegram_bot._auto_is_good_enough_mvp", lambda *_args, **_kwargs: False)
    monkeypatch.setattr("archmind.telegram_bot.sync_repo_after_auto_batch", lambda *_args, **_kwargs: {"status": "SYNCED"})
    monkeypatch.setattr("archmind.state.load_state", lambda *_args, **_kwargs: {})
    monkeypatch.setattr("archmind.state.write_state", lambda *_args, **_kwargs: None)
    executed: list[str] = []
    monkeypatch.setattr(
        "archmind.command_executor.execute_command",
        lambda command, *_args, **_kwargs: (executed.append(command) or {"ok": True, "detail": "ok"}),
    )

    out = _execute_auto_command(project_dir, project_name="demo", source="ui-next-run", auto_strategy="safe")
    assert out["ok"] is True
    assert executed == ["/add_api GET /tasks"]
    assert "strategy guard" in str(out["auto_result"]["stop_reason"]).lower()
    assert "safe strategy allows only high-priority actions" in str(out["auto_result"]["stop_explanation"]).lower()


def test_auto_plan_skips_stale_followup_steps_when_goal_satisfied_early(monkeypatch, tmp_path: Path) -> None:
    project_dir = tmp_path / "demo-stale-skip"
    project_dir.mkdir(parents=True, exist_ok=True)
    analyses = [
        {
            "next_action": {
                "kind": "relation_page_behavior",
                "message": "Add tags by entry page",
                "command": "/add_page tags/by_entry",
            },
            "next_action_explanation": {"reason_summary": "Entry->Tag relation flow is incomplete"},
            "suggestions": [
                {
                    "kind": "relation_scoped_api",
                    "message": "Add scoped relation API",
                    "command": "/add_api GET /entries/{id}/tags",
                },
                {
                    "kind": "relation_placeholder_page",
                    "message": "Implement relation page",
                    "command": "/implement_page tags/by_entry",
                },
            ],
            "entities": ["Entry", "Tag"],
            "fields_by_entity": {"Tag": [{"name": "entry_id"}]},
            "apis": [{"method": "GET", "path": "/entries"}, {"method": "GET", "path": "/tags"}],
            "pages": ["entries/list", "tags/list"],
            "placeholder_pages": ["tags/by_entry"],
            "entity_crud_status": {"Entry": {"missing_api": [], "missing_pages": []}, "Tag": {"missing_api": [], "missing_pages": []}},
            "drift_warnings": ["Relation-scoped API GET /entries/{id}/tags is missing."],
        },
        {
            "next_action": {"kind": "none", "message": "No immediate suggestions.", "command": ""},
            "next_action_explanation": {},
            "suggestions": [],
            "entities": ["Entry", "Tag"],
            "fields_by_entity": {"Tag": [{"name": "entry_id"}]},
            "apis": [{"method": "GET", "path": "/entries"}, {"method": "GET", "path": "/tags"}, {"method": "GET", "path": "/entries/{id}/tags"}],
            "pages": ["entries/list", "tags/list", "tags/by_entry"],
            "placeholder_pages": [],
            "entity_crud_status": {"Entry": {"missing_api": [], "missing_pages": []}, "Tag": {"missing_api": [], "missing_pages": []}},
            "drift_warnings": [],
        },
    ]
    call_idx = {"value": 0}

    def _fake_build_analysis(*_args, **_kwargs):  # type: ignore[no-untyped-def]
        idx = min(call_idx["value"], len(analyses) - 1)
        call_idx["value"] += 1
        return analyses[idx]

    monkeypatch.setattr("archmind.telegram_bot._build_project_analysis", _fake_build_analysis)
    monkeypatch.setattr("archmind.telegram_bot._compute_auto_iteration_budget", lambda *_args, **_kwargs: (3, ["base=3"]))
    monkeypatch.setattr("archmind.telegram_bot._auto_runtime_state_lines", lambda *_args, **_kwargs: [])
    monkeypatch.setattr("archmind.telegram_bot._auto_analysis_brief", lambda *_args, **_kwargs: "entities=2, apis=3, pages=3")
    monkeypatch.setattr("archmind.telegram_bot.sync_repo_after_auto_batch", lambda *_args, **_kwargs: {"status": "SYNCED"})
    monkeypatch.setattr("archmind.state.load_state", lambda *_args, **_kwargs: {})
    monkeypatch.setattr("archmind.state.write_state", lambda *_args, **_kwargs: None)
    executed: list[str] = []
    monkeypatch.setattr(
        "archmind.command_executor.execute_command",
        lambda command, *_args, **_kwargs: (executed.append(command) or {"ok": True, "detail": "ok"}),
    )

    out = _execute_auto_command(project_dir, project_name="demo", source="ui-next-run")
    assert out["ok"] is True
    assert executed == ["/add_api GET /entries/{id}/tags"]
    assert out["auto_result"]["goal_satisfied"] is True
    skipped = out["auto_result"]["skipped_steps"]
    assert any(step["command"] == "/add_page tags/by_entry" for step in skipped)
    assert any(step["command"] == "/implement_page tags/by_entry" for step in skipped)
    assert out["auto_result"]["plan_priority"] in {"high", "medium", "low", "none"}
    assert "goal_satisfied_after_reanalysis" in out["auto_result"]["plan_stop_conditions"]
