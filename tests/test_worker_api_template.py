from __future__ import annotations

from pathlib import Path

from archmind.generator import GenerateOptions, generate_project


def test_generate_worker_api_template_scaffold(tmp_path: Path) -> None:
    opt = GenerateOptions(out=tmp_path, force=False, name="worker_api_demo", template="worker-api")
    project_dir = generate_project("background batch processing api", opt)

    assert project_dir == tmp_path / "worker_api_demo"
    assert (project_dir / "app" / "workers" / "tasks.py").exists()
    assert (project_dir / "app" / "api" / "routers" / "worker.py").exists()

    api_router = (project_dir / "app" / "api" / "router.py").read_text(encoding="utf-8")
    assert "worker_router" in api_router

    readme = (project_dir / "README.md").read_text(encoding="utf-8")
    assert "worker-api" in readme
    assert "POST /worker/run" in readme
