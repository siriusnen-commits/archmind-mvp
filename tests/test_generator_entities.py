from __future__ import annotations

import importlib
import json
import os
import subprocess
import sys
from pathlib import Path

from archmind.generator import (
    GenerateOptions,
    apply_api_scaffold,
    apply_entity_fields_to_scaffold,
    apply_entity_scaffold,
    apply_frontend_page_scaffold,
    apply_page_scaffold,
    ensure_runtime_gitignore,
    generate_project,
    implement_page_scaffold,
)


def _import_generated_backend_app(project_dir: Path, db_url: str):
    prev = os.environ.get("DB_URL")
    os.environ["DB_URL"] = db_url
    sys.path.insert(0, str(project_dir))
    try:
        for mod in list(sys.modules):
            if mod == "app" or mod.startswith("app."):
                del sys.modules[mod]
        module = importlib.import_module("app.main")
        return module.app
    finally:
        if str(project_dir) in sys.path:
            sys.path.remove(str(project_dir))
        if prev is None:
            os.environ.pop("DB_URL", None)
        else:
            os.environ["DB_URL"] = prev


def test_apply_entity_scaffold_creates_backend_persistent_router_files(tmp_path: Path) -> None:
    project_dir = tmp_path / "backend_demo"
    (project_dir / "app").mkdir(parents=True, exist_ok=True)
    (project_dir / "requirements.txt").write_text("fastapi\n", encoding="utf-8")
    (project_dir / "app" / "main.py").write_text("from fastapi import FastAPI\n\napp = FastAPI()\n", encoding="utf-8")

    generated = apply_entity_scaffold(project_dir, "Task")

    assert "app/models/task.py" in generated
    assert "app/schemas/task.py" in generated
    assert "app/routers/task.py" in generated
    assert "app/main.py" in generated
    assert (project_dir / "app" / "models" / "task.py").exists()
    assert (project_dir / "app" / "schemas" / "task.py").exists()
    assert (project_dir / "app" / "routers" / "task.py").exists()
    router_text = (project_dir / "app" / "routers" / "task.py").read_text(encoding="utf-8")
    assert "def list_tasks()" in router_text
    assert "def create_task(payload: dict[str, Any] = Body(default_factory=dict))" in router_text
    assert "def get_task(id: int)" in router_text
    assert "def update_task(id: int, payload: dict[str, Any] = Body(default_factory=dict))" in router_text
    assert "def delete_task(id: int)" in router_text
    assert "sqlite3.connect" in router_text
    assert "CREATE TABLE IF NOT EXISTS" in router_text


def test_apply_entity_scaffold_router_persists_crud_across_app_reload(tmp_path: Path) -> None:
    from fastapi.testclient import TestClient

    project_dir = tmp_path / "backend_demo"
    (project_dir / "app").mkdir(parents=True, exist_ok=True)
    (project_dir / "requirements.txt").write_text("fastapi\n", encoding="utf-8")
    (project_dir / "app" / "main.py").write_text("from fastapi import FastAPI\n\napp = FastAPI()\n", encoding="utf-8")
    apply_entity_scaffold(project_dir, "Note")

    db_path = project_dir / "data" / "notes.db"
    db_url = f"sqlite:///{db_path}"

    app_first = _import_generated_backend_app(project_dir, db_url)
    client = TestClient(app_first)

    create = client.post("/notes", json={"title": "first memo", "content": "hello"})
    assert create.status_code == 200
    created = create.json()
    note_id = int(created["id"])
    assert created["title"] == "first memo"

    listing = client.get("/notes")
    assert listing.status_code == 200
    ids = [int(item["id"]) for item in listing.json()]
    assert note_id in ids

    detail = client.get(f"/notes/{note_id}")
    assert detail.status_code == 200
    assert detail.json()["title"] == "first memo"

    update = client.patch(f"/notes/{note_id}", json={"content": "updated content"})
    assert update.status_code == 200
    assert update.json()["content"] == "updated content"

    app_reloaded = _import_generated_backend_app(project_dir, db_url)
    reloaded_client = TestClient(app_reloaded)
    after_restart = reloaded_client.get(f"/notes/{note_id}")
    assert after_restart.status_code == 200
    assert after_restart.json()["content"] == "updated content"

    delete = reloaded_client.delete(f"/notes/{note_id}")
    assert delete.status_code == 200
    assert delete.json()["status"] == "deleted"

    app_reloaded_again = _import_generated_backend_app(project_dir, db_url)
    reloaded_again_client = TestClient(app_reloaded_again)
    assert reloaded_again_client.get(f"/notes/{note_id}").status_code == 404


def test_generate_project_fullstack_ddd_applies_project_spec_entities(tmp_path: Path) -> None:
    opt = GenerateOptions(out=tmp_path, force=False, name="diary_entities", template="fullstack-ddd")
    setattr(
        opt,
        "project_spec",
        {
            "entities": [
                {
                    "name": "Entry",
                    "fields": [
                        {"name": "title", "type": "string"},
                        {"name": "content", "type": "string"},
                    ],
                }
            ],
            "frontend_pages": ["entries/list"],
        },
    )

    project_dir = Path(generate_project("personal diary webapp", opt))
    assert (project_dir / "backend" / "app" / "routers" / "entry.py").exists()
    assert (project_dir / "frontend" / "app" / "entries" / "page.tsx").exists()

    backend_text = (project_dir / "backend" / "app" / "main.py").read_text(encoding="utf-8").lower()
    frontend_text = (project_dir / "frontend" / "app" / "entries" / "page.tsx").read_text(encoding="utf-8").lower()
    assert "defect" not in backend_text
    assert "defect" not in frontend_text


def test_generate_project_fullstack_ddd_normalizes_and_applies_multi_entity_seed(tmp_path: Path) -> None:
    opt = GenerateOptions(out=tmp_path, force=False, name="diary_entities_multi", template="fullstack-ddd")
    setattr(
        opt,
        "project_spec",
        {
            "entities": [
                {"name": "Entry", "fields": [{"name": "title", "type": "string"}]},
                "Tag",
            ],
            "api_endpoints": ["GET /entries", {"method": "GET", "path": "/tags"}],
            "frontend_pages": ["entries/list", {"path": "tags/list"}],
        },
    )

    project_dir = Path(generate_project("personal diary webapp", opt))
    assert (project_dir / "backend" / "app" / "routers" / "entry.py").exists()
    assert (project_dir / "backend" / "app" / "routers" / "tag.py").exists()
    assert (project_dir / "frontend" / "app" / "entries" / "page.tsx").exists()
    assert (project_dir / "frontend" / "app" / "tags" / "page.tsx").exists()
    navigation = (project_dir / "frontend" / "app" / "_lib" / "navigation.ts").read_text(encoding="utf-8")
    assert 'href: "/entries"' in navigation
    assert 'href: "/tags"' in navigation


