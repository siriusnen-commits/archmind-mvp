from __future__ import annotations

import json
import shutil
import subprocess
import sys
import time
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Optional


@dataclass
class RunConfig:
    project_dir: Path
    run_all: bool
    backend_only: bool
    frontend_only: bool
    no_install: bool
    timeout_s: int
    log_dir: Path
    json_summary: bool
    command: str


@dataclass
class CommandResult:
    cmd: list[str]
    cwd: Path
    exit_code: int
    duration_s: float
    stdout: str
    stderr: str
    timed_out: bool = False


@dataclass
class BackendResult:
    status: str
    cmd: Optional[str]
    cwd: Optional[str]
    exit_code: Optional[int]
    duration_s: Optional[float]
    output: str
    summary_lines: list[str]
    reason: Optional[str] = None


@dataclass
class FrontendStepResult:
    name: str
    cmd: list[str]
    exit_code: int
    duration_s: float
    stdout: str
    stderr: str
    timed_out: bool = False


@dataclass
class FrontendResult:
    status: str
    node_detected: bool
    npm_detected: bool
    install_attempted: bool
    steps: list[FrontendStepResult]
    summary_lines: list[str]
    reason: Optional[str] = None


@dataclass
class RunResult:
    backend: BackendResult
    frontend: FrontendResult
    overall_exit_code: int
    log_path: Path
    summary_path: Path
    json_summary_path: Optional[Path]
    timestamp: str


def _normalize_output(output: str | bytes | None) -> str:
    if output is None:
        return ""
    if isinstance(output, bytes):
        return output.decode("utf-8", errors="replace")
    return output


def run_cmd_capture(cmd: list[str], cwd: Path, timeout_s: int) -> CommandResult:
    start = time.monotonic()
    try:
        result = subprocess.run(
            cmd,
            cwd=cwd,
            capture_output=True,
            text=True,
            timeout=timeout_s,
        )
        duration = time.monotonic() - start
        return CommandResult(
            cmd=cmd,
            cwd=cwd,
            exit_code=result.returncode,
            duration_s=duration,
            stdout=result.stdout,
            stderr=result.stderr,
            timed_out=False,
        )
    except subprocess.TimeoutExpired as exc:
        duration = time.monotonic() - start
        stdout = _normalize_output(exc.stdout)
        stderr = _normalize_output(exc.stderr)
        return CommandResult(
            cmd=cmd,
            cwd=cwd,
            exit_code=124,
            duration_s=duration,
            stdout=stdout,
            stderr=stderr,
            timed_out=True,
        )


def _extract_tail_lines(text: str, max_lines: int = 60) -> list[str]:
    lines = text.splitlines()
    if len(lines) <= max_lines:
        return lines
    return lines[-max_lines:]


def _extract_key_lines(lines: list[str], max_lines: int = 3) -> list[str]:
    keywords = ["FAILED", "AssertionError", "Traceback", "short test summary info"]
    picked = [line for line in lines if any(key in line for key in keywords)]
    if not picked:
        picked = lines[-max_lines:]
    return picked[-max_lines:]


def _format_cmd(cmd: list[str]) -> str:
    return " ".join(cmd)


def run_backend_pytest(config: RunConfig) -> BackendResult:
    pytest_ini = config.project_dir / "pytest.ini"
    tests_dir = config.project_dir / "tests"

    if pytest_ini.exists():
        cmd = [sys.executable, "-m", "pytest", "-c", "./pytest.ini", "-q"]
    elif tests_dir.exists():
        cmd = [sys.executable, "-m", "pytest", "-q"]
    else:
        return BackendResult(
            status="SKIPPED",
            cmd=None,
            cwd=None,
            exit_code=None,
            duration_s=None,
            output="",
            summary_lines=[],
            reason="No pytest.ini or tests/ directory.",
        )

    result = run_cmd_capture(cmd, config.project_dir, config.timeout_s)
    combined = (result.stdout + "\n" + result.stderr).strip()
    tail_lines = _extract_tail_lines(combined)
    summary_lines = _extract_key_lines(tail_lines)

    status = "PASS" if result.exit_code == 0 else "FAIL"
    return BackendResult(
        status=status,
        cmd=_format_cmd(cmd),
        cwd=str(config.project_dir),
        exit_code=result.exit_code,
        duration_s=result.duration_s,
        output=combined,
        summary_lines=summary_lines,
    )


