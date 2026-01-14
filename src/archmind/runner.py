from __future__ import annotations

import json
import re
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


def _select_python_executable(project_dir: Path) -> str:
    venv_python = project_dir / ".venv" / "bin" / "python"
    if venv_python.is_file():
        return str(venv_python)
    return sys.executable


def _extract_failure_summary_lines(summary_path: Path, json_path: Optional[Path]) -> list[str]:
    if summary_path.exists():
        lines = summary_path.read_text(encoding="utf-8", errors="replace").splitlines()
        start = next((i for i, line in enumerate(lines) if line.startswith("4) Failure summary:")), -1)
        if start != -1:
            end = next(
                (i for i in range(start + 1, len(lines)) if lines[i].startswith("5) ")),
                len(lines),
            )
            section = [line.strip() for line in lines[start + 1 : end] if line.strip()]
            if section:
                return section
        return [line.strip() for line in lines[-10:] if line.strip()]

    if json_path is not None and json_path.exists():
        try:
            payload = json.loads(json_path.read_text(encoding="utf-8"))
        except Exception:
            return []
        backend_lines = payload.get("backend", {}).get("summary_lines") or []
        frontend_lines = payload.get("frontend", {}).get("summary_lines") or []
        return [str(line) for line in backend_lines + frontend_lines][:10]
    return []


def _extract_failure_details(output: str) -> dict[str, Optional[str | list[str]]]:
    lines = output.splitlines()
    test_name: Optional[str] = None
    file_path: Optional[str] = None

    for line in lines:
        if line.startswith("FAILED ") or line.startswith("ERROR "):
            candidate = line.split(" ", 1)[1]
            test_id = candidate.split(" - ", 1)[0].strip()
            test_name = test_id
            if "::" in test_id:
                file_path = test_id.split("::", 1)[0]
            else:
                file_path = test_id
            break

    if file_path is None:
        match = re.search(r'File "([^"]+)"', output)
        if match:
            file_path = match.group(1)

    trace_idx = next((i for i, line in enumerate(lines) if "Traceback" in line), -1)
    stack_top = lines[trace_idx : trace_idx + 6] if trace_idx != -1 else []
    stack_bottom = lines[-6:] if lines else []

    return {
        "test_name": test_name,
        "file_path": file_path,
        "stack_top": stack_top,
        "stack_bottom": stack_bottom,
    }


def _build_failure_prompt(
    command: str,
    summary_lines: list[str],
    details: dict[str, Optional[str | list[str]]],
    files_hint: list[str],
) -> str:
    test_name = details.get("test_name") or "확인 필요"
    file_path = details.get("file_path") or (files_hint[0] if files_hint else "확인 필요")
    stack_top = details.get("stack_top") or []
    stack_bottom = details.get("stack_bottom") or []

    summary_block = "\n".join(f"- {line}" for line in summary_lines) if summary_lines else "- (요약 없음)"
    files_block = file_path if isinstance(file_path, str) else "확인 필요"

    stack_top_block = "\n".join(stack_top) if stack_top else "(스택트레이스 상단 없음)"
    stack_bottom_block = "\n".join(stack_bottom) if stack_bottom else "(스택트레이스 하단 없음)"

    return (
        "# 재현 커맨드\n"
        f"{command}\n\n"
        "# 실패 요약\n"
        f"{summary_block}\n\n"
        "# 실패 지점\n"
        f"- 실패한 테스트: {test_name}\n"
        f"- 파일 경로: {files_block}\n"
        "- 스택트레이스(상단):\n"
        f"{stack_top_block}\n"
        "- 스택트레이스(하단):\n"
        f"{stack_bottom_block}\n\n"
        "# 수정 지시문\n"
        "- 목표: python -m pytest -q 통과\n"
        f"- 수정 대상: {files_block}\n"
        "- 변경 범위를 최소화하라\n\n"
        "# 완료 조건 체크리스트\n"
        "- [ ] python -m pytest -q 통과\n"
        "- [ ] 기존 기능 영향 없음\n"
    )


def write_failure_prompt(
    config: RunConfig,
    result: RunResult,
    command_override: Optional[str] = None,
) -> Optional[Path]:
    if result.overall_exit_code == 0:
        return None

    command = command_override or config.command
    summary_lines = _extract_failure_summary_lines(result.summary_path, result.json_summary_path)

    output = ""
    files_hint: list[str] = []
    if result.backend.status == "FAIL":
        output = result.backend.output
    elif result.frontend.status == "FAIL":
        output = "\n".join(
            f"{step.stdout}\n{step.stderr}" for step in result.frontend.steps if step.exit_code != 0
        )

    files_hint = []
    for match in re.findall(r'File "([^"]+)"', output):
        files_hint.append(match)
    for match in re.findall(r"^(.+?\.py):\d+:", output, flags=re.MULTILINE):
        files_hint.append(match)
    files_hint = list(dict.fromkeys(files_hint))

    details = _extract_failure_details(output)
    prompt_text = _build_failure_prompt(command, summary_lines, details, files_hint)

    prompt_path = config.log_dir / f"{result.timestamp}.prompt.md"
    prompt_path.write_text(prompt_text, encoding="utf-8")
    return prompt_path


def run_backend_pytest(config: RunConfig) -> BackendResult:
    pytest_ini = config.project_dir / "pytest.ini"
    tests_dir = config.project_dir / "tests"
    python_exec = _select_python_executable(config.project_dir)

    if pytest_ini.exists():
        cmd = [python_exec, "-m", "pytest", "-c", "./pytest.ini", "-q"]
    elif tests_dir.exists():
        cmd = [python_exec, "-m", "pytest", "-q"]
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

    result = RunResult(
        backend=backend,
        frontend=frontend,
        overall_exit_code=overall_exit_code,
        log_path=log_path,
        summary_path=summary_path,
        json_summary_path=json_path,
        timestamp=timestamp,
    )
    if overall_exit_code != 0:
        try:
            write_failure_prompt(config, result)
        except Exception:
            pass
    return result


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

    if config.backend_only:
        run_backend = True
        run_frontend = False
    elif config.frontend_only:
        run_backend = False
        run_frontend = True
    elif config.run_all:
        run_backend = True
        run_frontend = True
    else:
        # default to backend-only when no explicit flags are provided
        run_backend = True
        run_frontend = False

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