def test_apply_entity_scaffold_is_idempotent_and_does_not_overwrite_existing_files(tmp_path: Path) -> None:
    project_dir = tmp_path / "backend_demo"
    (project_dir / "app" / "models").mkdir(parents=True, exist_ok=True)
    (project_dir / "requirements.txt").write_text("fastapi\n", encoding="utf-8")
    (project_dir / "app" / "main.py").write_text("from fastapi import FastAPI\n\napp = FastAPI()\n", encoding="utf-8")
    model_path = project_dir / "app" / "models" / "task.py"
    model_path.write_text("# keep me\n", encoding="utf-8")

    first = apply_entity_scaffold(project_dir, "Task")
    second = apply_entity_scaffold(project_dir, "Task")

    assert model_path.read_text(encoding="utf-8") == "# keep me\n"
    assert any(path == "app/main.py" for path in first)
    assert second == []
    main_text = (project_dir / "app" / "main.py").read_text(encoding="utf-8")
    assert main_text.count("from app.routers.task import router as task_router") == 1
    assert main_text.count("app.include_router(task_router)") == 1


def test_apply_entity_scaffold_skips_frontend_only_projects(tmp_path: Path) -> None:
    project_dir = tmp_path / "frontend_demo"
    (project_dir / "app").mkdir(parents=True, exist_ok=True)
    (project_dir / "app" / "page.tsx").write_text("export default function Page(){return <div/>}\n", encoding="utf-8")
    (project_dir / "package.json").write_text('{"name":"frontend-demo"}\n', encoding="utf-8")

    generated = apply_entity_scaffold(project_dir, "Task")

    assert generated == []
    assert not (project_dir / "app" / "models" / "task.py").exists()


def test_apply_entity_fields_to_scaffold_updates_models_and_schemas(tmp_path: Path) -> None:
    project_dir = tmp_path / "backend_demo"
    (project_dir / "app").mkdir(parents=True, exist_ok=True)
    (project_dir / "requirements.txt").write_text("fastapi\n", encoding="utf-8")
    (project_dir / "app" / "main.py").write_text("from fastapi import FastAPI\n\napp = FastAPI()\n", encoding="utf-8")
    apply_entity_scaffold(project_dir, "Task")

    changed = apply_entity_fields_to_scaffold(
        project_dir,
        "Task",
        [{"name": "title", "type": "string"}, {"name": "due_date", "type": "datetime"}],
    )

    assert "app/models/task.py" in changed
    assert "app/schemas/task.py" in changed
    model_text = (project_dir / "app" / "models" / "task.py").read_text(encoding="utf-8")
    schema_text = (project_dir / "app" / "schemas" / "task.py").read_text(encoding="utf-8")
    assert "from datetime import datetime" in model_text
    assert "title: str" in model_text
    assert "due_date: datetime" in model_text
    assert "class TaskCreate" in schema_text
    assert "class TaskRead" in schema_text


def test_apply_entity_fields_to_scaffold_is_idempotent_for_same_fields(tmp_path: Path) -> None:
    project_dir = tmp_path / "backend_demo"
    (project_dir / "app").mkdir(parents=True, exist_ok=True)
    (project_dir / "requirements.txt").write_text("fastapi\n", encoding="utf-8")
    (project_dir / "app" / "main.py").write_text("from fastapi import FastAPI\n\napp = FastAPI()\n", encoding="utf-8")
    apply_entity_scaffold(project_dir, "Task")

    first = apply_entity_fields_to_scaffold(project_dir, "Task", [{"name": "title", "type": "string"}])
    second = apply_entity_fields_to_scaffold(project_dir, "Task", [{"name": "title", "type": "string"}])
    assert "app/models/task.py" in first
    assert "app/schemas/task.py" in first
    assert second == []


def test_apply_frontend_page_scaffold_creates_pages_for_frontend_structure(tmp_path: Path) -> None:
    project_dir = tmp_path / "fullstack_demo"
    (project_dir / "frontend" / "app").mkdir(parents=True, exist_ok=True)
    (project_dir / "frontend" / "package.json").write_text('{"name":"frontend"}\n', encoding="utf-8")

    generated = apply_frontend_page_scaffold(project_dir, "Task")
    assert "frontend/app/_lib/apiBase.ts" in generated
    assert "frontend/app/tasks/page.tsx" in generated
    assert "frontend/app/tasks/[id]/page.tsx" in generated
    helper_text = (project_dir / "frontend" / "app" / "_lib" / "apiBase.ts").read_text(encoding="utf-8")
    list_text = (project_dir / "frontend" / "app" / "tasks" / "page.tsx").read_text(encoding="utf-8")
    detail_text = (project_dir / "frontend" / "app" / "tasks" / "[id]" / "page.tsx").read_text(encoding="utf-8")
    assert "Loading tasks..." in list_text
    assert "Search tasks..." in list_text
    assert "No tasks yet. Add your first task." in list_text
    assert "statusTone(item.status)" in list_text
    assert "statusRank(a.status) - statusRank(b.status)" in list_text
    assert "Open task" in list_text
    assert "fetch(`${apiBaseUrl}/tasks`" in list_text
    assert 'from "../_lib/apiBase"' in list_text
    assert "useApiBaseUrl()" in list_text
    assert "useApiBaseUrl" in helper_text
    assert "setApiBaseUrl(resolveApiBaseInBrowser())" in helper_text
    assert "ENV_RUNTIME_BACKEND_URL" in helper_text
    assert "const explicitApiBase = String(ENV_API_BASE || \"\").trim();" in helper_text
    assert "const runtimeBackendBase = String(ENV_RUNTIME_BACKEND_URL || \"\").trim();" in helper_text
    assert 'const ENV_BACKEND_PORT = process.env.NEXT_PUBLIC_BACKEND_PORT || "";' in helper_text
    assert 'const fallbackPort = explicitPort || "8000";' not in helper_text
    assert "rewriteLoopbackToBrowserHost" in helper_text
    assert "if (explicitApiBase)" in helper_text
    assert "if (runtimeBackendBase)" in helper_text
    assert "if (explicitPort)" in helper_text
    assert "return `${browserProtocol}://${browserHost}:8000`;" in helper_text
    assert "parsed.hostname = browserHost" in helper_text
    assert "parsed.port" not in helper_text
    assert "return normalizeApiBase(parsed.toString());" in helper_text
    assert "if (browserHost)" in helper_text
    assert 'return "http://127.0.0.1:8000";' in helper_text
    assert "page placeholder for" not in list_text.lower()
    assert "Missing item id." in detail_text
    assert "Item not found." in detail_text
    assert "No details provided." in detail_text
    assert "Task #${id}" in detail_text
    assert "status ?? \"unknown\"" in detail_text
    assert "fetch(`${apiBaseUrl}/tasks/${id}`" in detail_text
    assert 'from "../../_lib/apiBase"' in detail_text
    assert "useApiBaseUrl()" in detail_text
    assert "placeholder" not in detail_text.lower()


