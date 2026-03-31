from __future__ import annotations

import json
from pathlib import Path
from urllib.parse import quote

from fastapi.testclient import TestClient

import archmind.current_project as current_project_state
from archmind.execution_history import append_execution_event
from archmind.state import write_state
from archmind.telegram_bot import clear_current_project, get_validated_current_project, set_current_project
from archmind.ui_api import create_ui_app


def _make_project(
    base: Path,
    name: str,
    *,
    provider_mode: str = "local",
    with_evolution: bool = True,
    display_name: str = "",
    repository: dict[str, str] | None = None,
) -> Path:
    project_dir = base / name
    archmind_dir = project_dir / ".archmind"
    archmind_dir.mkdir(parents=True, exist_ok=True)
    project_display_name = display_name.strip() or name
    write_state(
        project_dir,
        {
            "project_name": project_display_name,
            "effective_template": "fullstack-ddd",
            "architecture_app_shape": "fullstack",
            "provider": {"mode": provider_mode},
            "runtime": {
                "services": {
                    "backend": {"status": "STOPPED", "url": "http://127.0.0.1:8000"},
                    "frontend": {"status": "STOPPED", "url": "http://127.0.0.1:3000"},
                }
            },
            "repository": repository if isinstance(repository, dict) else {"status": "CREATED", "url": f"https://github.com/example/{name}"},
        },
    )
    spec = {
        "project_name": project_display_name,
        "shape": "fullstack",
        "template": "fullstack-ddd",
        "entities": [{"name": "Note", "fields": [{"name": "title", "type": "string"}]}],
        "api_endpoints": ["GET /notes"],
        "frontend_pages": ["notes/list"],
        "evolution": {"version": 1, "history": []},
    }
    if with_evolution:
        spec["evolution"]["history"] = [{"action": "add_entity", "entity": "Note"}]
    (archmind_dir / "project_spec.json").write_text(json.dumps(spec), encoding="utf-8")
    return project_dir


def test_ui_projects_response_shape(monkeypatch, tmp_path: Path) -> None:
    projects_root = tmp_path / "projects"
    _make_project(projects_root, "alpha")
    monkeypatch.setenv("ARCHMIND_PROJECTS_DIR", str(projects_root))
    client = TestClient(create_ui_app())

    response = client.get("/ui/projects")
    assert response.status_code == 200
    payload = response.json()
    assert "projects" in payload
    assert isinstance(payload["projects"], list)
    item = payload["projects"][0]
    for key in (
        "name",
        "display_name",
        "path",
        "status",
        "runtime",
        "runtime_state",
        "type",
        "template",
        "backend_url",
        "frontend_url",
        "backend_urls",
        "frontend_urls",
        "repository",
        "project_health_status",
        "is_current",
        "warning",
    ):
        assert key in item
    assert item["display_name"] == "alpha"
    assert item["status"] in {"RUNNING", "STOPPED", "FAIL"}
    assert item["runtime_state"] in {"RUNNING", "NOT_RUNNING", "FAIL"}
    assert item["backend_url"] == ""
    assert item["frontend_url"] == ""
    assert isinstance(item["backend_urls"], list)
    assert isinstance(item["frontend_urls"], list)
    assert item["project_health_status"] in {"RUNNING", "BROKEN", "NEEDS FIX", "IDLE"}
    assert item["repository"]["status"] == "CREATED"
    assert item["repository"]["url"] == "https://github.com/example/alpha"


def test_ui_projects_marks_current_project(monkeypatch, tmp_path: Path) -> None:
    projects_root = tmp_path / "projects"
    alpha = _make_project(projects_root, "alpha")
    _make_project(projects_root, "beta")
    monkeypatch.setenv("ARCHMIND_PROJECTS_DIR", str(projects_root))
    set_current_project(alpha)
    client = TestClient(create_ui_app())
    try:
        response = client.get("/ui/projects")
        assert response.status_code == 200
        payload = response.json()
        rows = {item["name"]: item for item in payload["projects"]}
        assert rows["alpha"]["is_current"] is True
        assert rows["beta"]["is_current"] is False
    finally:
        clear_current_project()


def test_ui_projects_reflects_persisted_current_project_when_in_memory_is_missing(monkeypatch, tmp_path: Path) -> None:
    projects_root = tmp_path / "projects"
    _make_project(projects_root, "alpha")
    beta = _make_project(projects_root, "beta")
    monkeypatch.setenv("ARCHMIND_PROJECTS_DIR", str(projects_root))
    monkeypatch.setattr("archmind.project_query.get_validated_current_project", lambda: beta)

    client = TestClient(create_ui_app())
    response = client.get("/ui/projects")
    assert response.status_code == 200
    rows = {item["name"]: item for item in response.json()["projects"]}
    assert rows["beta"]["is_current"] is True
    assert rows["alpha"]["is_current"] is False


def test_ui_projects_rejects_stale_persisted_current_project(monkeypatch, tmp_path: Path) -> None:
    projects_root = tmp_path / "projects"
    _make_project(projects_root, "alpha")
    _make_project(projects_root, "gamma")
    monkeypatch.setenv("ARCHMIND_PROJECTS_DIR", str(projects_root))
    monkeypatch.setattr("archmind.project_query.get_validated_current_project", lambda: None)

    client = TestClient(create_ui_app())
    response = client.get("/ui/projects")
    assert response.status_code == 200
    rows = response.json()["projects"]
    assert all(bool(item["is_current"]) is False for item in rows)


def test_ui_projects_show_distinct_runtime_frontend_urls_per_project(monkeypatch, tmp_path: Path) -> None:
    projects_root = tmp_path / "projects"
    _make_project(projects_root, "alpha")
    _make_project(projects_root, "beta")
    monkeypatch.setenv("ARCHMIND_PROJECTS_DIR", str(projects_root))

    def fake_runtime(project_dir: Path):  # type: ignore[no-untyped-def]
        if project_dir.name == "alpha":
            return {
                "backend": {"status": "RUNNING", "url": "http://127.0.0.1:61080"},
                "frontend": {"status": "RUNNING", "url": "http://127.0.0.1:5173"},
            }
        return {
            "backend": {"status": "RUNNING", "url": "http://127.0.0.1:62080"},
            "frontend": {"status": "RUNNING", "url": "http://127.0.0.1:5280"},
        }

    monkeypatch.setattr("archmind.project_query.get_local_runtime_status", fake_runtime)
    client = TestClient(create_ui_app())
    response = client.get("/ui/projects")
    assert response.status_code == 200
    rows = {item["name"]: item for item in response.json()["projects"]}
    assert rows["alpha"]["frontend_url"] == "http://127.0.0.1:5173"
    assert rows["beta"]["frontend_url"] == "http://127.0.0.1:5280"
    assert rows["alpha"]["frontend_url"] != rows["beta"]["frontend_url"]


def test_ui_projects_status_badge_running(monkeypatch, tmp_path: Path) -> None:
    projects_root = tmp_path / "projects"
    _make_project(projects_root, "running-badge")
    monkeypatch.setenv("ARCHMIND_PROJECTS_DIR", str(projects_root))

    def fake_runtime(_project_dir: Path):  # type: ignore[no-untyped-def]
        return {
            "backend": {"status": "RUNNING", "url": "http://127.0.0.1:7100"},
            "frontend": {"status": "NOT RUNNING", "url": ""},
        }

    monkeypatch.setattr("archmind.project_query.get_local_runtime_status", fake_runtime)
    client = TestClient(create_ui_app())
    payload = client.get("/ui/projects").json()
    rows = {item["name"]: item for item in payload["projects"]}
    assert rows["running-badge"]["project_health_status"] == "RUNNING"


def test_ui_projects_status_badge_broken_for_unresolved_failure(monkeypatch, tmp_path: Path) -> None:
    projects_root = tmp_path / "projects"
    project_dir = _make_project(projects_root, "broken-badge")
    monkeypatch.setenv("ARCHMIND_PROJECTS_DIR", str(projects_root))
    state_payload = json.loads((project_dir / ".archmind" / "state.json").read_text(encoding="utf-8"))
    state_payload["agent_state"] = "NOT_DONE"
    state_payload["runtime_failure_class"] = "runtime-entrypoint-error"
    state_payload["last_failure_class"] = "runtime-entrypoint-error"
    write_state(project_dir, state_payload)

    def fake_runtime(_project_dir: Path):  # type: ignore[no-untyped-def]
        return {
            "backend": {"status": "NOT RUNNING", "url": ""},
            "frontend": {"status": "NOT RUNNING", "url": ""},
        }

    monkeypatch.setattr("archmind.project_query.get_local_runtime_status", fake_runtime)
    client = TestClient(create_ui_app())
    payload = client.get("/ui/projects").json()
    rows = {item["name"]: item for item in payload["projects"]}
    assert rows["broken-badge"]["project_health_status"] == "BROKEN"


def test_ui_projects_status_badge_needs_fix_for_not_done_without_failure_class(monkeypatch, tmp_path: Path) -> None:
    projects_root = tmp_path / "projects"
    project_dir = _make_project(projects_root, "needs-fix-badge")
    monkeypatch.setenv("ARCHMIND_PROJECTS_DIR", str(projects_root))
    state_payload = json.loads((project_dir / ".archmind" / "state.json").read_text(encoding="utf-8"))
    state_payload["agent_state"] = "NOT_DONE"
    state_payload["runtime_failure_class"] = ""
    state_payload["last_failure_class"] = ""
    write_state(project_dir, state_payload)

    def fake_runtime(_project_dir: Path):  # type: ignore[no-untyped-def]
        return {
            "backend": {"status": "NOT RUNNING", "url": ""},
            "frontend": {"status": "NOT RUNNING", "url": ""},
        }

    monkeypatch.setattr("archmind.project_query.get_local_runtime_status", fake_runtime)
    client = TestClient(create_ui_app())
    payload = client.get("/ui/projects").json()
    rows = {item["name"]: item for item in payload["projects"]}
    assert rows["needs-fix-badge"]["project_health_status"] == "NEEDS FIX"


def test_ui_projects_status_badge_idle_for_inactive_non_failure_project(monkeypatch, tmp_path: Path) -> None:
    projects_root = tmp_path / "projects"
    _make_project(projects_root, "idle-badge")
    monkeypatch.setenv("ARCHMIND_PROJECTS_DIR", str(projects_root))

    def fake_runtime(_project_dir: Path):  # type: ignore[no-untyped-def]
        return {
            "backend": {"status": "NOT RUNNING", "url": ""},
            "frontend": {"status": "NOT RUNNING", "url": ""},
        }

    monkeypatch.setattr("archmind.project_query.get_local_runtime_status", fake_runtime)
    client = TestClient(create_ui_app())
    payload = client.get("/ui/projects").json()
    rows = {item["name"]: item for item in payload["projects"]}
    assert rows["idle-badge"]["project_health_status"] == "IDLE"


def test_ui_projects_status_badge_fallback_is_safe_with_partial_data(monkeypatch, tmp_path: Path) -> None:
    projects_root = tmp_path / "projects"
    _make_project(projects_root, "partial-badge")
    monkeypatch.setenv("ARCHMIND_PROJECTS_DIR", str(projects_root))

    def fake_runtime(_project_dir: Path):  # type: ignore[no-untyped-def]
        return {}

    monkeypatch.setattr("archmind.project_query.get_local_runtime_status", fake_runtime)
    client = TestClient(create_ui_app())
    payload = client.get("/ui/projects").json()
    rows = {item["name"]: item for item in payload["projects"]}
    assert rows["partial-badge"]["project_health_status"] in {"RUNNING", "BROKEN", "NEEDS FIX", "IDLE"}


def test_ui_project_detail_response_shape(monkeypatch, tmp_path: Path) -> None:
    projects_root = tmp_path / "projects"
    _make_project(projects_root, "beta", provider_mode="auto", display_name="베타 프로젝트")
    monkeypatch.setenv("ARCHMIND_PROJECTS_DIR", str(projects_root))
    client = TestClient(create_ui_app())

    response = client.get("/ui/projects/beta")
    assert response.status_code == 200
    payload = response.json()
    assert payload["name"] == "beta"
    assert payload["display_name"] == "베타 프로젝트"
    assert payload["provider_mode"] == "auto"
    assert payload["is_current"] is False
    assert "spec_summary" in payload
    assert "entities" in payload
    assert "Note" in payload["entities"]
    assert "runtime" in payload
    assert "architecture" in payload
    assert isinstance(payload["architecture"], dict)
    assert "recent_evolution" in payload
    assert "recent_runs" in payload
    assert isinstance(payload["recent_runs"], list)
    assert "logs" in payload
    assert isinstance(payload["logs"], dict)
    assert isinstance(payload["logs"].get("sources", []), list)
    assert isinstance(payload.get("auto_summary", {}), dict)
    assert "repository" in payload
    assert payload["repository"]["status"] == "CREATED"
    assert payload["repository"]["url"] == "https://github.com/example/beta"
    assert "analysis" in payload
    assert payload["analysis"]["project_name"] == "beta"
    assert isinstance(payload["analysis"]["suggestions"], list)
    assert isinstance(payload["analysis"].get("next_candidates", []), list)
    assert isinstance(payload["analysis"]["next_action"], dict)
    for key in ("kind", "message", "command"):
        assert key in payload["analysis"]["next_action"]
    assert "warning" in payload
    assert "safe" in payload
    assert "backend_urls" in payload["runtime"]
    assert "frontend_urls" in payload["runtime"]
    assert payload["spec_summary"]["stage"].startswith("Stage")


