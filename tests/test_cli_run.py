from __future__ import annotations

from pathlib import Path

from archmind.cli import main


def test_run_missing_path_returns_2(capsys, tmp_path: Path) -> None:
    missing = tmp_path / "missing_project"
    exit_code = main(["run", "--path", str(missing)])
    captured = capsys.readouterr()

    assert exit_code == 2
    assert "path not found" in captured.err.lower()


def test_run_pytest_failure_creates_logs(tmp_path: Path) -> None:
    test_file = tmp_path / "test_fail.py"
    test_file.write_text("def test_fail():\n    assert False\n", encoding="utf-8")

    exit_code = main(["run", "--path", str(tmp_path)])
    assert exit_code == 1

    log_dir = tmp_path / ".archmind" / "run_logs"
    log_files = list(log_dir.glob("pytest_*.log"))
    summary_files = list(log_dir.glob("pytest_*.summary.txt"))

    assert log_files, "Expected pytest log file to be created"
    assert summary_files, "Expected pytest summary file to be created"
    assert summary_files[0].read_text(encoding="utf-8").strip()