def test_ensure_runtime_gitignore_merges_without_overwriting_existing_rules(tmp_path: Path) -> None:
    project_dir = tmp_path / "gitignore_merge_demo"
    frontend_dir = project_dir / "frontend"
    frontend_dir.mkdir(parents=True, exist_ok=True)
    (project_dir / ".gitignore").write_text("custom.keep\n", encoding="utf-8")
    (frontend_dir / ".gitignore").write_text("frontend.keep\n", encoding="utf-8")

    changed = ensure_runtime_gitignore(project_dir)

    assert ".gitignore" in changed
    assert "frontend/.gitignore" in changed
    root_text = (project_dir / ".gitignore").read_text(encoding="utf-8")
    front_text = (frontend_dir / ".gitignore").read_text(encoding="utf-8")
    assert "custom.keep" in root_text
    assert ".archmind/" in root_text
    assert "*.log" in root_text
    assert ".next/" in root_text
    assert "frontend.keep" in front_text
    assert ".next/" in front_text
    assert "*.pid" in front_text

    second = ensure_runtime_gitignore(project_dir)
    assert second == []


def test_runtime_gitignore_rules_keep_working_tree_clean_for_runtime_artifacts(tmp_path: Path) -> None:
    project_dir = tmp_path / "clean_runtime_artifacts_demo"
    project_dir.mkdir(parents=True, exist_ok=True)
    ensure_runtime_gitignore(project_dir)
    (project_dir / "README.md").write_text("# demo\n", encoding="utf-8")

    subprocess.run(["git", "init"], cwd=project_dir, check=True, capture_output=True, text=True)
    subprocess.run(["git", "config", "user.email", "archmind@example.com"], cwd=project_dir, check=True, capture_output=True, text=True)
    subprocess.run(["git", "config", "user.name", "ArchMind"], cwd=project_dir, check=True, capture_output=True, text=True)
    subprocess.run(["git", "add", "."], cwd=project_dir, check=True, capture_output=True, text=True)
    subprocess.run(["git", "commit", "-m", "init"], cwd=project_dir, check=True, capture_output=True, text=True)

    (project_dir / "frontend" / ".next" / "cache").mkdir(parents=True, exist_ok=True)
    (project_dir / "frontend" / ".next" / "cache" / "x.txt").write_text("x\n", encoding="utf-8")
    (project_dir / "logs").mkdir(parents=True, exist_ok=True)
    (project_dir / "logs" / "runtime.log").write_text("log\n", encoding="utf-8")
    (project_dir / "tmp").mkdir(parents=True, exist_ok=True)
    (project_dir / "tmp" / "server.pid").write_text("123\n", encoding="utf-8")
    (project_dir / ".archmind").mkdir(parents=True, exist_ok=True)
    (project_dir / ".archmind" / "state.json").write_text("{}", encoding="utf-8")

    status = subprocess.run(
        ["git", "status", "--porcelain"],
        cwd=project_dir,
        check=True,
        capture_output=True,
        text=True,
    )
    assert status.stdout.strip() == ""


def test_apply_frontend_page_scaffold_note_entity_is_usable_crud_mvp(tmp_path: Path) -> None:
    project_dir = tmp_path / "fullstack_demo"
    (project_dir / "frontend" / "app").mkdir(parents=True, exist_ok=True)
    (project_dir / "frontend" / "package.json").write_text('{"name":"frontend"}\n', encoding="utf-8")

    generated = apply_frontend_page_scaffold(project_dir, "Note")
    assert "frontend/app/notes/page.tsx" in generated
    assert "frontend/app/notes/[id]/page.tsx" in generated

    list_text = (project_dir / "frontend" / "app" / "notes" / "page.tsx").read_text(encoding="utf-8")
    detail_text = (project_dir / "frontend" / "app" / "notes" / "[id]" / "page.tsx").read_text(encoding="utf-8")

    assert "Create note" in list_text
    assert "method: \"POST\"" in list_text
    assert "function mergeNoteItem(current: NoteItem[], incoming: NoteItem): NoteItem[]" in list_text
    assert "setItems((prev) => mergeNoteItem(prev, created));" in list_text
    assert "Title is required." in list_text
    assert "No notes yet." in list_text
    assert "Open detail" in list_text
    assert "Save changes" in detail_text
    assert "method: \"PUT\"" in detail_text
    assert "const updated = (await response.json()) as NoteItem;" in detail_text
    assert "setItem(updated);" in detail_text
    assert "method: \"PATCH\"" in detail_text
    assert "Delete note" in detail_text
    assert "method: \"DELETE\"" in detail_text


def test_apply_frontend_page_scaffold_diary_entry_has_search_empty_state_and_recent_first_ui(tmp_path: Path) -> None:
    project_dir = tmp_path / "fullstack_diary"
    (project_dir / "frontend" / "app").mkdir(parents=True, exist_ok=True)
    (project_dir / "frontend" / "package.json").write_text('{"name":"frontend"}\n', encoding="utf-8")

    generated = apply_frontend_page_scaffold(project_dir, "Entry")
    assert "frontend/app/entries/page.tsx" in generated

    list_text = (project_dir / "frontend" / "app" / "entries" / "page.tsx").read_text(encoding="utf-8")
    assert "Search diary entries..." in list_text
    assert "No diary entries yet. Start by writing your first entry." in list_text
    assert "No entries match your search." in list_text
    assert "Recent entries first. Search by title or content." in list_text
    assert "createdAtMs(b) - createdAtMs(a)" in list_text
    assert "previewText(item)" in list_text
    assert "max-w-2xl" in list_text
    assert "Open entry" in list_text


def test_apply_frontend_page_scaffold_bookmark_list_has_search_readability(tmp_path: Path) -> None:
    project_dir = tmp_path / "fullstack_bookmarks"
    (project_dir / "frontend" / "app").mkdir(parents=True, exist_ok=True)
    (project_dir / "frontend" / "package.json").write_text('{"name":"frontend"}\n', encoding="utf-8")

    generated = apply_frontend_page_scaffold(project_dir, "Bookmark")
    assert "frontend/app/bookmarks/page.tsx" in generated

    list_text = (project_dir / "frontend" / "app" / "bookmarks" / "page.tsx").read_text(encoding="utf-8")
    assert "Search bookmarks..." in list_text
    assert "No bookmarks yet. Save your first link." in list_text
    assert "No bookmarks match your search." in list_text
    assert "Search bookmarks by title, URL, or keywords." in list_text
    assert "Open bookmark" in list_text
    assert "No note yet." in list_text
    assert "Saved: {String(item.created_at)}" in list_text
    assert "{String(item.category)}" in list_text
    assert "createdAtMs(b) - createdAtMs(a)" in list_text


