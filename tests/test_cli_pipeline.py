from __future__ import annotations

from pathlib import Path

import pytest

from archmind.cli import main
from archmind.generator import (
    apply_api_scaffold,
    apply_entity_fields_to_scaffold,
    apply_entity_scaffold,
    apply_frontend_page_scaffold,
    apply_page_scaffold,
)
from archmind.project_analysis import analyze_project
from archmind.project_query import build_project_analysis, build_project_detail
from archmind.state import write_state
import json
import subprocess
import sys


def _write_backend_project(tmp_path: Path) -> None:
    tmp_path.joinpath("pytest.ini").write_text("[pytest]\naddopts = -q\n", encoding="utf-8")
    tmp_path.joinpath("test_ok.py").write_text("def test_ok():\n    assert True\n", encoding="utf-8")


def _write_backend_fail_project(tmp_path: Path) -> None:
    tmp_path.joinpath("pytest.ini").write_text("[pytest]\naddopts = -q\n", encoding="utf-8")
    tmp_path.joinpath("test_fail.py").write_text("def test_fail():\n    assert False\n", encoding="utf-8")


def _fake_generate_project(idea: str, opt) -> Path:
    project_name = (opt.name or "archmind_project").strip() or "archmind_project"
    project_dir = Path(opt.out) / project_name
    project_dir.mkdir(parents=True, exist_ok=True)
    template = str(getattr(opt, "template", "") or "").strip().lower()
    if template == "fullstack-ddd":
        (project_dir / "backend" / "app").mkdir(parents=True, exist_ok=True)
        (project_dir / "backend" / "app" / "main.py").write_text(
            "from fastapi import FastAPI\napp = FastAPI()\n",
            encoding="utf-8",
        )
        (project_dir / "backend" / "requirements.txt").write_text("fastapi\n", encoding="utf-8")
        (project_dir / "backend" / "pytest.ini").write_text("[pytest]\naddopts = -q\n", encoding="utf-8")
        (project_dir / "backend" / "test_ok.py").write_text("def test_ok():\n    assert True\n", encoding="utf-8")
        (project_dir / "frontend").mkdir(parents=True, exist_ok=True)
    else:
        project_dir.joinpath("pytest.ini").write_text("[pytest]\naddopts = -q\n", encoding="utf-8")
        project_dir.joinpath("test_ok.py").write_text("def test_ok():\n    assert True\n", encoding="utf-8")
    return project_dir


def _fake_generate_project_with_seed_scaffold(idea: str, opt) -> Path:
    del idea
    project_dir = _fake_generate_project("demo", opt)
    spec = getattr(opt, "project_spec", None)
    if not isinstance(spec, dict):
        return project_dir

    entities = spec.get("entities") if isinstance(spec.get("entities"), list) else []
    for raw in entities:
        if not isinstance(raw, dict):
            continue
        entity_name = str(raw.get("name") or "").strip()
        if not entity_name:
            continue
        apply_entity_scaffold(project_dir, entity_name)
        fields = raw.get("fields")
        if isinstance(fields, list):
            apply_entity_fields_to_scaffold(project_dir, entity_name, fields)
        apply_frontend_page_scaffold(project_dir, entity_name)

    api_endpoints = spec.get("api_endpoints") if isinstance(spec.get("api_endpoints"), list) else []
    for endpoint in api_endpoints:
        text = str(endpoint or "").strip()
        parts = text.split(maxsplit=1)
        if len(parts) != 2:
            continue
        method = str(parts[0]).upper().strip()
        path = str(parts[1]).strip()
        if method in {"GET", "POST", "PUT", "PATCH", "DELETE"} and path:
            apply_api_scaffold(project_dir, method, path)

    frontend_pages = spec.get("frontend_pages") if isinstance(spec.get("frontend_pages"), list) else []
    for page in frontend_pages:
        apply_page_scaffold(project_dir, str(page or ""))
    return project_dir


def test_pipeline_help() -> None:
    with pytest.raises(SystemExit) as exc:
        main(["pipeline", "--help"])
    assert exc.value.code == 0


def test_pipeline_invalid_path_returns_error(capsys, tmp_path: Path) -> None:
    missing = tmp_path / "missing"
    exit_code = main(["pipeline", "--path", str(missing), "--max-iterations", "1"])
    captured = capsys.readouterr()

    assert exit_code != 0
    assert "path is not a directory" in captured.err.lower() or "error" in captured.err.lower()


def test_pipeline_dry_run_no_artifacts(tmp_path: Path) -> None:
    exit_code = main(["pipeline", "--path", str(tmp_path), "--dry-run"])
    assert exit_code == 0
    assert not (tmp_path / ".archmind").exists()


def test_pipeline_backend_only_smoke(tmp_path: Path) -> None:
    _write_backend_project(tmp_path)

    exit_code = main(
        [
            "pipeline",
            "--path",
            str(tmp_path),
            "--backend-only",
            "--max-iterations",
            "1",
            "--model",
            "none",
            "--scope",
            "backend",
        ]
    )
    assert exit_code in (0, 1)


def test_pipeline_invokes_environment_readiness_check(tmp_path: Path, monkeypatch) -> None:
    _write_backend_project(tmp_path)
    calls = {"n": 0}

    def fake_readiness(project_dir):  # type: ignore[no-untyped-def]
        assert project_dir == tmp_path.resolve()
        calls["n"] += 1
        return {"issue": "env-readiness-ok", "reason": "ok", "actions": []}

    monkeypatch.setattr("archmind.pipeline.ensure_environment_readiness", fake_readiness)
    exit_code = main(
        [
            "pipeline",
            "--path",
            str(tmp_path),
            "--backend-only",
            "--max-iterations",
            "1",
            "--model",
            "none",
        ]
    )
    assert exit_code in (0, 1)
    assert calls["n"] >= 1


