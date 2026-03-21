from __future__ import annotations

import json
from pathlib import Path
from urllib.parse import quote

from fastapi.testclient import TestClient

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
        "type",
        "template",
        "backend_url",
        "frontend_url",
        "repository",
        "is_current",
        "warning",
    ):
        assert key in item
    assert item["display_name"] == "alpha"
    assert item["status"] in {"RUNNING", "STOPPED", "FAIL"}
    assert item["backend_url"] == ""
    assert item["frontend_url"] == ""
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
    assert payload["repository"]["status"] == "CREATED"
    assert payload["repository"]["url"] == "https://github.com/example/beta"
    assert "warning" in payload
    assert "safe" in payload
    assert "backend_urls" in payload["runtime"]
    assert "frontend_urls" in payload["runtime"]
    assert payload["spec_summary"]["stage"].startswith("Stage")


def test_ui_projects_response_includes_safe_repository_when_missing(monkeypatch, tmp_path: Path) -> None:
    projects_root = tmp_path / "projects"
    _make_project(projects_root, "no-repo", repository={"status": "SKIPPED", "url": ""})
    monkeypatch.setenv("ARCHMIND_PROJECTS_DIR", str(projects_root))
    client = TestClient(create_ui_app())

    response = client.get("/ui/projects")
    assert response.status_code == 200
    item = response.json()["projects"][0]
    assert "repository" in item
    assert item["repository"]["status"] == "SKIPPED"
    assert item["repository"]["url"] == ""


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
    assert item["repository"]["status"] == "CREATED"
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
    _make_project(projects_root, "repo-missing", repository={"status": "SKIPPED", "url": ""})
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
