from __future__ import annotations

from pathlib import Path

from archmind.generator import GenerateOptions, generate_project


def test_generate_internal_tool_template_scaffold(tmp_path: Path) -> None:
    opt = GenerateOptions(out=tmp_path, force=False, name="internal_tool_demo", template="internal-tool")
    project_dir = generate_project("internal admin dashboard for device status", opt)

    assert project_dir == tmp_path / "internal_tool_demo"
    assert (project_dir / "requirements.txt").exists()
    assert (project_dir / "frontend" / "package.json").exists()
    assert (project_dir / "frontend" / "app" / "page.tsx").exists()

    readme = (project_dir / "README.md").read_text(encoding="utf-8")
    assert "internal-tool" in readme
    assert "python -m uvicorn app.main:app --reload --host 0.0.0.0 --port ${PORT:-8000}" in readme
    assert "npm run dev" in readme
