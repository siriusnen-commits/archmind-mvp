from __future__ import annotations

from pathlib import Path

import pytest

from archmind.cli import main


def _write_backend_project(tmp_path: Path) -> None:
    tmp_path.joinpath("pytest.ini").write_text("[pytest]\naddopts = -q\n", encoding="utf-8")
    tmp_path.joinpath("test_ok.py").write_text("def test_ok():\n    assert True\n", encoding="utf-8")


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