def test_pipeline_idea_generates_and_runs(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr("archmind.pipeline._resolve_generator_entry", lambda: _fake_generate_project)

    exit_code = main(
        [
            "pipeline",
            "--idea",
            "demo",
            "--template",
            "fullstack-ddd",
            "--out",
            str(tmp_path),
            "--name",
            "demo_proj",
            "--backend-only",
            "--max-iterations",
            "1",
            "--model",
            "none",
        ]
    )
    assert exit_code == 0

    project_dir = tmp_path / "demo_proj"
    assert project_dir.exists()
    assert (project_dir / ".archmind" / "plan.md").exists()
    assert (project_dir / ".archmind" / "plan.json").exists()
    log_dir = project_dir / ".archmind" / "run_logs"
    assert log_dir.exists()
    assert list(log_dir.glob("run_*.summary.txt"))
    state_payload = json.loads((project_dir / ".archmind" / "state.json").read_text(encoding="utf-8"))
    assert state_payload.get("agent_state") in {"DONE", "NOT_DONE", "STUCK", "BLOCKED"}
    history = state_payload.get("history") or []
    assert any("pipeline planning" in str(item.get("action") or "") for item in history if isinstance(item, dict))
    assert any("pipeline run" in str(item.get("action") or "") for item in history if isinstance(item, dict))
    assert state_payload.get("current_step_key") == "finished"
    assert state_payload.get("current_step_label") == "Finished"
    assert state_payload.get("last_progress_at")


def test_pipeline_idea_fullstack_invalid_structure_stops_before_run(tmp_path: Path, monkeypatch) -> None:
    def fake_invalid_fullstack(_idea: str, opt) -> Path:  # type: ignore[no-untyped-def]
        project_name = (opt.name or "archmind_project").strip() or "archmind_project"
        project_dir = Path(opt.out) / project_name
        project_dir.mkdir(parents=True, exist_ok=True)
        (project_dir / "frontend").mkdir(parents=True, exist_ok=True)
        return project_dir

    monkeypatch.setattr("archmind.pipeline._resolve_generator_entry", lambda: fake_invalid_fullstack)
    exit_code = main(
        [
            "pipeline",
            "--idea",
            "blog webapp",
            "--template",
            "fullstack-ddd",
            "--out",
            str(tmp_path),
            "--name",
            "invalid_fullstack",
            "--backend-only",
            "--max-iterations",
            "1",
            "--model",
            "none",
        ]
    )
    assert exit_code == 1
    result_payload = json.loads((tmp_path / "invalid_fullstack" / ".archmind" / "result.json").read_text(encoding="utf-8"))
    assert result_payload.get("status") == "FAIL"
    assert result_payload.get("steps", {}).get("generate", {}).get("failure_class") == "generation-error"


def test_pipeline_todo_starter_profile_fails_when_project_is_only_generic_scaffold(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr("archmind.pipeline._resolve_generator_entry", lambda: _fake_generate_project)

    exit_code = main(
        [
            "pipeline",
            "--idea",
            "todo app",
            "--template",
            "fullstack-ddd",
            "--starter-profile",
            "todo",
            "--out",
            str(tmp_path),
            "--name",
            "todo_generic_only",
            "--backend-only",
            "--max-iterations",
            "1",
            "--model",
            "none",
        ]
    )
    assert exit_code != 0

    project_dir = tmp_path / "todo_generic_only"
    result_payload = json.loads((project_dir / ".archmind" / "result.json").read_text(encoding="utf-8"))
    assert result_payload.get("status") == "FAIL"
    assert result_payload.get("steps", {}).get("generate", {}).get("failure_class") == "generation-error"
    detail = str(result_payload.get("steps", {}).get("generate", {}).get("detail") or "")
    assert (
        "missing Task entity in spec" in detail
        or "frontend root is still generic fallback scaffold" in detail
        or "missing frontend tasks list page" in detail
        or "missing frontend tasks create page" in detail
    )


def test_pipeline_todo_starter_profile_passes_when_task_baseline_is_materialized(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr("archmind.pipeline._resolve_generator_entry", lambda: _fake_generate_project_with_seed_scaffold)
    monkeypatch.setattr(
        "archmind.pipeline.suggest_project_spec",
        lambda *_args, **_kwargs: {
            "entities": [{"name": "Task", "fields": [{"name": "title", "type": "string"}, {"name": "status", "type": "string"}]}],
            "api_endpoints": ["GET /tasks", "POST /tasks", "GET /tasks/{id}"],
            "frontend_pages": ["tasks/list", "tasks/detail", "tasks/new"],
        },
    )

    exit_code = main(
        [
            "pipeline",
            "--idea",
            "todo app",
            "--template",
            "fullstack-ddd",
            "--starter-profile",
            "todo",
            "--out",
            str(tmp_path),
            "--name",
            "todo_materialized",
            "--backend-only",
            "--max-iterations",
            "1",
            "--model",
            "none",
        ]
    )
    assert exit_code == 0

    project_dir = tmp_path / "todo_materialized"
    task_list = project_dir / "frontend" / "app" / "tasks" / "page.tsx"
    task_create = project_dir / "frontend" / "app" / "tasks" / "new" / "page.tsx"
    assert task_list.exists()
    assert task_create.exists()
    spec_payload = json.loads((project_dir / ".archmind" / "project_spec.json").read_text(encoding="utf-8"))
    entity_names = {
        str(item.get("name") or "").strip().lower()
        for item in (spec_payload.get("entities") or [])
        if isinstance(item, dict)
    }
    assert "task" in entity_names


def test_pipeline_idea_generator_receives_effective_template_for_frontend_web(tmp_path: Path, monkeypatch) -> None:
    captured: dict[str, str] = {}

    def fake_generate_project(idea: str, opt) -> Path:  # type: ignore[no-untyped-def]
        captured["idea"] = idea
        captured["template"] = str(getattr(opt, "template", ""))
        project_name = (opt.name or "archmind_project").strip() or "archmind_project"
        project_dir = Path(opt.out) / project_name
        project_dir.mkdir(parents=True, exist_ok=True)
        project_dir.joinpath("pytest.ini").write_text("[pytest]\naddopts = -q\n", encoding="utf-8")
        project_dir.joinpath("test_ok.py").write_text("def test_ok():\n    assert True\n", encoding="utf-8")
        return project_dir

    monkeypatch.setattr("archmind.pipeline._resolve_generator_entry", lambda: fake_generate_project)

    exit_code = main(
        [
            "pipeline",
            "--idea",
            "simple nextjs counter dashboard",
            "--out",
            str(tmp_path),
            "--name",
            "idea_frontend_route",
            "--backend-only",
            "--max-iterations",
            "1",
            "--model",
            "none",
        ]
    )
    assert exit_code == 0
    assert captured.get("idea") == "simple nextjs counter dashboard"
    assert captured.get("template") == "nextjs"

    result_payload = json.loads((tmp_path / "idea_frontend_route" / ".archmind" / "result.json").read_text(encoding="utf-8"))
    assert result_payload.get("selected_template") == "nextjs"
    assert result_payload.get("effective_template") == "nextjs"
    assert result_payload.get("template_fallback_reason") in ("", None)


@pytest.mark.parametrize(
    ("idea", "expected_template"),
    [
        ("internal admin dashboard for device status", "internal-tool"),
        ("background batch processing api", "worker-api"),
        ("inventory management tool for small business", "data-tool"),
    ],
)
def test_pipeline_idea_routes_to_new_templates(
    tmp_path: Path,
    monkeypatch,
    idea: str,
    expected_template: str,
) -> None:
    captured: dict[str, str] = {}

    def fake_generate_project(local_idea: str, opt) -> Path:  # type: ignore[no-untyped-def]
        captured["idea"] = local_idea
        captured["template"] = str(getattr(opt, "template", ""))
        project_name = (opt.name or "archmind_project").strip() or "archmind_project"
        project_dir = Path(opt.out) / project_name
        project_dir.mkdir(parents=True, exist_ok=True)
        project_dir.joinpath("pytest.ini").write_text("[pytest]\naddopts = -q\n", encoding="utf-8")
        project_dir.joinpath("test_ok.py").write_text("def test_ok():\n    assert True\n", encoding="utf-8")
        return project_dir

    monkeypatch.setattr("archmind.pipeline._resolve_generator_entry", lambda: fake_generate_project)
    exit_code = main(
        [
            "pipeline",
            "--idea",
            idea,
            "--out",
            str(tmp_path),
            "--name",
            f"route_{expected_template.replace('-', '_')}",
            "--backend-only",
            "--max-iterations",
            "1",
            "--model",
            "none",
        ]
    )
    assert exit_code == 0
    assert captured.get("template") == expected_template


def test_pipeline_frontend_web_routes_to_nextjs_without_fallback(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr("archmind.pipeline._resolve_generator_entry", lambda: _fake_generate_project)

    exit_code = main(
        [
            "pipeline",
            "--idea",
            "simple nextjs counter dashboard",
            "--out",
            str(tmp_path),
            "--name",
            "frontend_routing_demo",
            "--backend-only",
            "--max-iterations",
            "1",
            "--model",
            "none",
        ]
    )
    assert exit_code == 0

    project_dir = tmp_path / "frontend_routing_demo"
    result_payload = json.loads((project_dir / ".archmind" / "result.json").read_text(encoding="utf-8"))
    assert result_payload.get("project_type") == "frontend-web"
    assert result_payload.get("selected_template") == "nextjs"
    assert result_payload.get("effective_template") == "nextjs"
    assert result_payload.get("template_fallback_reason") in ("", None)

    state_payload = json.loads((project_dir / ".archmind" / "state.json").read_text(encoding="utf-8"))
    assert state_payload.get("effective_template") == "nextjs"
    assert state_payload.get("template_fallback_reason") in ("", None)


def test_pipeline_writes_architecture_reasoning_artifact_and_state_fields(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr("archmind.pipeline._resolve_generator_entry", lambda: _fake_generate_project)

    exit_code = main(
        [
            "pipeline",
            "--idea",
            "fullstack simple task tracker with fastapi backend and nextjs frontend",
            "--out",
            str(tmp_path),
            "--name",
            "brain_reasoning_demo",
            "--backend-only",
            "--max-iterations",
            "1",
            "--model",
            "none",
        ]
    )
    assert exit_code == 0

    project_dir = tmp_path / "brain_reasoning_demo"
    reasoning_payload = json.loads(
        (project_dir / ".archmind" / "architecture_reasoning.json").read_text(encoding="utf-8")
    )
    assert reasoning_payload.get("app_shape") == "fullstack"
    assert reasoning_payload.get("recommended_template") == "fullstack-ddd"
    assert "tasks" in (reasoning_payload.get("domains") or [])

    state_payload = json.loads((project_dir / ".archmind" / "state.json").read_text(encoding="utf-8"))
    assert state_payload.get("architecture_app_shape") == "fullstack"
    assert state_payload.get("architecture_recommended_template") == "fullstack-ddd"
    assert state_payload.get("architecture_reason_summary")


def test_pipeline_writes_project_spec_and_module_alignment(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr("archmind.pipeline._resolve_generator_entry", lambda: _fake_generate_project)

    exit_code = main(
        [
            "pipeline",
            "--idea",
            "team task tracker with login dashboard",
            "--out",
            str(tmp_path),
            "--name",
            "project_spec_demo",
            "--backend-only",
            "--max-iterations",
            "1",
            "--model",
            "none",
        ]
    )
    assert exit_code == 0

    project_dir = tmp_path / "project_spec_demo"
    reasoning_payload = json.loads(
        (project_dir / ".archmind" / "architecture_reasoning.json").read_text(encoding="utf-8")
    )
    spec_payload = json.loads((project_dir / ".archmind" / "project_spec.json").read_text(encoding="utf-8"))

    assert spec_payload.get("shape") == reasoning_payload.get("app_shape")
    assert spec_payload.get("modules") == reasoning_payload.get("modules")
    assert spec_payload.get("template")
    assert spec_payload.get("reason_summary")
    assert isinstance(spec_payload.get("entities"), list)
    assert isinstance(spec_payload.get("api_endpoints"), list)
    assert isinstance(spec_payload.get("frontend_pages"), list)
    assert len(spec_payload.get("entities") or []) >= 1
    assert len(spec_payload.get("api_endpoints") or []) >= 1
    evolution = spec_payload.get("evolution") or {}
    assert evolution.get("version") == 1
    assert evolution.get("added_modules") == []
    assert evolution.get("history") == []


def test_pipeline_generated_project_spec_is_visible_to_inspect_and_next(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr("archmind.pipeline._resolve_generator_entry", lambda: _fake_generate_project)

    exit_code = main(
        [
            "pipeline",
            "--idea",
            "personal diary webapp with notes and calendar",
            "--out",
            str(tmp_path),
            "--name",
            "spec_sync_demo",
            "--max-iterations",
            "1",
            "--model",
            "none",
        ]
    )
    assert exit_code == 0

    project_dir = tmp_path / "spec_sync_demo"
    spec_payload = json.loads((project_dir / ".archmind" / "project_spec.json").read_text(encoding="utf-8"))

    assert len(spec_payload.get("entities") or []) >= 1
    assert len(spec_payload.get("api_endpoints") or []) >= 1

    detail = build_project_detail(project_dir)
    assert detail.spec_summary.entities >= 1
    assert detail.spec_summary.apis >= 1

    analysis = analyze_project(project_dir, spec_payload=spec_payload, runtime_payload={})
    next_action = analysis.get("next_action") if isinstance(analysis.get("next_action"), dict) else {}
    assert str(next_action.get("kind") or "").strip().lower() in {
        "none",
        "missing_field",
        "missing_crud_api",
        "missing_page",
        "relation_page_behavior",
        "relation_scoped_api",
        "placeholder_page",
        "relation_placeholder_page",
    }


def test_pipeline_diary_spec_keeps_inspect_and_next_api_source_consistent(tmp_path: Path, monkeypatch) -> None:
    diary_spec = {
        "entities": [
            {
                "name": "Entry",
                "fields": [
                    {"name": "title", "type": "string"},
                    {"name": "content", "type": "string"},
                ],
            }
        ],
        "api_endpoints": [
            "GET /entries",
            "POST /entries",
            "GET /entries/{entry_id}",
            "PATCH /entries/:id",
            "DELETE /entries/[id]",
        ],
        "frontend_pages": ["entries/list", "entries/detail"],
    }
    monkeypatch.setattr("archmind.pipeline._resolve_generator_entry", lambda: _fake_generate_project_with_seed_scaffold)
    monkeypatch.setattr("archmind.pipeline.suggest_project_spec", lambda *_a, **_k: diary_spec)

    exit_code = main(
        [
            "pipeline",
            "--idea",
            "personal diary webapp with entries",
            "--out",
            str(tmp_path),
            "--name",
            "diary_runtime_consistency_demo",
            "--max-iterations",
            "1",
            "--model",
            "none",
        ]
    )
    assert exit_code == 0

    project_dir = tmp_path / "diary_runtime_consistency_demo"
    detail = build_project_detail(project_dir)
    detail_analysis = detail.analysis if isinstance(detail.analysis, dict) else {}
    analysis = build_project_analysis(project_dir)

    inspect_api_set = {
        f"{str(item.get('method') or '').strip().upper()} {str(item.get('path') or '').strip()}"
        for item in (detail_analysis.get("apis") or [])
        if isinstance(item, dict) and str(item.get("method") or "").strip() and str(item.get("path") or "").strip()
    }
    next_api_set = {
        f"{str(item.get('method') or '').strip().upper()} {str(item.get('path') or '').strip()}"
        for item in (analysis.get("apis") or [])
        if isinstance(item, dict) and str(item.get("method") or "").strip() and str(item.get("path") or "").strip()
    }

    assert inspect_api_set == next_api_set
    assert "GET /entries/{id}" in inspect_api_set
    assert "PATCH /entries/{id}" in inspect_api_set
    assert "DELETE /entries/{id}" in inspect_api_set
    next_action = analysis.get("next_action") if isinstance(analysis.get("next_action"), dict) else {}
    assert str(next_action.get("command") or "").strip() != "/add_api GET /entries/{id}"


def test_pipeline_fullstack_seed_spec_applies_to_generated_scaffold(tmp_path: Path, monkeypatch) -> None:
    diary_spec = {
        "entities": [
            {
                "name": "Entry",
                "fields": [
                    {"name": "title", "type": "string"},
                    {"name": "content", "type": "string"},
                ],
            }
        ],
        "api_endpoints": ["GET /entries", "POST /entries"],
        "frontend_pages": ["entries/list"],
    }
    monkeypatch.setattr("archmind.pipeline._resolve_generator_entry", lambda: _fake_generate_project_with_seed_scaffold)
    monkeypatch.setattr("archmind.pipeline.suggest_project_spec", lambda *_a, **_k: diary_spec)

    exit_code = main(
        [
            "pipeline",
            "--idea",
            "my diary app with entry title and content",
            "--out",
            str(tmp_path),
            "--name",
            "diary_seed_demo",
            "--max-iterations",
            "1",
            "--model",
            "none",
        ]
    )
    assert exit_code == 0

    project_dir = tmp_path / "diary_seed_demo"
    assert (project_dir / "backend" / "app" / "routers" / "entry.py").exists()
    assert (project_dir / "frontend" / "app" / "entries" / "page.tsx").exists()
    merged = "\n".join(
        [
            (project_dir / "backend" / "app" / "main.py").read_text(encoding="utf-8").lower(),
            (project_dir / "frontend" / "app" / "entries" / "page.tsx").read_text(encoding="utf-8").lower(),
        ]
    )
    assert "defect intake" not in merged
    assert "create note" not in merged

    spec_payload = json.loads((project_dir / ".archmind" / "project_spec.json").read_text(encoding="utf-8"))
    assert len(spec_payload.get("entities") or []) >= 1
    assert len(spec_payload.get("api_endpoints") or []) >= 1
    assert len(spec_payload.get("frontend_pages") or []) >= 1

    detail = build_project_detail(project_dir)
    assert detail.spec_summary.entities >= 1
    assert detail.spec_summary.apis >= 1
    assert detail.spec_summary.pages >= 1

    analysis = analyze_project(project_dir, spec_payload=spec_payload, runtime_payload={})
    suggestions = analysis.get("suggestions") if isinstance(analysis.get("suggestions"), list) else []
    commands = {str(item.get("command") or "").strip() for item in suggestions if isinstance(item, dict)}
    assert "/add_entity Task" not in commands
    next_action = analysis.get("next_action") if isinstance(analysis.get("next_action"), dict) else {}
    assert str(next_action.get("command") or "").strip() != "/add_entity Task"


def test_pipeline_fullstack_seed_spec_projects_all_entities_and_pages(tmp_path: Path, monkeypatch) -> None:
    diary_spec = {
        "entities": [
            {
                "name": "Entry",
                "fields": [
                    {"name": "title", "type": "string"},
                    {"name": "content", "type": "string"},
                ],
            },
            "Tag",
        ],
        "api_endpoints": ["GET /entries", "POST /entries", {"method": "GET", "path": "/tags"}],
        "frontend_pages": ["entries/list", {"path": "tags/list"}, "entry/new"],
    }
    monkeypatch.setattr("archmind.pipeline._resolve_generator_entry", lambda: _fake_generate_project_with_seed_scaffold)
    monkeypatch.setattr("archmind.pipeline.suggest_project_spec", lambda *_a, **_k: diary_spec)

    exit_code = main(
        [
            "pipeline",
            "--idea",
            "my diary app with entries and tags",
            "--out",
            str(tmp_path),
            "--name",
            "diary_seed_multi_demo",
            "--max-iterations",
            "1",
            "--model",
            "none",
        ]
    )
    assert exit_code == 0

    project_dir = tmp_path / "diary_seed_multi_demo"
    assert (project_dir / "backend" / "app" / "routers" / "entry.py").exists()
    assert (project_dir / "backend" / "app" / "routers" / "tag.py").exists()
    assert (project_dir / "frontend" / "app" / "entries" / "page.tsx").exists()
    assert (project_dir / "frontend" / "app" / "tags" / "page.tsx").exists()
    assert (project_dir / "frontend" / "app" / "entries" / "new" / "page.tsx").exists()

    nav_text = (project_dir / "frontend" / "app" / "_lib" / "navigation.ts").read_text(encoding="utf-8")
    assert 'href: "/entries"' in nav_text
    assert 'href: "/tags"' in nav_text
    assert 'href: "/entries/new"' in nav_text

    spec_payload = json.loads((project_dir / ".archmind" / "project_spec.json").read_text(encoding="utf-8"))
    assert len(spec_payload.get("entities") or []) >= 2
    assert len(spec_payload.get("api_endpoints") or []) >= 3
    assert len(spec_payload.get("frontend_pages") or []) >= 3

    detail = build_project_detail(project_dir)
    assert detail.spec_summary.entities >= 2
    assert detail.spec_summary.pages >= 3


@pytest.mark.parametrize(
    ("idea", "project_name", "required_entities", "relation_entity", "relation_field", "required_resources"),
    [
        (
            "kanban board app with boards and cards",
            "kanban_multi_entity_demo",
            {"Board", "Card"},
            "Card",
            "board_id",
            {"boards", "cards"},
        ),
        (
            "diary app with entries and tags",
            "diary_tag_multi_entity_demo",
            {"Entry", "Tag"},
            "Tag",
            "entry_id",
            {"entries", "tags"},
        ),
        (
            "bookmark manager with categories",
            "bookmark_category_multi_entity_demo",
            {"Bookmark", "Category"},
            "",
            "",
            {"bookmarks", "categories"},
        ),
    ],
)
def test_pipeline_idea_preserves_multi_entity_projection_in_canonical_inspect(
    tmp_path: Path,
    monkeypatch,
    idea: str,
    project_name: str,
    required_entities: set[str],
    relation_entity: str,
    relation_field: str,
    required_resources: set[str],
) -> None:
    monkeypatch.setattr("archmind.pipeline._resolve_generator_entry", lambda: _fake_generate_project_with_seed_scaffold)

    exit_code = main(
        [
            "pipeline",
            "--idea",
            idea,
            "--out",
            str(tmp_path),
            "--name",
            project_name,
            "--max-iterations",
            "1",
            "--model",
            "none",
        ]
    )
    assert exit_code == 0

    project_dir = tmp_path / project_name
    detail = build_project_detail(project_dir)
    analysis = detail.analysis if isinstance(detail.analysis, dict) else {}

    entities = {str(x) for x in (analysis.get("entities") or []) if str(x).strip()}
    assert required_entities.issubset(entities)
    assert detail.spec_summary.entities >= len(required_entities)

    fields_by_entity = analysis.get("fields_by_entity") if isinstance(analysis.get("fields_by_entity"), dict) else {}
    if relation_entity and relation_field:
        rows = fields_by_entity.get(relation_entity) if isinstance(fields_by_entity.get(relation_entity), list) else []
        field_names = {str(item.get("name") or "").strip() for item in rows if isinstance(item, dict)}
        assert relation_field in field_names

    apis = analysis.get("apis") if isinstance(analysis.get("apis"), list) else []
    resources_in_api = {
        str(item.get("path") or "").strip().split("/", 2)[1]
        for item in apis
        if isinstance(item, dict) and str(item.get("path") or "").strip().startswith("/") and len(str(item.get("path") or "").strip().split("/")) >= 2
    }
    pages = {str(x) for x in (analysis.get("pages") or []) if str(x).strip()}
    resources_in_pages = {page.split("/", 1)[0] for page in pages if "/" in page}
    assert required_resources.issubset(resources_in_api | resources_in_pages)


def test_pipeline_continue_does_not_erase_persisted_spec(tmp_path: Path, monkeypatch) -> None:
    diary_spec = {
        "entities": [
            {
                "name": "Entry",
                "fields": [
                    {"name": "title", "type": "string"},
                    {"name": "content", "type": "string"},
                ],
            },
            {
                "name": "User",
                "fields": [
                    {"name": "name", "type": "string"},
                    {"name": "email", "type": "string"},
                ],
            },
        ],
        "api_endpoints": ["GET /entries", "POST /entries", "GET /users", "POST /users"],
        "frontend_pages": ["entries/list", "entries/detail", "users/list"],
    }
    monkeypatch.setattr("archmind.pipeline._resolve_generator_entry", lambda: _fake_generate_project_with_seed_scaffold)
    monkeypatch.setattr("archmind.pipeline.suggest_project_spec", lambda *_a, **_k: diary_spec)

    first_exit = main(
        [
            "pipeline",
            "--idea",
            "diary app with users and entry pages",
            "--out",
            str(tmp_path),
            "--name",
            "diary_lifecycle_demo",
            "--max-iterations",
            "1",
            "--model",
            "none",
        ]
    )
    assert first_exit == 0

    project_dir = tmp_path / "diary_lifecycle_demo"
    spec_path = project_dir / ".archmind" / "project_spec.json"
    before = json.loads(spec_path.read_text(encoding="utf-8"))
    assert len(before.get("entities") or []) >= 2
    assert len(before.get("api_endpoints") or []) >= 2
    assert len(before.get("frontend_pages") or []) >= 2

    continue_exit = main(
        [
            "pipeline",
            "--path",
            str(project_dir),
            "--max-iterations",
            "1",
            "--model",
            "none",
        ]
    )
    assert continue_exit in (0, 1)

    after = json.loads(spec_path.read_text(encoding="utf-8"))
    assert len(after.get("entities") or []) >= 2
    assert len(after.get("api_endpoints") or []) >= 2
    assert len(after.get("frontend_pages") or []) >= 2
    assert (project_dir / "frontend" / "app" / "entries" / "page.tsx").exists()

    detail = build_project_detail(project_dir)
    assert detail.spec_summary.entities >= 2
    assert detail.spec_summary.apis >= 2
    assert detail.spec_summary.pages >= 2
    analysis = analyze_project(project_dir, spec_payload=after, runtime_payload={})
    next_action = analysis.get("next_action") if isinstance(analysis.get("next_action"), dict) else {}
    assert str(next_action.get("command") or "").strip() != "/add_entity Task"


def test_pipeline_idea_rerun_does_not_overwrite_non_empty_spec_with_empty_suggestion(tmp_path: Path, monkeypatch) -> None:
    rich_spec = {
        "entities": [{"name": "Entry", "fields": [{"name": "title", "type": "string"}]}],
        "api_endpoints": ["GET /entries", "POST /entries"],
        "frontend_pages": ["entries/list"],
    }
    monkeypatch.setattr("archmind.pipeline._resolve_generator_entry", lambda: _fake_generate_project_with_seed_scaffold)
    monkeypatch.setattr("archmind.pipeline.suggest_project_spec", lambda *_a, **_k: rich_spec)

    first_exit = main(
        [
            "pipeline",
            "--idea",
            "diary app",
            "--out",
            str(tmp_path),
            "--name",
            "spec_preserve_demo",
            "--max-iterations",
            "1",
            "--model",
            "none",
        ]
    )
    assert first_exit == 0

    project_dir = tmp_path / "spec_preserve_demo"
    spec_path = project_dir / ".archmind" / "project_spec.json"
    first = json.loads(spec_path.read_text(encoding="utf-8"))
    assert len(first.get("entities") or []) >= 1

    monkeypatch.setattr("archmind.pipeline.suggest_project_spec", lambda *_a, **_k: {})
    second_exit = main(
        [
            "pipeline",
            "--idea",
            "diary app",
            "--out",
            str(tmp_path),
            "--name",
            "spec_preserve_demo",
            "--max-iterations",
            "1",
            "--model",
            "none",
        ]
    )
    assert second_exit == 0

    second = json.loads(spec_path.read_text(encoding="utf-8"))
    assert len(second.get("entities") or []) >= 1
    assert len(second.get("api_endpoints") or []) >= 1
    assert len(second.get("frontend_pages") or []) >= 1


def test_pipeline_cli_type_keeps_fallback_metadata(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr("archmind.pipeline._resolve_generator_entry", lambda: _fake_generate_project)

    exit_code = main(
        [
            "pipeline",
            "--idea",
            "python cli tool for csv merge",
            "--out",
            str(tmp_path),
            "--name",
            "cli_routing_demo",
            "--backend-only",
            "--max-iterations",
            "1",
            "--model",
            "none",
        ]
    )
    assert exit_code == 0

    project_dir = tmp_path / "cli_routing_demo"
    result_payload = json.loads((project_dir / ".archmind" / "result.json").read_text(encoding="utf-8"))
    assert result_payload.get("project_type") == "cli-tool"
    assert result_payload.get("selected_template") == "cli"
    assert result_payload.get("effective_template") == "fastapi"
    assert "template not supported" in str(result_payload.get("template_fallback_reason") or "")


def test_pipeline_path_runs_backend_only(tmp_path: Path) -> None:
    _write_backend_project(tmp_path)

    exit_code = main(
        [
            "pipeline",
            "--path",
            str(tmp_path),
            "--backend-only",
            "--max-iterations",
            "1",
            "--model",
            "none",
        ]
    )
    assert exit_code == 0

    log_dir = tmp_path / ".archmind" / "run_logs"
    assert (tmp_path / ".archmind" / "plan.md").exists()
    assert (tmp_path / ".archmind" / "plan.json").exists()
    assert (tmp_path / ".archmind" / "tasks.json").exists()
    result_payload = json.loads((tmp_path / ".archmind" / "result.json").read_text(encoding="utf-8"))
    assert "current_task" in result_payload
    assert list(log_dir.glob("run_*.summary.txt"))


def test_pipeline_failure_creates_prompt_and_summary(tmp_path: Path) -> None:
    _write_backend_fail_project(tmp_path)

    exit_code = main(
        [
            "pipeline",
            "--path",
            str(tmp_path),
            "--backend-only",
            "--max-iterations",
            "1",
            "--model",
            "none",
        ]
    )
    assert exit_code != 0

    log_dir = tmp_path / ".archmind" / "run_logs"
    assert list(log_dir.glob("run_*.summary.txt"))
    prompts = list(log_dir.glob("fix_*.prompt.md"))
    assert prompts
    prompt_text = prompts[-1].read_text(encoding="utf-8")
    assert "Plan 요약" in prompt_text


def test_pipeline_frontend_only_skips_backend(tmp_path: Path) -> None:
    tmp_path.joinpath("pytest.ini").write_text("[pytest]\naddopts = -q\n", encoding="utf-8")

    exit_code = main(
        [
            "pipeline",
            "--path",
            str(tmp_path),
            "--frontend-only",
            "--max-iterations",
            "1",
            "--model",
            "none",
        ]
    )
    assert exit_code == 0

    log_dir = tmp_path / ".archmind" / "run_logs"
    summaries = sorted(log_dir.glob("run_*.summary.txt"))
    assert summaries, "Expected run summary to be created"
    summary_text = summaries[-1].read_text(encoding="utf-8")
    assert "Backend:" in summary_text
    assert "backend not requested" in summary_text


def test_pipeline_backend_only_skips_frontend_in_subprocess(tmp_path: Path) -> None:
    _write_backend_project(tmp_path)
    repo_root = Path(__file__).resolve().parents[1]

    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "archmind.cli",
            "pipeline",
            "--path",
            str(tmp_path),
            "--backend-only",
            "--max-iterations",
            "1",
            "--model",
            "none",
        ],
        cwd=repo_root,
        capture_output=True,
        text=True,
        timeout=120,
    )
    assert result.returncode == 0, result.stderr

    log_dir = tmp_path / ".archmind" / "run_logs"
    summaries = sorted(log_dir.glob("run_*.summary.txt"))
    assert summaries, "Expected run summary to be created"
    summary_text = summaries[-1].read_text(encoding="utf-8")
    assert "Frontend:" in summary_text
    assert "frontend not requested" in summary_text


def test_pipeline_auto_deploy_local_calls_deploy(monkeypatch, tmp_path: Path) -> None:
    _write_backend_project(tmp_path)
    captured: dict[str, object] = {}

    def fake_deploy(project_dir, target="railway", allow_real_deploy=False):  # type: ignore[no-untyped-def]
        captured["project_dir"] = project_dir
        captured["target"] = target
        captured["allow_real_deploy"] = allow_real_deploy
        return {
            "ok": True,
            "target": "local",
            "mode": "real",
            "kind": "backend",
            "status": "SUCCESS",
            "url": "http://127.0.0.1:8011",
            "detail": "local backend started",
            "backend_smoke_url": "http://127.0.0.1:8011/health",
            "backend_smoke_status": "SUCCESS",
            "backend_smoke_detail": "health endpoint returned status ok",
            "frontend_smoke_url": "",
            "frontend_smoke_status": "SKIPPED",
            "frontend_smoke_detail": "frontend not deployed",
        }

    monkeypatch.setattr("archmind.pipeline.deploy_project", fake_deploy)

    exit_code = main(
        [
            "pipeline",
            "--path",
            str(tmp_path),
            "--backend-only",
            "--max-iterations",
            "1",
            "--model",
            "none",
            "--auto-deploy",
            "--deploy-target",
            "local",
        ]
    )
    assert exit_code == 0
    assert captured["project_dir"] == tmp_path.resolve()
    assert captured["target"] == "local"
    assert captured["allow_real_deploy"] is True

    result_payload = json.loads((tmp_path / ".archmind" / "result.json").read_text(encoding="utf-8"))
    assert result_payload.get("auto_deploy_enabled") is True
    assert result_payload.get("auto_deploy_target") == "local"
    assert result_payload.get("auto_deploy_status") == "SUCCESS"


def test_pipeline_auto_deploy_fail_does_not_fail_pipeline(monkeypatch, tmp_path: Path) -> None:
    _write_backend_project(tmp_path)

    monkeypatch.setattr(
        "archmind.pipeline.deploy_project",
        lambda *a, **k: {
            "ok": False,
            "target": "local",
            "mode": "real",
            "kind": "backend",
            "status": "FAIL",
            "url": None,
            "detail": "local backend start failed",
            "backend_smoke_url": "",
            "backend_smoke_status": "SKIPPED",
            "backend_smoke_detail": "deploy failed before smoke check",
            "frontend_smoke_url": "",
            "frontend_smoke_status": "SKIPPED",
            "frontend_smoke_detail": "frontend not deployed",
        },
    )

    exit_code = main(
        [
            "pipeline",
            "--path",
            str(tmp_path),
            "--backend-only",
            "--max-iterations",
            "1",
            "--model",
            "none",
            "--auto-deploy",
        ]
    )
    assert exit_code == 0

    result_payload = json.loads((tmp_path / ".archmind" / "result.json").read_text(encoding="utf-8"))
    assert result_payload.get("status") == "SUCCESS"
    assert result_payload.get("auto_deploy_status") == "FAIL"


def test_pipeline_repo_attempted_even_when_runtime_not_done(monkeypatch, tmp_path: Path) -> None:
    calls = {"n": 0}

    def fake_generate_fail_run(_idea: str, opt) -> Path:  # type: ignore[no-untyped-def]
        project_name = (opt.name or "archmind_project").strip() or "archmind_project"
        project_dir = Path(opt.out) / project_name
        project_dir.mkdir(parents=True, exist_ok=True)
        project_dir.joinpath("pytest.ini").write_text("[pytest]\naddopts = -q\n", encoding="utf-8")
        project_dir.joinpath("test_fail.py").write_text("def test_fail():\n    assert False\n", encoding="utf-8")
        return project_dir

    def fake_repo_create(_project_dir, enabled=True):  # type: ignore[no-untyped-def]
        calls["n"] += 1
        return {
            "status": "CREATED",
            "url": "https://github.com/siriusnen-commits/repo_attempted",
            "name": "repo_attempted",
            "reason": "",
            "attempted": True,
        }

    monkeypatch.setattr("archmind.pipeline._resolve_generator_entry", lambda: fake_generate_fail_run)
    monkeypatch.setattr("archmind.pipeline.create_github_repo_with_status", fake_repo_create)
    exit_code = main(
        [
            "pipeline",
            "--idea",
            "failing notes api",
            "--out",
            str(tmp_path),
            "--name",
            "repo_attempted",
            "--backend-only",
            "--max-iterations",
            "1",
            "--model",
            "none",
        ]
    )
    assert exit_code != 0
    assert calls["n"] == 1


def test_pipeline_repo_created_status_is_persisted(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr("archmind.pipeline._resolve_generator_entry", lambda: _fake_generate_project)
    monkeypatch.setattr(
        "archmind.pipeline.create_github_repo_with_status",
        lambda _project_dir, enabled=True: {  # noqa: ARG001
            "status": "CREATED",
            "url": "https://github.com/siriusnen-commits/repo_created",
            "name": "repo_created",
            "reason": "",
            "attempted": True,
        },
    )
    exit_code = main(
        [
            "pipeline",
            "--idea",
            "simple fastapi notes api",
            "--out",
            str(tmp_path),
            "--name",
            "repo_created",
            "--backend-only",
            "--max-iterations",
            "1",
            "--model",
            "none",
        ]
    )
    assert exit_code == 0
    state_payload = json.loads((tmp_path / "repo_created" / ".archmind" / "state.json").read_text(encoding="utf-8"))
    assert (state_payload.get("repository") or {}).get("status") == "CREATED"
    assert (state_payload.get("repository") or {}).get("url") == "https://github.com/siriusnen-commits/repo_created"


def test_pipeline_repo_failed_reason_is_persisted(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr("archmind.pipeline._resolve_generator_entry", lambda: _fake_generate_project)
    monkeypatch.setattr(
        "archmind.pipeline.create_github_repo_with_status",
        lambda _project_dir, enabled=True: {  # noqa: ARG001
            "status": "FAILED",
            "url": "",
            "name": "repo_failed",
            "reason": "gh auth missing",
            "attempted": True,
        },
    )
    exit_code = main(
        [
            "pipeline",
            "--idea",
            "simple fastapi notes api",
            "--out",
            str(tmp_path),
            "--name",
            "repo_failed",
            "--backend-only",
            "--max-iterations",
            "1",
            "--model",
            "none",
        ]
    )
    assert exit_code == 0
    result_payload = json.loads((tmp_path / "repo_failed" / ".archmind" / "result.json").read_text(encoding="utf-8"))
    assert (result_payload.get("repository") or {}).get("status") == "FAILED"
    assert "gh auth missing" in str((result_payload.get("repository") or {}).get("reason") or "")


def test_pipeline_generation_failure_marks_repository_skipped(monkeypatch, tmp_path: Path) -> None:
    def fake_invalid_fullstack(_idea: str, opt) -> Path:  # type: ignore[no-untyped-def]
        project_name = (opt.name or "archmind_project").strip() or "archmind_project"
        project_dir = Path(opt.out) / project_name
        project_dir.mkdir(parents=True, exist_ok=True)
        (project_dir / "frontend").mkdir(parents=True, exist_ok=True)
        return project_dir

    monkeypatch.setattr("archmind.pipeline._resolve_generator_entry", lambda: fake_invalid_fullstack)
    exit_code = main(
        [
            "pipeline",
            "--idea",
            "blog webapp",
            "--template",
            "fullstack-ddd",
            "--out",
            str(tmp_path),
            "--name",
            "repo_skipped_generation_fail",
            "--backend-only",
            "--max-iterations",
            "1",
            "--model",
            "none",
        ]
    )
    assert exit_code == 1
    result_payload = json.loads((tmp_path / "repo_skipped_generation_fail" / ".archmind" / "result.json").read_text(encoding="utf-8"))
    repository = result_payload.get("repository") or {}
    assert repository.get("status") == "SKIPPED"


def test_pipeline_path_preserves_existing_repository_metadata(monkeypatch, tmp_path: Path) -> None:
    project_dir = tmp_path / "continue_repo_preserve"
    project_dir.mkdir(parents=True, exist_ok=True)
    _write_backend_project(project_dir)
    write_state(
        project_dir,
        {
            "repository": {
                "status": "CREATED",
                "repo_status": "CREATED",
                "url": "https://github.com/siriusnen-commits/continue_repo_preserve",
                "repo_url": "https://github.com/siriusnen-commits/continue_repo_preserve",
                "attempted": True,
            },
            "github_repo_url": "https://github.com/siriusnen-commits/continue_repo_preserve",
        },
    )

    # non-idea pipeline run (/continue-like) must not downgrade persisted repository existence.
    exit_code = main(
        [
            "pipeline",
            "--path",
            str(project_dir),
            "--backend-only",
            "--max-iterations",
            "1",
            "--model",
            "none",
        ]
    )
    assert exit_code in (0, 1)

    state_payload = json.loads((project_dir / ".archmind" / "state.json").read_text(encoding="utf-8"))
    repository = state_payload.get("repository") or {}
    assert repository.get("url") == "https://github.com/siriusnen-commits/continue_repo_preserve"
    assert repository.get("status") in {"CREATED", "EXISTS"}
    assert repository.get("status") not in {"NONE", "SKIPPED"}
    assert state_payload.get("github_repo_url") == "https://github.com/siriusnen-commits/continue_repo_preserve"

    result_payload = json.loads((project_dir / ".archmind" / "result.json").read_text(encoding="utf-8"))
    result_repository = result_payload.get("repository") or {}
    assert result_repository.get("url") == "https://github.com/siriusnen-commits/continue_repo_preserve"
    assert result_repository.get("status") in {"CREATED", "EXISTS"}


def test_pipeline_final_status_done_when_detect_ok_and_no_failure(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr("archmind.pipeline._resolve_generator_entry", lambda: _fake_generate_project)
    monkeypatch.setattr(
        "archmind.pipeline.create_github_repo_with_status",
        lambda _project_dir, enabled=True: {"status": "FAILED", "url": "", "name": "x", "reason": "gh auth missing", "attempted": True},
    )
    monkeypatch.setattr(
        "archmind.pipeline.detect_backend_runtime_entry_shared",
        lambda _project_dir, port=8000: {"ok": True, "backend_entry": "app.main:app"},
    )
    exit_code = main(
        [
            "pipeline",
            "--idea",
            "simple fastapi notes api",
            "--out",
            str(tmp_path),
            "--name",
            "final_status_done",
            "--backend-only",
            "--max-iterations",
            "1",
            "--model",
            "none",
        ]
    )
    assert exit_code == 0
    result_payload = json.loads((tmp_path / "final_status_done" / ".archmind" / "result.json").read_text(encoding="utf-8"))
    assert result_payload.get("final_status") == "DONE"


def test_pipeline_final_status_not_done_when_detect_fails(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr("archmind.pipeline._resolve_generator_entry", lambda: _fake_generate_project)
    monkeypatch.setattr(
        "archmind.pipeline.create_github_repo_with_status",
        lambda _project_dir, enabled=True: {"status": "CREATED", "url": "https://github.com/siriusnen-commits/detect_fail", "name": "detect_fail", "reason": "", "attempted": True},
    )
    monkeypatch.setattr(
        "archmind.pipeline.detect_backend_runtime_entry_shared",
        lambda _project_dir, port=8000: {"ok": False, "failure_class": "generation-error"},
    )
    exit_code = main(
        [
            "pipeline",
            "--idea",
            "simple fastapi notes api",
            "--out",
            str(tmp_path),
            "--name",
            "final_status_not_done",
            "--backend-only",
            "--max-iterations",
            "1",
            "--model",
            "none",
        ]
    )
    assert exit_code == 0
    result_payload = json.loads((tmp_path / "final_status_not_done" / ".archmind" / "result.json").read_text(encoding="utf-8"))
    assert result_payload.get("final_status") == "NOT_DONE"
    repository = result_payload.get("repository") or {}
    assert repository.get("status") == "CREATED"


def test_pipeline_auto_deploy_skipped_only_does_not_make_not_done(monkeypatch, tmp_path: Path) -> None:
    _write_backend_project(tmp_path)
    monkeypatch.setattr(
        "archmind.pipeline.detect_backend_runtime_entry_shared",
        lambda _project_dir, port=8000: {"ok": True, "backend_entry": "app.main:app"},
    )
    exit_code = main(
        [
            "pipeline",
            "--path",
            str(tmp_path),
            "--backend-only",
            "--max-iterations",
            "1",
            "--model",
            "none",
            "--auto-deploy",
            "--deploy-target",
            "railway",
        ]
    )
    assert exit_code == 0
    result_payload = json.loads((tmp_path / ".archmind" / "result.json").read_text(encoding="utf-8"))
    assert result_payload.get("auto_deploy_status") == "SKIPPED"
    assert result_payload.get("final_status") == "DONE"
