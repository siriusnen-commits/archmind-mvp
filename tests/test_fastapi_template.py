from __future__ import annotations

from pathlib import Path

from archmind.cli import main
from archmind.generator import GenerateOptions, generate_project


def _fake_backend_spec(prompt: str, idea: str, opt: GenerateOptions):  # type: ignore[no-untyped-def]
    return {
        "project_name": (opt.name or "archmind_project"),
        "summary": "backend baseline",
        "directories": [],
        "files": {},
    }


def test_fastapi_template_generates_pytest_ready_scaffold(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr("archmind.generator.generate_valid_spec", _fake_backend_spec)
    opt = GenerateOptions(out=tmp_path, force=False, name="fastapi_demo", template="fastapi")
    project_dir = generate_project("simple fastapi notes api", opt)

    assert (project_dir / "app" / "main.py").exists()
    assert (project_dir / "main.py").exists()
    assert (project_dir / "tests" / "test_health.py").exists()
    assert (project_dir / "pytest.ini").exists()

    requirements = (project_dir / "requirements.txt").read_text(encoding="utf-8")
    assert "fastapi==0.115.0" in requirements
    assert "uvicorn[standard]==0.30.6" in requirements
    assert "pytest==9.0.2" in requirements
    assert "httpx==0.27.0" in requirements


def test_generated_fastapi_project_backend_run_is_not_skipped(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr("archmind.generator.generate_valid_spec", _fake_backend_spec)
    opt = GenerateOptions(out=tmp_path, force=False, name="fastapi_run_demo", template="fastapi")
    project_dir = generate_project("simple fastapi notes api", opt)

    exit_code = main(["run", "--path", str(project_dir), "--backend-only"])
    assert exit_code == 0

    summaries = sorted((project_dir / ".archmind" / "run_logs").glob("run_*.summary.txt"))
    assert summaries
    summary_text = summaries[-1].read_text(encoding="utf-8")
    assert "No pytest.ini or tests/ directory." not in summary_text
    assert "status: PASS" in summary_text


def test_fastapi_generation_handles_requirements_case_collision_without_duplicate_write(
    tmp_path: Path, monkeypatch
) -> None:
    def fake_case_collision_spec(prompt: str, idea: str, opt: GenerateOptions):  # type: ignore[no-untyped-def]
        return {
            "project_name": (opt.name or "archmind_project"),
            "summary": "backend baseline",
            "directories": [],
            "files": {
                "Requirements.txt": "requests==2.32.0\n",
                "main.py": "print('placeholder')\n",
            },
        }

    monkeypatch.setattr("archmind.generator.generate_valid_spec", fake_case_collision_spec)
    opt = GenerateOptions(out=tmp_path, force=False, name="fastapi_case_demo", template="fastapi")
    project_dir = generate_project("simple fastapi notes api", opt)

    requirements_path = project_dir / "requirements.txt"
    assert requirements_path.exists()
    text = requirements_path.read_text(encoding="utf-8")
    assert "requests==2.32.0" in text
    assert "fastapi==0.115.0" in text


def test_fastapi_readme_run_command_is_runtime_neutral(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr("archmind.generator.generate_valid_spec", _fake_backend_spec)
    opt = GenerateOptions(out=tmp_path, force=False, name="fastapi_runtime_demo", template="fastapi")
    project_dir = generate_project("simple fastapi notes api", opt)

    readme = (project_dir / "README.md").read_text(encoding="utf-8")
    assert "python -m uvicorn app.main:app --reload --host 0.0.0.0 --port ${APP_PORT:-${PORT:-8000}}" in readme