def test_apply_frontend_page_scaffold_bookmark_detail_is_readable(tmp_path: Path) -> None:
    project_dir = tmp_path / "fullstack_bookmark_detail"
    (project_dir / "frontend" / "app").mkdir(parents=True, exist_ok=True)
    (project_dir / "frontend" / "package.json").write_text('{"name":"frontend"}\n', encoding="utf-8")

    apply_frontend_page_scaffold(project_dir, "Bookmark")
    detail_text = (project_dir / "frontend" / "app" / "bookmarks" / "[id]" / "page.tsx").read_text(encoding="utf-8")
    assert "Bookmark #${id}" in detail_text
    assert "URL unavailable." in detail_text
    assert "Category:" in detail_text
    assert "Saved:" in detail_text
    assert "No note yet." in detail_text


def test_apply_frontend_page_scaffold_diary_entry_detail_is_readable(tmp_path: Path) -> None:
    project_dir = tmp_path / "fullstack_diary_detail"
    (project_dir / "frontend" / "app").mkdir(parents=True, exist_ok=True)
    (project_dir / "frontend" / "package.json").write_text('{"name":"frontend"}\n', encoding="utf-8")

    apply_frontend_page_scaffold(project_dir, "Entry")
    detail_text = (project_dir / "frontend" / "app" / "entries" / "[id]" / "page.tsx").read_text(encoding="utf-8")
    assert "whitespace-pre-wrap" in detail_text
    assert "Entry #${id}" in detail_text
    assert "Created time unavailable" in detail_text
    assert "No content yet." in detail_text


def test_apply_frontend_page_scaffold_board_and_card_have_kanban_quality_ui(tmp_path: Path) -> None:
    project_dir = tmp_path / "fullstack_kanban"
    (project_dir / "frontend" / "app").mkdir(parents=True, exist_ok=True)
    (project_dir / "frontend" / "package.json").write_text('{"name":"frontend"}\n', encoding="utf-8")

    board_generated = apply_frontend_page_scaffold(project_dir, "Board")
    card_generated = apply_frontend_page_scaffold(project_dir, "Card")
    assert "frontend/app/boards/page.tsx" in board_generated
    assert "frontend/app/cards/page.tsx" in card_generated

    board_list_text = (project_dir / "frontend" / "app" / "boards" / "page.tsx").read_text(encoding="utf-8")
    card_list_text = (project_dir / "frontend" / "app" / "cards" / "page.tsx").read_text(encoding="utf-8")
    card_detail_text = (project_dir / "frontend" / "app" / "cards" / "[id]" / "page.tsx").read_text(encoding="utf-8")

    assert "Search boards..." in board_list_text
    assert "No boards yet. Create your first board." in board_list_text
    assert "Open board" in board_list_text
    assert "Search cards..." in card_list_text
    assert "statusTone(item.status)" in card_list_text
    assert "Board: {String(item.board_id" in card_list_text
    assert "Open card" in card_list_text
    assert "Card #${id}" in card_detail_text
    assert "Assignee:" in card_detail_text
    assert "Board: {String((item as Record<string, unknown>).board_id" in card_detail_text


def test_apply_frontend_page_scaffold_board_detail_surfaces_relation_context_text(tmp_path: Path) -> None:
    project_dir = tmp_path / "fullstack_board_detail"
    (project_dir / "frontend" / "app").mkdir(parents=True, exist_ok=True)
    (project_dir / "frontend" / "package.json").write_text('{"name":"frontend"}\n', encoding="utf-8")

    apply_frontend_page_scaffold(project_dir, "Board")
    detail_text = (project_dir / "frontend" / "app" / "boards" / "[id]" / "page.tsx").read_text(encoding="utf-8")
    assert "Board #${id}" in detail_text
    assert "No board description provided." in detail_text
    assert "Cards linked to this board are listed below." in detail_text


def test_apply_frontend_page_scaffold_task_detail_shows_due_date_when_present(tmp_path: Path) -> None:
    project_dir = tmp_path / "fullstack_task_detail"
    (project_dir / "frontend" / "app").mkdir(parents=True, exist_ok=True)
    (project_dir / "frontend" / "package.json").write_text('{"name":"frontend"}\n', encoding="utf-8")

    apply_frontend_page_scaffold(project_dir, "Task")
    detail_text = (project_dir / "frontend" / "app" / "tasks" / "[id]" / "page.tsx").read_text(encoding="utf-8")
    assert 'due_date || (item as Record<string, unknown>).due' in detail_text
    assert "Due:" in detail_text


def test_relation_surface_board_detail_includes_card_section(tmp_path: Path) -> None:
    project_dir = tmp_path / "relation_board_card"
    (project_dir / "frontend" / "app").mkdir(parents=True, exist_ok=True)
    (project_dir / "frontend" / "package.json").write_text('{"name":"frontend"}\n', encoding="utf-8")
    (project_dir / ".archmind").mkdir(parents=True, exist_ok=True)
    (project_dir / ".archmind" / "project_spec.json").write_text(
        json.dumps(
            {
                "entities": [
                    {"name": "Board", "fields": [{"name": "title", "type": "string"}]},
                    {"name": "Card", "fields": [{"name": "title", "type": "string"}, {"name": "board_id", "type": "int"}]},
                ]
            }
        ),
        encoding="utf-8",
    )

    apply_frontend_page_scaffold(project_dir, "Board")
    apply_frontend_page_scaffold(project_dir, "Card")
    detail_text = (project_dir / "frontend" / "app" / "boards" / "[id]" / "page.tsx").read_text(encoding="utf-8")
    assert "Cards" in detail_text
    assert "fetch(`${apiBaseUrl}/boards/${id}/cards`" in detail_text
    assert "fetch(`${apiBaseUrl}/cards`" in detail_text
    assert '["board_id"]' in detail_text
    assert "/cards/by_board?board_id=${id}" in detail_text
    assert "/cards/new?board_id=${id}" in detail_text


def test_relation_surface_entry_detail_includes_tag_section(tmp_path: Path) -> None:
    project_dir = tmp_path / "relation_entry_tag"
    (project_dir / "frontend" / "app").mkdir(parents=True, exist_ok=True)
    (project_dir / "frontend" / "package.json").write_text('{"name":"frontend"}\n', encoding="utf-8")
    (project_dir / ".archmind").mkdir(parents=True, exist_ok=True)
    (project_dir / ".archmind" / "project_spec.json").write_text(
        json.dumps(
            {
                "entities": [
                    {"name": "Entry", "fields": [{"name": "title", "type": "string"}]},
                    {"name": "Tag", "fields": [{"name": "name", "type": "string"}, {"name": "entry_id", "type": "int"}]},
                ]
            }
        ),
        encoding="utf-8",
    )

    apply_frontend_page_scaffold(project_dir, "Entry")
    apply_frontend_page_scaffold(project_dir, "Tag")
    detail_text = (project_dir / "frontend" / "app" / "entries" / "[id]" / "page.tsx").read_text(encoding="utf-8")
    assert "Tags" in detail_text
    assert "fetch(`${apiBaseUrl}/entries/${id}/tags`" in detail_text
    assert "fetch(`${apiBaseUrl}/tags`" in detail_text
    assert '["entry_id"]' in detail_text
    assert "/tags/by_entry?entry_id=${id}" in detail_text