def _read_package_scripts(package_json: Path) -> dict[str, str]:
    data = json.loads(package_json.read_text(encoding="utf-8"))
    scripts = data.get("scripts") or {}
    if isinstance(scripts, dict):
        return {k: str(v) for k, v in scripts.items()}
    return {}


def run_frontend_pipeline(config: RunConfig) -> FrontendResult:
    frontend_dir = config.project_dir / "frontend"
    package_json = frontend_dir / "package.json"

    if not package_json.exists():
        return FrontendResult(
            status="ABSENT",
            node_detected=False,
            npm_detected=False,
            install_attempted=False,
            steps=[],
            summary_lines=[],
            reason="frontend/package.json not found.",
        )

    node_detected = shutil.which("node") is not None
    npm_detected = shutil.which("npm") is not None
    if not node_detected or not npm_detected:
        return FrontendResult(
            status="SKIPPED",
            node_detected=node_detected,
            npm_detected=npm_detected,
            install_attempted=False,
            steps=[],
            summary_lines=[],
            reason="node/npm not available.",
        )

    try:
        scripts = _read_package_scripts(package_json)
    except Exception as exc:
        return FrontendResult(
            status="FAIL",
            node_detected=node_detected,
            npm_detected=npm_detected,
            install_attempted=False,
            steps=[],
            summary_lines=[f"package.json parse error: {exc}"],
            reason="package.json parse error.",
        )

    wanted = [name for name in ("lint", "test", "build") if name in scripts]
    if not wanted:
        return FrontendResult(
            status="SKIPPED",
            node_detected=node_detected,
            npm_detected=npm_detected,
            install_attempted=False,
            steps=[],
            summary_lines=[],
            reason="no scripts (lint/test/build) found.",
        )

    steps: list[FrontendStepResult] = []
    summary_lines: list[str] = []
    install_attempted = False

    if not config.no_install:
        install_attempted = True
        install_cmd = ["npm", "ci"]
        install_result = run_cmd_capture(install_cmd, frontend_dir, config.timeout_s)
        steps.append(
            FrontendStepResult(
                name="install",
                cmd=install_cmd,
                exit_code=install_result.exit_code,
                duration_s=install_result.duration_s,
                stdout=install_result.stdout,
                stderr=install_result.stderr,
                timed_out=install_result.timed_out,
            )
        )
        if install_result.exit_code != 0:
            fallback_cmd = ["npm", "install"]
            fallback_result = run_cmd_capture(fallback_cmd, frontend_dir, config.timeout_s)
            steps.append(
                FrontendStepResult(
                    name="install-fallback",
                    cmd=fallback_cmd,
                    exit_code=fallback_result.exit_code,
                    duration_s=fallback_result.duration_s,
                    stdout=fallback_result.stdout,
                    stderr=fallback_result.stderr,
                    timed_out=fallback_result.timed_out,
                )
            )
            if fallback_result.exit_code != 0:
                combined = (fallback_result.stdout + "\n" + fallback_result.stderr).strip()
                summary_lines = _extract_key_lines(_extract_tail_lines(combined))
                return FrontendResult(
                    status="FAIL",
                    node_detected=node_detected,
                    npm_detected=npm_detected,
                    install_attempted=True,
                    steps=steps,
                    summary_lines=summary_lines,
                    reason="npm install failed.",
                )

    for script_name in wanted:
        cmd = ["npm", "run", script_name]
        step_result = run_cmd_capture(cmd, frontend_dir, config.timeout_s)
        steps.append(
            FrontendStepResult(
                name=script_name,
                cmd=cmd,
                exit_code=step_result.exit_code,
                duration_s=step_result.duration_s,
                stdout=step_result.stdout,
                stderr=step_result.stderr,
                timed_out=step_result.timed_out,
            )
        )
        if step_result.exit_code != 0:
            combined = (step_result.stdout + "\n" + step_result.stderr).strip()
            summary_lines = _extract_key_lines(_extract_tail_lines(combined))
            return FrontendResult(
                status="FAIL",
                node_detected=node_detected,
                npm_detected=npm_detected,
                install_attempted=install_attempted,
                steps=steps,
                summary_lines=summary_lines,
                reason=f"{script_name} failed.",
            )

    return FrontendResult(
        status="PASS",
        node_detected=node_detected,
        npm_detected=npm_detected,
        install_attempted=install_attempted,
        steps=steps,
        summary_lines=[],
    )


