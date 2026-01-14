from __future__ import annotations

import json
from pathlib import Path

from archmind.cli import main
from archmind.runner import BackendResult, FrontendResult, RunResult


def _write_run_artifacts(tmp_path: Path) -> RunResult:
    log_dir = tmp_path / ".archmind" / "run_logs"
    log_dir.mkdir(parents=True, exist_ok=True)
    log_path = log_dir / "run_20240101_000000.log"
    log_path.write_text(
        "Traceback:\nFile \"app/api/routers/defects.py\", line 1\nNameError: name 'Query' is not defined\n",
        encoding="utf-8",
    )
    summary_path = log_dir / "run_20240101_000000.summary.txt"
    summary_path.write_text("", encoding="utf-8")

    summary_json = log_dir / "run_20240101_000000.summary.json"
    payload = {
        "meta": {
            "project_dir": str(tmp_path),
            "timestamp": "20240101_000000",
            "command": "archmind run",
            "log_path": str(log_path),
            "summary_path": str(summary_path),
        },
        "backend": {
            "status": "FAIL",
            "cmd": "pytest",
            "cwd": str(tmp_path),
            "exit_code": 1,
            "duration_s": 0.1,
            "summary_lines": ["NameError: name 'Query' is not defined"],
        },
        "frontend": {
            "status": "SKIPPED",
            "node_detected": False,
            "npm_detected": False,
            "install_attempted": False,
            "steps": [],
            "reason": "frontend not requested.",
            "summary_lines": [],
        },
        "overall_exit_code": 1,
    }
    summary_json.write_text(json.dumps(payload), encoding="utf-8")

    backend = BackendResult(
        status="FAIL",
        cmd="pytest",
        cwd=str(tmp_path),
        exit_code=1,
        duration_s=0.1,
        output="",
        summary_lines=["NameError: name 'Query' is not defined"],
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
        json_summary_path=summary_json,
        timestamp="20240101_000000",
    )


def test_fix_plan_generation_creates_plan_files(tmp_path: Path, monkeypatch) -> None:
    run_result = _write_run_artifacts(tmp_path)

    monkeypatch.setattr("archmind.fixer.run_pipeline", lambda _: run_result)

    exit_code = main(
        [
            "fix",
            "--path",
            str(tmp_path),
            "--dry-run",
            "--model",
            "none",
            "--scope",
            "backend",
        ]
    )
    assert exit_code == 1

    plan_dir = tmp_path / ".archmind" / "fix_plans"
    plans = list(plan_dir.glob("fix_*.plan.json"))
    mds = list(plan_dir.glob("fix_*.plan.md"))
    assert plans, "Expected plan.json to be created"
    assert mds, "Expected plan.md to be created"


def test_fix_max_iterations_stops_after_one(tmp_path: Path, monkeypatch) -> None:
    run_result = _write_run_artifacts(tmp_path)

    monkeypatch.setattr("archmind.fixer.run_pipeline", lambda _: run_result)
    monkeypatch.setattr(
        "archmind.fixer.build_plan",
        lambda *_: {
            "meta": {"timestamp": "20240101_000001", "project_dir": str(tmp_path)},
            "iteration": 1,
            "scope": "backend",
            "diagnosis": {},
            "changes": [],
            "commands_after": [],
        },
    )

    exit_code = main(
        [
            "fix",
            "--path",
            str(tmp_path),
            "--model",
            "none",
            "--scope",
            "backend",
            "--max-iterations",
            "1",
            "--apply",
        ]
    )
    assert exit_code == 1
