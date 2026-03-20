from __future__ import annotations

from pathlib import Path

from archmind.generator import GenerateOptions, generate_project, validate_generated_project_structure


def test_backend_fastapi_normalizes_absolute_paths_and_avoids_duplicate_writes(tmp_path: Path, monkeypatch) -> None:
    def fake_generate_valid_spec(prompt: str, idea: str, opt: GenerateOptions):  # type: ignore[no-untyped-def]
        return {
            "project_name": "backend_demo",
            "summary": "backend",
            "directories": ["/notes"],
            "files": {
                "/requirements.txt": "requests==2.32.0\n",
                "requirements.txt": "httpx==0.27.0\n",
                "/main.py": "print('hello')\n",
            },
        }

    monkeypatch.setattr("archmind.generator.generate_valid_spec", fake_generate_valid_spec)
    opt = GenerateOptions(out=tmp_path, force=False, name="backend_demo", template="fastapi")
    project_dir = generate_project("simple fastapi notes api", opt)

    assert project_dir == tmp_path / "backend_demo"
    assert (project_dir / "notes").exists()
    assert (project_dir / "requirements.txt").exists()

    requirements = (project_dir / "requirements.txt").read_text(encoding="utf-8")
    assert "fastapi" in requirements
    assert "uvicorn[standard]" in requirements
    assert requirements.count("fastapi") == 1


def test_nextjs_and_fullstack_templates_still_generate(tmp_path: Path) -> None:
    nextjs_opt = GenerateOptions(out=tmp_path, force=False, name="nextjs_demo", template="nextjs")
    nextjs_dir = generate_project("simple nextjs counter dashboard", nextjs_opt)
    assert (nextjs_dir / "app" / "page.tsx").exists()
    assert (nextjs_dir / "package.json").exists()

    fullstack_opt = GenerateOptions(out=tmp_path, force=False, name="fullstack_demo", template="fullstack-ddd")
    fullstack_dir = generate_project("fullstack app with fastapi backend and nextjs frontend", fullstack_opt)
    assert (fullstack_dir / "backend" / "requirements.txt").exists()
    assert (fullstack_dir / "backend" / "app" / "main.py").exists()
    assert not (fullstack_dir / "main.py").exists()
    assert (fullstack_dir / "frontend" / "package.json").exists()


def test_validate_generated_project_structure_for_fullstack_contract(tmp_path: Path) -> None:
    project = tmp_path / "contract"
    (project / "backend" / "app").mkdir(parents=True, exist_ok=True)
    (project / "backend" / "app" / "main.py").write_text("from fastapi import FastAPI\napp = FastAPI()\n", encoding="utf-8")
    (project / "backend" / "requirements.txt").write_text("fastapi\n", encoding="utf-8")
    (project / "frontend").mkdir(parents=True, exist_ok=True)
    check = validate_generated_project_structure(project, template_name="fullstack-ddd")
    assert check["ok"] is True


def test_validate_generated_project_structure_for_fastapi_accepts_backend_prefixed_layout(tmp_path: Path) -> None:
    project = tmp_path / "fastapi_backend_prefixed"
    (project / "backend" / "app").mkdir(parents=True, exist_ok=True)
    (project / "backend" / "app" / "main.py").write_text("from fastapi import FastAPI\napp = FastAPI()\n", encoding="utf-8")
    (project / "backend" / "requirements.txt").write_text("fastapi\n", encoding="utf-8")

    check = validate_generated_project_structure(project, template_name="fastapi-ddd")
    assert check["ok"] is True


def test_validate_generated_project_structure_for_data_tool_contract(tmp_path: Path) -> None:
    project = tmp_path / "data_tool_contract"
    (project / "backend" / "app").mkdir(parents=True, exist_ok=True)
    (project / "backend" / "app" / "main.py").write_text("from fastapi import FastAPI\napp = FastAPI()\n", encoding="utf-8")
    (project / "backend" / "requirements.txt").write_text("fastapi\n", encoding="utf-8")
    (project / "frontend" / "app").mkdir(parents=True, exist_ok=True)
    (project / "frontend" / "package.json").write_text("{\"name\":\"demo\"}\n", encoding="utf-8")
    (project / "frontend" / "app" / "page.tsx").write_text("export default function Page(){return null}\n", encoding="utf-8")

    check = validate_generated_project_structure(project, template_name="data-tool")
    assert check["ok"] is True


def test_validate_generated_project_structure_for_data_tool_reports_template_specific_reason(tmp_path: Path) -> None:
    project = tmp_path / "data_tool_invalid"
    (project / "frontend").mkdir(parents=True, exist_ok=True)
    (project / "frontend" / "package.json").write_text("{\"name\":\"demo\"}\n", encoding="utf-8")

    check = validate_generated_project_structure(project, template_name="data-tool")
    assert check["ok"] is False
    assert str(check.get("reason", "")).startswith("invalid data-tool structure:")
