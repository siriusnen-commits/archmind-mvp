from __future__ import annotations

import importlib
import os
import sys
from pathlib import Path

from archmind.generator import GenerateOptions, apply_frontend_page_scaffold, generate_project


def _generate_fullstack(tmp_path: Path, name: str = "fullstack_demo") -> Path:
    opt = GenerateOptions(out=tmp_path, force=False, name=name, template="fullstack-ddd")
    project_dir = generate_project("defect tracker", opt)
    return Path(project_dir)


def _import_app(project_dir: Path, db_url: str):
    prev = os.environ.get("DB_URL")
    os.environ["DB_URL"] = db_url
    db_path = db_url.replace("sqlite:///", "", 1)
    if db_path:
        Path(db_path).parent.mkdir(parents=True, exist_ok=True)
    backend_dir = project_dir / "backend"
    sys.path.insert(0, str(backend_dir))
    try:
        from sqlmodel import SQLModel

        SQLModel.metadata.clear()
        for mod in list(sys.modules):
            if mod == "app" or mod.startswith("app."):
                del sys.modules[mod]
        module = importlib.import_module("app.main")
        from app.db.session import init_db

        init_db()
        return module.app
    finally:
        if str(backend_dir) in sys.path:
            sys.path.remove(str(backend_dir))
        if prev is None:
            os.environ.pop("DB_URL", None)
        else:
            os.environ["DB_URL"] = prev


def test_fullstack_ddd_template_pytest_passes(tmp_path: Path) -> None:
    import subprocess

    project_dir = _generate_fullstack(tmp_path)
    result = subprocess.run(
        [sys.executable, "-m", "pytest", "-q"],
        cwd=project_dir / "backend",
        capture_output=True,
        text=True,
        timeout=120,
    )
    assert result.returncode == 0, result.stderr


def test_defects_query_sort_pagination(tmp_path: Path) -> None:
    project_dir = _generate_fullstack(tmp_path)
    db_path = project_dir / "backend" / "data" / "test.db"
    db_url = f"sqlite:///{db_path}"
    app = _import_app(project_dir, db_url)

    from fastapi.testclient import TestClient

    client = TestClient(app)
    for dtype in ["HDMI_CEC", "HDMI_ARC", "USB_POWER"]:
        r = client.post("/defects", json={"defect_type": dtype, "note": f"note {dtype}"})
        assert r.status_code == 200

    r = client.get("/defects", params={"defect_type": "HDMI"})
    assert r.status_code == 200
    data = r.json()
    assert data["total"] == 2

    r = client.get("/defects", params={"q": "USB"})
    assert r.status_code == 200
    assert r.json()["total"] == 1

    r = client.get("/defects", params={"page": 1, "page_size": 2})
    assert r.status_code == 200
    assert len(r.json()["items"]) == 2

    r = client.get("/defects", params={"sort": "id", "order": "asc"})
    assert r.status_code == 200
    ids = [item["id"] for item in r.json()["items"]]
    assert ids == sorted(ids)