def test_relation_surface_category_detail_includes_bookmark_section(tmp_path: Path) -> None:
    project_dir = tmp_path / "relation_category_bookmark"
    (project_dir / "frontend" / "app").mkdir(parents=True, exist_ok=True)
    (project_dir / "frontend" / "package.json").write_text('{"name":"frontend"}\n', encoding="utf-8")
    (project_dir / ".archmind").mkdir(parents=True, exist_ok=True)
    (project_dir / ".archmind" / "project_spec.json").write_text(
        json.dumps(
            {
                "entities": [
                    {"name": "Category", "fields": [{"name": "name", "type": "string"}]},
                    {"name": "Bookmark", "fields": [{"name": "title", "type": "string"}, {"name": "category_id", "type": "int"}]},
                ]
            }
        ),
        encoding="utf-8",
    )

    apply_frontend_page_scaffold(project_dir, "Category")
    apply_frontend_page_scaffold(project_dir, "Bookmark")
    detail_text = (project_dir / "frontend" / "app" / "categories" / "[id]" / "page.tsx").read_text(encoding="utf-8")
    assert "Bookmarks" in detail_text
    assert "fetch(`${apiBaseUrl}/categories/${id}/bookmarks`" in detail_text
    assert "fetch(`${apiBaseUrl}/bookmarks`" in detail_text
    assert '["category_id"]' in detail_text
    assert "/bookmarks/by_category?category_id=${id}" in detail_text
    assert "/bookmarks/new?category_id=${id}" in detail_text


def test_single_entity_detail_page_has_no_relation_surface(tmp_path: Path) -> None:
    project_dir = tmp_path / "single_entity_no_relation"
    (project_dir / "frontend" / "app").mkdir(parents=True, exist_ok=True)
    (project_dir / "frontend" / "package.json").write_text('{"name":"frontend"}\n', encoding="utf-8")
    (project_dir / ".archmind").mkdir(parents=True, exist_ok=True)
    (project_dir / ".archmind" / "project_spec.json").write_text(
        json.dumps({"entities": [{"name": "Task", "fields": [{"name": "title", "type": "string"}]}]}),
        encoding="utf-8",
    )

    apply_frontend_page_scaffold(project_dir, "Task")
    detail_text = (project_dir / "frontend" / "app" / "tasks" / "[id]" / "page.tsx").read_text(encoding="utf-8")
    assert "Loading related items..." not in detail_text
    assert "View all" not in detail_text
    assert "/tasks/by_task" not in detail_text


def test_relation_create_page_card_uses_query_prefill_and_parent_selector(tmp_path: Path) -> None:
    project_dir = tmp_path / "relation_create_board_card"
    (project_dir / "frontend" / "app").mkdir(parents=True, exist_ok=True)
    (project_dir / "frontend" / "package.json").write_text('{"name":"frontend"}\n', encoding="utf-8")
    (project_dir / ".archmind").mkdir(parents=True, exist_ok=True)
    (project_dir / ".archmind" / "project_spec.json").write_text(
        json.dumps(
            {
                "entities": [
                    {"name": "Board", "fields": [{"name": "title", "type": "string"}]},
                    {"name": "Card", "fields": [{"name": "title", "type": "string"}, {"name": "board_id", "type": "int"}]},
                ]
            }
        ),
        encoding="utf-8",
    )

    apply_page_scaffold(project_dir, "cards/new")
    apply_page_scaffold(project_dir, "cards/by_board")
    create_text = (project_dir / "frontend" / "app" / "cards" / "new" / "page.tsx").read_text(encoding="utf-8")
    relation_text = (project_dir / "frontend" / "app" / "cards" / "by_board" / "page.tsx").read_text(encoding="utf-8")
    assert 'searchParams.get("board_id")' in create_text
    assert "Prefilled from parent context." in create_text
    assert "fetch(`${apiBaseUrl}/boards`" in create_text
    assert "Option fetch unavailable. Raw input fallback." in create_text
    assert 'method: "POST"' in create_text
    assert 'fetch(`${apiBaseUrl}/cards`' in create_text
    assert "/cards/new?board_id=${relationValue}" in relation_text


def test_relation_create_page_tag_respects_entry_context_and_has_fallback(tmp_path: Path) -> None:
    project_dir = tmp_path / "relation_create_entry_tag"
    (project_dir / "frontend" / "app").mkdir(parents=True, exist_ok=True)
    (project_dir / "frontend" / "package.json").write_text('{"name":"frontend"}\n', encoding="utf-8")
    (project_dir / ".archmind").mkdir(parents=True, exist_ok=True)
    (project_dir / ".archmind" / "project_spec.json").write_text(
        json.dumps(
            {
                "entities": [
                    {"name": "Entry", "fields": [{"name": "title", "type": "string"}]},
                    {"name": "Tag", "fields": [{"name": "name", "type": "string"}, {"name": "entry_id", "type": "int"}]},
                ]
            }
        ),
        encoding="utf-8",
    )

    apply_page_scaffold(project_dir, "tags/new")
    create_text = (project_dir / "frontend" / "app" / "tags" / "new" / "page.tsx").read_text(encoding="utf-8")
    assert 'searchParams.get("entry_id")' in create_text
    assert "fetch(`${apiBaseUrl}/entries`" in create_text
    assert "Option fetch unavailable. Raw input fallback." in create_text


def test_relation_create_and_detail_page_bookmark_category_surface_relation_meaningfully(tmp_path: Path) -> None:
    project_dir = tmp_path / "relation_create_bookmark_category"
    (project_dir / "frontend" / "app").mkdir(parents=True, exist_ok=True)
    (project_dir / "frontend" / "package.json").write_text('{"name":"frontend"}\n', encoding="utf-8")
    (project_dir / ".archmind").mkdir(parents=True, exist_ok=True)
    (project_dir / ".archmind" / "project_spec.json").write_text(
        json.dumps(
            {
                "entities": [
                    {"name": "Category", "fields": [{"name": "name", "type": "string"}]},
                    {"name": "Bookmark", "fields": [{"name": "title", "type": "string"}, {"name": "category_id", "type": "int"}]},
                ]
            }
        ),
        encoding="utf-8",
    )

    apply_frontend_page_scaffold(project_dir, "Bookmark")
    apply_page_scaffold(project_dir, "bookmarks/new")
    create_text = (project_dir / "frontend" / "app" / "bookmarks" / "new" / "page.tsx").read_text(encoding="utf-8")
    detail_text = (project_dir / "frontend" / "app" / "bookmarks" / "[id]" / "page.tsx").read_text(encoding="utf-8")
    assert 'searchParams.get("category_id")' in create_text
    assert "fetch(`${apiBaseUrl}/categories`" in create_text
    assert "Select parent" in create_text
    assert "Relations" in detail_text
    assert "Category" in detail_text


