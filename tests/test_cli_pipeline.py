from __future__ import annotations

from pathlib import Path

import pytest

from archmind.cli import main


def _write_backend_project(tmp_path: Path) -> None:
    tmp_path.joinpath("pytest.ini").write_text("[pytest]\naddopts = -q\n", encoding="utf-8")
    tmp_path.joinpath("test_ok.py").write_text("def test_ok():\n    assert True\n", encoding="utf-8")


def _write_backend_fail_project(tmp_path: Path) -> None:
    tmp_path.joinpath("pytest.ini").write_text("[pytest]\naddopts = -q\n", encoding="utf-8")
    tmp_path.joinpath("test_fail.py").write_text("def test_fail():\n    assert False\n", encoding="utf-8")


def _fake_generate_project(idea: str, opt) -> Path:
    project_name = (opt.name or "archmind_project").strip() or "archmind_project"
    project_dir = Path(opt.out) / project_name
    project_dir.mkdir(parents=True, exist_ok=True)
    project_dir.joinpath("pytest.ini").write_text("[pytest]\naddopts = -q\n", encoding="utf-8")
    project_dir.joinpath("test_ok.py").write_text("def test_ok():\n    assert True\n", encoding="utf-8")
    return project_dir


def test_pipeline_help() -> None:
    with pytest.raises(SystemExit) as exc:
        main(["pipeline", "--help"])
    assert exc.value.code == 0


def test_pipeline_invalid_path_returns_error(capsys, tmp_path: Path) -> None:
    missing = tmp_path / "missing"
    exit_code = main(["pipeline", "--path", str(missing), "--max-iterations", "1"])
    captured = capsys.readouterr()

    assert exit_code != 0
    assert "path is not a directory" in captured.err.lower() or "error" in captured.err.lower()


def test_pipeline_dry_run_no_artifacts(tmp_path: Path) -> None:
    exit_code = main(["pipeline", "--path", str(tmp_path), "--dry-run"])
    assert exit_code == 0
    assert not (tmp_path / ".archmind").exists()


def test_pipeline_backend_only_smoke(tmp_path: Path) -> None:
    _write_backend_project(tmp_path)

    exit_code = main(
        [
            "pipeline",
            "--path",
            str(tmp_path),
            "--backend-only",
            "--max-iterations",
            "1",
            "--model",
            "none",
            "--scope",
            "backend",
        ]
    )
    assert exit_code in (0, 1)


def test_pipeline_idea_generates_and_runs(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr("archmind.pipeline.generate_project", _fake_generate_project)

    exit_code = main(
        [
            "pipeline",
            "--idea",
            "demo",
            "--template",
            "fullstack-ddd",
            "--out",
            str(tmp_path),
            "--name",
            "demo_proj",
            "--backend-only",
            "--max-iterations",
            "1",
            "--model",
            "none",
        ]
    )
    assert exit_code == 0

    project_dir = tmp_path / "demo_proj"
    assert project_dir.exists()
    log_dir = project_dir / ".archmind" / "run_logs"
    assert log_dir.exists()
    assert list(log_dir.glob("run_*.summary.txt"))


def test_pipeline_path_runs_backend_only(tmp_path: Path) -> None:
    _write_backend_project(tmp_path)

    exit_code = main(
        [
            "pipeline",
            "--path",
            str(tmp_path),
            "--backend-only",
            "--max-iterations",
            "1",
            "--model",
            "none",
        ]
    )
    assert exit_code == 0

    log_dir = tmp_path / ".archmind" / "run_logs"
    assert list(log_dir.glob("run_*.summary.txt"))


def test_pipeline_failure_creates_prompt_and_summary(tmp_path: Path) -> None:
    _write_backend_fail_project(tmp_path)

    exit_code = main(
        [
            "pipeline",
            "--path",
            str(tmp_path),
            "--backend-only",
            "--max-iterations",
            "1",
            "--model",
            "none",
        ]
    )
    assert exit_code != 0

    log_dir = tmp_path / ".archmind" / "run_logs"
    assert list(log_dir.glob("run_*.summary.txt"))
    assert list(log_dir.glob("*.prompt.md"))
