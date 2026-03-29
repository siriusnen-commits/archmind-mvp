from __future__ import annotations

from pathlib import Path

from archmind.generator import GenerateOptions, generate_project


def test_generate_nextjs_template_scaffold(tmp_path: Path) -> None:
    opt = GenerateOptions(out=tmp_path, force=False, name="nextjs_demo", template="nextjs")
    project_dir = generate_project("simple nextjs counter dashboard", opt)

    assert project_dir == tmp_path / "nextjs_demo"
    assert (project_dir / "package.json").exists()
    assert (project_dir / "app" / "page.tsx").exists()
    assert (project_dir / "tsconfig.json").exists()
    assert (project_dir / ".eslintrc.json").exists()
    assert (project_dir / ".gitignore").exists()

    package_text = (project_dir / "package.json").read_text(encoding="utf-8")
    assert '"next"' in package_text
    assert '"lint": "next lint"' in package_text
    assert '"start": "sh -c \'next start -p ${PORT:-3000}\'"' in package_text
    gitignore_text = (project_dir / ".gitignore").read_text(encoding="utf-8")
    assert ".next/" in gitignore_text
    assert ".archmind/" in gitignore_text
    assert "*.tmp" in gitignore_text
