from __future__ import annotations

import shlex
import subprocess
import sys
from datetime import datetime
from pathlib import Path
from typing import Optional, Sequence


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


def run_project(
    project_dir: Path,
    cmd: str,
    pytest_args: Optional[str],
    timeout_s: int,
) -> int:
    if cmd != "pytest":
        print(f"[ERROR] Unsupported command preset: {cmd}", file=sys.stderr)
        return 2

    venv_python = _find_venv_python(project_dir)
    if venv_python is None:
        print(
            "[INFO] No venv found (.venv/venv). Using current interpreter.",
            file=sys.stderr,
        )
        venv_python = Path(sys.executable)

    command = _build_pytest_command(venv_python, pytest_args)
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
            print(
                f"[ERROR] pytest failed (exit {result.returncode}). Log: {log_path}",
                file=sys.stderr,
            )
            return 1

        print(f"[OK] pytest passed. Log: {log_path}")
        return 0
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
        print(
            f"[ERROR] pytest timed out after {timeout_s}s. Log: {log_path}",
            file=sys.stderr,
        )
        return 1