def test_fullstack_defects_persist_crud_across_backend_reload(tmp_path: Path) -> None:
    project_dir = _generate_fullstack(tmp_path, name="defect_persistence")
    db_path = project_dir / "backend" / "data" / "defect_persistence.db"
    db_url = f"sqlite:///{db_path}"
    app = _import_app(project_dir, db_url)

    from fastapi.testclient import TestClient

    client = TestClient(app)
    create = client.post("/defects", json={"defect_type": "HDMI_CEC", "note": "first"})
    assert create.status_code == 200
    defect_id = int(create.json()["id"])

    app_reloaded = _import_app(project_dir, db_url)
    client_reloaded = TestClient(app_reloaded)

    listing = client_reloaded.get("/defects")
    assert listing.status_code == 200
    ids = [int(item["id"]) for item in listing.json()["items"]]
    assert defect_id in ids

    update = client_reloaded.put(f"/defects/{defect_id}", json={"note": "updated"})
    assert update.status_code == 200
    assert update.json()["note"] == "updated"

    app_reloaded_again = _import_app(project_dir, db_url)
    client_reloaded_again = TestClient(app_reloaded_again)
    persisted_listing = client_reloaded_again.get("/defects")
    assert persisted_listing.status_code == 200
    persisted_rows = persisted_listing.json()["items"]
    persisted_row = next((item for item in persisted_rows if int(item["id"]) == defect_id), None)
    assert persisted_row is not None
    assert persisted_row["note"] == "updated"

    delete = client_reloaded_again.delete(f"/defects/{defect_id}")
    assert delete.status_code == 200

    app_reloaded_after_delete = _import_app(project_dir, db_url)
    client_reloaded_after_delete = TestClient(app_reloaded_after_delete)
    listing_after_delete = client_reloaded_after_delete.get("/defects")
    assert listing_after_delete.status_code == 200
    ids_after_delete = [int(item["id"]) for item in listing_after_delete.json()["items"]]
    assert defect_id not in ids_after_delete


def test_pipeline_generate_and_run_backend_only(tmp_path: Path) -> None:
    from archmind.cli import main

    exit_code = main(
        [
            "pipeline",
            "--idea",
            "defect tracker",
            "--template",
            "fullstack-ddd",
            "--out",
            str(tmp_path),
            "--name",
            "fs_pipeline",
            "--backend-only",
            "--max-iterations",
            "1",
            "--model",
            "none",
        ]
    )
    assert exit_code == 0

    project_dir = tmp_path / "fs_pipeline"
    log_dir = project_dir / ".archmind" / "run_logs"
    assert log_dir.exists()
    assert list(log_dir.glob("run_*.summary.txt"))


def test_fullstack_frontend_start_script_is_runtime_neutral(tmp_path: Path) -> None:
    project_dir = _generate_fullstack(tmp_path, name="fullstack_runtime_neutral")
    package_text = (project_dir / "frontend" / "package.json").read_text(encoding="utf-8")
    assert '"start": "sh -c \'next start -p ${PORT:-3000}\'"' in package_text
    assert not (project_dir / "main.py").exists()
    assert (project_dir / "backend" / "app" / "main.py").exists()