def test_single_entity_create_page_remains_simple_without_relation_selector(tmp_path: Path) -> None:
    project_dir = tmp_path / "single_create_no_relation"
    (project_dir / "frontend" / "app").mkdir(parents=True, exist_ok=True)
    (project_dir / "frontend" / "package.json").write_text('{"name":"frontend"}\n', encoding="utf-8")
    (project_dir / ".archmind").mkdir(parents=True, exist_ok=True)
    (project_dir / ".archmind" / "project_spec.json").write_text(
        json.dumps({"entities": [{"name": "Task", "fields": [{"name": "title", "type": "string"}]}]}),
        encoding="utf-8",
    )

    apply_page_scaffold(project_dir, "tasks/new")
    create_text = (project_dir / "frontend" / "app" / "tasks" / "new" / "page.tsx").read_text(encoding="utf-8")
    assert "Select parent" not in create_text
    assert "Prefilled from parent context." not in create_text
    assert 'fetch(`${apiBaseUrl}/tasks`' in create_text


def test_apply_frontend_page_scaffold_updates_navigation_with_new_entity_route(tmp_path: Path) -> None:
    project_dir = tmp_path / "fullstack_demo"
    (project_dir / "frontend" / "app").mkdir(parents=True, exist_ok=True)
    (project_dir / "frontend" / "package.json").write_text('{"name":"frontend"}\n', encoding="utf-8")
    (project_dir / "frontend" / "app" / "layout.tsx").write_text("export default function Layout(){return null}\n", encoding="utf-8")

    apply_frontend_page_scaffold(project_dir, "Note")
    apply_frontend_page_scaffold(project_dir, "Task")

    nav_text = (project_dir / "frontend" / "app" / "_lib" / "navigation.ts").read_text(encoding="utf-8")
    assert 'href: "/notes"' in nav_text
    assert 'href: "/tasks"' in nav_text


def test_apply_page_scaffold_updates_navigation_with_new_explicit_page(tmp_path: Path) -> None:
    project_dir = tmp_path / "fullstack_demo"
    (project_dir / "frontend" / "app").mkdir(parents=True, exist_ok=True)
    (project_dir / "frontend" / "package.json").write_text('{"name":"frontend"}\n', encoding="utf-8")
    (project_dir / "frontend" / "app" / "layout.tsx").write_text("export default function Layout(){return null}\n", encoding="utf-8")

    apply_page_scaffold(project_dir, "reports/list")

    nav_text = (project_dir / "frontend" / "app" / "_lib" / "navigation.ts").read_text(encoding="utf-8")
    assert 'href: "/reports"' in nav_text


def test_apply_page_scaffold_normalizes_single_segment_and_dedupes_navigation(tmp_path: Path) -> None:
    project_dir = tmp_path / "fullstack_demo"
    (project_dir / "frontend" / "app").mkdir(parents=True, exist_ok=True)
    (project_dir / "frontend" / "package.json").write_text('{"name":"frontend"}\n', encoding="utf-8")
    (project_dir / "frontend" / "app" / "layout.tsx").write_text("export default function Layout(){return null}\n", encoding="utf-8")

    first = apply_page_scaffold(project_dir, "Tests")
    second = apply_page_scaffold(project_dir, "/tests/list/")

    assert "frontend/app/tests/page.tsx" in first
    assert second == []
    nav_text = (project_dir / "frontend" / "app" / "_lib" / "navigation.ts").read_text(encoding="utf-8")
    assert nav_text.count('href: "/tests"') == 1


def test_apply_page_scaffold_navigation_uses_canonical_routes_without_duplicates(tmp_path: Path) -> None:
    project_dir = tmp_path / "fullstack_demo"
    (project_dir / "frontend" / "app").mkdir(parents=True, exist_ok=True)
    (project_dir / "frontend" / "package.json").write_text('{"name":"frontend"}\n', encoding="utf-8")
    (project_dir / "frontend" / "app" / "layout.tsx").write_text("export default function Layout(){return null}\n", encoding="utf-8")

    apply_page_scaffold(project_dir, "entries/list")
    apply_page_scaffold(project_dir, "entries/detail")
    apply_page_scaffold(project_dir, "entries/new")

    nav_text = (project_dir / "frontend" / "app" / "_lib" / "navigation.ts").read_text(encoding="utf-8")
    assert 'href: "/entries"' in nav_text
    assert 'label: "Entries"' in nav_text
    assert 'href: "/entries/new"' in nav_text
    assert 'label: "New Entry"' in nav_text
    assert 'href: "/entries/[id]"' not in nav_text
    assert nav_text.count('label: "Entries"') == 1


def test_apply_page_scaffold_backfills_legacy_memo_shell_and_surfaces_new_pages(tmp_path: Path) -> None:
    project_dir = tmp_path / "legacy_memo"
    app_dir = project_dir / "frontend" / "app"
    app_dir.mkdir(parents=True, exist_ok=True)
    (project_dir / "frontend" / "package.json").write_text('{"name":"frontend"}\n', encoding="utf-8")
    (app_dir / "notes").mkdir(parents=True, exist_ok=True)
    (app_dir / "notes" / "page.tsx").write_text("export default function Notes(){return null}\n", encoding="utf-8")
    (app_dir / "layout.tsx").write_text(
        'import "./globals.css";\n\n'
        "export const metadata = {\n"
        '  title: "legacy_memo",\n'
        "};\n\n"
        "export default function RootLayout({ children }: { children: React.ReactNode }) {\n"
        "  return (\n"
        "    <html lang=\"en\"><body>\n"
        "      <div>\n"
        "        <div>FastAPI + Next.js workspace</div>\n"
        "        <div>/ · /notes</div>\n"
        "        {children}\n"
        "      </div>\n"
        "    </body></html>\n"
        "  );\n"
        "}\n",
        encoding="utf-8",
    )
    (app_dir / "page.tsx").write_text(
        '"use client";\n'
        'import Link from "next/link";\n'
        "import { useRouter } from \"next/navigation\";\n"
        "export default function Page(){\n"
        "  const router = useRouter();\n"
        '  return <div><p>Open the generated domain pages.</p><Link href="/notes">Notes</Link></div>;\n'
        "}\n",
        encoding="utf-8",
    )

    apply_page_scaffold(project_dir, "reminders/list")

    nav_text = (app_dir / "_lib" / "navigation.ts").read_text(encoding="utf-8")
    layout_text = (app_dir / "layout.tsx").read_text(encoding="utf-8")
    root_text = (app_dir / "page.tsx").read_text(encoding="utf-8")
    assert 'href: "/notes"' in nav_text
    assert 'href: "/reminders"' in nav_text
    assert "APP_NAV_LINKS.map" in layout_text
    assert 'from "./_lib/navigation"' in root_text
    assert "Primary section" in root_text
    assert "Open {primaryCollection.label}" in root_text


