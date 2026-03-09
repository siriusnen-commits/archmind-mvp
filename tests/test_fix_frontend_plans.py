from __future__ import annotations

import json
from pathlib import Path

from archmind.fixer import _write_fix_prompt
from archmind.runner import BackendResult, FrontendResult, FrontendStepResult, RunResult


def test_frontend_fix_prompt_contains_error_summary(tmp_path: Path) -> None:
    plan_path = tmp_path / ".archmind" / "plan.md"
    plan_path.parent.mkdir(parents=True, exist_ok=True)
    plan_path.write_text("# ArchMind Plan\n- 핵심 단계: lint 오류 수정\n", encoding="utf-8")
    (tmp_path / ".archmind" / "tasks.json").write_text(
        json.dumps(
            {
                "project_dir": str(tmp_path.resolve()),
                "created_at": "20260101_000000",
                "tasks": [
                    {"id": 1, "title": "create backend skeleton", "status": "todo", "source": "plan", "notes": ""},
                    {"id": 2, "title": "add API endpoints", "status": "doing", "source": "plan", "notes": ""},
                ],
            }
        ),
        encoding="utf-8",
    )

    log_dir = tmp_path / ".archmind" / "run_logs"
    log_dir.mkdir(parents=True, exist_ok=True)

    summary_path = log_dir / "run.summary.txt"
    summary_path.write_text(
        "4) Failure summary:\n- Frontend: lint failed\n5) Next actions:\n",
        encoding="utf-8",
    )

    frontend_step = FrontendStepResult(
        name="lint",
        cmd=["npm", "run", "lint"],
        exit_code=2,
        duration_s=1.0,
        stdout="",
        stderr="frontend/app/page.tsx:10:1 error no-unused-vars\n",
        summary_lines=["frontend/app/page.tsx:10:1 error no-unused-vars"],
    )

    run_result = RunResult(
        backend=BackendResult(
            status="SKIPPED",
            cmd=None,
            cwd=None,
            exit_code=None,
            duration_s=None,
            output="",
            summary_lines=[],
            reason="backend not requested.",
        ),
        frontend=FrontendResult(
            status="FAIL",
            node_detected=True,
            npm_detected=True,
            install_attempted=True,
            steps=[frontend_step],
            summary_lines=["lint failed"],
            reason="lint failed.",
        ),
        overall_exit_code=2,
        log_path=log_dir / "run.log",
        summary_path=summary_path,
        json_summary_path=None,
        timestamp="20260128_000000",
    )

    prompt_path = _write_fix_prompt(
        log_dir,
        "20260128_000000",
        "archmind fix --path /tmp/project --scope frontend",
        run_result,
        ["frontend/app/page.tsx:10:1 error no-unused-vars"],
        "frontend",
    )

    prompt_text = prompt_path.read_text(encoding="utf-8")
    assert "Plan 요약" in prompt_text
    assert "Current Task" in prompt_text
    assert "Current Evaluation" in prompt_text
    assert "State Summary" in prompt_text
    assert "[2] doing add API endpoints" in prompt_text
    assert "핵심 단계: lint 오류 수정" in prompt_text
    assert "프론트 오류 요약" in prompt_text
    assert "no-unused-vars" in prompt_text
    assert "# Relevant Files" in prompt_text
    assert "린트/타입체크" in prompt_text


def test_frontend_fix_prompt_marks_missing_plan(tmp_path: Path) -> None:
    log_dir = tmp_path / ".archmind" / "run_logs"
    log_dir.mkdir(parents=True, exist_ok=True)
    summary_path = log_dir / "run.summary.txt"
    summary_path.write_text("4) Failure summary:\n- Frontend: lint failed\n", encoding="utf-8")

    frontend_step = FrontendStepResult(
        name="lint",
        cmd=["npm", "run", "lint"],
        exit_code=2,
        duration_s=1.0,
        stdout="",
        stderr="lint failed\n",
        summary_lines=["lint failed"],
    )
    run_result = RunResult(
        backend=BackendResult(
            status="SKIPPED",
            cmd=None,
            cwd=None,
            exit_code=None,
            duration_s=None,
            output="",
            summary_lines=[],
            reason="backend not requested.",
        ),
        frontend=FrontendResult(
            status="FAIL",
            node_detected=True,
            npm_detected=True,
            install_attempted=True,
            steps=[frontend_step],
            summary_lines=["lint failed"],
            reason="lint failed.",
        ),
        overall_exit_code=2,
        log_path=log_dir / "run.log",
        summary_path=summary_path,
        json_summary_path=None,
        timestamp="20260128_000001",
    )

    prompt_path = _write_fix_prompt(
        log_dir,
        "20260128_000001",
        "archmind fix --path /tmp/project --scope frontend",
        run_result,
        ["lint failed"],
        "frontend",
    )
    prompt_text = prompt_path.read_text(encoding="utf-8")
    assert "plan missing" in prompt_text
    assert "Current Evaluation" in prompt_text
    assert "State Summary" in prompt_text
