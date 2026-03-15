from __future__ import annotations

import json
from pathlib import Path

from archmind.brain import reason_architecture_from_idea
from archmind.cli import main
from archmind.generator import GenerateOptions, generate_project


def _fake_generate_project(idea: str, opt) -> Path:  # type: ignore[no-untyped-def]
    del idea
    project_name = (opt.name or "archmind_project").strip() or "archmind_project"
    project_dir = Path(opt.out) / project_name
    project_dir.mkdir(parents=True, exist_ok=True)
    project_dir.joinpath("pytest.ini").write_text("[pytest]\naddopts = -q\n", encoding="utf-8")
    project_dir.joinpath("test_ok.py").write_text("def test_ok():\n    assert True\n", encoding="utf-8")
    project_dir.joinpath("README.md").write_text("# demo\n", encoding="utf-8")
    return project_dir


def test_module_reasoning_login_dashboard_case() -> None:
    out = reason_architecture_from_idea("team task tracker with login dashboard")
    modules = list(out.get("modules") or [])
    assert "auth" in modules
    assert "db" in modules
    assert "dashboard" in modules


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
    assert "This project was generated with modules selected by ArchMind reasoning." in readme


def test_auth_module_creates_backend_router_file(tmp_path: Path) -> None:
    opt = GenerateOptions(out=tmp_path, force=False, name="module_auth_backend", template="fastapi-ddd")
    setattr(opt, "modules", ["auth"])
    project_dir = generate_project("simple auth api", opt)
    assert (project_dir / "app" / "auth" / "router.py").exists()


def test_db_module_creates_backend_database_file(tmp_path: Path) -> None:
    opt = GenerateOptions(out=tmp_path, force=False, name="module_db_backend", template="fastapi-ddd")
    setattr(opt, "modules", ["db"])
    project_dir = generate_project("simple tracker api", opt)
    assert (project_dir / "app" / "db" / "database.py").exists()


def test_dashboard_module_creates_frontend_page(tmp_path: Path) -> None:
    opt = GenerateOptions(out=tmp_path, force=False, name="module_dashboard_frontend", template="nextjs")
    setattr(opt, "modules", ["dashboard"])
    project_dir = generate_project("simple nextjs dashboard", opt)
    assert (project_dir / "app" / "dashboard" / "page.tsx").exists()


def test_pipeline_project_spec_modules_match_reasoning(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr("archmind.pipeline._resolve_generator_entry", lambda: _fake_generate_project)

    exit_code = main(
        [
            "pipeline",
            "--idea",
            "team task tracker with login dashboard",
            "--out",
            str(tmp_path),
            "--name",
            "module_spec_demo",
            "--backend-only",
            "--max-iterations",
            "1",
            "--model",
            "none",
        ]
    )
    assert exit_code == 0

    project_dir = tmp_path / "module_spec_demo"
    reasoning = json.loads((project_dir / ".archmind" / "architecture_reasoning.json").read_text(encoding="utf-8"))
    project_spec = json.loads((project_dir / ".archmind" / "project_spec.json").read_text(encoding="utf-8"))
    assert project_spec.get("modules") == reasoning.get("modules")
    assert project_spec.get("evolution", {}).get("version") == 1
