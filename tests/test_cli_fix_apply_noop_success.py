from __future__ import annotations

from pathlib import Path

from archmind.cli import main


def _write_passing_project(root: Path) -> None:
    root.joinpath("pytest.ini").write_text("[pytest]\naddopts = -q\n", encoding="utf-8")
    root.joinpath("test_ok.py").write_text("def test_ok():\n    assert True\n", encoding="utf-8")
    app_dir = root / "app"
    app_dir.mkdir(parents=True, exist_ok=True)


def test_fix_apply_on_passing_project_creates_summary(tmp_path: Path) -> None:
    _write_passing_project(tmp_path)

    exit_code = main(["fix", "--path", str(tmp_path), "--apply", "--model", "none"])
    assert exit_code == 0

    log_dir = tmp_path / ".archmind" / "run_logs"
    summaries = list(log_dir.glob("fix_*.summary.txt"))
    assert summaries, "Expected fix summary to be created"
