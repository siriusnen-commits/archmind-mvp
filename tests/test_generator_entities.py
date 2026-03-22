from __future__ import annotations

from pathlib import Path

from archmind.generator import (
    apply_api_scaffold,
    apply_entity_fields_to_scaffold,
    apply_entity_scaffold,
    apply_frontend_page_scaffold,
    apply_page_scaffold,
)


def test_apply_entity_scaffold_creates_backend_placeholder_files(tmp_path: Path) -> None:
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
    assert "def create_task()" in router_text
    assert "def get_task(id: int)" in router_text
    assert "def update_task(id: int)" in router_text
    assert "def delete_task(id: int)" in router_text


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
    assert "Loading..." in list_text
    assert "No items found." in list_text
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
    assert "placeholder" not in list_text.lower()
    assert "Missing item id." in detail_text
    assert "Item not found." in detail_text
    assert "fetch(`${apiBaseUrl}/tasks/${id}`" in detail_text
    assert 'from "../../_lib/apiBase"' in detail_text
    assert "useApiBaseUrl()" in detail_text
    assert "placeholder" not in detail_text.lower()


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
    assert "Title is required." in list_text
    assert "No notes yet." in list_text
    assert "Open detail" in list_text
    assert "Save changes" in detail_text
    assert "method: \"PUT\"" in detail_text
    assert "method: \"PATCH\"" in detail_text
    assert "Delete note" in detail_text
    assert "method: \"DELETE\"" in detail_text


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


def test_apply_page_scaffold_creates_explicit_page_and_is_idempotent(tmp_path: Path) -> None:
    project_dir = tmp_path / "fullstack_demo"
    (project_dir / "frontend" / "app").mkdir(parents=True, exist_ok=True)
    (project_dir / "frontend" / "package.json").write_text('{"name":"frontend"}\n', encoding="utf-8")

    first = apply_page_scaffold(project_dir, "reports/list")
    second = apply_page_scaffold(project_dir, "reports/list")
    assert "frontend/app/_lib/apiBase.ts" in first
    assert "frontend/app/reports/list/page.tsx" in first
    assert second == []
    page_text = (project_dir / "frontend" / "app" / "reports" / "list" / "page.tsx").read_text(encoding="utf-8")
    assert "Loading..." in page_text
    assert "No items found." in page_text
    assert "fetch(`${apiBaseUrl}/reports`" in page_text
    assert 'from "../../_lib/apiBase"' in page_text
    assert "placeholder" not in page_text.lower()


def test_apply_page_scaffold_detail_generates_non_placeholder_page(tmp_path: Path) -> None:
    project_dir = tmp_path / "fullstack_demo"
    (project_dir / "frontend" / "app").mkdir(parents=True, exist_ok=True)
    (project_dir / "frontend" / "package.json").write_text('{"name":"frontend"}\n', encoding="utf-8")

    generated = apply_page_scaffold(project_dir, "notes/detail")
    assert "frontend/app/_lib/apiBase.ts" in generated
    assert "frontend/app/notes/detail/page.tsx" in generated
    page_text = (project_dir / "frontend" / "app" / "notes" / "detail" / "page.tsx").read_text(encoding="utf-8")
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
