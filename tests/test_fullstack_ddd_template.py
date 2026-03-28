from __future__ import annotations

import importlib
import os
import subprocess
import sys
from pathlib import Path

from archmind.generator import GenerateOptions, generate_project


def _generate_fullstack(tmp_path: Path, name: str = "fullstack_demo", spec: dict | None = None) -> Path:
    opt = GenerateOptions(out=tmp_path, force=False, name=name, template="fullstack-ddd")
    if spec is not None:
        setattr(opt, "project_spec", spec)
    project_dir = generate_project("personal diary webapp", opt)
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
        for mod in list(sys.modules):
            if mod == "app" or mod.startswith("app."):
                del sys.modules[mod]
        module = importlib.import_module("app.main")
        return module.app
    finally:
        if str(backend_dir) in sys.path:
            sys.path.remove(str(backend_dir))
        if prev is None:
            os.environ.pop("DB_URL", None)
        else:
            os.environ["DB_URL"] = prev


def test_fullstack_ddd_template_backend_pytest_passes(tmp_path: Path) -> None:
    project_dir = _generate_fullstack(tmp_path)
    result = subprocess.run(
        [sys.executable, "-m", "pytest", "-q"],
        cwd=project_dir / "backend",
        capture_output=True,
        text=True,
        timeout=120,
    )
    assert result.returncode == 0, result.stderr


def test_fullstack_template_is_domain_neutral_for_diary_generation(tmp_path: Path) -> None:
    project_dir = _generate_fullstack(tmp_path, name="diary_webapp")

    frontend_root = project_dir / "frontend" / "app"
    backend_root = project_dir / "backend" / "app"

    collected = []
    for path in list(frontend_root.rglob("*.ts")) + list(frontend_root.rglob("*.tsx")) + list(backend_root.rglob("*.py")):
        collected.append(path.read_text(encoding="utf-8"))
    merged = "\n".join(collected).lower()

    assert "defect" not in merged
    assert "hdmi_cec" not in merged
    assert "defect intake" not in merged
    assert "create note" not in merged
    assert (project_dir / "frontend" / "app" / "page.tsx").exists()
    assert (project_dir / "backend" / "app" / "api" / "routers" / "health.py").exists()


def test_fullstack_scaffolds_entities_and_pages_from_project_spec(tmp_path: Path) -> None:
    spec = {
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
    project_dir = _generate_fullstack(tmp_path, name="diary_spec", spec=spec)

    entry_router = project_dir / "backend" / "app" / "routers" / "entry.py"
    main_file = project_dir / "backend" / "app" / "main.py"
    entry_model = project_dir / "backend" / "app" / "models" / "entry.py"
    frontend_entries = project_dir / "frontend" / "app" / "entries" / "page.tsx"
    navigation_file = project_dir / "frontend" / "app" / "_lib" / "navigation.ts"
    frontend_root = project_dir / "frontend" / "app" / "page.tsx"
    frontend_layout = project_dir / "frontend" / "app" / "layout.tsx"
    frontend_eslint = project_dir / "frontend" / ".eslintrc.json"

    assert entry_router.exists()
    assert entry_model.exists()
    assert frontend_entries.exists()
    assert navigation_file.exists()
    assert frontend_root.exists()
    assert frontend_layout.exists()
    assert frontend_eslint.exists()

    assert "title: str" in entry_model.read_text(encoding="utf-8")
    assert "content: str" in entry_model.read_text(encoding="utf-8")
    assert "from app.routers.entry import router as entry_router" in main_file.read_text(encoding="utf-8")
    assert 'fetch(`${apiBaseUrl}/entries`' in frontend_entries.read_text(encoding="utf-8")
    assert 'href: "/entries"' in navigation_file.read_text(encoding="utf-8")
    assert "ArchMind Fullstack Workspace" not in frontend_root.read_text(encoding="utf-8")
    assert "This scaffold is domain-neutral." not in frontend_root.read_text(encoding="utf-8")
    assert 'from "./_lib/navigation"' in frontend_root.read_text(encoding="utf-8")
    assert "APP_NAV_LINKS.map" in frontend_layout.read_text(encoding="utf-8")
    assert frontend_eslint.read_text(encoding="utf-8").strip() == '{\n  "extends": ["next/core-web-vitals"]\n}'


def test_fullstack_scaffolds_all_entities_and_pages_from_multi_entity_spec(tmp_path: Path) -> None:
    spec = {
        "entities": [
            {
                "name": "Entry",
                "fields": [
                    {"name": "title", "type": "string"},
                    {"name": "content", "type": "string"},
                ],
            },
            {
                "name": "Tag",
                "fields": [
                    {"name": "name", "type": "string"},
                ],
            },
        ],
        "api_endpoints": ["GET /entries", "POST /entries", "GET /tags", "POST /tags"],
        "frontend_pages": ["entries/list", "entries/new", "tags/list"],
    }
    project_dir = _generate_fullstack(tmp_path, name="diary_spec_multi", spec=spec)

    assert (project_dir / "backend" / "app" / "routers" / "entry.py").exists()
    assert (project_dir / "backend" / "app" / "routers" / "tag.py").exists()
    assert (project_dir / "frontend" / "app" / "entries" / "page.tsx").exists()
    assert (project_dir / "frontend" / "app" / "entries" / "new" / "page.tsx").exists()
    assert (project_dir / "frontend" / "app" / "tags" / "page.tsx").exists()

    nav_text = (project_dir / "frontend" / "app" / "_lib" / "navigation.ts").read_text(encoding="utf-8")
    assert 'href: "/entries"' in nav_text
    assert 'href: "/tags"' in nav_text
    assert 'href: "/entries/new"' in nav_text


def test_fullstack_spec_driven_crud_works_for_diary_entry(tmp_path: Path) -> None:
    spec = {
        "entities": [
            {
                "name": "Entry",
                "fields": [
                    {"name": "title", "type": "string"},
                    {"name": "content", "type": "string"},
                ],
            }
        ]
    }
    project_dir = _generate_fullstack(tmp_path, name="diary_crud", spec=spec)
    db_path = project_dir / "backend" / "data" / "entry.db"
    app = _import_app(project_dir, f"sqlite:///{db_path}")

    from fastapi.testclient import TestClient

    client = TestClient(app)

    create = client.post("/entries", json={"title": "day 1", "content": "hello"})
    assert create.status_code == 200
    entry_id = int(create.json()["id"])

    listing = client.get("/entries")
    assert listing.status_code == 200
    items = listing.json()
    assert any(int(item["id"]) == entry_id for item in items)

    detail = client.get(f"/entries/{entry_id}")
    assert detail.status_code == 200
    assert detail.json()["title"] == "day 1"

    update = client.patch(f"/entries/{entry_id}", json={"content": "updated"})
    assert update.status_code == 200
    assert update.json()["content"] == "updated"

    delete = client.delete(f"/entries/{entry_id}")
    assert delete.status_code == 200
    assert client.get(f"/entries/{entry_id}").status_code == 404
