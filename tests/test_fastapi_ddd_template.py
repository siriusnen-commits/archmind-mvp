from __future__ import annotations

from pathlib import Path

from archmind.generator import GenerateOptions, generate_project


def test_fastapi_ddd_readme_run_command_is_runtime_neutral(tmp_path: Path) -> None:
    opt = GenerateOptions(out=tmp_path, force=False, name="fastapi_ddd_demo", template="fastapi-ddd")
    project_dir = generate_project("defect tracker api", opt)

    readme = (project_dir / "README.md").read_text(encoding="utf-8")
    assert "python -m uvicorn app.main:app --reload --host 0.0.0.0 --port ${PORT:-8000}" in readme