def test_fullstack_runtime_env_template_uses_api_base_url_and_settings(tmp_path: Path) -> None:
    project_dir = _generate_fullstack(tmp_path, name="fullstack_runtime_env")
    settings_text = (project_dir / "backend" / "app" / "core" / "settings.py").read_text(encoding="utf-8")
    frontend_env_example = (project_dir / "frontend" / ".env.example").read_text(encoding="utf-8")
    frontend_page = (project_dir / "frontend" / "app" / "ui" / "DefectsPage.tsx").read_text(encoding="utf-8")
    frontend_api_helper = (project_dir / "frontend" / "app" / "_lib" / "apiBase.ts").read_text(encoding="utf-8")
    backend_main = (project_dir / "backend" / "app" / "main.py").read_text(encoding="utf-8")
    root_page = (project_dir / "frontend" / "app" / "page.tsx").read_text(encoding="utf-8")
    layout_page = (project_dir / "frontend" / "app" / "layout.tsx").read_text(encoding="utf-8")
    defects_route = (project_dir / "frontend" / "app" / "ui" / "defects" / "page.tsx").read_text(encoding="utf-8")
    navigation_file = (project_dir / "frontend" / "app" / "_lib" / "navigation.ts").read_text(encoding="utf-8")

    assert "cors_allow_origins" in settings_text
    assert "from fastapi.middleware.cors import CORSMiddleware" in backend_main
    assert "app.add_middleware(" in backend_main
    assert 'allow_origins=["*"]' in backend_main
    assert "allow_credentials=True" in backend_main
    assert 'allow_methods=["*"]' in backend_main
    assert 'allow_headers=["*"]' in backend_main
    assert "NEXT_PUBLIC_API_BASE_URL=" in frontend_env_example
    assert "NEXT_PUBLIC_RUNTIME_BACKEND_URL=" in frontend_env_example
    assert "NEXT_PUBLIC_FRONTEND_PORT=" in frontend_env_example
    assert "NEXT_PUBLIC_API_BASE_URL=http://127.0.0.1:8000" not in frontend_env_example
    assert "NEXT_PUBLIC_RUNTIME_BACKEND_URL=http://127.0.0.1:8000" not in frontend_env_example
    assert 'useApiBaseUrl' in frontend_page
    assert 'from "../_lib/apiBase"' in frontend_page
    assert "useApiBaseUrl" in frontend_api_helper
    assert "setApiBaseUrl(resolveRuntimeApiBaseUrl())" in frontend_api_helper
    assert 'typeof window === "undefined"' in frontend_api_helper
    assert "ENV_RUNTIME_BACKEND_URL" in frontend_api_helper
    assert "const explicitApiBase = String(ENV_API_BASE || \"\").trim();" in frontend_api_helper
    assert "const runtimeBackendBase = String(ENV_RUNTIME_BACKEND_URL || \"\").trim();" in frontend_api_helper
    assert "rewriteLoopbackToBrowserHost" in frontend_api_helper
    assert "window.location.hostname" in frontend_api_helper
    assert "LOOPBACK_HOSTS" in frontend_api_helper
    assert "parsed.hostname = browserHost" in frontend_api_helper
    assert 'return "http://127.0.0.1:8000";' in frontend_api_helper
    assert "NEXT_PUBLIC_BACKEND_URL" not in frontend_page
    assert "Backend: {backendUrl}" not in frontend_page
    assert 'Backend: {apiBaseLoading ? "(resolving...)" : apiBaseUrl}' in frontend_page
    assert 'from "./_lib/apiBase"' in root_page
    assert 'from "./_lib/navigation"' in root_page
    assert "APP_NAV_LINKS" in root_page
    assert "primaryHref" in root_page
    assert "useApiBaseUrl()" in root_page
    assert 'API: {apiBaseLoading ? "(resolving...)" : apiBaseUrl}' in root_page
    assert "router.replace(primaryHref)" in root_page
    assert "APP_NAV_LINKS.map" in layout_page
    assert '/ui/defects", label: "Defects", primary: true' in navigation_file
    assert "DefectsPage" not in root_page
    assert "Defect Ledger" not in layout_page
    assert "FastAPI + Next.js workspace" in layout_page
    assert "DefectsPage" in defects_route


def test_fullstack_note_project_has_note_oriented_shell_and_pages(tmp_path: Path) -> None:
    project_dir = _generate_fullstack(tmp_path, name="memo_workspace")
    layout_page = (project_dir / "frontend" / "app" / "layout.tsx").read_text(encoding="utf-8")
    root_page = (project_dir / "frontend" / "app" / "page.tsx").read_text(encoding="utf-8")
    notes_page = (project_dir / "frontend" / "app" / "notes" / "page.tsx").read_text(encoding="utf-8")
    note_detail_page = (project_dir / "frontend" / "app" / "notes" / "[id]" / "page.tsx").read_text(encoding="utf-8")
    navigation_file = (project_dir / "frontend" / "app" / "_lib" / "navigation.ts").read_text(encoding="utf-8")
    backend_router = (project_dir / "backend" / "app" / "api" / "router.py").read_text(encoding="utf-8")
    backend_notes_router = (project_dir / "backend" / "app" / "api" / "routers" / "notes.py").read_text(encoding="utf-8")

    assert "/ui/defects" not in layout_page
    assert "/ui/defects" not in root_page
    assert "/notes" in notes_page
    assert "/notes/" in note_detail_page
    assert "Create note" in notes_page
    assert "Create your first note above." in notes_page
    assert "Save changes" in note_detail_page
    assert "Delete note" in note_detail_page
    assert '/notes", label: "Notes", primary: true' in navigation_file
    assert "notes_router" in backend_router
    assert "defects_router" not in backend_router
    assert 'prefix="/notes"' in backend_notes_router
    assert not (project_dir / "backend" / "app" / "api" / "routers" / "defects.py").exists()
    assert not (project_dir / "frontend" / "app" / "ui" / "DefectsPage.tsx").exists()


