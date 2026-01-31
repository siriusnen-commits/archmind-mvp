from __future__ import annotations

from pathlib import Path

from archmind.cli import main
from archmind.runner import BackendResult, FrontendResult, RunResult


def _write_defects_file(root: Path) -> Path:
    target = root / "app" / "api" / "routers" / "defects.py"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(
        "from fastapi import APIRouter\n\n"
        "router = APIRouter()\n\n"
        "def list_defects(q: str = Query(None)):\n"
        "    return q\n",
        encoding="utf-8",
    )
    return target


def _make_run_result(tmp_path: Path, log_text: str, summary_lines: list[str], exit_code: int) -> RunResult:
    log_dir = tmp_path / ".archmind" / "run_logs"
    log_dir.mkdir(parents=True, exist_ok=True)
    log_path = log_dir / f"run_{exit_code}_000000.log"
    summary_path = log_dir / f"run_{exit_code}_000000.summary.txt"
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


def test_fix_applies_query_import(tmp_path: Path, monkeypatch) -> None:
    target = _write_defects_file(tmp_path)

    calls = {"count": 0}

    def fake_run_and_collect(
        project_dir: Path, timeout_s: int, scope: str = "backend", **_: object
    ) -> RunResult:
        calls["count"] += 1
        if calls["count"] == 1:
            log = f"Traceback:\nFile \"{target}\", line 4\nNameError: name 'Query' is not defined\n"
            return _make_run_result(tmp_path, log, ["NameError: name 'Query' is not defined"], 1)
        return _make_run_result(tmp_path, "", [], 0)

    monkeypatch.setattr("archmind.fixer.run_and_collect", fake_run_and_collect)

    exit_code = main(["fix", "--path", str(tmp_path), "--apply", "--max-iterations", "2"])
    assert exit_code == 0

    updated = target.read_text(encoding="utf-8")
    assert "Query" in updated
    assert "from fastapi import" in updated


def test_fix_dry_run_does_not_modify(tmp_path: Path, monkeypatch) -> None:
    target = _write_defects_file(tmp_path)
    original = target.read_text(encoding="utf-8")

    def fake_run_and_collect(
        project_dir: Path, timeout_s: int, scope: str = "backend", **_: object
    ) -> RunResult:
        log = f"Traceback:\nFile \"{target}\", line 4\nNameError: name 'Query' is not defined\n"
        return _make_run_result(tmp_path, log, ["NameError: name 'Query' is not defined"], 1)

    monkeypatch.setattr("archmind.fixer.run_and_collect", fake_run_and_collect)

    exit_code = main(["fix", "--path", str(tmp_path), "--dry-run"])
    assert exit_code == 2
    assert target.read_text(encoding="utf-8") == original

    log_dir = tmp_path / ".archmind" / "run_logs"
    assert list(log_dir.glob("fix_*.prompt.md"))
    assert list(log_dir.glob("fix_*.plan.json"))
