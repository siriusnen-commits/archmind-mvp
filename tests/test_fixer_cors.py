from __future__ import annotations

from pathlib import Path

from archmind.cli import main
from archmind.runner import BackendResult, FrontendResult, RunResult


def _write_app_main(root: Path) -> Path:
    target = root / "app" / "main.py"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(
        "from fastapi import FastAPI\n\n"
        "app = FastAPI()\n",
        encoding="utf-8",
    )
    return target


def _make_run_result(tmp_path: Path, log_text: str, summary_lines: list[str], exit_code: int) -> RunResult:
    log_dir = tmp_path / ".archmind" / "run_logs"
    log_dir.mkdir(parents=True, exist_ok=True)
    log_path = log_dir / f"run_cors_{exit_code}.log"
    summary_path = log_dir / f"run_cors_{exit_code}.summary.txt"
    log_path.write_text(log_text, encoding="utf-8")
    summary_path.write_text("\n".join(summary_lines), encoding="utf-8")

    backend = BackendResult(
        status="PASS" if exit_code == 0 else "FAIL",
        cmd="pytest",
        cwd=str(tmp_path),
        exit_code=exit_code,
        duration_s=0.1,
        output="",
        summary_lines=summary_lines,
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
        overall_exit_code=exit_code,
        log_path=log_path,
        summary_path=summary_path,
        json_summary_path=None,
        timestamp="000000",
    )


def test_fix_adds_cors_middleware(tmp_path: Path, monkeypatch) -> None:
    target = _write_app_main(tmp_path)

    calls = {"count": 0}

    def fake_run_and_collect(project_dir: Path, timeout_s: int, scope: str = "backend") -> RunResult:
        calls["count"] += 1
        if calls["count"] == 1:
            log = "CORS error detected"
            return _make_run_result(tmp_path, log, ["CORS"], 1)
        return _make_run_result(tmp_path, "", [], 0)

    monkeypatch.setattr("archmind.fixer.run_and_collect", fake_run_and_collect)

    exit_code = main(["fix", "--path", str(tmp_path), "--apply", "--max-iterations", "2"])
    assert exit_code == 0

    updated = target.read_text(encoding="utf-8")
    assert "CORSMiddleware" in updated
    assert "allow_origin_regex" in updated
