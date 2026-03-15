from __future__ import annotations

import json
from pathlib import Path

from archmind.generator import GenerateOptions, generate_project


def test_generate_project_calls_module_hook(tmp_path: Path, monkeypatch) -> None:
    captured: dict[str, object] = {}

    def fake_apply_modules(project_dir: Path, template_name: str, modules: list[str]) -> None:
        captured["project_dir"] = project_dir
        captured["template_name"] = template_name
        captured["modules"] = list(modules)

    monkeypatch.setattr("archmind.generator.apply_modules_to_project", fake_apply_modules)

    opt = GenerateOptions(out=tmp_path, force=False, name="module_hook_demo", template="nextjs")
    setattr(opt, "modules", ["auth", "db"])
    project_dir = generate_project("simple nextjs counter dashboard", opt)

    assert captured.get("project_dir") == project_dir
    assert captured.get("template_name") == "nextjs"
    assert captured.get("modules") == ["auth", "db"]


def test_generate_project_reflects_modules_in_readme_and_artifact(tmp_path: Path) -> None:
    opt = GenerateOptions(out=tmp_path, force=False, name="module_readme_demo", template="fullstack-ddd")
    setattr(opt, "modules", ["auth", "db", "dashboard"])
    project_dir = generate_project("fullstack app with auth dashboard", opt)

    selected_modules = json.loads((project_dir / ".archmind" / "selected_modules.json").read_text(encoding="utf-8"))
    assert selected_modules.get("modules") == ["auth", "db", "dashboard"]

    readme = (project_dir / "README.md").read_text(encoding="utf-8")
    assert "## Selected modules" in readme
    assert "- auth" in readme
    assert "- db" in readme
    assert "- dashboard" in readme
