from __future__ import annotations

from pathlib import Path

from archmind.fixer import _write_fix_prompt
from archmind.runner import BackendResult, FrontendResult, FrontendStepResult, RunResult


def test_frontend_fix_prompt_contains_error_summary(tmp_path: Path) -> None:
    log_dir = tmp_path / "logs"
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
    assert "프론트 오류 요약" in prompt_text
    assert "no-unused-vars" in prompt_text
    assert "린트/타입체크" in prompt_text