def test_fullstack_note_project_backend_and_frontend_are_aligned_on_notes_routes(tmp_path: Path) -> None:
    project_dir = _generate_fullstack(tmp_path, name="memo_alignment")
    db_path = project_dir / "backend" / "data" / "note.db"
    db_url = f"sqlite:///{db_path}"
    app = _import_app(project_dir, db_url)

    from fastapi.testclient import TestClient

    client = TestClient(app)

    create = client.post("/notes", json={"title": "first memo", "content": "hello"})
    assert create.status_code == 200
    note_id = create.json()["id"]

    listing = client.get("/notes")
    assert listing.status_code == 200
    assert listing.json()["total"] >= 1

    detail = client.get(f"/notes/{note_id}")
    assert detail.status_code == 200
    assert detail.json()["title"] == "first memo"

    update = client.put(f"/notes/{note_id}", json={"title": "updated memo", "content": "updated"})
    assert update.status_code == 200
    assert update.json()["title"] == "updated memo"

    delete = client.delete(f"/notes/{note_id}")
    assert delete.status_code == 200

    assert client.post("/defects", json={"defect_type": "x", "note": "y"}).status_code == 404


def test_fullstack_note_project_persists_crud_across_backend_reload(tmp_path: Path) -> None:
    project_dir = _generate_fullstack(tmp_path, name="memo_persistence")
    db_path = project_dir / "backend" / "data" / "memo_persistence.db"
    db_url = f"sqlite:///{db_path}"
    app = _import_app(project_dir, db_url)

    from fastapi.testclient import TestClient

    client = TestClient(app)
    create = client.post("/notes", json={"title": "first memo", "content": "hello"})
    assert create.status_code == 200
    note_id = int(create.json()["id"])

    app_reloaded = _import_app(project_dir, db_url)
    client_reloaded = TestClient(app_reloaded)

    listing = client_reloaded.get("/notes")
    assert listing.status_code == 200
    ids = [int(item["id"]) for item in listing.json()["items"]]
    assert note_id in ids

    detail = client_reloaded.get(f"/notes/{note_id}")
    assert detail.status_code == 200
    assert detail.json()["content"] == "hello"

    update = client_reloaded.patch(f"/notes/{note_id}", json={"content": "updated memo"})
    assert update.status_code == 200
    assert update.json()["content"] == "updated memo"

    app_reloaded_again = _import_app(project_dir, db_url)
    client_reloaded_again = TestClient(app_reloaded_again)
    persisted_detail = client_reloaded_again.get(f"/notes/{note_id}")
    assert persisted_detail.status_code == 200
    assert persisted_detail.json()["content"] == "updated memo"

    delete = client_reloaded_again.delete(f"/notes/{note_id}")
    assert delete.status_code == 200

    app_reloaded_after_delete = _import_app(project_dir, db_url)
    client_reloaded_after_delete = TestClient(app_reloaded_after_delete)
    assert client_reloaded_after_delete.get(f"/notes/{note_id}").status_code == 404


def test_fullstack_note_project_surfaces_newly_added_entity_pages_in_navigation(tmp_path: Path) -> None:
    project_dir = _generate_fullstack(tmp_path, name="memo_growth")
    apply_frontend_page_scaffold(project_dir, "Task")

    nav_text = (project_dir / "frontend" / "app" / "_lib" / "navigation.ts").read_text(encoding="utf-8")
    assert 'href: "/notes"' in nav_text
    assert 'href: "/tasks"' in nav_text