def test_ui_project_detail_summary_counts_match_analysis_lists(monkeypatch, tmp_path: Path) -> None:
    projects_root = tmp_path / "projects"
    project_dir = _make_project(projects_root, "summary-consistent")
    archmind_dir = project_dir / ".archmind"
    (archmind_dir / "project_spec.json").write_text(
        json.dumps(
            {
                "project_name": "summary-consistent",
                "shape": "fullstack",
                "template": "fullstack-ddd",
                "entities": [{"name": "Entry", "fields": [{"name": "title", "type": "string"}]}],
                "api_endpoints": ["GET /entries", "POST /entries"],
                "frontend_pages": ["entries/list", "entries/new"],
                "evolution": {"version": 1, "history": []},
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("ARCHMIND_PROJECTS_DIR", str(projects_root))
    client = TestClient(create_ui_app())

    response = client.get("/ui/projects/summary-consistent")
    assert response.status_code == 200
    payload = response.json()
    analysis = payload["analysis"]
    assert payload["spec_summary"]["entities"] == len(analysis["entities"])
    assert payload["spec_summary"]["apis"] == len(analysis["apis"])
    assert payload["spec_summary"]["pages"] == len(analysis["pages"])
    assert payload["spec_summary"]["apis"] == 5
    assert payload["spec_summary"]["pages"] == 3
    assert payload["runtime"]["overall_status"] in {"RUNNING", "NOT_RUNNING", "FAIL"}


def test_ui_project_detail_uses_spec_fallback_when_canonical_analysis_is_temporarily_empty(monkeypatch, tmp_path: Path) -> None:
    projects_root = tmp_path / "projects"
    _make_project(projects_root, "spec-fallback")
    monkeypatch.setenv("ARCHMIND_PROJECTS_DIR", str(projects_root))

    def _empty_analysis(*_args, **_kwargs):  # type: ignore[no-untyped-def]
        return {
            "project_name": "spec-fallback",
            "entities": [],
            "fields_by_entity": {},
            "apis": [],
            "pages": [],
            "suggestions": [],
            "next_candidates": [],
            "next_action": {"kind": "none", "message": "none", "command": ""},
            "next_action_explanation": {},
        }

    monkeypatch.setattr("archmind.project_query.analyze_project", _empty_analysis)
    client = TestClient(create_ui_app())
    payload = client.get("/ui/projects/spec-fallback").json()
    assert payload["spec_summary"]["entities"] >= 1
    assert payload["spec_summary"]["apis"] >= 1
    assert payload["spec_summary"]["pages"] >= 1
    assert payload["analysis"]["data_source"] == "spec_fallback"
    assert payload["analysis"]["entities"] != []
    assert payload["analysis"]["apis"] != []
    assert payload["analysis"]["pages"] != []
    assert "Canonical analysis was incomplete" in payload["warning"]


def test_ui_project_detail_includes_visualization_for_single_entity(monkeypatch, tmp_path: Path) -> None:
    projects_root = tmp_path / "projects"
    _make_project(projects_root, "single-entity-viz")
    monkeypatch.setenv("ARCHMIND_PROJECTS_DIR", str(projects_root))
    client = TestClient(create_ui_app())

    response = client.get("/ui/projects/single-entity-viz")
    assert response.status_code == 200
    analysis = response.json()["analysis"]
    graph = analysis["entity_graph"]
    assert [node["label"] for node in graph["nodes"]] == ["Note"]
    assert graph["edges"] == []

    api_groups = {group["resource"]: group for group in analysis["api_map"]["groups"]}
    assert "notes" in api_groups
    assert "GET /notes" in api_groups["notes"]["core_crud"]

    page_groups = {group["resource"]: group for group in analysis["page_map"]["groups"]}
    assert "notes" in page_groups
    assert "notes/list" in page_groups["notes"]["core_pages"]
    assert page_groups["notes"]["relation_pages"] == []


def test_ui_project_detail_includes_visualization_for_entry_tag_relation(monkeypatch, tmp_path: Path) -> None:
    projects_root = tmp_path / "projects"
    project_dir = _make_project(projects_root, "entry-tag-viz")
    spec_path = project_dir / ".archmind" / "project_spec.json"
    payload = json.loads(spec_path.read_text(encoding="utf-8"))
    payload["entities"] = [
        {"name": "Entry", "fields": [{"name": "title", "type": "string"}]},
        {"name": "Tag", "fields": [{"name": "name", "type": "string"}, {"name": "entry_id", "type": "int"}]},
    ]
    payload["api_endpoints"] = [
        "GET /entries",
        "POST /entries",
        "GET /entries/{id}",
        "PATCH /entries/{id}",
        "DELETE /entries/{id}",
        "GET /tags",
        "POST /tags",
        "GET /tags/{id}",
        "PATCH /tags/{id}",
        "DELETE /tags/{id}",
        "GET /entries/{id}/tags",
    ]
    payload["frontend_pages"] = ["entries/list", "entries/new", "entries/detail", "tags/list", "tags/new", "tags/detail", "tags/by_entry"]
    spec_path.write_text(json.dumps(payload), encoding="utf-8")

    monkeypatch.setenv("ARCHMIND_PROJECTS_DIR", str(projects_root))
    client = TestClient(create_ui_app())
    response = client.get("/ui/projects/entry-tag-viz")
    assert response.status_code == 200
    analysis = response.json()["analysis"]

    edges = analysis["entity_graph"]["edges"]
    assert any(edge["from"] == "Entry" and edge["to"] == "Tag" and edge["label"] == "entry_id" for edge in edges)

    api_groups = {group["resource"]: group for group in analysis["api_map"]["groups"]}
    assert "GET /entries/{id}/tags" in api_groups["tags"]["relation_scoped"]

    page_groups = {group["resource"]: group for group in analysis["page_map"]["groups"]}
    assert "tags/by_entry" in page_groups["tags"]["relation_pages"]


def test_ui_project_detail_includes_visualization_for_board_card_relation(monkeypatch, tmp_path: Path) -> None:
    projects_root = tmp_path / "projects"
    project_dir = _make_project(projects_root, "board-card-viz")
    spec_path = project_dir / ".archmind" / "project_spec.json"
    payload = json.loads(spec_path.read_text(encoding="utf-8"))
    payload["entities"] = [
        {"name": "Board", "fields": [{"name": "title", "type": "string"}]},
        {"name": "Card", "fields": [{"name": "title", "type": "string"}, {"name": "board_id", "type": "int"}]},
    ]
    payload["api_endpoints"] = [
        "GET /boards",
        "POST /boards",
        "GET /boards/{id}",
        "PATCH /boards/{id}",
        "DELETE /boards/{id}",
        "GET /cards",
        "POST /cards",
        "GET /cards/{id}",
        "PATCH /cards/{id}",
        "DELETE /cards/{id}",
        "GET /boards/{id}/cards",
    ]
    payload["frontend_pages"] = ["boards/list", "boards/detail", "cards/list", "cards/new", "cards/detail", "cards/by_board"]
    spec_path.write_text(json.dumps(payload), encoding="utf-8")

    monkeypatch.setenv("ARCHMIND_PROJECTS_DIR", str(projects_root))
    client = TestClient(create_ui_app())
    response = client.get("/ui/projects/board-card-viz")
    assert response.status_code == 200
    analysis = response.json()["analysis"]

    edges = analysis["entity_graph"]["edges"]
    assert any(edge["from"] == "Board" and edge["to"] == "Card" and edge["label"] == "board_id" for edge in edges)

    api_groups = {group["resource"]: group for group in analysis["api_map"]["groups"]}
    assert "GET /boards/{id}/cards" in api_groups["cards"]["relation_scoped"]

    page_groups = {group["resource"]: group for group in analysis["page_map"]["groups"]}
    assert "cards/by_board" in page_groups["cards"]["relation_pages"]


def test_ui_project_detail_includes_visualization_for_inferred_relation(monkeypatch, tmp_path: Path) -> None:
    projects_root = tmp_path / "projects"
    project_dir = _make_project(projects_root, "inferred-viz")
    spec_path = project_dir / ".archmind" / "project_spec.json"
    payload = json.loads(spec_path.read_text(encoding="utf-8"))
    payload["entities"] = [
        {"name": "Category", "fields": [{"name": "name", "type": "string"}]},
        {"name": "Bookmark", "fields": [{"name": "title", "type": "string"}]},
    ]
    payload["api_endpoints"] = ["GET /categories", "POST /categories", "GET /bookmarks", "POST /bookmarks"]
    payload["frontend_pages"] = ["categories/list", "bookmarks/list"]
    spec_path.write_text(json.dumps(payload), encoding="utf-8")

    monkeypatch.setenv("ARCHMIND_PROJECTS_DIR", str(projects_root))
    client = TestClient(create_ui_app())
    response = client.get("/ui/projects/inferred-viz")
    assert response.status_code == 200
    analysis = response.json()["analysis"]

    edges = analysis["entity_graph"]["edges"]
    assert any(edge["from"] == "Category" and edge["to"] == "Bookmark" and edge["inferred"] is True for edge in edges)


def test_ui_project_detail_does_not_expose_stale_runtime_url_as_running(monkeypatch, tmp_path: Path) -> None:
    projects_root = tmp_path / "projects"
    _make_project(projects_root, "stale-runtime")
    monkeypatch.setenv("ARCHMIND_PROJECTS_DIR", str(projects_root))
    monkeypatch.setattr(
        "archmind.project_query.get_local_runtime_status",
        lambda _project_dir: {
            "backend": {"status": "NOT RUNNING", "url": "http://127.0.0.1:8123"},
            "frontend": {"status": "NOT RUNNING", "url": "http://127.0.0.1:3123"},
        },
    )
    client = TestClient(create_ui_app())
    response = client.get("/ui/projects/stale-runtime")
    assert response.status_code == 200
    runtime = response.json()["runtime"]
    assert runtime["backend_status"] == "NOT RUNNING"
    assert runtime["frontend_status"] == "NOT RUNNING"
    assert runtime["backend_url"] == ""
    assert runtime["frontend_url"] == ""
    assert runtime["backend_last_known_url"] == "http://127.0.0.1:8123"
    assert runtime["frontend_last_known_url"] == "http://127.0.0.1:3123"


def test_ui_project_detail_includes_recent_runs_newest_first(monkeypatch, tmp_path: Path) -> None:
    projects_root = tmp_path / "projects"
    project_dir = _make_project(projects_root, "recent-runs")
    monkeypatch.setenv("ARCHMIND_PROJECTS_DIR", str(projects_root))
    assert append_execution_event(
        project_dir,
        project_name="recent-runs",
        source="telegram-next",
        command="/add_field Task title:string",
        status="ok",
        message="Field added",
        timestamp="2026-03-22T00:00:01Z",
    )
    assert append_execution_event(
        project_dir,
        project_name="recent-runs",
        source="telegram-auto",
        command="/auto",
        status="stop",
        message="Stopped",
        stop_reason="low-priority next action",
        timestamp="2026-03-22T00:00:02Z",
    )

    client = TestClient(create_ui_app())
    response = client.get("/ui/projects/recent-runs")
    assert response.status_code == 200
    payload = response.json()
    runs = payload["recent_runs"]
    assert isinstance(runs, list)
    assert len(runs) == 2
    assert runs[0]["command"] == "/auto"
    assert runs[0]["status"] == "stop"
    assert runs[0]["stop_reason"] == "low-priority next action"
    assert runs[0]["timestamp"] == "2026-03-22 00:00:02"
    assert runs[1]["command"] == "/add_field Task title:string"
    assert runs[1]["status"] == "ok"
    assert runs[1]["timestamp"] == "2026-03-22 00:00:01"
    history = payload["evolution_history"]
    assert isinstance(history, list)
    assert history[0]["title"] == "/auto"
    assert history[0]["status"] == "STOPPED"
    assert history[0]["summary"] == "low-priority next action"
    assert history[0]["action_type"] == "auto"
    assert history[0]["timestamp"] == "2026-03-22 00:00:02"


def test_ui_project_logs_endpoint_returns_backend_and_frontend_content(monkeypatch, tmp_path: Path) -> None:
    projects_root = tmp_path / "projects"
    project_dir = _make_project(projects_root, "logs-available")
    monkeypatch.setenv("ARCHMIND_PROJECTS_DIR", str(projects_root))
    archmind_dir = project_dir / ".archmind"
    (archmind_dir / "backend.log").write_text("backend line 1\nbackend line 2\n", encoding="utf-8")
    (archmind_dir / "frontend.log").write_text("frontend line 1\nfrontend line 2\n", encoding="utf-8")

    client = TestClient(create_ui_app())
    response = client.get("/ui/projects/logs-available/logs")
    assert response.status_code == 200
    payload = response.json()
    assert payload["project_name"] == "logs-available"
    groups = {row["key"]: row for row in payload["sources"]}
    assert groups["backend"]["available"] is True
    assert "backend line 2" in groups["backend"]["content"]
    assert groups["frontend"]["available"] is True
    assert "frontend line 2" in groups["frontend"]["content"]


def test_ui_project_logs_endpoint_missing_logs_is_safe_empty(monkeypatch, tmp_path: Path) -> None:
    projects_root = tmp_path / "projects"
    _make_project(projects_root, "logs-missing")
    monkeypatch.setenv("ARCHMIND_PROJECTS_DIR", str(projects_root))

    client = TestClient(create_ui_app())
    response = client.get("/ui/projects/logs-missing/logs")
    assert response.status_code == 200
    payload = response.json()
    groups = {row["key"]: row for row in payload["sources"]}
    assert groups["backend"]["available"] is False
    assert groups["backend"]["content"] == ""
    assert groups["frontend"]["available"] is False
    assert groups["latest"]["available"] is False


def test_ui_project_logs_endpoint_large_log_is_bounded(monkeypatch, tmp_path: Path) -> None:
    projects_root = tmp_path / "projects"
    project_dir = _make_project(projects_root, "logs-large")
    monkeypatch.setenv("ARCHMIND_PROJECTS_DIR", str(projects_root))
    archmind_dir = project_dir / ".archmind"
    lines = [f"line-{idx}" for idx in range(500)]
    (archmind_dir / "backend.log").write_text("\n".join(lines) + "\n", encoding="utf-8")

    client = TestClient(create_ui_app())
    response = client.get("/ui/projects/logs-large/logs")
    assert response.status_code == 200
    payload = response.json()
    groups = {row["key"]: row for row in payload["sources"]}
    backend = groups["backend"]
    assert backend["available"] is True
    assert backend["truncated"] is True
    assert "line-499" in backend["content"]
    assert "line-0" not in backend["content"]


def test_ui_project_logs_endpoint_unreadable_source_reports_error(monkeypatch, tmp_path: Path) -> None:
    projects_root = tmp_path / "projects"
    project_dir = _make_project(projects_root, "logs-unreadable")
    monkeypatch.setenv("ARCHMIND_PROJECTS_DIR", str(projects_root))
    bad_path = project_dir / ".archmind" / "bad-backend-log"
    bad_path.mkdir(parents=True, exist_ok=True)
    state_payload = json.loads((project_dir / ".archmind" / "state.json").read_text(encoding="utf-8"))
    runtime = state_payload.get("runtime", {})
    runtime["backend_log_path"] = str(bad_path)
    state_payload["runtime"] = runtime
    write_state(project_dir, state_payload)

    client = TestClient(create_ui_app())
    response = client.get("/ui/projects/logs-unreadable/logs")
    assert response.status_code == 200
    payload = response.json()
    groups = {row["key"]: row for row in payload["sources"]}
    assert groups["backend"]["available"] is False
    assert "not a file" in str(groups["backend"]["error"]).lower()


def test_ui_project_detail_recent_runs_empty_when_history_missing(monkeypatch, tmp_path: Path) -> None:
    projects_root = tmp_path / "projects"
    _make_project(projects_root, "no-history")
    monkeypatch.setenv("ARCHMIND_PROJECTS_DIR", str(projects_root))

    client = TestClient(create_ui_app())
    response = client.get("/ui/projects/no-history")
    assert response.status_code == 200
    payload = response.json()
    assert "recent_runs" in payload
    assert payload["recent_runs"] == []
    assert "evolution_history" in payload
    assert payload["evolution_history"] == []


def test_ui_project_detail_includes_fix_and_continue_in_evolution_history(monkeypatch, tmp_path: Path) -> None:
    projects_root = tmp_path / "projects"
    project_dir = _make_project(projects_root, "history-actions")
    monkeypatch.setenv("ARCHMIND_PROJECTS_DIR", str(projects_root))
    assert append_execution_event(
        project_dir,
        project_name="history-actions",
        source="telegram-fix",
        command="/fix",
        status="ok",
        message="Fix completed",
        timestamp="2026-03-22T00:00:03Z",
    )
    assert append_execution_event(
        project_dir,
        project_name="history-actions",
        source="telegram-continue",
        command="/continue",
        status="ok",
        message="Continue completed",
        timestamp="2026-03-22T00:00:04Z",
    )

    client = TestClient(create_ui_app())
    response = client.get("/ui/projects/history-actions")
    assert response.status_code == 200
    payload = response.json()
    history = payload["evolution_history"]
    assert history[0]["title"] == "/continue"
    assert history[0]["action_type"] == "continue"
    assert history[1]["title"] == "/fix"
    assert history[1]["action_type"] == "fix"


def test_ui_projects_response_includes_safe_repository_when_missing(monkeypatch, tmp_path: Path) -> None:
    projects_root = tmp_path / "projects"
    _make_project(projects_root, "no-repo", repository={"status": "NONE", "url": ""})
    monkeypatch.setenv("ARCHMIND_PROJECTS_DIR", str(projects_root))
    client = TestClient(create_ui_app())

    response = client.get("/ui/projects")
    assert response.status_code == 200
    item = response.json()["projects"][0]
    assert "repository" in item
    assert item["repository"]["status"] == "NONE"
    assert item["repository"]["url"] == ""


def test_ui_project_analysis_endpoint_response_shape(monkeypatch, tmp_path: Path) -> None:
    projects_root = tmp_path / "projects"
    _make_project(projects_root, "analysis-project")
    monkeypatch.setenv("ARCHMIND_PROJECTS_DIR", str(projects_root))
    client = TestClient(create_ui_app())

    response = client.get("/ui/projects/analysis-project/analysis")
    assert response.status_code == 200
    payload = response.json()
    assert payload["project_name"] == "analysis-project"
    assert isinstance(payload["entities"], list)
    assert isinstance(payload["fields_by_entity"], dict)
    assert isinstance(payload["apis"], list)
    assert isinstance(payload["pages"], list)
    assert isinstance(payload["entity_graph"], dict)
    assert isinstance(payload["api_map"], dict)
    assert isinstance(payload["page_map"], dict)
    assert isinstance(payload["visualization_gaps"], list)
    assert isinstance(payload["entity_crud_status"], dict)
    assert isinstance(payload["placeholder_pages"], list)
    assert isinstance(payload["nav_visible_pages"], list)
    assert isinstance(payload["runtime_status"], dict)
    assert isinstance(payload["suggestions"], list)
    assert isinstance(payload["next_candidates"], list)
    assert isinstance(payload["next_action"], dict)
    assert isinstance(payload["next_action_explanation"], dict)
    for key in ("kind", "message", "command"):
        assert key in payload["next_action"]
    for key in ("gap_type", "reason_summary", "priority_reason", "expected_effect"):
        assert key in payload["next_action_explanation"]


def test_ui_project_analysis_endpoint_filters_and_limits_next_candidates(monkeypatch, tmp_path: Path) -> None:
    projects_root = tmp_path / "projects"
    _make_project(projects_root, "analysis-next-candidates")
    monkeypatch.setenv("ARCHMIND_PROJECTS_DIR", str(projects_root))

    def _fake_build_project_analysis(_project_dir: Path) -> dict[str, object]:
        return {
            "project_name": "analysis-next-candidates",
            "entities": ["Task"],
            "fields_by_entity": {"Task": [{"name": "title", "type": "string"}]},
            "apis": [],
            "pages": [],
            "entity_graph": {},
            "api_map": {},
            "page_map": {},
            "visualization_gaps": [],
            "entity_crud_status": {},
            "placeholder_pages": [],
            "nav_visible_pages": [],
            "runtime_status": {},
            "suggestions": [],
            "next_candidates": [
                {"command": "/add_page tasks/list", "gap_type": "page_missing", "priority": "high", "reason": "a", "expected_effect": "ea"},
                {"command": "", "gap_type": "page_missing", "priority": "high", "reason": "skip", "expected_effect": "skip"},
                {"command": "/add_api GET /tasks", "gap_type": "crud_api_missing", "priority": "high", "reason_summary": "b", "expected_effect": "eb"},
                {"command": "/implement_page tasks/list", "gap_type": "placeholder_page", "priority": "medium", "reason": "c", "expected_effect": "ec"},
                {"command": "/add_field Task description:string", "gap_type": "field_missing", "priority": "medium", "reason": "drop by cap", "expected_effect": "ed"},
            ],
            "next_action": {"kind": "missing_page", "message": "msg", "command": "/add_page tasks/list"},
            "next_action_explanation": {
                "gap_type": "page_missing",
                "reason_summary": "msg",
                "priority": "high",
                "priority_reason": "reason",
                "expected_effect": "effect",
            },
        }

    monkeypatch.setattr("archmind.ui_api.build_project_analysis", _fake_build_project_analysis)
    client = TestClient(create_ui_app())
    response = client.get("/ui/projects/analysis-next-candidates/analysis")
    assert response.status_code == 200
    payload = response.json()
    rows = payload["next_candidates"]
    assert len(rows) == 3
    assert [row["command"] for row in rows] == [
        "/add_page tasks/list",
        "/add_api GET /tasks",
        "/implement_page tasks/list",
    ]
    assert rows[1]["reason"] == "b"
    assert rows[1]["reason_summary"] == "b"


def test_ui_project_analysis_visualization_matches_relation_aware_canonical_state(monkeypatch, tmp_path: Path) -> None:
    projects_root = tmp_path / "projects"
    project_dir = _make_project(projects_root, "analysis-visualization")
    spec_path = project_dir / ".archmind" / "project_spec.json"
    payload = json.loads(spec_path.read_text(encoding="utf-8"))
    payload["entities"] = [
        {"name": "Entry", "fields": [{"name": "title", "type": "string"}]},
        {"name": "Tag", "fields": [{"name": "name", "type": "string"}, {"name": "entry_id", "type": "int"}]},
    ]
    payload["api_endpoints"] = [
        "GET /entries",
        "POST /entries",
        "GET /entries/{id}",
        "PATCH /entries/{id}",
        "DELETE /entries/{id}",
        "GET /tags",
        "POST /tags",
        "GET /tags/{id}",
        "PATCH /tags/{id}",
        "DELETE /tags/{id}",
        "GET /entries/{id}/tags",
    ]
    payload["frontend_pages"] = [
        "entries/list",
        "entries/new",
        "entries/detail",
        "tags/list",
        "tags/new",
        "tags/detail",
        "tags/by_entry",
    ]
    spec_path.write_text(json.dumps(payload), encoding="utf-8")

    monkeypatch.setenv("ARCHMIND_PROJECTS_DIR", str(projects_root))
    client = TestClient(create_ui_app())
    response = client.get("/ui/projects/analysis-visualization/analysis")
    assert response.status_code == 200
    analysis = response.json()

    graph_edges = analysis["entity_graph"]["edges"]
    assert any(edge["from"] == "Entry" and edge["to"] == "Tag" and edge["label"] == "entry_id" for edge in graph_edges)

    api_groups = {group["resource"]: group for group in analysis["api_map"]["groups"]}
    assert "GET /entries/{id}/tags" in api_groups["tags"]["relation_scoped"]
    assert "GET /tags" in api_groups["tags"]["core_crud"]

    page_groups = {group["resource"]: group for group in analysis["page_map"]["groups"]}
    assert "tags/by_entry" in page_groups["tags"]["relation_pages"]
    assert "tags/detail" in page_groups["tags"]["core_pages"]
    assert isinstance(analysis["visualization_gaps"], list)


def test_ui_project_analysis_uses_canonical_expanded_apis_for_next_action(monkeypatch, tmp_path: Path) -> None:
    projects_root = tmp_path / "projects"
    project_dir = _make_project(projects_root, "analysis-crud-gap")
    spec_path = project_dir / ".archmind" / "project_spec.json"
    payload = json.loads(spec_path.read_text(encoding="utf-8"))
    payload["entities"] = [{"name": "Entry", "fields": [{"name": "title", "type": "string"}]}]
    payload["api_endpoints"] = ["GET /entries", "POST /entries"]
    payload["frontend_pages"] = ["entries/list", "entries/new", "entries/detail"]
    spec_path.write_text(json.dumps(payload), encoding="utf-8")

    monkeypatch.setenv("ARCHMIND_PROJECTS_DIR", str(projects_root))
    client = TestClient(create_ui_app())
    response = client.get("/ui/projects/analysis-crud-gap/analysis")
    assert response.status_code == 200
    analysis = response.json()
    assert analysis["next_action"]["kind"] != "missing_crud_api"
    assert analysis["next_action"]["command"] != "/add_api GET /entries/{id}"


def test_ui_project_analysis_visualization_defaults_when_payload_fields_are_invalid(monkeypatch, tmp_path: Path) -> None:
    projects_root = tmp_path / "projects"
    _make_project(projects_root, "analysis-viz-invalid")
    monkeypatch.setenv("ARCHMIND_PROJECTS_DIR", str(projects_root))

    def _broken_analysis(_project_dir: Path) -> dict[str, object]:
        return {
            "project_name": "analysis-viz-invalid",
            "entities": ["Note"],
            "fields_by_entity": {},
            "apis": [],
            "pages": [],
            "entity_graph": [],
            "api_map": ["bad"],
            "page_map": "broken",
            "entity_crud_status": {},
            "placeholder_pages": [],
            "nav_visible_pages": [],
            "runtime_status": {},
            "suggestions": [],
            "next_action": {"kind": "none", "message": "No immediate suggestions.", "command": ""},
        }

    monkeypatch.setattr("archmind.ui_api.build_project_analysis", _broken_analysis)
    client = TestClient(create_ui_app())
    response = client.get("/ui/projects/analysis-viz-invalid/analysis")
    assert response.status_code == 200
    payload = response.json()
    assert payload["entity_graph"] == {}
    assert payload["api_map"] == {}
    assert payload["page_map"] == {}
    assert payload["visualization_gaps"] == []


def test_ui_project_detail_visualization_gap_action_for_missing_board_card_relation_page(monkeypatch, tmp_path: Path) -> None:
    projects_root = tmp_path / "projects"
    project_dir = _make_project(projects_root, "board-card-gap-page-ui")
    spec_path = project_dir / ".archmind" / "project_spec.json"
    payload = json.loads(spec_path.read_text(encoding="utf-8"))
    payload["entities"] = [
        {"name": "Board", "fields": [{"name": "title", "type": "string"}]},
        {"name": "Card", "fields": [{"name": "title", "type": "string"}, {"name": "board_id", "type": "int"}]},
    ]
    payload["api_endpoints"] = [
        "GET /boards",
        "POST /boards",
        "GET /boards/{id}",
        "PATCH /boards/{id}",
        "DELETE /boards/{id}",
        "GET /cards",
        "POST /cards",
        "GET /cards/{id}",
        "PATCH /cards/{id}",
        "DELETE /cards/{id}",
        "GET /boards/{id}/cards",
    ]
    payload["frontend_pages"] = ["boards/list", "boards/detail", "cards/list", "cards/new", "cards/detail"]
    spec_path.write_text(json.dumps(payload), encoding="utf-8")

    monkeypatch.setenv("ARCHMIND_PROJECTS_DIR", str(projects_root))
    client = TestClient(create_ui_app())
    response = client.get("/ui/projects/board-card-gap-page-ui")
    assert response.status_code == 200
    analysis = response.json()["analysis"]
    gaps = [row for row in analysis["visualization_gaps"] if row.get("gap_type") == "missing_relation_page"]
    assert any(row.get("expected") == "cards/by_board" for row in gaps)
    assert any(row.get("command") == "/add_page cards/by_board" for row in gaps)


def test_ui_project_detail_visualization_gap_action_for_missing_board_card_relation_api(monkeypatch, tmp_path: Path) -> None:
    projects_root = tmp_path / "projects"
    project_dir = _make_project(projects_root, "board-card-gap-api-ui")
    spec_path = project_dir / ".archmind" / "project_spec.json"
    payload = json.loads(spec_path.read_text(encoding="utf-8"))
    payload["entities"] = [
        {"name": "Board", "fields": [{"name": "title", "type": "string"}]},
        {"name": "Card", "fields": [{"name": "title", "type": "string"}, {"name": "board_id", "type": "int"}]},
    ]
    payload["api_endpoints"] = [
        "GET /boards",
        "POST /boards",
        "GET /boards/{id}",
        "PATCH /boards/{id}",
        "DELETE /boards/{id}",
        "GET /cards",
        "POST /cards",
        "GET /cards/{id}",
        "PATCH /cards/{id}",
        "DELETE /cards/{id}",
    ]
    payload["frontend_pages"] = ["boards/list", "boards/detail", "cards/list", "cards/new", "cards/detail", "cards/by_board"]
    spec_path.write_text(json.dumps(payload), encoding="utf-8")

    monkeypatch.setenv("ARCHMIND_PROJECTS_DIR", str(projects_root))
    client = TestClient(create_ui_app())
    response = client.get("/ui/projects/board-card-gap-api-ui")
    assert response.status_code == 200
    analysis = response.json()["analysis"]
    gaps = [row for row in analysis["visualization_gaps"] if row.get("gap_type") == "missing_relation_scoped_api"]
    assert any(row.get("expected") == "GET /boards/{id}/cards" for row in gaps)
    assert any(row.get("command") == "/add_api GET /boards/{id}/cards" for row in gaps)


def test_ui_project_detail_visualization_gap_disappears_when_resolved(monkeypatch, tmp_path: Path) -> None:
    projects_root = tmp_path / "projects"
    project_dir = _make_project(projects_root, "board-card-gap-resolved-ui")
    spec_path = project_dir / ".archmind" / "project_spec.json"
    payload = json.loads(spec_path.read_text(encoding="utf-8"))
    payload["entities"] = [
        {"name": "Board", "fields": [{"name": "title", "type": "string"}]},
        {"name": "Card", "fields": [{"name": "title", "type": "string"}, {"name": "board_id", "type": "int"}]},
    ]
    payload["api_endpoints"] = [
        "GET /boards",
        "POST /boards",
        "GET /boards/{id}",
        "PATCH /boards/{id}",
        "DELETE /boards/{id}",
        "GET /cards",
        "POST /cards",
        "GET /cards/{id}",
        "PATCH /cards/{id}",
        "DELETE /cards/{id}",
        "GET /boards/{id}/cards",
    ]
    payload["frontend_pages"] = ["boards/list", "boards/detail", "cards/list", "cards/new", "cards/detail", "cards/by_board"]
    spec_path.write_text(json.dumps(payload), encoding="utf-8")

    monkeypatch.setenv("ARCHMIND_PROJECTS_DIR", str(projects_root))
    client = TestClient(create_ui_app())
    response = client.get("/ui/projects/board-card-gap-resolved-ui")
    assert response.status_code == 200
    analysis = response.json()["analysis"]
    assert analysis["visualization_gaps"] == []


def test_ui_projects_response_tolerates_malformed_repository_metadata(monkeypatch, tmp_path: Path) -> None:
    projects_root = tmp_path / "projects"
    project_dir = _make_project(projects_root, "broken-repo")
    state_payload = json.loads((project_dir / ".archmind" / "state.json").read_text(encoding="utf-8"))
    state_payload["repository"] = "not-a-dict"
    state_payload["github_repo_url"] = 12345
    write_state(project_dir, state_payload)

    monkeypatch.setenv("ARCHMIND_PROJECTS_DIR", str(projects_root))
    client = TestClient(create_ui_app())
    response = client.get("/ui/projects")
    assert response.status_code == 200
    item = response.json()["projects"][0]
    assert item["repository"]["status"] == "EXISTS"
    assert item["repository"]["url"] == "12345"


def test_ui_repository_visibility_is_consistent_between_list_and_detail_with_repo(monkeypatch, tmp_path: Path) -> None:
    projects_root = tmp_path / "projects"
    _make_project(projects_root, "repo-consistent")
    monkeypatch.setenv("ARCHMIND_PROJECTS_DIR", str(projects_root))
    client = TestClient(create_ui_app())

    list_response = client.get("/ui/projects")
    assert list_response.status_code == 200
    list_item = list_response.json()["projects"][0]

    detail_response = client.get("/ui/projects/repo-consistent")
    assert detail_response.status_code == 200
    detail_payload = detail_response.json()

    assert list_item["repository"]["status"] == detail_payload["repository"]["status"]
    assert list_item["repository"]["url"] == detail_payload["repository"]["url"]
    assert list_item["repository"]["url"] == "https://github.com/example/repo-consistent"


def test_ui_repository_visibility_is_consistent_between_list_and_detail_without_repo(monkeypatch, tmp_path: Path) -> None:
    projects_root = tmp_path / "projects"
    _make_project(projects_root, "repo-missing", repository={"status": "NONE", "url": ""})
    monkeypatch.setenv("ARCHMIND_PROJECTS_DIR", str(projects_root))
    client = TestClient(create_ui_app())

    list_response = client.get("/ui/projects")
    assert list_response.status_code == 200
    list_item = list_response.json()["projects"][0]

    detail_response = client.get("/ui/projects/repo-missing")
    assert detail_response.status_code == 200
    detail_payload = detail_response.json()

    assert list_item["repository"]["status"] == detail_payload["repository"]["status"]
    assert list_item["repository"]["url"] == detail_payload["repository"]["url"]
    assert list_item["repository"]["url"] == ""


def test_ui_provider_get(monkeypatch, tmp_path: Path) -> None:
    projects_root = tmp_path / "projects"
    _make_project(projects_root, "gamma", provider_mode="cloud")
    monkeypatch.setenv("ARCHMIND_PROJECTS_DIR", str(projects_root))
    client = TestClient(create_ui_app())

    response = client.get("/ui/projects/gamma/provider")
    assert response.status_code == 200
    assert response.json() == {"mode": "cloud"}


def test_ui_provider_post_updates_mode(monkeypatch, tmp_path: Path) -> None:
    projects_root = tmp_path / "projects"
    project_dir = _make_project(projects_root, "delta", provider_mode="local")
    monkeypatch.setenv("ARCHMIND_PROJECTS_DIR", str(projects_root))
    client = TestClient(create_ui_app())

    response = client.post("/ui/projects/delta/provider", json={"mode": "auto"})
    assert response.status_code == 200
    assert response.json() == {"mode": "auto"}

    detail_response = client.get("/ui/projects/delta")
    assert detail_response.status_code == 200
    assert detail_response.json()["provider_mode"] == "auto"

    provider_response = client.get("/ui/projects/delta/provider")
    assert provider_response.status_code == 200
    assert provider_response.json() == {"mode": "auto"}

    state_payload = json.loads((project_dir / ".archmind" / "state.json").read_text(encoding="utf-8"))
    assert state_payload.get("provider", {}).get("mode") == "auto"


def test_ui_project_not_found_returns_404(monkeypatch, tmp_path: Path) -> None:
    projects_root = tmp_path / "projects"
    projects_root.mkdir(parents=True, exist_ok=True)
    monkeypatch.setenv("ARCHMIND_PROJECTS_DIR", str(projects_root))
    client = TestClient(create_ui_app())

    response = client.get("/ui/projects/not-exists")
    assert response.status_code == 404
    response = client.get("/ui/projects/not-exists/provider")
    assert response.status_code == 404


def test_ui_select_project_marks_it_current_and_unsets_previous(monkeypatch, tmp_path: Path) -> None:
    projects_root = tmp_path / "projects"
    alpha = _make_project(projects_root, "alpha")
    _make_project(projects_root, "beta")
    monkeypatch.setenv("ARCHMIND_PROJECTS_DIR", str(projects_root))
    set_current_project(alpha)
    client = TestClient(create_ui_app())
    try:
        response = client.post("/ui/projects/beta/select")
        assert response.status_code == 200
        payload = response.json()
        assert payload["ok"] is True
        assert payload["project_name"] == "beta"
        assert payload["is_current"] is True

        list_response = client.get("/ui/projects")
        assert list_response.status_code == 200
        rows = {item["name"]: item for item in list_response.json()["projects"]}
        assert rows["beta"]["is_current"] is True
        assert rows["alpha"]["is_current"] is False

        detail_response = client.get("/ui/projects/beta")
        assert detail_response.status_code == 200
        assert detail_response.json()["is_current"] is True
    finally:
        clear_current_project()


def test_ui_select_project_updates_shared_backend_current_state(monkeypatch, tmp_path: Path) -> None:
    projects_root = tmp_path / "projects"
    alpha = _make_project(projects_root, "alpha")
    beta = _make_project(projects_root, "beta")
    monkeypatch.setenv("ARCHMIND_PROJECTS_DIR", str(projects_root))
    set_current_project(alpha)
    client = TestClient(create_ui_app())
    try:
        response = client.post("/ui/projects/beta/select")
        assert response.status_code == 200
        payload = response.json()
        assert payload["ok"] is True
        assert payload["project_name"] == "beta"
        current = get_validated_current_project()
        assert current is not None
        assert current.resolve() == beta.resolve()
    finally:
        clear_current_project()


def test_ui_projects_reflect_backend_current_change_from_telegram_use(monkeypatch, tmp_path: Path) -> None:
    projects_root = tmp_path / "projects"
    alpha = _make_project(projects_root, "alpha")
    beta = _make_project(projects_root, "beta")
    monkeypatch.setenv("ARCHMIND_PROJECTS_DIR", str(projects_root))
    client = TestClient(create_ui_app())
    try:
        set_current_project(alpha)
        first_rows = {item["name"]: item for item in client.get("/ui/projects").json()["projects"]}
        assert first_rows["alpha"]["is_current"] is True
        assert first_rows["beta"]["is_current"] is False

        # Telegram /use updates backend current project selection.
        set_current_project(beta)

        second_rows = {item["name"]: item for item in client.get("/ui/projects").json()["projects"]}
        assert second_rows["beta"]["is_current"] is True
        assert second_rows["alpha"]["is_current"] is False

        alpha_detail = client.get("/ui/projects/alpha").json()
        beta_detail = client.get("/ui/projects/beta").json()
        assert alpha_detail["is_current"] is False
        assert beta_detail["is_current"] is True
    finally:
        clear_current_project()


def test_ui_projects_reflects_persisted_current_update_even_when_process_cache_is_stale(
    monkeypatch, tmp_path: Path
) -> None:
    projects_root = tmp_path / "projects"
    alpha = _make_project(projects_root, "alpha")
    beta = _make_project(projects_root, "beta")
    monkeypatch.setenv("ARCHMIND_PROJECTS_DIR", str(projects_root))
    current_project_state._CURRENT_PROJECT = alpha.resolve()
    current_project_state.save_last_project_path(beta)

    client = TestClient(create_ui_app())
    try:
        rows = {item["name"]: item for item in client.get("/ui/projects").json()["projects"]}
        assert rows["beta"]["is_current"] is True
        assert rows["alpha"]["is_current"] is False
    finally:
        clear_current_project()


def test_ui_select_project_invalid_name_returns_safe_error(monkeypatch, tmp_path: Path) -> None:
    projects_root = tmp_path / "projects"
    _make_project(projects_root, "valid-project")
    monkeypatch.setenv("ARCHMIND_PROJECTS_DIR", str(projects_root))
    client = TestClient(create_ui_app())

    response = client.post("/ui/projects/not-exists/select")
    assert response.status_code == 200
    payload = response.json()
    assert payload["ok"] is False
    assert payload["project_name"] == "not-exists"
    assert payload["is_current"] is False
    assert "not found" in str(payload["detail"]).lower()


def test_ui_select_project_failure_does_not_change_current_project(monkeypatch, tmp_path: Path) -> None:
    projects_root = tmp_path / "projects"
    alpha = _make_project(projects_root, "alpha")
    _make_project(projects_root, "beta")
    monkeypatch.setenv("ARCHMIND_PROJECTS_DIR", str(projects_root))
    set_current_project(alpha)
    client = TestClient(create_ui_app())
    try:
        response = client.post("/ui/projects/not-exists/select")
        assert response.status_code == 200
        payload = response.json()
        assert payload["ok"] is False
        current = get_validated_current_project()
        assert current is not None
        assert current.resolve() == alpha.resolve()

        rows = {item["name"]: item for item in client.get("/ui/projects").json()["projects"]}
        assert rows["alpha"]["is_current"] is True
        assert rows["beta"]["is_current"] is False
    finally:
        clear_current_project()


def test_ui_select_project_reuses_telegram_selection_helpers(monkeypatch, tmp_path: Path) -> None:
    projects_root = tmp_path / "projects"
    project = _make_project(projects_root, "alpha")
    monkeypatch.setenv("ARCHMIND_PROJECTS_DIR", str(projects_root))
    calls: dict[str, Path | None] = {"current": None, "last": None}

    def fake_set_current(target: Path) -> None:
        calls["current"] = target.resolve()

    def fake_save_last(target: Path) -> None:
        calls["last"] = target.resolve()

    monkeypatch.setattr("archmind.project_query.set_current_project", fake_set_current)
    monkeypatch.setattr("archmind.project_query.save_last_project_path", fake_save_last)

    client = TestClient(create_ui_app())
    response = client.post("/ui/projects/alpha/select")
    assert response.status_code == 200
    payload = response.json()
    assert payload["ok"] is True
    assert calls["current"] == project.resolve()
    assert calls["last"] == project.resolve()


def test_ui_add_entity_succeeds_and_returns_updated_spec(monkeypatch, tmp_path: Path) -> None:
    projects_root = tmp_path / "projects"
    _make_project(projects_root, "entity-project")
    monkeypatch.setenv("ARCHMIND_PROJECTS_DIR", str(projects_root))
    client = TestClient(create_ui_app())

    response = client.post("/ui/projects/entity-project/entities", json={"entity_name": "task"})
    assert response.status_code == 200
    payload = response.json()
    assert payload["ok"] is True
    assert payload["project_name"] == "entity-project"
    assert payload["entity_name"] == "Task"
    assert payload["spec_summary"]["entities"] >= 2
    assert any("add_entity Task" in str(item) for item in payload["recent_evolution"])

    detail_response = client.get("/ui/projects/entity-project")
    assert detail_response.status_code == 200
    detail_payload = detail_response.json()
    assert detail_payload["spec_summary"]["entities"] >= 2
    assert any("add_entity Task" in str(item) for item in detail_payload["recent_evolution"])


def test_ui_run_command_executes_add_entity_same_as_telegram(monkeypatch, tmp_path: Path) -> None:
    projects_root = tmp_path / "projects"
    _make_project(projects_root, "command-project")
    monkeypatch.setenv("ARCHMIND_PROJECTS_DIR", str(projects_root))
    client = TestClient(create_ui_app())

    response = client.post("/ui/projects/command-project/commands", json={"command": "/add_entity Task"})
    assert response.status_code == 200
    payload = response.json()
    assert payload["ok"] is True
    assert payload["project_name"] == "command-project"
    assert payload["command"] == "/add_entity Task"
    assert payload["spec_summary"]["entities"] >= 2


def test_ui_run_command_rejects_invalid_consistently(monkeypatch, tmp_path: Path) -> None:
    projects_root = tmp_path / "projects"
    _make_project(projects_root, "command-invalid")
    monkeypatch.setenv("ARCHMIND_PROJECTS_DIR", str(projects_root))
    client = TestClient(create_ui_app())

    response = client.post("/ui/projects/command-invalid/commands", json={"command": "/unknown foo"})
    assert response.status_code == 200
    payload = response.json()
    assert payload["ok"] is False
    assert "Unsupported command" in str(payload["error"])


def test_ui_add_entity_rejects_empty_name_safely(monkeypatch, tmp_path: Path) -> None:
    projects_root = tmp_path / "projects"
    _make_project(projects_root, "entity-empty")
    monkeypatch.setenv("ARCHMIND_PROJECTS_DIR", str(projects_root))
    client = TestClient(create_ui_app())

    response = client.post("/ui/projects/entity-empty/entities", json={"entity_name": "   "})
    assert response.status_code == 200
    payload = response.json()
    assert payload["ok"] is False
    assert payload["project_name"] == "entity-empty"
    assert payload["entity_name"] == ""
    assert "invalid entity name" in str(payload["detail"]).lower()


def test_ui_add_entity_rejects_invalid_name_safely(monkeypatch, tmp_path: Path) -> None:
    projects_root = tmp_path / "projects"
    _make_project(projects_root, "entity-invalid")
    monkeypatch.setenv("ARCHMIND_PROJECTS_DIR", str(projects_root))
    client = TestClient(create_ui_app())

    response = client.post("/ui/projects/entity-invalid/entities", json={"entity_name": "123-Task"})
    assert response.status_code == 200
    payload = response.json()
    assert payload["ok"] is False
    assert payload["project_name"] == "entity-invalid"
    assert payload["entity_name"] == "123-Task"
    assert "invalid entity name" in str(payload["detail"]).lower()


def test_ui_add_field_succeeds_and_returns_updated_spec(monkeypatch, tmp_path: Path) -> None:
    projects_root = tmp_path / "projects"
    _make_project(projects_root, "field-project")
    monkeypatch.setenv("ARCHMIND_PROJECTS_DIR", str(projects_root))
    client = TestClient(create_ui_app())

    response = client.post(
        "/ui/projects/field-project/fields",
        json={"entity_name": "Note", "field_name": "priority", "field_type": "int"},
    )
    assert response.status_code == 200
    payload = response.json()
    assert payload["ok"] is True
    assert payload["project_name"] == "field-project"
    assert payload["entity_name"] == "Note"
    assert payload["field_name"] == "priority"
    assert payload["field_type"] == "int"
    assert payload["spec_summary"]["entities"] >= 1
    assert any("add_field Note priority:int" in str(item) for item in payload["recent_evolution"])

    detail_response = client.get("/ui/projects/field-project")
    assert detail_response.status_code == 200
    detail_payload = detail_response.json()
    assert "Note" in detail_payload["entities"]
    assert any("add_field Note priority:int" in str(item) for item in detail_payload["recent_evolution"])


def test_ui_add_field_succeeds_for_task_priority_string_regression(monkeypatch, tmp_path: Path) -> None:
    projects_root = tmp_path / "projects"
    _make_project(projects_root, "field-task")
    monkeypatch.setenv("ARCHMIND_PROJECTS_DIR", str(projects_root))
    client = TestClient(create_ui_app())
    add_entity_response = client.post(
        "/ui/projects/field-task/entities",
        json={"entity_name": "Task"},
    )
    assert add_entity_response.status_code == 200
    assert add_entity_response.json().get("ok") is True

    response = client.post(
        "/ui/projects/field-task/fields",
        json={"entity_name": "Task", "field_name": "priority", "field_type": "string"},
    )
    assert response.status_code == 200
    payload = response.json()
    assert payload["ok"] is True
    assert payload["project_name"] == "field-task"
    assert payload["entity_name"] == "Task"
    assert payload["field_name"] == "priority"
    assert payload["field_type"] == "string"
    assert "required" not in str(payload.get("error") or "").lower()
    assert "required" not in str(payload.get("detail") or "").lower()


def test_ui_add_field_targets_requested_entity_without_touching_others(monkeypatch, tmp_path: Path) -> None:
    projects_root = tmp_path / "projects"
    project_dir = _make_project(projects_root, "field-target-entity")
    monkeypatch.setenv("ARCHMIND_PROJECTS_DIR", str(projects_root))
    client = TestClient(create_ui_app())

    for entity in ("Task", "Reminder", "Test"):
        response = client.post(f"/ui/projects/{project_dir.name}/entities", json={"entity_name": entity})
        assert response.status_code == 200
        assert response.json().get("ok") is True

    response = client.post(
        f"/ui/projects/{project_dir.name}/fields",
        json={"entity_name": "Test", "field_name": "title", "field_type": "string"},
    )
    assert response.status_code == 200
    payload = response.json()
    assert payload["ok"] is True
    assert payload["entity_name"] == "Test"
    assert payload["field_name"] == "title"
    assert payload["field_type"] == "string"

    spec = json.loads((project_dir / ".archmind" / "project_spec.json").read_text(encoding="utf-8"))
    entities = spec.get("entities") if isinstance(spec.get("entities"), list) else []
    fields_by_entity = {
        str(item.get("name")): {
            str(field.get("name"))
            for field in (item.get("fields") or [])
            if isinstance(field, dict) and str(field.get("name") or "").strip()
        }
        for item in entities
        if isinstance(item, dict) and str(item.get("name") or "").strip()
    }
    assert "title" in fields_by_entity.get("Test", set())
    assert "title" not in fields_by_entity.get("Task", set())
    assert "title" not in fields_by_entity.get("Reminder", set())


def test_ui_fields_proxy_route_uses_json_body_with_expected_keys() -> None:
    route_path = Path("frontend/app/api/ui/projects/[project]/fields/route.ts")
    source = route_path.read_text(encoding="utf-8")

    assert "await request.json()" in source
    assert "entity_name" in source
    assert "field_name" in source
    assert "field_type" in source
    assert "body: JSON.stringify(body)" in source

    card_source = Path("frontend/components/AddFieldCard.tsx").read_text(encoding="utf-8")
    assert "entity_name: targetEntity" in card_source
    assert "field_name: targetFieldName" in card_source
    assert "field_type: targetFieldType" in card_source

    command_route_source = Path("frontend/app/api/ui/projects/[project]/commands/route.ts").read_text(encoding="utf-8")
    assert "/commands" in command_route_source
    assert "body: bodyText" in command_route_source

    next_action_source = Path("frontend/components/NextActionCard.tsx").read_text(encoding="utf-8")
    assert "/commands" in next_action_source
    assert "JSON.stringify({ command: normalizedCommand })" in next_action_source
    assert "parseNextCommand" not in next_action_source
    assert 'type RunState = "idle" | "running" | "success" | "error"' in next_action_source
    assert 'setRunState("running")' in next_action_source
    assert 'setRunState("success")' in next_action_source
    assert 'setRunState("error")' in next_action_source
    assert "Executed: {executedCommand}" in next_action_source
    assert "Refresh suggestions" in next_action_source
    assert '{runState === "running" ? "Running..." : runState === "success" ? "Completed" : "Run"}' in next_action_source


def test_frontend_ui_proxy_routes_use_single_backend_base_source_with_8000_default() -> None:
    backend_source = Path("frontend/app/api/ui/projects/_backend.ts").read_text(encoding="utf-8")
    assert "ARCHMIND_UI_API_BASE" in backend_source
    assert "http://127.0.0.1:8000/ui" in backend_source
    assert "8010" not in backend_source

    for route_path in Path("frontend/app/api/ui/projects").rglob("route.ts"):
        source = route_path.read_text(encoding="utf-8")
        assert "getBackendUiBase" in source
        assert "8010" not in source
        assert "ARCHMIND_UI_API_BASE ||" not in source


def test_dashboard_and_project_detail_share_ui_api_base_resolver() -> None:
    helper_source = Path("frontend/app/_lib/uiApiBase.ts").read_text(encoding="utf-8")
    assert "resolveUiApiBaseUrl" in helper_source
    assert '/api/ui' in helper_source

    dashboard_source = Path("frontend/app/dashboard/page.tsx").read_text(encoding="utf-8")
    project_detail_source = Path("frontend/app/projects/[project]/page.tsx").read_text(encoding="utf-8")
    assert 'from "@/app/_lib/uiApiBase"' in dashboard_source
    assert 'from "@/app/_lib/uiApiBase"' in project_detail_source
    assert "resolveUiApiBaseUrl()" in dashboard_source
    assert "resolveUiApiBaseUrl()" in project_detail_source
    assert "resolveApiBaseUrl" not in dashboard_source
    assert "resolveApiBaseUrl" not in project_detail_source


def test_project_detail_source_always_renders_structure_visualization_card() -> None:
    project_detail_source = Path("frontend/app/projects/[project]/page.tsx").read_text(encoding="utf-8")
    assert 'import StructureVisualizationCard from "@/components/StructureVisualizationCard"' in project_detail_source
    assert "<StructureVisualizationCard" in project_detail_source
    assert "&& <StructureVisualizationCard" not in project_detail_source
    assert "detail.analysis?.entity_graph &&" not in project_detail_source
    assert "detail.analysis?.api_map &&" not in project_detail_source
    assert "detail.analysis?.page_map &&" not in project_detail_source


def test_project_detail_source_renders_next_candidates_panel() -> None:
    project_detail_source = Path("frontend/app/projects/[project]/page.tsx").read_text(encoding="utf-8")
    assert 'import NextCandidatesCard from "@/components/NextCandidatesCard"' in project_detail_source
    assert "<NextCandidatesCard" in project_detail_source
    assert "candidates={analysis?.next_candidates}" in project_detail_source
    assert "&& <NextCandidatesCard" not in project_detail_source


def test_project_detail_source_renders_auto_control_panel() -> None:
    project_detail_source = Path("frontend/app/projects/[project]/page.tsx").read_text(encoding="utf-8")
    assert 'import AutoControlPanel from "@/components/AutoControlPanel"' in project_detail_source
    assert "<AutoControlPanel" in project_detail_source
    assert "autoSummary={detail.auto_summary}" in project_detail_source
    assert "&& <AutoControlPanel" not in project_detail_source


def test_project_detail_source_renders_command_console_panel() -> None:
    project_detail_source = Path("frontend/app/projects/[project]/page.tsx").read_text(encoding="utf-8")
    assert 'import CommandConsole from "@/components/CommandConsole"' in project_detail_source
    assert "<CommandConsole" in project_detail_source
    assert "projectName={detail.name}" in project_detail_source
    assert "&& <CommandConsole" not in project_detail_source


def test_project_detail_source_renders_evolution_history_panel() -> None:
    project_detail_source = Path("frontend/app/projects/[project]/page.tsx").read_text(encoding="utf-8")
    assert 'import EvolutionHistoryCard from "@/components/EvolutionHistoryCard"' in project_detail_source
    assert "<EvolutionHistoryCard" in project_detail_source
    assert "items={Array.isArray(detail.evolution_history) ? detail.evolution_history : []}" in project_detail_source
    assert "&& <EvolutionHistoryCard" not in project_detail_source


def test_project_detail_source_renders_inspect_overview_panel() -> None:
    project_detail_source = Path("frontend/app/projects/[project]/page.tsx").read_text(encoding="utf-8")
    assert 'import InspectOverviewCard from "@/components/InspectOverviewCard"' in project_detail_source
    assert "<InspectOverviewCard" in project_detail_source
    assert "project={detail}" in project_detail_source
    assert "&& <InspectOverviewCard" not in project_detail_source


def test_project_detail_source_renders_logs_viewer_panel() -> None:
    project_detail_source = Path("frontend/app/projects/[project]/page.tsx").read_text(encoding="utf-8")
    assert 'import LogsViewerCard from "@/components/LogsViewerCard"' in project_detail_source
    assert "<LogsViewerCard" in project_detail_source
    assert "projectName={detail.name}" in project_detail_source
    assert "initialLogs={detail.logs}" in project_detail_source
    assert "&& <LogsViewerCard" not in project_detail_source


def test_dashboard_source_renders_current_project_indicator() -> None:
    source = Path("frontend/app/dashboard/page.tsx").read_text(encoding="utf-8")
    assert 'import CurrentProjectIndicator from "@/components/CurrentProjectIndicator"' in source
    assert 'import NewProjectWizard from "@/components/NewProjectWizard"' in source
    assert 'import SettingsPanel from "@/components/SettingsPanel"' in source
    assert "<NewProjectWizard />" in source
    assert "<SettingsPanel />" in source
    assert "<CurrentProjectIndicator" in source
    assert "projectName={currentProjectName}" in source
    assert "displayName={String(currentProject?.display_name || currentProjectName || \"\")}" in source


def test_new_project_wizard_source_renders_fields_and_submit_contract() -> None:
    source = Path("frontend/components/NewProjectWizard.tsx").read_text(encoding="utf-8")
    assert '"use client";' in source
    assert "New Project" in source
    assert "Generate Project" in source
    assert "Generation Mode" in source
    assert "Project Language" in source
    assert "LLM Mode" in source
    assert "readArchmindSettings" in source
    assert "setTemplate(defaults.defaultTemplate)" in source
    assert "setMode(defaults.defaultMode)" in source
    assert "setLanguage(defaults.defaultLanguage)" in source
    assert "setLlmMode(defaults.defaultLLM)" in source
    assert "/projects/idea_local" in source
    assert "template," in source
    assert "mode," in source
    assert "language," in source
    assert "llm_mode: llmMode" in source
    assert 'router.push(`/projects/${encodeURIComponent(name)}`)' in source
    assert "Generating..." in source


def test_settings_panel_source_renders_sections_and_persists_to_local_storage() -> None:
    source = Path("frontend/components/SettingsPanel.tsx").read_text(encoding="utf-8")
    assert '"use client";' in source
    assert "Settings" in source
    assert "UI Language" in source
    assert "Layout Density" in source
    assert "Preview Mode" in source
    assert "Generation Defaults" in source
    assert "Default Template" in source
    assert "Default Generation Mode" in source
    assert "Default Project Language" in source
    assert "Default LLM Mode" in source
    assert "Advanced" in source
    assert "Developer Mode" in source
    assert "writeArchmindSettings(next)" in source
    assert "Settings saved" in source


def test_settings_store_source_uses_archmind_settings_key_with_safe_fallbacks() -> None:
    source = Path("frontend/components/settingsStore.ts").read_text(encoding="utf-8")
    assert "ARCHMIND_SETTINGS_KEY = \"archmind.settings\"" in source
    assert "window.localStorage.getItem(ARCHMIND_SETTINGS_KEY)" in source
    assert "window.localStorage.setItem(ARCHMIND_SETTINGS_KEY" in source
    assert "archmind.settings.generation_mode" in source
    assert "archmind.settings.project_language" in source
    assert "archmind.settings.llm_mode" in source


def test_current_project_indicator_component_tracks_local_context_and_syncs_current_project() -> None:
    source = Path("frontend/components/CurrentProjectIndicator.tsx").read_text(encoding="utf-8")
    assert '"use client";' in source
    assert "Current Project Context" in source
    assert "Current Project:" in source
    assert "archmind.currentProject" in source
    assert "localStorage.getItem" in source
    assert "localStorage.setItem" in source
    assert "/select" in source
    assert "setOnMount" in source
    assert "Commands from this view apply to this project context." in source
    assert "return null" not in source


def test_project_list_component_renders_strong_current_badge() -> None:
    source = Path("frontend/components/ProjectList.tsx").read_text(encoding="utf-8")
    assert "CURRENT" in source
    assert "Set current" in source


def test_project_list_component_renders_quick_actions_and_uses_card_scoped_command_path() -> None:
    source = Path("frontend/components/ProjectList.tsx").read_text(encoding="utf-8")
    assert "Open" in source
    assert "Inspect" in source
    assert "href={`/projects/${encodeURIComponent(name)}`}" in source
    assert "Auto" in source
    assert "Fix" in source
    assert "runQuickCommand" in source
    assert 'runQuickCommand(name, "/auto")' in source
    assert 'runQuickCommand(name, "/fix")' in source
    assert "/projects/${encodeURIComponent(target)}/commands" in source
    assert 'body: JSON.stringify({ command })' in source
    assert "disabled={isCommandRunning}" in source
    assert "name ? (" in source
    assert "Running..." in source
    assert "status: \"OK\"" in source
    assert "status: \"FAILED\"" in source


def test_project_detail_source_passes_project_name_to_command_panels_for_context_safety() -> None:
    source = Path("frontend/app/projects/[project]/page.tsx").read_text(encoding="utf-8")
    assert "NextActionCard projectName={detail.name}" in source
    assert "NextCandidatesCard projectName={detail.name}" in source
    assert "AutoControlPanel projectName={detail.name}" in source
    assert "CommandConsole projectName={detail.name}" in source
    assert "RuntimeActionsCard projectName={detail.name}" in source


def test_structure_visualization_component_has_robust_empty_states_and_no_null_bailout() -> None:
    source = Path("frontend/components/StructureVisualizationCard.tsx").read_text(encoding="utf-8")
    assert '"use client";' in source
    assert "/commands" in source
    assert "JSON.stringify({ command: normalizedCommand })" in source
    assert "Relation-scoped Gaps" in source
    assert "Relation Page Gaps" in source
    assert "Missing:" in source
    assert "Fixing..." in source
    assert "Fixed" in source
    assert "Structure visualization is not available yet." in source
    assert "No entities available." in source
    assert "No relations detected." in source
    assert "No API groups available." in source
    assert "No page groups available." in source
    assert "return null" not in source


def test_next_candidates_component_renders_empty_state_and_uses_command_execution_path() -> None:
    source = Path("frontend/components/NextCandidatesCard.tsx").read_text(encoding="utf-8")
    assert '"use client";' in source
    assert "Next Candidates" in source
    assert "No immediate next action." in source
    assert "/commands" in source
    assert "JSON.stringify({ command: normalizedCommand })" in source
    assert "Running..." in source
    assert "Completed" in source
    assert "Executed: {executedCommand}" in source
    assert "return null" not in source


def test_auto_control_panel_renders_states_and_uses_auto_command_path() -> None:
    source = Path("frontend/components/AutoControlPanel.tsx").read_text(encoding="utf-8")
    assert '"use client";' in source
    assert "Auto Control" in source
    assert "No auto run yet." in source
    assert "Latest Auto Result" in source
    assert "Strategy" in source
    assert "<option value=\"safe\">Safe</option>" in source
    assert "<option value=\"balanced\">Balanced</option>" in source
    assert "<option value=\"aggressive\">Aggressive</option>" in source
    assert "/commands" in source
    assert 'JSON.stringify({ command: "/auto", strategy: selectedStrategy })' in source
    assert "Running Auto..." in source
    assert "Auto failed:" in source
    assert "Failure reason:" in source
    assert "Last successful step:" in source
    assert "Suggested next action:" in source
    assert "Open Logs Viewer below, then run /fix or retry /auto." in source
    assert "Progress score:" in source
    assert "Strategy: {strategy}" in source
    assert "Plan Goal:" in source
    assert "Plan Reason:" in source
    assert "Planned Steps:" in source
    assert "Executed Steps:" in source
    assert "Skipped Steps:" in source
    assert "Goal satisfied:" in source
    assert "Runtime: backend=" in source
    assert "return null" not in source


def test_command_console_component_renders_input_and_uses_commands_execution_path() -> None:
    source = Path("frontend/components/CommandConsole.tsx").read_text(encoding="utf-8")
    assert '"use client";' in source
    assert "Command Console" in source
    assert "Enter command (e.g. /add_api GET /boards/{id}/cards)" in source
    assert "/commands" in source
    assert "JSON.stringify({ command })" in source
    assert "Running..." in source
    assert "Execute" in source
    assert "Command: {result.command}" in source
    assert "Status: {result.status}" in source
    assert "Summary: {result.summary || \"No summary available\"}" in source
    assert "Enter a command." in source
    assert "onSubmit={handleSubmit}" in source
    assert "No summary available" in source
    assert "classifyActionFailure" in source
    assert "classifyNetworkFailure" in source
    assert "recoveryHint" in source
    assert "return null" not in source


def test_project_list_component_surfaces_actionable_failure_messages_and_hints() -> None:
    source = Path("frontend/components/ProjectList.tsx").read_text(encoding="utf-8")
    assert "classifyActionFailure" in source
    assert "classifyNetworkFailure" in source
    assert "feedback.hint" in source


def test_frontend_action_error_helper_distinguishes_failure_kinds() -> None:
    source = Path("frontend/components/actionError.ts").read_text(encoding="utf-8")
    assert "backend_unavailable" in source
    assert "request_failure" in source
    assert "malformed_response" in source
    assert "execution_failure" in source
    assert "classifyActionFailure" in source
    assert "classifyNetworkFailure" in source


def test_evolution_history_component_has_empty_state_and_partial_payload_safety() -> None:
    source = Path("frontend/components/EvolutionHistoryCard.tsx").read_text(encoding="utf-8")
    assert '"use client";' in source
    assert "Evolution History" in source
    assert "No evolution history yet." in source
    assert "Array.isArray(items)" in source
    assert "Unknown action" in source
    assert "rows.length === 0" in source
    assert "suppressHydrationWarning" in source
    assert "new Date(" not in source
    assert "toLocaleString" not in source
    assert "Intl.DateTimeFormat" not in source
    assert "return null" not in source


def test_recent_runs_component_is_hydration_safe_for_server_timestamp_strings() -> None:
    source = Path("frontend/components/RecentRunsCard.tsx").read_text(encoding="utf-8")
    assert "suppressHydrationWarning" in source
    assert "new Date(" not in source
    assert "toLocaleString" not in source
    assert "Intl.DateTimeFormat" not in source


def test_logs_viewer_component_handles_sources_refresh_and_empty_states() -> None:
    source = Path("frontend/components/LogsViewerCard.tsx").read_text(encoding="utf-8")
    assert '"use client";' in source
    assert "Logs" in source
    assert "Refresh Logs" in source
    assert "Refreshing..." in source
    assert "/logs" in source
    assert "No logs available yet." in source
    assert "No " in source and "logs available." in source
    assert "max-h-80 overflow-auto" in source
    assert "return null" not in source


def test_inspect_overview_component_surfaces_inspect_grade_sections_and_safe_fallbacks() -> None:
    source = Path("frontend/components/InspectOverviewCard.tsx").read_text(encoding="utf-8")
    assert "Inspect Overview" in source
    assert "Spec Overview" in source
    assert "Architecture / Structure" in source
    assert "Entities & Fields" in source
    assert "APIs & Pages" in source
    assert "Relations & Drift" in source
    assert "Runtime / Repository / Sync" in source
    assert "Why Next?" in source
    assert "No domains available" in source
    assert "No drift warnings" in source
    assert "No immediate next rationale available." in source
    assert "return null" not in source


def test_ui_project_detail_includes_auto_summary_when_present(monkeypatch, tmp_path: Path) -> None:
    projects_root = tmp_path / "projects"
    _make_project(projects_root, "auto-summary-detail")
    monkeypatch.setenv("ARCHMIND_PROJECTS_DIR", str(projects_root))

    def _fake_build_project_detail(_project_dir: Path):
        from archmind.ui_models import ProjectDetailResponse, RuntimeSummary, SpecSummary

        return ProjectDetailResponse(
            name="auto-summary-detail",
            spec_summary=SpecSummary(stage="Stage 4", entities=2, apis=6, pages=6, history_count=1),
            entities=["Board", "Card"],
            runtime=RuntimeSummary(),
            auto_summary={
                "run_id": "auto-1",
                "strategy": "balanced",
                "executed": 2,
                "commands": ["/add_page cards/by_board", "/add_api GET /boards/{id}/cards"],
                "plan_goal": "complete_relation_flow",
                "plan_reason": "Board -> Card relation starter is incomplete",
                "planned_steps": [
                    {"command": "/add_api GET /boards/{id}/cards", "priority": "high"},
                    {"command": "/add_page cards/by_board", "priority": "high"},
                ],
                "executed_steps": [{"command": "/add_api GET /boards/{id}/cards", "priority": "high"}],
                "skipped_steps": [{"command": "/add_page cards/by_board", "reason": "stale_after_reanalysis"}],
                "goal_satisfied": True,
                "stop_reason": "good enough MVP reached",
                "stop_explanation": "Core CRUD and relation flow are complete.",
                "progress_made": True,
                "progress_score": 9,
            },
            analysis={"project_name": "auto-summary-detail", "next_action": {"kind": "none", "message": "No immediate suggestions.", "command": ""}},
            safe=True,
        )

    monkeypatch.setattr("archmind.ui_api.build_project_detail", _fake_build_project_detail)
    client = TestClient(create_ui_app())
    response = client.get("/ui/projects/auto-summary-detail")
    assert response.status_code == 200
    payload = response.json()
    assert payload["auto_summary"]["executed"] == 2
    assert payload["auto_summary"]["strategy"] == "balanced"
    assert payload["auto_summary"]["plan_goal"] == "complete_relation_flow"
    assert payload["auto_summary"]["goal_satisfied"] is True
    assert payload["auto_summary"]["planned_steps"][0]["command"] == "/add_api GET /boards/{id}/cards"
    assert payload["auto_summary"]["stop_reason"] == "good enough MVP reached"


def test_ui_project_detail_accepts_partial_evolution_history_payload(monkeypatch, tmp_path: Path) -> None:
    projects_root = tmp_path / "projects"
    _make_project(projects_root, "partial-evolution-history")
    monkeypatch.setenv("ARCHMIND_PROJECTS_DIR", str(projects_root))

    def _fake_build_project_detail(_project_dir: Path):
        from archmind.ui_models import ProjectDetailResponse, RuntimeSummary, SpecSummary

        return ProjectDetailResponse(
            name="partial-evolution-history",
            spec_summary=SpecSummary(),
            entities=[],
            runtime=RuntimeSummary(),
            evolution_history=[
                {"title": "/auto", "status": "STOPPED"},
                {"summary": "missing title is allowed"},
            ],
            analysis={"project_name": "partial-evolution-history"},
            safe=True,
        )

    monkeypatch.setattr("archmind.ui_api.build_project_detail", _fake_build_project_detail)
    client = TestClient(create_ui_app())
    response = client.get("/ui/projects/partial-evolution-history")
    assert response.status_code == 200
    payload = response.json()
    assert isinstance(payload["evolution_history"], list)
    assert payload["evolution_history"][0]["status"] == "STOPPED"
    assert "summary" in payload["evolution_history"][1]


def test_ui_run_command_auto_response_includes_auto_result(monkeypatch, tmp_path: Path) -> None:
    projects_root = tmp_path / "projects"
    _make_project(projects_root, "auto-command")
    monkeypatch.setenv("ARCHMIND_PROJECTS_DIR", str(projects_root))

    def _fake_execute_command(command: str, project_name: str, *, source: str = "manual-command", auto_strategy: str | None = None, **_: object) -> dict[str, object]:
        assert command == "/auto"
        assert project_name == "auto-command"
        assert source == "ui-next-run"
        assert auto_strategy == "safe"
        return {
            "ok": True,
            "project_name": project_name,
            "command": command,
            "detail": "Auto completed",
            "auto_result": {
                "run_id": "auto-2",
                "strategy": "safe",
                "executed": 1,
                "commands": ["/add_api GET /boards/{id}/cards"],
                "plan_goal": "complete_relation_flow",
                "goal_satisfied": False,
                "stop_reason": "no immediate next action",
                "stop_explanation": "Canonical analysis no longer returns an actionable next command.",
                "progress_made": True,
                "progress_score": 3,
            },
        }

    monkeypatch.setattr("archmind.ui_api.execute_command", _fake_execute_command)
    client = TestClient(create_ui_app())
    response = client.post("/ui/projects/auto-command/commands", json={"command": "/auto", "strategy": "safe"})
    assert response.status_code == 200
    payload = response.json()
    assert payload["ok"] is True
    assert payload["command"] == "/auto"
    assert payload["auto_result"]["run_id"] == "auto-2"
    assert payload["auto_result"]["strategy"] == "safe"
    assert payload["auto_result"]["executed"] == 1
    assert payload["auto_result"]["plan_goal"] == "complete_relation_flow"
    assert payload["auto_result"]["goal_satisfied"] is False


def test_ui_idea_local_accepts_extended_payload_and_returns_project_info(monkeypatch, tmp_path: Path) -> None:
    projects_root = tmp_path / "projects"
    projects_root.mkdir(parents=True, exist_ok=True)
    monkeypatch.setenv("ARCHMIND_PROJECTS_DIR", str(projects_root))

    captured: dict[str, str] = {}

    def _fake_start(*, idea: str, template: str, mode: str, language: str, llm_mode: str):  # type: ignore[no-untyped-def]
        captured["idea"] = idea
        captured["template"] = template
        captured["mode"] = mode
        captured["language"] = language
        captured["llm_mode"] = llm_mode
        return True, "demo_project", ""

    monkeypatch.setattr("archmind.ui_api._start_wizard_generation", _fake_start)
    client = TestClient(create_ui_app())
    response = client.post(
        "/ui/projects/idea_local",
        json={
            "idea": "todo app with deadlines",
            "template": "todo",
            "mode": "high_quality",
            "language": "korean",
            "llm_mode": "hybrid",
        },
    )
    assert response.status_code == 200
    payload = response.json()
    assert payload["ok"] is True
    assert payload["status"] == "STARTED"
    assert payload["project_name"] == "demo_project"
    assert captured["template"] == "todo"
    assert captured["mode"] == "high_quality"
    assert captured["language"] == "korean"
    assert captured["llm_mode"] == "hybrid"


def test_ui_idea_local_defaults_apply_when_optional_fields_missing(monkeypatch, tmp_path: Path) -> None:
    projects_root = tmp_path / "projects"
    projects_root.mkdir(parents=True, exist_ok=True)
    monkeypatch.setenv("ARCHMIND_PROJECTS_DIR", str(projects_root))

    captured: dict[str, str] = {}

    def _fake_start(*, idea: str, template: str, mode: str, language: str, llm_mode: str):  # type: ignore[no-untyped-def]
        captured["idea"] = idea
        captured["template"] = template
        captured["mode"] = mode
        captured["language"] = language
        captured["llm_mode"] = llm_mode
        return True, "demo_defaults", ""

    monkeypatch.setattr("archmind.ui_api._start_wizard_generation", _fake_start)
    client = TestClient(create_ui_app())
    response = client.post("/ui/projects/idea_local", json={"idea": "personal diary app"})
    assert response.status_code == 200
    payload = response.json()
    assert payload["ok"] is True
    assert payload["request"]["template"] == "auto"
    assert payload["request"]["mode"] == "balanced"
    assert payload["request"]["language"] == "english"
    assert payload["request"]["llm_mode"] == "local"
    assert captured["template"] == "auto"
    assert captured["mode"] == "balanced"
    assert captured["language"] == "english"
    assert captured["llm_mode"] == "local"


def test_ui_idea_local_invalid_request_is_handled_safely(monkeypatch, tmp_path: Path) -> None:
    projects_root = tmp_path / "projects"
    projects_root.mkdir(parents=True, exist_ok=True)
    monkeypatch.setenv("ARCHMIND_PROJECTS_DIR", str(projects_root))

    monkeypatch.setattr("archmind.ui_api._start_wizard_generation", lambda **_kwargs: (True, "unused", ""))
    client = TestClient(create_ui_app())
    response = client.post("/ui/projects/idea_local", json={"idea": ""})
    assert response.status_code == 200
    payload = response.json()
    assert payload["ok"] is False
    assert payload["status"] == "INVALID"
    assert "idea is required" in str(payload["error"]).lower()


def test_ui_project_detail_normalizes_partial_auto_summary_plan_fields(monkeypatch, tmp_path: Path) -> None:
    projects_root = tmp_path / "projects"
    project_dir = _make_project(projects_root, "partial-auto-summary")
    monkeypatch.setenv("ARCHMIND_PROJECTS_DIR", str(projects_root))
    state = {
        "auto_last_result": {
            "run_id": "auto-partial",
            "plan_goal": "complete_crud_gap",
            "goal_satisfied": True,
            "planned_steps": [{"command": "/add_api GET /tasks"}],
            "executed_steps": [],
            "skipped_steps": [{"command": "/add_page tasks/list"}],
            "stop_explanation": "Goal satisfied by first step.",
        }
    }
    write_state(project_dir, state)

    client = TestClient(create_ui_app())
    response = client.get("/ui/projects/partial-auto-summary")
    assert response.status_code == 200
    payload = response.json()
    summary = payload["auto_summary"]
    assert summary["plan_goal"] == "complete_crud_gap"
    assert summary["goal_satisfied"] is True
    assert summary["planned_steps"][0]["command"] == "/add_api GET /tasks"
    assert isinstance(summary["executed_steps"], list)
    assert isinstance(summary["skipped_steps"], list)


def test_ui_evolution_history_auto_summary_is_enriched_when_plan_context_exists(monkeypatch, tmp_path: Path) -> None:
    projects_root = tmp_path / "projects"
    project_dir = _make_project(projects_root, "auto-history-enriched")
    monkeypatch.setenv("ARCHMIND_PROJECTS_DIR", str(projects_root))
    assert append_execution_event(
        project_dir,
        project_name="auto-history-enriched",
        source="telegram-auto",
        command="/auto",
        status="stop",
        message="Stopped",
        stop_reason="no material progress",
        timestamp="2026-03-22T01:00:02Z",
    )
    write_state(
        project_dir,
        {
            "auto_last_result": {
                "plan_goal": "complete_crud_gap",
                "goal_satisfied": False,
                "stop_reason": "no material progress",
            }
        },
    )

    client = TestClient(create_ui_app())
    response = client.get("/ui/projects/auto-history-enriched")
    assert response.status_code == 200
    payload = response.json()
    history = payload["evolution_history"]
    assert history[0]["title"] == "/auto"
    assert history[0]["summary"] == "complete_crud_gap - stopped: no material progress"


def test_ui_project_detail_tolerates_partial_visualization_analysis_payload(monkeypatch, tmp_path: Path) -> None:
    projects_root = tmp_path / "projects"
    _make_project(projects_root, "partial-viz")
    monkeypatch.setenv("ARCHMIND_PROJECTS_DIR", str(projects_root))

    def _partial_detail(_project_dir: Path):
        from archmind.ui_models import ProjectDetailResponse, RuntimeSummary, SpecSummary

        return ProjectDetailResponse(
            name="partial-viz",
            spec_summary=SpecSummary(stage="Stage 4", entities=1, apis=1, pages=1, history_count=0),
            entities=["Note"],
            runtime=RuntimeSummary(),
            analysis={
                "project_name": "partial-viz",
                "next_action": {"kind": "none", "message": "No immediate suggestions.", "command": ""},
                "entity_graph": {"nodes": [{"label": "Note"}], "edges": []},
                # api_map/page_map intentionally omitted to simulate partial payload
            },
            safe=True,
        )

    monkeypatch.setattr("archmind.ui_api.build_project_detail", _partial_detail)
    client = TestClient(create_ui_app())
    response = client.get("/ui/projects/partial-viz")
    assert response.status_code == 200
    payload = response.json()
    assert payload["analysis"]["entity_graph"]["nodes"][0]["label"] == "Note"
    assert "api_map" not in payload["analysis"] or isinstance(payload["analysis"].get("api_map"), dict)
    assert "page_map" not in payload["analysis"] or isinstance(payload["analysis"].get("page_map"), dict)


def test_ui_add_field_rejects_empty_inputs_safely(monkeypatch, tmp_path: Path) -> None:
    projects_root = tmp_path / "projects"
    _make_project(projects_root, "field-empty")
    monkeypatch.setenv("ARCHMIND_PROJECTS_DIR", str(projects_root))
    client = TestClient(create_ui_app())

    response = client.post(
        "/ui/projects/field-empty/fields",
        json={"entity_name": " ", "field_name": " ", "field_type": " "},
    )
    assert response.status_code == 200
    payload = response.json()
    assert payload["ok"] is False
    assert payload["project_name"] == "field-empty"
    assert "invalid field input" in str(payload["detail"]).lower()


def test_ui_add_field_rejects_invalid_field_name_safely(monkeypatch, tmp_path: Path) -> None:
    projects_root = tmp_path / "projects"
    _make_project(projects_root, "field-invalid")
    monkeypatch.setenv("ARCHMIND_PROJECTS_DIR", str(projects_root))
    client = TestClient(create_ui_app())

    response = client.post(
        "/ui/projects/field-invalid/fields",
        json={"entity_name": "Note", "field_name": "123-priority", "field_type": "int"},
    )
    assert response.status_code == 200
    payload = response.json()
    assert payload["ok"] is False
    assert payload["project_name"] == "field-invalid"
    assert payload["field_name"] == "123-priority"
    assert "invalid field name" in str(payload["detail"]).lower()


def test_ui_add_field_duplicate_is_safe(monkeypatch, tmp_path: Path) -> None:
    projects_root = tmp_path / "projects"
    _make_project(projects_root, "field-duplicate")
    monkeypatch.setenv("ARCHMIND_PROJECTS_DIR", str(projects_root))
    client = TestClient(create_ui_app())

    response = client.post(
        "/ui/projects/field-duplicate/fields",
        json={"entity_name": "Note", "field_name": "title", "field_type": "string"},
    )
    assert response.status_code == 200
    payload = response.json()
    assert payload["ok"] is False
    assert payload["project_name"] == "field-duplicate"
    assert payload["entity_name"] == "Note"
    assert payload["field_name"] == "title"
    assert payload["field_type"] == "string"
    assert "already exists" in str(payload["detail"]).lower()


def test_ui_add_api_succeeds_and_returns_updated_spec(monkeypatch, tmp_path: Path) -> None:
    projects_root = tmp_path / "projects"
    _make_project(projects_root, "api-project")
    monkeypatch.setenv("ARCHMIND_PROJECTS_DIR", str(projects_root))
    client = TestClient(create_ui_app())

    response = client.post(
        "/ui/projects/api-project/apis",
        json={"method": "GET", "path": "/reports"},
    )
    assert response.status_code == 200
    payload = response.json()
    assert payload["ok"] is True
    assert payload["project_name"] == "api-project"
    assert payload["method"] == "GET"
    assert payload["path"] == "/reports"
    assert payload["spec_summary"]["apis"] >= 2
    assert any("add_api GET /reports" in str(item) for item in payload["recent_evolution"])

    detail_response = client.get("/ui/projects/api-project")
    assert detail_response.status_code == 200
    detail_payload = detail_response.json()
    assert detail_payload["spec_summary"]["apis"] >= 2
    assert any("add_api GET /reports" in str(item) for item in detail_payload["recent_evolution"])


def test_ui_add_api_rejects_empty_values_safely(monkeypatch, tmp_path: Path) -> None:
    projects_root = tmp_path / "projects"
    _make_project(projects_root, "api-empty")
    monkeypatch.setenv("ARCHMIND_PROJECTS_DIR", str(projects_root))
    client = TestClient(create_ui_app())

    response = client.post(
        "/ui/projects/api-empty/apis",
        json={"method": " ", "path": " "},
    )
    assert response.status_code == 200
    payload = response.json()
    assert payload["ok"] is False
    assert payload["project_name"] == "api-empty"
    assert "invalid api input" in str(payload["detail"]).lower()


def test_ui_add_api_duplicate_is_safe(monkeypatch, tmp_path: Path) -> None:
    projects_root = tmp_path / "projects"
    _make_project(projects_root, "api-duplicate")
    monkeypatch.setenv("ARCHMIND_PROJECTS_DIR", str(projects_root))
    client = TestClient(create_ui_app())

    response = client.post(
        "/ui/projects/api-duplicate/apis",
        json={"method": "GET", "path": "/notes"},
    )
    assert response.status_code == 200
    payload = response.json()
    assert payload["ok"] is False
    assert payload["project_name"] == "api-duplicate"
    assert payload["method"] == "GET"
    assert payload["path"] == "/notes"
    assert "already exists" in str(payload["detail"]).lower()


def test_ui_add_api_put_is_accepted_via_shared_normalization(monkeypatch, tmp_path: Path) -> None:
    projects_root = tmp_path / "projects"
    _make_project(projects_root, "api-put")
    monkeypatch.setenv("ARCHMIND_PROJECTS_DIR", str(projects_root))
    client = TestClient(create_ui_app())

    response = client.post(
        "/ui/projects/api-put/apis",
        json={"method": "PUT", "path": "/reports/{id}"},
    )
    assert response.status_code == 200
    payload = response.json()
    assert payload["ok"] is True
    assert payload["project_name"] == "api-put"
    assert payload["method"] == "PATCH"
    assert payload["path"] == "/reports/{id}"


def test_ui_add_page_succeeds_and_returns_updated_spec(monkeypatch, tmp_path: Path) -> None:
    projects_root = tmp_path / "projects"
    _make_project(projects_root, "page-project")
    monkeypatch.setenv("ARCHMIND_PROJECTS_DIR", str(projects_root))
    client = TestClient(create_ui_app())

    response = client.post(
        "/ui/projects/page-project/pages",
        json={"page_path": "dashboard/home"},
    )
    assert response.status_code == 200
    payload = response.json()
    assert payload["ok"] is True
    assert payload["project_name"] == "page-project"
    assert payload["page_path"] == "dashboard/home"
    assert payload["spec_summary"]["pages"] >= 2
    assert any("add_page dashboard/home" in str(item) for item in payload["recent_evolution"])

    detail_response = client.get("/ui/projects/page-project")
    assert detail_response.status_code == 200
    detail_payload = detail_response.json()
    assert detail_payload["spec_summary"]["pages"] >= 2
    assert any("add_page dashboard/home" in str(item) for item in detail_payload["recent_evolution"])


def test_ui_add_page_rejects_empty_path_safely(monkeypatch, tmp_path: Path) -> None:
    projects_root = tmp_path / "projects"
    _make_project(projects_root, "page-empty")
    monkeypatch.setenv("ARCHMIND_PROJECTS_DIR", str(projects_root))
    client = TestClient(create_ui_app())

    response = client.post(
        "/ui/projects/page-empty/pages",
        json={"page_path": " "},
    )
    assert response.status_code == 200
    payload = response.json()
    assert payload["ok"] is False
    assert payload["project_name"] == "page-empty"
    assert "invalid page path" in str(payload["detail"]).lower()


def test_ui_add_page_rejects_invalid_path_safely(monkeypatch, tmp_path: Path) -> None:
    projects_root = tmp_path / "projects"
    _make_project(projects_root, "page-invalid")
    monkeypatch.setenv("ARCHMIND_PROJECTS_DIR", str(projects_root))
    client = TestClient(create_ui_app())

    response = client.post(
        "/ui/projects/page-invalid/pages",
        json={"page_path": "invalid path"},
    )
    assert response.status_code == 200
    payload = response.json()
    assert payload["ok"] is False
    assert payload["project_name"] == "page-invalid"
    assert payload["page_path"] == "invalid path"
    assert "invalid page path" in str(payload["detail"]).lower()


def test_ui_add_page_duplicate_is_safe(monkeypatch, tmp_path: Path) -> None:
    projects_root = tmp_path / "projects"
    _make_project(projects_root, "page-duplicate")
    monkeypatch.setenv("ARCHMIND_PROJECTS_DIR", str(projects_root))
    client = TestClient(create_ui_app())

    response = client.post(
        "/ui/projects/page-duplicate/pages",
        json={"page_path": "notes/list"},
    )
    assert response.status_code == 200
    payload = response.json()
    assert payload["ok"] is False
    assert payload["project_name"] == "page-duplicate"
    assert payload["page_path"] == "notes/list"
    assert "already exists" in str(payload["detail"]).lower()


def test_ui_implement_page_succeeds_for_placeholder(monkeypatch, tmp_path: Path) -> None:
    projects_root = tmp_path / "projects"
    project_dir = _make_project(projects_root, "implement-page")
    target_page = project_dir / "frontend" / "app" / "reports" / "list" / "page.tsx"
    target_page.parent.mkdir(parents=True, exist_ok=True)
    target_page.write_text(
        '"use client";\n'
        "export default function ReportsListPage(){\n"
        "  return <p>Page placeholder for reports/list</p>;\n"
        "}\n",
        encoding="utf-8",
    )
    spec_path = project_dir / ".archmind" / "project_spec.json"
    spec_payload = json.loads(spec_path.read_text(encoding="utf-8"))
    spec_payload["frontend_pages"] = ["reports/list"]
    spec_path.write_text(json.dumps(spec_payload, ensure_ascii=False, indent=2), encoding="utf-8")
    monkeypatch.setenv("ARCHMIND_PROJECTS_DIR", str(projects_root))
    client = TestClient(create_ui_app())

    response = client.post("/ui/projects/implement-page/implement-page", json={"page_path": "reports/list"})
    assert response.status_code == 200
    payload = response.json()
    assert payload["ok"] is True
    assert payload["project_name"] == "implement-page"
    assert payload["page_path"] == "reports/list"
    assert "Implemented page: reports/list" in str(payload["detail"])


def test_ui_implement_page_returns_already_implemented_info(monkeypatch, tmp_path: Path) -> None:
    projects_root = tmp_path / "projects"
    project_dir = _make_project(projects_root, "implement-page-ready")
    target_page = project_dir / "frontend" / "app" / "reports" / "list" / "page.tsx"
    target_page.parent.mkdir(parents=True, exist_ok=True)
    target_page.write_text(
        '"use client";\n'
        'import { useApiBaseUrl } from "../../_lib/apiBase";\n'
        "export default function ReportsListPage(){\n"
        "  const { apiBaseUrl } = useApiBaseUrl();\n"
        "  return <div>{apiBaseUrl}</div>;\n"
        "}\n",
        encoding="utf-8",
    )
    spec_path = project_dir / ".archmind" / "project_spec.json"
    spec_payload = json.loads(spec_path.read_text(encoding="utf-8"))
    spec_payload["frontend_pages"] = ["reports/list"]
    spec_path.write_text(json.dumps(spec_payload, ensure_ascii=False, indent=2), encoding="utf-8")
    monkeypatch.setenv("ARCHMIND_PROJECTS_DIR", str(projects_root))
    client = TestClient(create_ui_app())

    response = client.post("/ui/projects/implement-page-ready/implement-page", json={"page_path": "reports/list"})
    assert response.status_code == 200
    payload = response.json()
    assert payload["ok"] is True
    assert payload["project_name"] == "implement-page-ready"
    assert payload["page_path"] == "reports/list"
    assert "Page already implemented: reports/list" in str(payload["detail"])


def test_ui_implement_page_returns_not_found_error(monkeypatch, tmp_path: Path) -> None:
    projects_root = tmp_path / "projects"
    project_dir = _make_project(projects_root, "implement-page-missing")
    (project_dir / "frontend" / "app").mkdir(parents=True, exist_ok=True)
    (project_dir / "frontend" / "package.json").write_text('{"name":"frontend"}\n', encoding="utf-8")
    monkeypatch.setenv("ARCHMIND_PROJECTS_DIR", str(projects_root))
    client = TestClient(create_ui_app())

    response = client.post("/ui/projects/implement-page-missing/implement-page", json={"page_path": "reports/list"})
    assert response.status_code == 200
    payload = response.json()
    assert payload["ok"] is False
    assert payload["project_name"] == "implement-page-missing"
    assert payload["page_path"] == "reports/list"
    assert "page not found" in str(payload["detail"]).lower()


def test_ui_display_name_falls_back_to_identifier(monkeypatch, tmp_path: Path) -> None:
    projects_root = tmp_path / "projects"
    project_dir = projects_root / "safe-id"
    archmind_dir = project_dir / ".archmind"
    archmind_dir.mkdir(parents=True, exist_ok=True)
    write_state(
        project_dir,
        {
            "effective_template": "fullstack-ddd",
            "architecture_app_shape": "fullstack",
            "provider": {"mode": "local"},
        },
    )
    (archmind_dir / "project_spec.json").write_text(json.dumps({"shape": "fullstack"}), encoding="utf-8")
    monkeypatch.setenv("ARCHMIND_PROJECTS_DIR", str(projects_root))
    client = TestClient(create_ui_app())

    response = client.get("/ui/projects")
    assert response.status_code == 200
    payload = response.json()
    assert payload["projects"][0]["name"] == "safe-id"
    assert payload["projects"][0]["display_name"] == "safe-id"


def test_ui_korean_project_identifier_route_works(monkeypatch, tmp_path: Path) -> None:
    projects_root = tmp_path / "projects"
    project_name = "프로젝트-한글"
    _make_project(projects_root, project_name, display_name="표시 전용 이름")
    monkeypatch.setenv("ARCHMIND_PROJECTS_DIR", str(projects_root))
    client = TestClient(create_ui_app())

    response = client.get(f"/ui/projects/{quote(project_name)}")
    assert response.status_code == 200
    payload = response.json()
    assert payload["name"] == project_name
    assert payload["display_name"] == "표시 전용 이름"


def test_ui_project_detail_uses_stable_name_not_display_name(monkeypatch, tmp_path: Path) -> None:
    projects_root = tmp_path / "projects"
    _make_project(projects_root, "stable-id", display_name="한글 표시명")
    monkeypatch.setenv("ARCHMIND_PROJECTS_DIR", str(projects_root))
    client = TestClient(create_ui_app())

    response = client.get(f"/ui/projects/{quote('한글 표시명')}")
    assert response.status_code == 404

    response = client.get("/ui/projects/stable-id")
    assert response.status_code == 200
    assert response.json()["display_name"] == "한글 표시명"


def test_ui_runtime_action_endpoints(monkeypatch, tmp_path: Path) -> None:
    projects_root = tmp_path / "projects"
    _make_project(projects_root, "runtime-project")
    monkeypatch.setenv("ARCHMIND_PROJECTS_DIR", str(projects_root))

    monkeypatch.setattr(
        "archmind.ui_api.get_local_runtime_status",
        lambda _project_dir: {
            "backend": {"status": "RUNNING", "url": "http://127.0.0.1:8000"},
            "frontend": {"status": "RUNNING", "url": "http://127.0.0.1:3000"},
        },
    )
    monkeypatch.setattr(
        "archmind.ui_api.run_project_backend",
        lambda _project_dir: {"ok": True, "status": "SUCCESS", "detail": "backend started"},
    )
    monkeypatch.setattr(
        "archmind.ui_api.run_project_all",
        lambda _project_dir: {"ok": True, "status": "SUCCESS", "detail": "all started"},
    )
    monkeypatch.setattr(
        "archmind.ui_api.restart_project_runtime",
        lambda _project_dir: {"ok": True, "status": "SUCCESS", "detail": "restarted"},
    )
    monkeypatch.setattr(
        "archmind.ui_api.stop_project_runtime",
        lambda _project_dir: {"ok": True, "status": "SUCCESS", "detail": "stopped"},
    )

    client = TestClient(create_ui_app())
    for action in ("run-backend", "run-all", "restart", "stop"):
        response = client.post(f"/ui/projects/runtime-project/{action}")
        assert response.status_code == 200
        payload = response.json()
        assert payload["ok"] is True
        assert payload["backend_status"] == "RUNNING"
        assert payload["frontend_status"] == "RUNNING"
        assert payload["backend_url"] == "http://127.0.0.1:8000"
        assert payload["frontend_url"] == "http://127.0.0.1:3000"
        assert payload["error"] == ""


def test_ui_delete_local_action_does_not_call_repo_delete(monkeypatch, tmp_path: Path) -> None:
    projects_root = tmp_path / "projects"
    _make_project(projects_root, "delete-local-only")
    monkeypatch.setenv("ARCHMIND_PROJECTS_DIR", str(projects_root))
    calls = {"local": 0, "repo": 0}

    def fake_local(_project_dir: Path):  # type: ignore[no-untyped-def]
        calls["local"] += 1
        return {
            "ok": True,
            "mode": "local",
            "local_status": "DELETED",
            "local_detail": "local project directory deleted",
            "repo_status": "UNCHANGED",
            "repo_detail": "",
            "stop": {
                "backend": {"status": "STOPPED"},
                "frontend": {"status": "STOPPED"},
            },
        }

    def fake_repo(_project_dir: Path):  # type: ignore[no-untyped-def]
        calls["repo"] += 1
        return {"ok": True}

    monkeypatch.setattr("archmind.ui_api.delete_project_local", fake_local)
    monkeypatch.setattr("archmind.ui_api.delete_project_repo", fake_repo)

    client = TestClient(create_ui_app())
    response = client.post("/ui/projects/delete-local-only/delete-local")
    assert response.status_code == 200
    payload = response.json()
    assert payload["ok"] is True
    assert payload["action"] == "delete-local"
    assert payload["project_name"] == "delete-local-only"
    assert payload["local_deleted"] is True
    assert payload["github_deleted"] is False
    assert payload["runtime_stopped"] is True
    assert calls["local"] == 1
    assert calls["repo"] == 0


def test_ui_delete_repo_action_is_separate_from_local(monkeypatch, tmp_path: Path) -> None:
    projects_root = tmp_path / "projects"
    _make_project(projects_root, "delete-repo-only")
    monkeypatch.setenv("ARCHMIND_PROJECTS_DIR", str(projects_root))
    calls = {"local": 0, "repo": 0}

    def fake_local(_project_dir: Path):  # type: ignore[no-untyped-def]
        calls["local"] += 1
        return {"ok": True}

    def fake_repo(_project_dir: Path):  # type: ignore[no-untyped-def]
        calls["repo"] += 1
        return {
            "ok": True,
            "mode": "repo",
            "repo_status": "DELETED",
            "repo_detail": "github repository deleted",
            "repo_slug": "example/demo",
        }

    monkeypatch.setattr("archmind.ui_api.delete_project_local", fake_local)
    monkeypatch.setattr("archmind.ui_api.delete_project_repo", fake_repo)
    client = TestClient(create_ui_app())
    response = client.post("/ui/projects/delete-repo-only/delete-repo")
    assert response.status_code == 200
    payload = response.json()
    assert payload["ok"] is True
    assert payload["local_deleted"] is False
    assert payload["github_deleted"] is True
    assert payload["runtime_stopped"] is False
    assert calls["repo"] == 1
    assert calls["local"] == 0


def test_ui_delete_all_reports_partial_failure_safely(monkeypatch, tmp_path: Path) -> None:
    projects_root = tmp_path / "projects"
    _make_project(projects_root, "delete-all-mixed")
    monkeypatch.setenv("ARCHMIND_PROJECTS_DIR", str(projects_root))
    monkeypatch.setattr(
        "archmind.ui_api.delete_project_all",
        lambda _project_dir: {
            "ok": False,
            "mode": "all",
            "local_status": "DELETED",
            "local_detail": "local project directory deleted",
            "repo_status": "FAIL",
            "repo_detail": "github repo delete failed",
            "stop": {"backend": {"status": "STOPPED"}, "frontend": {"status": "STOPPED"}},
        },
    )

    client = TestClient(create_ui_app())
    response = client.post("/ui/projects/delete-all-mixed/delete-all")
    assert response.status_code == 200
    payload = response.json()
    assert payload["ok"] is False
    assert payload["local_deleted"] is True
    assert payload["github_deleted"] is False
    assert payload["runtime_stopped"] is True
    assert "github repo delete failed" in payload["error"]


def test_ui_delete_local_removes_project_from_projects_list(tmp_path: Path, monkeypatch) -> None:
    projects_root = tmp_path / "projects"
    project_dir = _make_project(projects_root, "to-be-deleted")
    monkeypatch.setenv("ARCHMIND_PROJECTS_DIR", str(projects_root))
    client = TestClient(create_ui_app())

    before = client.get("/ui/projects")
    assert before.status_code == 200
    before_names = {item["name"] for item in before.json().get("projects", [])}
    assert "to-be-deleted" in before_names
    assert project_dir.exists()

    deleted = client.post("/ui/projects/to-be-deleted/delete-local")
    assert deleted.status_code == 200
    payload = deleted.json()
    assert payload["ok"] is True
    assert payload["local_deleted"] is True
    assert not project_dir.exists()

    after = client.get("/ui/projects")
    assert after.status_code == 200
    after_names = {item["name"] for item in after.json().get("projects", [])}
    assert "to-be-deleted" not in after_names


def test_ui_runtime_url_expansion_with_lan_and_tailscale(monkeypatch, tmp_path: Path) -> None:
    projects_root = tmp_path / "projects"
    _make_project(projects_root, "runtime-url-project")
    monkeypatch.setenv("ARCHMIND_PROJECTS_DIR", str(projects_root))
    monkeypatch.setenv("ARCHMIND_UI_RUNTIME_HOSTS_PATH", str(tmp_path / "ui_runtime_hosts.json"))
    monkeypatch.setenv("ARCHMIND_LAN_HOST", "192.168.0.197")
    monkeypatch.setenv("ARCHMIND_TAILSCALE_HOST", "100.117.128.20")
    monkeypatch.setattr(
        "archmind.project_query.get_local_runtime_status",
        lambda _project_dir: {
            "backend": {"status": "RUNNING", "url": "http://127.0.0.1:8123"},
            "frontend": {"status": "RUNNING", "url": "http://127.0.0.1:3123"},
        },
    )

    client = TestClient(create_ui_app())
    response = client.get("/ui/projects/runtime-url-project")
    assert response.status_code == 200
    payload = response.json()
    runtime = payload["runtime"]
    assert runtime["backend_urls"] == [
        "http://127.0.0.1:8123",
        "http://192.168.0.197:8123",
        "http://100.117.128.20:8123",
    ]
    assert runtime["frontend_urls"] == [
        "http://127.0.0.1:3123",
        "http://192.168.0.197:3123",
        "http://100.117.128.20:3123",
    ]


def test_ui_runtime_url_expansion_auto_detects_lan_without_env(monkeypatch, tmp_path: Path) -> None:
    projects_root = tmp_path / "projects"
    _make_project(projects_root, "runtime-auto-lan")
    monkeypatch.setenv("ARCHMIND_PROJECTS_DIR", str(projects_root))
    monkeypatch.setenv("ARCHMIND_UI_RUNTIME_HOSTS_PATH", str(tmp_path / "ui_runtime_hosts.json"))
    monkeypatch.delenv("ARCHMIND_LAN_HOST", raising=False)
    monkeypatch.delenv("ARCHMIND_TAILSCALE_HOST", raising=False)
    monkeypatch.setattr("archmind.project_query._detect_lan_host", lambda: "192.168.0.201")
    monkeypatch.setattr("archmind.project_query._detect_tailscale_host", lambda: "")
    monkeypatch.setattr(
        "archmind.project_query.get_local_runtime_status",
        lambda _project_dir: {
            "backend": {"status": "RUNNING", "url": "http://127.0.0.1:8222"},
            "frontend": {"status": "RUNNING", "url": "http://127.0.0.1:3222"},
        },
    )

    client = TestClient(create_ui_app())
    response = client.get("/ui/projects/runtime-auto-lan")
    assert response.status_code == 200
    runtime = response.json()["runtime"]
    assert runtime["backend_urls"] == ["http://127.0.0.1:8222", "http://192.168.0.201:8222"]
    assert runtime["frontend_urls"] == ["http://127.0.0.1:3222", "http://192.168.0.201:3222"]


def test_ui_runtime_url_expansion_auto_detects_tailscale_without_env(monkeypatch, tmp_path: Path) -> None:
    projects_root = tmp_path / "projects"
    _make_project(projects_root, "runtime-auto-ts")
    monkeypatch.setenv("ARCHMIND_PROJECTS_DIR", str(projects_root))
    monkeypatch.setenv("ARCHMIND_UI_RUNTIME_HOSTS_PATH", str(tmp_path / "ui_runtime_hosts.json"))
    monkeypatch.delenv("ARCHMIND_LAN_HOST", raising=False)
    monkeypatch.delenv("ARCHMIND_TAILSCALE_HOST", raising=False)
    monkeypatch.setattr("archmind.project_query._detect_lan_host", lambda: "")
    monkeypatch.setattr("archmind.project_query._detect_tailscale_host", lambda: "100.117.128.20")
    monkeypatch.setattr(
        "archmind.project_query.get_local_runtime_status",
        lambda _project_dir: {
            "backend": {"status": "RUNNING", "url": "http://127.0.0.1:8333"},
            "frontend": {"status": "RUNNING", "url": "http://127.0.0.1:3333"},
        },
    )

    client = TestClient(create_ui_app())
    response = client.get("/ui/projects/runtime-auto-ts")
    assert response.status_code == 200
    runtime = response.json()["runtime"]
    assert runtime["backend_urls"] == ["http://127.0.0.1:8333", "http://100.117.128.20:8333"]
    assert runtime["frontend_urls"] == ["http://127.0.0.1:3333", "http://100.117.128.20:3333"]


def test_ui_runtime_url_expansion_loopback_only_when_no_detection(monkeypatch, tmp_path: Path) -> None:
    projects_root = tmp_path / "projects"
    _make_project(projects_root, "runtime-loopback-only")
    monkeypatch.setenv("ARCHMIND_PROJECTS_DIR", str(projects_root))
    monkeypatch.setenv("ARCHMIND_UI_RUNTIME_HOSTS_PATH", str(tmp_path / "ui_runtime_hosts.json"))
    monkeypatch.delenv("ARCHMIND_LAN_HOST", raising=False)
    monkeypatch.delenv("ARCHMIND_TAILSCALE_HOST", raising=False)
    monkeypatch.setattr("archmind.project_query._detect_lan_host", lambda: "")
    monkeypatch.setattr("archmind.project_query._detect_tailscale_host", lambda: "")
    monkeypatch.setattr(
        "archmind.project_query.get_local_runtime_status",
        lambda _project_dir: {
            "backend": {"status": "RUNNING", "url": "http://127.0.0.1:8444"},
            "frontend": {"status": "RUNNING", "url": "http://127.0.0.1:3444"},
        },
    )

    client = TestClient(create_ui_app())
    response = client.get("/ui/projects/runtime-loopback-only")
    assert response.status_code == 200
    runtime = response.json()["runtime"]
    assert runtime["backend_urls"] == ["http://127.0.0.1:8444"]
    assert runtime["frontend_urls"] == ["http://127.0.0.1:3444"]


def test_ui_runtime_url_expansion_uses_persisted_hosts_when_env_missing(monkeypatch, tmp_path: Path) -> None:
    projects_root = tmp_path / "projects"
    _make_project(projects_root, "runtime-persisted-hosts")
    monkeypatch.setenv("ARCHMIND_PROJECTS_DIR", str(projects_root))
    hosts_path = tmp_path / "ui_runtime_hosts.json"
    hosts_path.write_text('{"lan_host":"192.168.0.250","tailscale_host":"100.64.0.8"}', encoding="utf-8")
    monkeypatch.setenv("ARCHMIND_UI_RUNTIME_HOSTS_PATH", str(hosts_path))
    monkeypatch.delenv("ARCHMIND_LAN_HOST", raising=False)
    monkeypatch.delenv("ARCHMIND_TAILSCALE_HOST", raising=False)
    monkeypatch.setattr("archmind.project_query._detect_lan_host", lambda: "")
    monkeypatch.setattr("archmind.project_query._detect_tailscale_host", lambda: "")
    monkeypatch.setattr(
        "archmind.project_query.get_local_runtime_status",
        lambda _project_dir: {
            "backend": {"status": "RUNNING", "url": "http://127.0.0.1:8555"},
            "frontend": {"status": "RUNNING", "url": "http://127.0.0.1:3555"},
        },
    )

    client = TestClient(create_ui_app())
    response = client.get("/ui/projects/runtime-persisted-hosts")
    assert response.status_code == 200
    runtime = response.json()["runtime"]
    assert runtime["backend_urls"] == [
        "http://127.0.0.1:8555",
        "http://192.168.0.250:8555",
        "http://100.64.0.8:8555",
    ]
    assert runtime["frontend_urls"] == [
        "http://127.0.0.1:3555",
        "http://192.168.0.250:3555",
        "http://100.64.0.8:3555",
    ]


def test_ui_runtime_action_failure_detail_propagation(monkeypatch, tmp_path: Path) -> None:
    projects_root = tmp_path / "projects"
    _make_project(projects_root, "runtime-fail")
    monkeypatch.setenv("ARCHMIND_PROJECTS_DIR", str(projects_root))
    monkeypatch.setattr(
        "archmind.ui_api.get_local_runtime_status",
        lambda _project_dir: {
            "backend": {"status": "FAIL", "url": ""},
            "frontend": {"status": "STOPPED", "url": ""},
        },
    )
    monkeypatch.setattr(
        "archmind.ui_api.run_project_backend",
        lambda _project_dir: {
            "ok": False,
            "status": "FAIL",
            "detail": "backend start failed",
            "error": "port already in use",
        },
    )

    client = TestClient(create_ui_app())
    response = client.post("/ui/projects/runtime-fail/run-backend")
    assert response.status_code == 200
    payload = response.json()
    assert payload["ok"] is False
    assert payload["detail"] == "backend start failed"
    assert payload["error"] == "port already in use"


def test_ui_projects_list_tolerates_broken_project_metadata(monkeypatch, tmp_path: Path) -> None:
    projects_root = tmp_path / "projects"
    _make_project(projects_root, "good")
    _make_project(projects_root, "broken")
    monkeypatch.setenv("ARCHMIND_PROJECTS_DIR", str(projects_root))

    def fake_runtime(project_dir: Path):  # type: ignore[no-untyped-def]
        if project_dir.name == "broken":
            raise RuntimeError("runtime state corrupted")
        return {
            "backend": {"status": "STOPPED", "url": ""},
            "frontend": {"status": "STOPPED", "url": ""},
        }

    monkeypatch.setattr("archmind.project_query.get_local_runtime_status", fake_runtime)
    client = TestClient(create_ui_app())
    response = client.get("/ui/projects")
    assert response.status_code == 200
    payload = response.json()
    rows = {item["name"]: item for item in payload["projects"]}
    assert "good" in rows
    assert "broken" in rows
    assert rows["good"]["warning"] == ""
    assert "Failed to inspect project metadata" in rows["broken"]["warning"]


def test_ui_project_detail_returns_safe_fallback_when_runtime_breaks(monkeypatch, tmp_path: Path) -> None:
    projects_root = tmp_path / "projects"
    _make_project(projects_root, "broken")
    monkeypatch.setenv("ARCHMIND_PROJECTS_DIR", str(projects_root))

    monkeypatch.setattr("archmind.project_query.get_local_runtime_status", lambda _project_dir: (_ for _ in ()).throw(RuntimeError("bad runtime block")))
    client = TestClient(create_ui_app())
    response = client.get("/ui/projects/broken")
    assert response.status_code == 200
    payload = response.json()
    assert payload["name"] == "broken"
    assert payload["safe"] is True
    assert "Failed to load full project detail" in payload["warning"]
    assert payload["runtime"]["backend_status"] == "STOPPED"


def test_ui_provider_route_returns_structured_error_on_unexpected_exception(monkeypatch, tmp_path: Path) -> None:
    projects_root = tmp_path / "projects"
    _make_project(projects_root, "alpha")
    monkeypatch.setenv("ARCHMIND_PROJECTS_DIR", str(projects_root))
    monkeypatch.setattr("archmind.ui_api.build_project_detail", lambda _project_dir: (_ for _ in ()).throw(RuntimeError("detail explode")))

    client = TestClient(create_ui_app())
    response = client.get("/ui/projects/alpha/provider")
    assert response.status_code == 500
    payload = response.json()
    assert payload["detail"] == "Failed to load provider data"
    assert "detail explode" in payload["error"]
    assert payload["project_name"] == "alpha"
    assert payload["safe"] is True


def test_ui_projects_route_returns_structured_error_when_listing_fails(monkeypatch) -> None:
    monkeypatch.setattr("archmind.ui_api.list_project_dirs", lambda: (_ for _ in ()).throw(RuntimeError("cannot scan projects")))
    client = TestClient(create_ui_app())
    response = client.get("/ui/projects")
    assert response.status_code == 500
    payload = response.json()
    assert payload["detail"] == "Failed to load projects"
    assert "cannot scan projects" in payload["error"]
    assert payload["safe"] is True


def test_ui_runtime_action_route_handles_unexpected_exception(monkeypatch, tmp_path: Path) -> None:
    projects_root = tmp_path / "projects"
    _make_project(projects_root, "runtime-broken")
    monkeypatch.setenv("ARCHMIND_PROJECTS_DIR", str(projects_root))
    monkeypatch.setattr("archmind.ui_api.run_project_backend", lambda _project_dir: (_ for _ in ()).throw(RuntimeError("start exploded")))

    client = TestClient(create_ui_app())
    response = client.post("/ui/projects/runtime-broken/run-backend")
    assert response.status_code == 200
    payload = response.json()
    assert payload["ok"] is False
    assert payload["status"] == "FAIL"
    assert payload["detail"] == "Failed to run action"
    assert "start exploded" in payload["error"]