def test_apply_page_scaffold_upgrades_fullstack_template_shell_to_navigation_home(tmp_path: Path) -> None:
    project_dir = tmp_path / "fullstack_shell"
    app_dir = project_dir / "frontend" / "app"
    app_dir.mkdir(parents=True, exist_ok=True)
    (project_dir / "frontend" / "package.json").write_text('{"name":"frontend"}\n', encoding="utf-8")
    (app_dir / "layout.tsx").write_text(
        'import "./globals.css";\n'
        "\n"
        "export const metadata = {\n"
        '  title: "fullstack_shell",\n'
        "};\n"
        "\n"
        "export default function RootLayout({ children }: { children: React.ReactNode }) {\n"
        "  return (\n"
        '    <html lang="en">\n'
        "      <body>\n"
        '        <main className="mx-auto min-h-screen max-w-4xl p-6">{children}</main>\n'
        "      </body>\n"
        "    </html>\n"
        "  );\n"
        "}\n",
        encoding="utf-8",
    )
    (app_dir / "page.tsx").write_text(
        "export default function HomePage() {\n"
        "  return (\n"
        '    <section className="space-y-3 rounded-xl border border-slate-800 bg-slate-900/60 p-6">\n'
        '      <h1 className="text-2xl font-semibold">ArchMind Fullstack Workspace</h1>\n'
        '      <p className="text-sm text-slate-300">\n'
        "        This scaffold is domain-neutral. Entities, APIs, and pages are generated from project spec.\n"
        "      </p>\n"
        "    </section>\n"
        "  );\n"
        "}\n",
        encoding="utf-8",
    )

    apply_page_scaffold(project_dir, "entries/list")

    root_text = (app_dir / "page.tsx").read_text(encoding="utf-8")
    layout_text = (app_dir / "layout.tsx").read_text(encoding="utf-8")
    nav_text = (app_dir / "_lib" / "navigation.ts").read_text(encoding="utf-8")
    assert "ArchMind Fullstack Workspace" not in root_text
    assert "This scaffold is domain-neutral." not in root_text
    assert 'from "./_lib/navigation"' in root_text
    assert "Primary section" in root_text
    assert "APP_NAV_LINKS.map" in layout_text
    assert 'href: "/entries"' in nav_text


def test_apply_page_scaffold_landing_surfaces_create_cta_when_new_page_exists(tmp_path: Path) -> None:
    project_dir = tmp_path / "landing_cta"
    app_dir = project_dir / "frontend" / "app"
    app_dir.mkdir(parents=True, exist_ok=True)
    (project_dir / "frontend" / "package.json").write_text('{"name":"frontend"}\n', encoding="utf-8")
    (app_dir / "layout.tsx").write_text("export default function Layout(){return null}\n", encoding="utf-8")
    (app_dir / "page.tsx").write_text(
        "export default function HomePage() {\n"
        "  return <div>ArchMind Fullstack Workspace</div>;\n"
        "}\n",
        encoding="utf-8",
    )

    apply_page_scaffold(project_dir, "entries/list")
    apply_page_scaffold(project_dir, "entries/new")

    root_text = (app_dir / "page.tsx").read_text(encoding="utf-8")
    nav_text = (app_dir / "_lib" / "navigation.ts").read_text(encoding="utf-8")
    assert 'href: "/entries/new"' in nav_text
    assert "createAction" in root_text
    assert "{createAction.label}" in root_text


def test_apply_frontend_page_scaffold_is_idempotent_and_skips_backend_only(tmp_path: Path) -> None:
    backend_only = tmp_path / "backend_demo"
    (backend_only / "app").mkdir(parents=True, exist_ok=True)
    (backend_only / "requirements.txt").write_text("fastapi\n", encoding="utf-8")
    assert apply_frontend_page_scaffold(backend_only, "Task") == []

    frontend = tmp_path / "next_demo"
    (frontend / "app").mkdir(parents=True, exist_ok=True)
    (frontend / "package.json").write_text('{"name":"next-demo"}\n', encoding="utf-8")
    first = apply_frontend_page_scaffold(frontend, "Task")
    second = apply_frontend_page_scaffold(frontend, "Task")
    assert "app/tasks/page.tsx" in first
    assert "app/tasks/[id]/page.tsx" in first
    assert second == []


def test_apply_api_scaffold_creates_custom_router_and_registers_main(tmp_path: Path) -> None:
    project_dir = tmp_path / "backend_demo"
    (project_dir / "app").mkdir(parents=True, exist_ok=True)
    (project_dir / "requirements.txt").write_text("fastapi\n", encoding="utf-8")
    (project_dir / "app" / "main.py").write_text("from fastapi import FastAPI\n\napp = FastAPI()\n", encoding="utf-8")

    first = apply_api_scaffold(project_dir, "GET", "/reports")
    second = apply_api_scaffold(project_dir, "GET", "/reports")
    assert "app/routers/custom.py" in first
    assert first.count("app/main.py") <= 1
    assert second == []
    custom_text = (project_dir / "app" / "routers" / "custom.py").read_text(encoding="utf-8")
    assert '@router.get("/reports")' in custom_text
    assert custom_text.count('@router.get("/reports")') == 1
    main_text = (project_dir / "app" / "main.py").read_text(encoding="utf-8")
    assert "from app.routers.custom import router as custom_router" in main_text
    assert main_text.count("app.include_router(custom_router)") == 1


def test_apply_api_scaffold_normalizes_singular_path_to_plural(tmp_path: Path) -> None:
    project_dir = tmp_path / "backend_demo"
    (project_dir / "app").mkdir(parents=True, exist_ok=True)
    (project_dir / "requirements.txt").write_text("fastapi\n", encoding="utf-8")
    (project_dir / "app" / "main.py").write_text("from fastapi import FastAPI\n\napp = FastAPI()\n", encoding="utf-8")

    generated = apply_api_scaffold(project_dir, "GET", "/task")
    assert "app/routers/custom.py" in generated
    custom_text = (project_dir / "app" / "routers" / "custom.py").read_text(encoding="utf-8")
    assert '@router.get("/tasks")' in custom_text


def test_apply_page_scaffold_creates_explicit_page_and_is_idempotent(tmp_path: Path) -> None:
    project_dir = tmp_path / "fullstack_demo"
    (project_dir / "frontend" / "app").mkdir(parents=True, exist_ok=True)
    (project_dir / "frontend" / "package.json").write_text('{"name":"frontend"}\n', encoding="utf-8")

    first = apply_page_scaffold(project_dir, "reports/list")
    second = apply_page_scaffold(project_dir, "reports/list")
    assert "frontend/app/_lib/apiBase.ts" in first
    assert "frontend/app/reports/page.tsx" in first
    assert second == []
    page_text = (project_dir / "frontend" / "app" / "reports" / "page.tsx").read_text(encoding="utf-8")
    assert "Loading..." in page_text
    assert "No items found." in page_text
    assert "fetch(`${apiBaseUrl}/reports`" in page_text
    assert 'from "../_lib/apiBase"' in page_text
    assert "placeholder" not in page_text.lower()


