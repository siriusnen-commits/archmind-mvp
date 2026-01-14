from __future__ import annotations

import shlex
import subprocess
import sys
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Optional, Sequence

from archmind.fixer import FixResult, generate_patch
from archmind.patcher import apply_unified_diff


def _find_venv_python(project_dir: Path) -> Optional[Path]:
    candidates = [
        project_dir / ".venv" / "bin" / "python",
        project_dir / "venv" / "bin" / "python",
    ]
    for candidate in candidates:
        if candidate.exists():
            return candidate
    return None


def _normalize_output(output: str | bytes | None) -> str:
    if output is None:
        return ""
    if isinstance(output, bytes):
        return output.decode("utf-8", errors="replace")
    return output


def _format_log(
    cmd: Sequence[str],
    cwd: Path,
    stdout: str,
    stderr: str,
    exit_code: str,
    timestamp: str,
) -> str:
    return "\n".join(
        [
            f"COMMAND: {' '.join(cmd)}",
            f"CWD: {cwd}",
            f"EXIT_CODE: {exit_code}",
            f"TIMESTAMP: {timestamp}",
            "",
            "STDOUT:",
            stdout.rstrip(),
            "",
            "STDERR:",
            stderr.rstrip(),
            "",
        ]
    )


def _extract_failure_summary(log_text: str) -> str:
    keywords = ["FAILURES", "E   ", "Traceback"]
    last_index = -1
    for kw in keywords:
        idx = log_text.rfind(kw)
        if idx > last_index:
            last_index = idx

    excerpt = log_text[last_index:] if last_index != -1 else log_text
    lines = excerpt.splitlines()
    if len(lines) > 200:
        lines = lines[-200:]
    return "\n".join(lines).rstrip() + "\n"


def _build_pytest_command(python_path: Path, pytest_args: Optional[str]) -> list[str]:
    cmd = [str(python_path), "-m", "pytest", "-q"]
    if pytest_args:
        cmd.extend(shlex.split(pytest_args))
    return cmd


@dataclass
class RunResult:
    exit_code: int
    log_path: Path
    summary_path: Optional[Path]
    log_text: str


def _run_pytest(
    project_dir: Path,
    pytest_args: Optional[str],
    timeout_s: int,
    python_path: Path,
) -> RunResult:
    command = _build_pytest_command(python_path, pytest_args)
    log_dir = project_dir / ".archmind" / "run_logs"
    log_dir.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    log_path = log_dir / f"pytest_{timestamp}.log"
    summary_path = log_dir / f"pytest_{timestamp}.summary.txt"

    try:
        result = subprocess.run(
            command,
            cwd=project_dir,
            capture_output=True,
            text=True,
            timeout=timeout_s,
        )
        log_text = _format_log(
            command,
            project_dir,
            result.stdout,
            result.stderr,
            str(result.returncode),
            timestamp,
        )
        log_path.write_text(log_text, encoding="utf-8")

        if result.returncode != 0:
            summary = _extract_failure_summary(log_text)
            summary_path.write_text(summary, encoding="utf-8")
            return RunResult(
                exit_code=1,
                log_path=log_path,
                summary_path=summary_path,
                log_text=log_text,
            )

        return RunResult(exit_code=0, log_path=log_path, summary_path=None, log_text=log_text)
    except subprocess.TimeoutExpired as exc:
        stdout = _normalize_output(exc.stdout)
        stderr = _normalize_output(exc.stderr)
        log_text = _format_log(
            command,
            project_dir,
            stdout,
            stderr,
            "timeout",
            timestamp,
        )
        log_path.write_text(log_text, encoding="utf-8")
        summary = _extract_failure_summary(log_text)
        summary_path.write_text(summary, encoding="utf-8")
        return RunResult(
            exit_code=1,
            log_path=log_path,
            summary_path=summary_path,
            log_text=log_text,
        )


def _resolve_python(project_dir: Path) -> Path:
    venv_python = _find_venv_python(project_dir)
    if venv_python is None:
        print(
            "[INFO] No venv found (.venv/venv). Using current interpreter.",
            file=sys.stderr,
        )
        venv_python = Path(sys.executable)
    return venv_python


def _maybe_auto_commit(project_dir: Path) -> None:
    if not (project_dir / ".git").exists():
        print("[INFO] No git repo found. Skipping auto-commit.", file=sys.stderr)
        return

    status = subprocess.run(
        ["git", "status", "--porcelain"],
        cwd=project_dir,
        capture_output=True,
        text=True,
        check=False,
    )
    if not status.stdout.strip():
        print("[INFO] No changes to commit.", file=sys.stderr)
        return

    subprocess.run(["git", "add", "-A"], cwd=project_dir, check=False)
    subprocess.run(
        ["git", "commit", "-m", "archmind auto-fix"],
        cwd=project_dir,
        check=False,
    )


def run_project(
    project_dir: Path,
    cmd: str,
    pytest_args: Optional[str],
    timeout_s: int,
) -> int:
    if cmd != "pytest":
        print(f"[ERROR] Unsupported command preset: {cmd}", file=sys.stderr)
        return 2

    venv_python = _resolve_python(project_dir)
    result = _run_pytest(project_dir, pytest_args, timeout_s, venv_python)
    if result.exit_code != 0:
        print(
            f"[ERROR] pytest failed. Log: {result.log_path}",
            file=sys.stderr,
        )
        return 1

    print(f"[OK] pytest passed. Log: {result.log_path}")
    return 0


def run_project_with_fix(
    project_dir: Path,
    cmd: str,
    pytest_args: Optional[str],
    timeout_s: int,
    max_iter: int,
    dry_run: bool,
    auto_commit: bool,
) -> int:
    if cmd != "pytest":
        print(f"[ERROR] Unsupported command preset: {cmd}", file=sys.stderr)
        return 2

    venv_python = _resolve_python(project_dir)

    for iteration in range(1, max_iter + 1):
        result = _run_pytest(project_dir, pytest_args, timeout_s, venv_python)
        if result.exit_code == 0:
            print(f"[OK] pytest passed on iteration {iteration}. Log: {result.log_path}")
            if auto_commit:
                _maybe_auto_commit(project_dir)
            return 0

        if result.summary_path is None or not result.summary_path.exists():
            print("[ERROR] No summary found for failed run.", file=sys.stderr)
            return 1

        summary_text = result.summary_path.read_text(encoding="utf-8")
        log_text = result.log_path.read_text(encoding="utf-8")
        fix: FixResult = generate_patch(project_dir, summary_text, log_text)
        if not fix.diff:
            print(f"[ERROR] No fix generated: {fix.reason}", file=sys.stderr)
            return 1

        if dry_run:
            print(fix.diff)
            return 1

        try:
            apply_unified_diff(project_dir, fix.diff)
        except Exception as exc:
            print(f"[ERROR] Patch apply failed: {exc}", file=sys.stderr)
            return 1

    print("[ERROR] Max iterations exceeded without passing tests.", file=sys.stderr)
    return 1
