from __future__ import annotations

from pathlib import Path

from archmind.generator import GenerateOptions, generate_project


def test_generate_data_tool_template_scaffold(tmp_path: Path) -> None:
    opt = GenerateOptions(out=tmp_path, force=False, name="data_tool_demo", template="data-tool")
    project_dir = generate_project("inventory management tool for small business", opt)

    assert project_dir == tmp_path / "data_tool_demo"
    assert (project_dir / "requirements.txt").exists()
    assert (project_dir / "frontend" / "package.json").exists()
    assert (project_dir / "frontend" / "app" / "page.tsx").exists()

    page_text = (project_dir / "frontend" / "app" / "page.tsx").read_text(encoding="utf-8")
    assert "Data Tool Dashboard" in page_text

    readme = (project_dir / "README.md").read_text(encoding="utf-8")
    assert "data-tool" in readme
    assert "data viewer" in readme.lower()
