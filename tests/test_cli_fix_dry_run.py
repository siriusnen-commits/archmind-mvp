from __future__ import annotations

from pathlib import Path

from archmind.cli import main
from archmind.runner import BackendResult, FrontendResult, RunResult


def _snapshot_files(root: Path) -> dict[Path, bytes]:
    snapshots: dict[Path, bytes] = {}
    for path in root.rglob("*"):
        if ".archmind" in path.parts:
            continue
        if path.is_file():
            snapshots[path] = path.read_bytes()
    return snapshots


def _make_run_result(tmp_path: Path) -> RunResult:
    log_dir = tmp_path / ".archmind" / "run_logs"
    log_dir.mkdir(parents=True, exist_ok=True)
    log_path = log_dir / "run_dry_000000.log"
    summary_path = log_dir / "run_dry_000000.summary.txt"
    log_text = "Traceback:\nFile \"app/main.py\", line 1\nAssertionError: fail\n"
    log_path.write_text(log_text, encoding="utf-8")
    summary_path.write_text("4) Failure summary:\n- Backend: AssertionError\n", encoding="utf-8")

    backend = BackendResult(
        status="FAIL",
        cmd="pytest",
        cwd=str(tmp_path),
        exit_code=1,
        duration_s=0.1,
        output=log_text,
        summary_lines=["AssertionError"],
        reason=None,
    )
    frontend = FrontendResult(
        status="SKIPPED",
        node_detected=False,
        npm_detected=False,
        install_attempted=False,
        steps=[],
        summary_lines=[],
        reason="frontend not requested.",
    )
    return RunResult(
        backend=backend,
        frontend=frontend,
        overall_exit_code=1,
        log_path=log_path,
        summary_path=summary_path,
        json_summary_path=None,
        timestamp="000000",
    )


def test_fix_dry_run_creates_prompt_and_plan(tmp_path: Path, monkeypatch) -> None:
    tmp_path.joinpath("pytest.ini").write_text("[pytest]\naddopts = -q\n", encoding="utf-8")
    app_file = tmp_path / "app" / "main.py"
    app_file.parent.mkdir(parents=True, exist_ok=True)
    app_file.write_text("print('ok')\n", encoding="utf-8")

    run_result = _make_run_result(tmp_path)
    monkeypatch.setattr("archmind.fixer.run_and_collect", lambda *_args, **_kwargs: run_result)

    before = _snapshot_files(tmp_path)
    exit_code = main(["fix", "--path", str(tmp_path), "--dry-run", "--model", "none"])
    after = _snapshot_files(tmp_path)

    assert exit_code == 2
    assert before == after

    log_dir = tmp_path / ".archmind" / "run_logs"
    assert list(log_dir.glob("fix_*.prompt.md"))
    assert list(log_dir.glob("fix_*.plan.json"))
