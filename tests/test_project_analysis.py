from __future__ import annotations

from pathlib import Path

from archmind.project_analysis import analyze_project


def _write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def test_project_analysis_extracts_entities_fields_apis_pages_and_crud(tmp_path: Path) -> None:
    project_dir = tmp_path / "memo-app"
    spec = {
        "entities": [
            {
                "name": "Task",
                "fields": [
                    {"name": "title", "type": "string"},
                    {"name": "created_at", "type": "datetime"},
                ],
            }
        ],
        "api_endpoints": [
            "GET /tasks",
            "POST /tasks",
            "GET /tasks/{task_id}",
            "PUT /tasks/{task_id}",
            "DELETE /tasks/{task_id}",
        ],
        "frontend_pages": ["tasks/list", "tasks/detail"],
    }
    _write(project_dir / "frontend" / "app" / "tasks" / "page.tsx", "export default function Page() { return <div>ok</div>; }")
    _write(project_dir / "frontend" / "app" / "tasks" / "[id]" / "page.tsx", "export default function Page() { return <div>ok</div>; }")
    _write(
        project_dir / "frontend" / "app" / "_lib" / "navigation.ts",
        'export const navigationItems = [{ href: "/tasks/list", label: "Tasks" }];\n',
    )

    out = analyze_project(
        project_dir,
        project_name="memo-app",
        spec_payload=spec,
        runtime_payload={"backend": {"status": "RUNNING", "url": "http://127.0.0.1:61080"}},
    )

    assert out["project_name"] == "memo-app"
    assert out["entities"] == ["Task"]
    assert out["fields_by_entity"]["Task"][0]["name"] == "title"
    assert any(item["method"] == "GET" and item["path"] == "/tasks" for item in out["apis"])
    assert "tasks/list" in out["pages"]
    assert out["entity_crud_status"]["Task"]["api"]["delete"] is True
    assert out["entity_crud_status"]["Task"]["pages"]["detail"] is True
    assert out["placeholder_pages"] == []
    assert "tasks/list" in out["nav_visible_pages"]
    assert out["runtime_status"]["backend_status"] == "RUNNING"


def test_project_analysis_detects_placeholder_pages_and_suggestions_priority(tmp_path: Path) -> None:
    project_dir = tmp_path / "placeholder-app"
    spec = {
        "entities": [{"name": "Note", "fields": [{"name": "title", "type": "string"}]}],
        "api_endpoints": ["GET /notes", "POST /notes"],
        "frontend_pages": ["notes/list", "notes/detail"],
    }
    _write(
        project_dir / "frontend" / "app" / "notes" / "page.tsx",
        "export default function Page() { return <p>Page placeholder for notes/list</p>; }",
    )

    out = analyze_project(project_dir, spec_payload=spec, runtime_payload={})

    assert "notes/list" in out["placeholder_pages"]
    assert len(out["suggestions"]) >= 1
    assert out["suggestions"][0]["kind"] == "placeholder_page"
    assert out["next_action"]["kind"] == "placeholder_page"


def test_project_analysis_next_action_prioritizes_missing_crud_then_pages_then_fields(tmp_path: Path) -> None:
    project_dir = tmp_path / "priority-app"
    spec = {
        "entities": [{"name": "Reminder", "fields": []}],
        "api_endpoints": ["GET /reminders"],
        "frontend_pages": [],
    }

    out = analyze_project(project_dir, spec_payload=spec, runtime_payload={})

    assert out["next_action"]["kind"] == "missing_crud_api"
    assert "create API" in out["next_action"]["message"] or "CRUD API" in out["next_action"]["message"]


def test_project_analysis_safe_with_missing_or_malformed_data(tmp_path: Path) -> None:
    project_dir = tmp_path / "broken-app"
    spec = {
        "entities": [None, {"name": "", "fields": ["x"]}, {"name": "Task", "fields": [{"name": "", "type": "string"}]}],
        "api_endpoints": [None, "INVALID", "GET"],
        "frontend_pages": [None, "", " bad path "],
    }

    out = analyze_project(project_dir, spec_payload=spec, runtime_payload=None)

    assert out["project_name"] == "broken-app"
    assert out["entities"] == ["Task"]
    assert out["fields_by_entity"]["Task"] == []
    assert out["apis"] == []
    assert out["pages"] == []
    assert out["runtime_status"]["backend_status"] == "STOPPED"
    assert out["next_action"]["kind"] in {"missing_crud_api", "none", "missing_page", "missing_field"}