def _compute_exit_code(config: RunConfig, backend: BackendResult, frontend: FrontendResult) -> int:
    if config.frontend_only:
        return 2 if frontend.status == "FAIL" else 0

    if backend.status == "FAIL":
        return 1

    if frontend.status == "FAIL":
        return 2

    return 0


def _status_line(status: str, reason: Optional[str]) -> str:
    if reason:
        return f"{status} ({reason})"
    return status


def write_log_and_summary(config: RunConfig, backend: BackendResult, frontend: FrontendResult) -> RunResult:
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    config.log_dir.mkdir(parents=True, exist_ok=True)

    log_path = config.log_dir / f"run_{timestamp}.log"
    summary_path = config.log_dir / f"run_{timestamp}.summary.txt"
    json_path = config.log_dir / f"run_{timestamp}.summary.json" if config.json_summary else None

    log_lines: list[str] = []
    log_lines.append("== Run Log ==")
    log_lines.append(f"timestamp: {timestamp}")
    log_lines.append(f"project_dir: {config.project_dir}")
    log_lines.append("")

    log_lines.append("== Backend ==")
    if backend.status == "SKIPPED":
        log_lines.append(f"status: {backend.status}")
        if backend.reason:
            log_lines.append(f"reason: {backend.reason}")
    else:
        log_lines.append(f"status: {backend.status}")
        log_lines.append(f"cmd: {backend.cmd}")
        log_lines.append(f"cwd: {backend.cwd}")
        log_lines.append(f"exit_code: {backend.exit_code}")
        log_lines.append(f"duration_s: {backend.duration_s:.2f}")
        log_lines.append("STDOUT/STDERR:")
        log_lines.append(backend.output)
    log_lines.append("")

    log_lines.append("== Frontend ==")
    log_lines.append(f"status: {frontend.status}")
    log_lines.append(f"node_detected: {frontend.node_detected}")
    log_lines.append(f"npm_detected: {frontend.npm_detected}")
    log_lines.append(f"install_attempted: {frontend.install_attempted}")
    if frontend.reason:
        log_lines.append(f"reason: {frontend.reason}")
    for step in frontend.steps:
        log_lines.append(f"-- step: {step.name}")
        log_lines.append(f"cmd: {_format_cmd(step.cmd)}")
        log_lines.append(f"exit_code: {step.exit_code}")
        log_lines.append(f"duration_s: {step.duration_s:.2f}")
        log_lines.append("STDOUT:")
        log_lines.append(step.stdout)
        log_lines.append("STDERR:")
        log_lines.append(step.stderr)
    log_lines.append("")

    log_path.write_text("\n".join(log_lines).strip() + "\n", encoding="utf-8")

    overall_exit_code = _compute_exit_code(config, backend, frontend)

    summary_lines: list[str] = []
    summary_lines.append("1) Run meta:")
    summary_lines.append(f"- project_dir: {config.project_dir}")
    summary_lines.append(f"- timestamp: {timestamp}")
    summary_lines.append(f"- command: {config.command}")

    summary_lines.append("2) Backend:")
    summary_lines.append(f"- status: {_status_line(backend.status, backend.reason)}")
    summary_lines.append(f"- cmd: {backend.cmd or 'N/A'}")
    summary_lines.append(f"- cwd: {backend.cwd or 'N/A'}")
    summary_lines.append(f"- exit_code: {backend.exit_code if backend.exit_code is not None else 'N/A'}")
    summary_lines.append(f"- duration_s: {backend.duration_s if backend.duration_s is not None else 'N/A'}")

    summary_lines.append("3) Frontend:")
    summary_lines.append(f"- status: {_status_line(frontend.status, frontend.reason)}")
    summary_lines.append(f"- node_detected: {frontend.node_detected}")
    summary_lines.append(f"- npm_detected: {frontend.npm_detected}")
    summary_lines.append(f"- install_attempted: {frontend.install_attempted}")
    if frontend.steps:
        for step in frontend.steps:
            summary_lines.append(
                f"- step: {step.name} exit_code={step.exit_code} duration_s={step.duration_s:.2f}"
            )
    else:
        summary_lines.append("- steps: none")

    if backend.status == "FAIL" or frontend.status == "FAIL":
        summary_lines.append("4) Failure summary:")
        if backend.status == "FAIL":
            for line in backend.summary_lines:
                summary_lines.append(f"- Backend: {line}")
        if frontend.status == "FAIL":
            for line in frontend.summary_lines:
                summary_lines.append(f"- Frontend: {line}")

        summary_lines.append("5) Next actions:")
        actions: list[str] = []
        if backend.status == "FAIL":
            for line in backend.summary_lines:
                actions.append(f"pytest failed: {line}")
        if frontend.status == "FAIL":
            for line in frontend.summary_lines:
                actions.append(f"frontend failed: {line}")
        if not actions:
            actions.append("Check log output for failing command.")
        for line in actions[:5]:
            summary_lines.append(f"- {line}")

    summary_path.write_text("\n".join(summary_lines).strip() + "\n", encoding="utf-8")

    if json_path is not None:
        json_payload = {
            "meta": {
                "project_dir": str(config.project_dir),
                "timestamp": timestamp,
                "command": config.command,
                "log_path": str(log_path),
                "summary_path": str(summary_path),
            },
            "backend": {
                "status": backend.status,
                "cmd": backend.cmd,
                "cwd": backend.cwd,
                "exit_code": backend.exit_code,
                "duration_s": backend.duration_s,
                "summary_lines": backend.summary_lines,
            },
            "frontend": {
                "status": frontend.status,
                "node_detected": frontend.node_detected,
                "npm_detected": frontend.npm_detected,
                "install_attempted": frontend.install_attempted,
                "steps": [
                    {
                        "name": step.name,
                        "cmd": step.cmd,
                        "exit_code": step.exit_code,
                        "duration_s": step.duration_s,
                    }
                    for step in frontend.steps
                ],
                "reason": frontend.reason,
                "summary_lines": frontend.summary_lines,
            },
            "overall_exit_code": overall_exit_code,
        }
        json_path.write_text(json.dumps(json_payload, indent=2), encoding="utf-8")

    return RunResult(
        backend=backend,
        frontend=frontend,
        overall_exit_code=overall_exit_code,
        log_path=log_path,
        summary_path=summary_path,
        json_summary_path=json_path,
        timestamp=timestamp,
    )


def run_pipeline(config: RunConfig) -> RunResult:
    backend = BackendResult(
        status="SKIPPED",
        cmd=None,
        cwd=None,
        exit_code=None,
        duration_s=None,
        output="",
        summary_lines=[],
        reason="backend not requested.",
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

    run_backend = config.run_all or config.backend_only or not config.frontend_only
    run_frontend = config.run_all or config.frontend_only

    if run_backend:
        backend = run_backend_pytest(config)
    if run_frontend:
        frontend = run_frontend_pipeline(config)

    return write_log_and_summary(config, backend, frontend)


def print_run_result(result: RunResult) -> None:
    if result.overall_exit_code == 0:
        print(f"[OK] Run completed. Log: {result.log_path}")
    else:
        print(f"[ERROR] Run failed. Log: {result.log_path}", file=sys.stderr)
