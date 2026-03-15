from __future__ import annotations

from pathlib import Path

from archmind.generator import apply_entity_scaffold


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
