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
    assert out["suggestions"][0]["command"] == "/add_page notes/list"


def test_project_analysis_treats_page_with_real_flow_signals_as_usable(tmp_path: Path) -> None:
    project_dir = tmp_path / "memo-usable-app"
    spec = {
        "entities": [{"name": "Note", "fields": [{"name": "title", "type": "string"}]}],
        "api_endpoints": ["GET /notes", "POST /notes", "GET /notes/{note_id}"],
        "frontend_pages": ["notes/list"],
    }
    _write(
        project_dir / "frontend" / "app" / "notes" / "page.tsx",
        """
export default function NotesPage() {
  // TODO: polish copy later
  async function loadNotes() { return await fetch("/api/notes"); }
  const items = [{ id: "1", title: "hello" }];
  return <ul>{items.map((item) => <li key={item.id}>{item.title}</li>)}</ul>;
}
""",
    )
    out = analyze_project(project_dir, spec_payload=spec, runtime_payload={})
    assert "notes/list" not in out["placeholder_pages"]
    assert all(s.get("kind") != "placeholder_page" for s in out["suggestions"])


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


def test_project_analysis_uses_model_field_inference_to_avoid_false_missing_title(tmp_path: Path) -> None:
    project_dir = tmp_path / "memo-field-inference"
    spec = {
        "entities": [{"name": "Note", "fields": []}],
        "api_endpoints": ["GET /notes", "POST /notes"],
        "frontend_pages": ["notes/list"],
    }
    _write(
        project_dir / "backend" / "app" / "models" / "note.py",
        """
class NoteBase:
    title: str
    content: str
""",
    )

    out = analyze_project(project_dir, spec_payload=spec, runtime_payload={})
    missing_fields = out["entity_crud_status"]["Note"]["missing_important_fields"]
    assert "title" not in missing_fields
    assert any(f.get("name") == "title" for f in out["fields_by_entity"]["Note"])


def test_project_analysis_backend_first_uses_class_variants_for_entity_matching(tmp_path: Path) -> None:
    project_dir = tmp_path / "memo-backend-class-variants"
    spec = {
        "entities": [{"name": "Note", "fields": []}],
        "api_endpoints": ["GET /notes", "POST /notes"],
        "frontend_pages": ["notes/list"],
    }
    _write(
        project_dir / "backend" / "app" / "schemas" / "note.py",
        """
class NoteSchema:
    title: str
    content: str

class NoteModel:
    created_at: str
""",
    )
    out = analyze_project(project_dir, spec_payload=spec, runtime_payload={})
    names = {str(f.get("name")) for f in out["fields_by_entity"]["Note"]}
    assert "title" in names
    assert "created_at" in names
    assert not any("Note is missing an important field: title" in str(s.get("message")) for s in out["suggestions"])


def test_project_analysis_backend_first_can_still_report_real_missing_title(tmp_path: Path) -> None:
    project_dir = tmp_path / "memo-backend-missing-title"
    spec = {
        "entities": [{"name": "Note", "fields": [{"name": "title", "type": "string"}]}],
        "api_endpoints": ["GET /notes", "POST /notes"],
        "frontend_pages": ["notes/list"],
    }
    _write(
        project_dir / "backend" / "app" / "models" / "note.py",
        """
class NoteModel:
    content: str
""",
    )
    out = analyze_project(project_dir, spec_payload=spec, runtime_payload={})
    missing = out["entity_crud_status"]["Note"]["missing_important_fields"]
    assert "title" in missing
    assert any("Note is missing an important field: title" in str(s.get("message")) for s in out["suggestions"])


def test_project_analysis_limits_missing_field_suggestions_to_reduce_repetition(tmp_path: Path) -> None:
    project_dir = tmp_path / "multi-entity-app"
    spec = {
        "entities": [{"name": "Note", "fields": []}, {"name": "Task", "fields": []}],
        "api_endpoints": ["GET /notes", "POST /notes", "GET /tasks", "POST /tasks"],
        "frontend_pages": ["notes/list", "tasks/list"],
    }
    out = analyze_project(project_dir, spec_payload=spec, runtime_payload={})
    missing_field_rows = [row for row in out["suggestions"] if row.get("kind") == "missing_field"]
    assert len(missing_field_rows) <= 1


def test_project_analysis_does_not_suggest_created_at_as_important_field(tmp_path: Path) -> None:
    project_dir = tmp_path / "created-at-low-priority"
    spec = {
        "entities": [{"name": "Note", "fields": [{"name": "title", "type": "string"}]}],
        "api_endpoints": ["GET /notes", "POST /notes"],
        "frontend_pages": ["notes/list"],
    }
    out = analyze_project(project_dir, spec_payload=spec, runtime_payload={})
    missing_fields = out["entity_crud_status"]["Note"]["missing_important_fields"]
    assert "created_at" not in missing_fields
    assert not any(
        "important field: created_at" in str(item.get("message") or "")
        for item in out["suggestions"]
    )


def test_project_analysis_still_suggests_high_priority_missing_title(tmp_path: Path) -> None:
    project_dir = tmp_path / "title-high-priority-backend-missing"
    spec = {
        "entities": [{"name": "Note", "fields": []}],
        "api_endpoints": ["GET /notes", "POST /notes"],
        "frontend_pages": ["notes/list"],
    }
    _write(
        project_dir / "backend" / "app" / "models" / "note.py",
        """
class NoteModel:
    content: str
""",
    )
    out = analyze_project(project_dir, spec_payload=spec, runtime_payload={})
    assert "title" in out["entity_crud_status"]["Note"]["missing_important_fields"]
    assert any(
        "important field: title" in str(item.get("message") or "")
        for item in out["suggestions"]
    )


def test_project_analysis_canonicalizes_noncanonical_page_path_in_suggestions(tmp_path: Path) -> None:
    project_dir = tmp_path / "task-placeholder-app"
    spec = {
        "entities": [{"name": "Task", "fields": [{"name": "title", "type": "string"}]}],
        "api_endpoints": ["GET /task", "POST /task"],
        "frontend_pages": ["task/lists"],
    }
    _write(
        project_dir / "frontend" / "app" / "tasks" / "page.tsx",
        "export default function Page() { return <p>TODO placeholder list</p>; }",
    )

    out = analyze_project(project_dir, spec_payload=spec, runtime_payload={})
    assert out["pages"] == ["tasks/list"]
    assert out["suggestions"][0]["command"] == "/add_page tasks/list"
    assert "task/lists" not in out["suggestions"][0]["command"]


def test_project_analysis_note_template_does_not_suggest_missing_title_when_present(tmp_path: Path) -> None:
    project_dir = tmp_path / "memo-note-app"
    spec = {
        "entities": [{"name": "Note", "fields": [{"name": "title", "type": "string"}, {"name": "content", "type": "string"}]}],
        "api_endpoints": [
            "GET /notes",
            "POST /notes",
            "GET /notes/{id}",
            "PUT /notes/{id}",
            "DELETE /notes/{id}",
        ],
        "frontend_pages": ["notes/list", "notes/detail"],
    }
    _write(project_dir / "frontend" / "app" / "notes" / "page.tsx", "export default function Page() { return <div>ok</div>; }")
    _write(project_dir / "frontend" / "app" / "notes" / "[id]" / "page.tsx", "export default function Page() { return <div>ok</div>; }")
    out = analyze_project(project_dir, spec_payload=spec, runtime_payload={})
    assert "title" not in out["entity_crud_status"]["Note"]["missing_important_fields"]
    assert not any("Note is missing an important field: title" in str(s.get("message")) for s in out["suggestions"])


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
