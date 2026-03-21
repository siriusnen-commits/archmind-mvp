from __future__ import annotations

import json
from pathlib import Path

from fastapi.testclient import TestClient

from archmind.state import write_state
from archmind.telegram_bot import clear_current_project, set_current_project
from archmind.ui_api import create_ui_app


def _make_project(
    base: Path,
    name: str,
    *,
    provider_mode: str = "local",
    with_evolution: bool = True,
    display_name: str = "",
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
            "repository": {"status": "CREATED", "url": f"https://github.com/example/{name}"},
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
        "type",
        "template",
        "backend_url",
        "frontend_url",
        "is_current",
    ):
        assert key in item
    assert item["display_name"] == "alpha"
    assert item["status"] in {"RUNNING", "STOPPED", "FAIL"}
    assert item["backend_url"] == ""
    assert item["frontend_url"] == ""


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
    assert "runtime" in payload
    assert "recent_evolution" in payload
    assert "repository" in payload
    assert payload["spec_summary"]["stage"].startswith("Stage")


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
