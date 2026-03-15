from __future__ import annotations

from pathlib import Path
import subprocess
import sys

from archmind.generator import GenerateOptions, generate_project


def test_generate_worker_api_template_scaffold(tmp_path: Path) -> None:
    opt = GenerateOptions(out=tmp_path, force=False, name="worker_api_demo", template="worker-api")
    project_dir = generate_project("background batch processing api", opt)

    assert project_dir == tmp_path / "worker_api_demo"
    assert (project_dir / "app" / "workers" / "tasks.py").exists()
    assert (project_dir / "app" / "api" / "routers" / "worker.py").exists()
    assert (project_dir / "data" / ".gitkeep").exists()

    api_router = (project_dir / "app" / "api" / "router.py").read_text(encoding="utf-8")
    assert "worker_router" in api_router

    session_py = (project_dir / "app" / "db" / "session.py").read_text(encoding="utf-8")
    assert "def _ensure_sqlite_parent_dir" in session_py
    assert 'if not value.startswith("sqlite:///")' in session_py
    assert "Path(db_path).expanduser().parent.mkdir(parents=True, exist_ok=True)" in session_py

    readme = (project_dir / "README.md").read_text(encoding="utf-8")
    assert "worker-api" in readme
    assert "POST /worker/run" in readme


def test_worker_api_generated_project_pytest_passes(tmp_path: Path) -> None:
    opt = GenerateOptions(out=tmp_path, force=False, name="worker_api_pytest_demo", template="worker-api")
    project_dir = generate_project("background batch processing api", opt)
    result = subprocess.run(
        [sys.executable, "-m", "pytest", "-q"],
        cwd=project_dir,
        capture_output=True,
        text=True,
        timeout=120,
    )
    assert result.returncode == 0, result.stderr