def test_apply_page_scaffold_detail_generates_non_placeholder_page(tmp_path: Path) -> None:
    project_dir = tmp_path / "fullstack_demo"
    (project_dir / "frontend" / "app").mkdir(parents=True, exist_ok=True)
    (project_dir / "frontend" / "package.json").write_text('{"name":"frontend"}\n', encoding="utf-8")

    generated = apply_page_scaffold(project_dir, "notes/detail")
    assert "frontend/app/_lib/apiBase.ts" in generated
    assert "frontend/app/notes/[id]/page.tsx" in generated
    page_text = (project_dir / "frontend" / "app" / "notes" / "[id]" / "page.tsx").read_text(encoding="utf-8")
    assert "Missing item id." in page_text
    assert "Item not found." in page_text
    assert "fetch(`${apiBaseUrl}/notes/${id}`" in page_text
    assert 'from "../../_lib/apiBase"' in page_text
    assert "placeholder" not in page_text.lower()


def test_apply_page_scaffold_generic_page_uses_shared_api_base_helper(tmp_path: Path) -> None:
    project_dir = tmp_path / "fullstack_demo"
    (project_dir / "frontend" / "app").mkdir(parents=True, exist_ok=True)
    (project_dir / "frontend" / "package.json").write_text('{"name":"frontend"}\n', encoding="utf-8")

    generated = apply_page_scaffold(project_dir, "admin/home")
    assert "frontend/app/_lib/apiBase.ts" in generated
    assert "frontend/app/admin/home/page.tsx" in generated
    page_text = (project_dir / "frontend" / "app" / "admin" / "home" / "page.tsx").read_text(encoding="utf-8")
    assert 'from "../../_lib/apiBase"' in page_text
    assert "useApiBaseUrl()" in page_text
    assert 'API: {apiBaseLoading ? "(resolving...)" : apiBaseUrl}' in page_text


def test_apply_page_scaffold_sanitizes_component_name_for_numeric_segments(tmp_path: Path) -> None:
    project_dir = tmp_path / "fullstack_demo"
    (project_dir / "frontend" / "app").mkdir(parents=True, exist_ok=True)
    (project_dir / "frontend" / "package.json").write_text('{"name":"frontend"}\n', encoding="utf-8")

    generated = apply_page_scaffold(project_dir, "2026/reports/list")
    assert "frontend/app/2026s/reports/page.tsx" in generated
    page_text = (project_dir / "frontend" / "app" / "2026s" / "reports" / "page.tsx").read_text(encoding="utf-8")
    assert "export default function P2026sReportsListPage()" in page_text
    assert "export default function 2026sReportsListPage()" not in page_text


def test_implement_page_scaffold_upgrades_placeholder_list_page(tmp_path: Path) -> None:
    project_dir = tmp_path / "fullstack_demo"
    (project_dir / "frontend" / "app").mkdir(parents=True, exist_ok=True)
    (project_dir / "frontend" / "package.json").write_text('{"name":"frontend"}\n', encoding="utf-8")
    target = project_dir / "frontend" / "app" / "tasks" / "page.tsx"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(
        '"use client";\n'
        "export default function TasksListPage(){\n"
        "  return <p>Page placeholder for tasks</p>;\n"
        "}\n",
        encoding="utf-8",
    )

    result = implement_page_scaffold(project_dir, "tasks/list")
    assert result["ok"] is True
    assert result["status"] == "implemented"
    assert result["page_path"] == "tasks/list"
    assert "Implemented page: tasks/list" in str(result["detail"])

    page_text = (project_dir / "frontend" / "app" / "tasks" / "page.tsx").read_text(encoding="utf-8")
    assert "Page placeholder for tasks" not in page_text
    assert "fetch(`${apiBaseUrl}/tasks`" in page_text
    assert "No items found." in page_text


def test_implement_page_scaffold_upgrades_placeholder_detail_page(tmp_path: Path) -> None:
    project_dir = tmp_path / "fullstack_demo"
    (project_dir / "frontend" / "app").mkdir(parents=True, exist_ok=True)
    (project_dir / "frontend" / "package.json").write_text('{"name":"frontend"}\n', encoding="utf-8")
    target = project_dir / "frontend" / "app" / "tasks" / "[id]" / "page.tsx"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(
        '"use client";\n'
        "export default function TasksDetailPage(){\n"
        "  return <p>Page placeholder for tasks/[id]</p>;\n"
        "}\n",
        encoding="utf-8",
    )

    result = implement_page_scaffold(project_dir, "tasks/detail")
    assert result["ok"] is True
    assert result["status"] == "implemented"
    assert result["page_path"] == "tasks/detail"

    page_text = (project_dir / "frontend" / "app" / "tasks" / "[id]" / "page.tsx").read_text(encoding="utf-8")
    assert "Page placeholder for tasks/[id]" not in page_text
    assert "Missing item id." in page_text
    assert "Item not found." in page_text


def test_implement_page_scaffold_upgrades_placeholder_custom_page(tmp_path: Path) -> None:
    project_dir = tmp_path / "fullstack_demo"
    (project_dir / "frontend" / "app").mkdir(parents=True, exist_ok=True)
    (project_dir / "frontend" / "package.json").write_text('{"name":"frontend"}\n', encoding="utf-8")
    apply_page_scaffold(project_dir, "songs/favorite")

    result = implement_page_scaffold(project_dir, "songs/favorite")
    assert result["ok"] is True
    assert result["status"] == "implemented"
    assert result["page_path"] == "songs/favorite"

    page_text = (project_dir / "frontend" / "app" / "songs" / "favorite" / "page.tsx").read_text(encoding="utf-8")
    assert "Page placeholder for songs/favorite" not in page_text
    assert "This page is implemented and ready for project-specific content." in page_text


def test_implement_page_scaffold_returns_safe_info_when_already_implemented(tmp_path: Path) -> None:
    project_dir = tmp_path / "fullstack_demo"
    (project_dir / "frontend" / "app").mkdir(parents=True, exist_ok=True)
    (project_dir / "frontend" / "package.json").write_text('{"name":"frontend"}\n', encoding="utf-8")
    apply_page_scaffold(project_dir, "tasks/list")

    result = implement_page_scaffold(project_dir, "tasks/list")
    assert result["ok"] is True
    assert result["status"] == "already_implemented"
    assert "Page already implemented: tasks/list" in str(result["detail"])


def test_implement_page_scaffold_returns_not_found_for_missing_page(tmp_path: Path) -> None:
    project_dir = tmp_path / "fullstack_demo"
    (project_dir / "frontend" / "app").mkdir(parents=True, exist_ok=True)
    (project_dir / "frontend" / "package.json").write_text('{"name":"frontend"}\n', encoding="utf-8")

    result = implement_page_scaffold(project_dir, "tasks/list")
    assert result["ok"] is False
    assert result["status"] == "not_found"
    assert "Page not found: tasks/list" in str(result["detail"])
