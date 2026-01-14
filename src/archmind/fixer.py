from __future__ import annotations

import difflib
import json
import re
import time
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Optional

from archmind.patcher import apply_unified_diff
from archmind.runner import RunConfig, RunResult, run_pipeline

LOG_PY_TRACE_RE = re.compile(r'File "([^"]+)", line (\d+)')
LOG_PYTEST_RE = re.compile(r"^(.+?\.py):(\d+):", re.MULTILINE)

KEYWORDS = [
    "Traceback",
    "ModuleNotFoundError",
    "NameError",
    "AssertionError",
    "ImportError",
    "FAILED",
    "CORS",
    "404",
    "Query",
]

CORS_REGEX = (
    "https?://(localhost|127\\.0\\.0\\.1|192\\.168\\..*|10\\..*|"
    "172\\.(1[6-9]|2\\d|3[0-1])\\..*)"
)


@dataclass
class FixPlan:
    plan_json_path: Path
    plan_md_path: Path
    plan: dict[str, Any]


def run_and_collect(project_dir: Path, timeout_s: int, scope: str = "backend") -> RunResult:
    config = RunConfig(
        project_dir=project_dir,
        run_all=(scope == "all"),
        backend_only=(scope == "backend"),
        frontend_only=(scope == "frontend"),
        no_install=False,
        timeout_s=timeout_s,
        log_dir=project_dir / ".archmind" / "run_logs",
        json_summary=False,
        command=f"archmind run --path {project_dir}",
    )
    return run_pipeline(config)


def find_latest_run_log(project_dir: Path) -> Optional[Path]:
    log_dir = project_dir / ".archmind" / "run_logs"
    if not log_dir.exists():
        return None
    logs = sorted(log_dir.glob("run_*.log"), key=lambda p: p.stat().st_mtime, reverse=True)
    return logs[0] if logs else None


def read_tail(file_path: Path, n: int = 120) -> list[str]:
    if not file_path.exists():
        return []
    lines = file_path.read_text(encoding="utf-8", errors="replace").splitlines()
    return lines[-n:]


def extract_files_hint(log_tail: list[str]) -> list[str]:
    files: list[str] = []
    text = "\n".join(log_tail)
    for match in LOG_PY_TRACE_RE.findall(text):
        files.append(match[0])
    for match in LOG_PYTEST_RE.findall(text):
        files.append(match[0])
    return list(dict.fromkeys(files))


def _collect_key_errors(lines: list[str]) -> list[str]:
    return [line for line in lines if any(key in line for key in KEYWORDS)]


def _read_summary_lines(summary_path: Optional[Path]) -> list[str]:
    if summary_path is None or not summary_path.exists():
        return []
    return summary_path.read_text(encoding="utf-8", errors="replace").splitlines()


def _read_failure_summary_section(summary_path: Optional[Path]) -> list[str]:
    lines = _read_summary_lines(summary_path)
    if not lines:
        return []
    start = next((i for i, line in enumerate(lines) if line.startswith("4) Failure summary:")), -1)
    if start == -1:
        return [line for line in lines[-10:] if line.strip()]
    end = next((i for i in range(start + 1, len(lines)) if lines[i].startswith("5) ")), len(lines))
    section = [line.strip() for line in lines[start + 1 : end] if line.strip()]
    return section or [line for line in lines[-10:] if line.strip()]


def _extract_failure_details(text: str) -> dict[str, Optional[str | list[str]]]:
    lines = text.splitlines()
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
        match = re.search(r'File "([^"]+)"', text)
        if match:
            file_path = match.group(1)
        else:
            match = re.search(r"^(.+?\.py):\d+:", text, flags=re.MULTILINE)
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


def _build_fix_prompt(
    command: str,
    summary_lines: list[str],
    failure_details: dict[str, Optional[str | list[str]]],
    files_hint: list[str],
) -> str:
    test_name = failure_details.get("test_name") or "확인 필요"
    file_path = failure_details.get("file_path") or (files_hint[0] if files_hint else "확인 필요")
    stack_top = failure_details.get("stack_top") or []
    stack_bottom = failure_details.get("stack_bottom") or []

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


def _write_fix_prompt(
    log_dir: Path,
    timestamp: str,
    command: str,
    run_result: RunResult,
    log_tail: list[str],
) -> Path:
    summary_lines = _read_failure_summary_section(run_result.summary_path)
    log_text = "\n".join(log_tail)
    details = _extract_failure_details(log_text)
    files_hint = extract_files_hint(log_tail)
    prompt_text = _build_fix_prompt(command, summary_lines, details, files_hint)
    prompt_path = log_dir / f"fix_{timestamp}.prompt.md"
    prompt_path.write_text(prompt_text, encoding="utf-8")
    return prompt_path


def _write_fix_summary(
    log_dir: Path,
    timestamp: str,
    command: str,
    project_dir: Path,
    exit_code: int,
    run_result: RunResult,
    dry_run: bool,
    applied: bool,
    iteration: int,
) -> None:
    summary_path = log_dir / f"fix_{timestamp}.summary.txt"
    json_path = log_dir / f"fix_{timestamp}.summary.json"

    lines = [
        "1) Fix meta:",
        f"- project_dir: {project_dir}",
        f"- timestamp: {timestamp}",
        f"- command: {command}",
        f"- exit_code: {exit_code}",
        f"- iteration: {iteration}",
        f"- dry_run: {dry_run}",
        f"- applied: {applied}",
        "2) Run summary:",
        f"- run_exit_code: {run_result.overall_exit_code}",
        f"- run_log: {run_result.log_path}",
        f"- run_summary: {run_result.summary_path}",
    ]
    summary_path.write_text("\n".join(lines) + "\n", encoding="utf-8")

    payload = {
        "meta": {
            "project_dir": str(project_dir),
            "timestamp": timestamp,
            "command": command,
            "exit_code": exit_code,
            "iteration": iteration,
            "dry_run": dry_run,
            "applied": applied,
        },
        "run": {
            "exit_code": run_result.overall_exit_code,
            "log_path": str(run_result.log_path),
            "summary_path": str(run_result.summary_path),
        },
    }
    json_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")


def build_plan(
    diagnosis: dict[str, Any],
    scope: str,
    iteration: int,
    project_dir: Path,
) -> dict[str, Any]:
    key_errors = diagnosis.get("key_errors", [])
    files_hint = diagnosis.get("files_hint", [])

    actions: list[dict[str, Any]] = []
    changes: list[dict[str, Any]] = []

    if any("Query" in err and "NameError" in err for err in key_errors):
        actions.append(
            {
                "type": "edit",
                "path": None,
                "reason": "Query not defined",
                "applied": False,
                "rule": "fastapi_imports",
                "names": ["Query"],
                "files_hint": files_hint,
            }
        )

    if any("CORS" in err for err in key_errors):
        actions.append(
            {
                "type": "edit",
                "path": "app/main.py",
                "reason": "CORS middleware missing or too strict",
                "applied": False,
                "rule": "cors_middleware",
            }
        )

    if any("/defects" in err and "404" in err for err in key_errors):
        actions.append(
            {
                "type": "edit",
                "path": "app/api/router.py",
                "reason": "/defects 404 (router not included)",
                "applied": False,
                "rule": "defects_router",
            }
        )

    changes = list(actions)

    return {
        "iteration": iteration,
        "path": str(project_dir),
        "key_errors": key_errors,
        "files_hint": files_hint,
        "files": files_hint,
        "actions": actions,
        "changes": changes,
        "rationale": "Derived from failure summary and log tail.",
        "commands_to_verify": ["python -m pytest -q"],
        "diagnosis": diagnosis,
        "scope": scope,
        "meta": {
            "timestamp": datetime.now().strftime("%Y%m%d_%H%M%S"),
            "project_dir": str(project_dir),
        },
    }


def _plan_to_markdown(plan: dict[str, Any]) -> str:
    lines = [
        f"- path: {plan.get('path')}",
        f"- iteration: {plan.get('iteration')}",
        "- actions:",
    ]
    actions = plan.get("actions", [])
    if not actions:
        lines.append("  - (none)")
    else:
        for action in actions:
            lines.append(
                f"  - {action.get('path') or 'auto'}: {action.get('reason')}"
            )
    return "\n".join(lines) + "\n"


def _find_candidate_file(project_dir: Path, files_hint: list[str], suffixes: tuple[str, ...]) -> Optional[Path]:
    for hint in files_hint:
        path = Path(hint)
        if not path.is_absolute():
            path = (project_dir / path).resolve()
        if path.exists() and path.suffix in suffixes:
            try:
                path.resolve().relative_to(project_dir.resolve())
                return path
            except ValueError:
                continue
    return None


def _find_insertion_index(lines: list[str]) -> int:
    idx = 0
    if lines and lines[0].startswith("#!"):
        idx = 1
    if idx < len(lines) and lines[idx].lstrip().startswith(('"""', "'''")):
        quote = lines[idx].lstrip()[:3]
        idx += 1
        while idx < len(lines):
            if quote in lines[idx]:
                idx += 1
                break
            idx += 1
    while idx < len(lines) and lines[idx].startswith("from __future__ import"):
        idx += 1
    return idx


def _ensure_fastapi_imports(path: Path, names: list[str]) -> Optional[str]:
    content = path.read_text(encoding="utf-8")
    if not any(name in content for name in names):
        return None

    lines = content.splitlines()
    import_idx = None
    existing: list[str] = []
    for idx, line in enumerate(lines):
        if line.startswith("from fastapi import"):
            import_idx = idx
            existing = [part.strip() for part in line.split("import", 1)[1].split(",")]
            break

    missing = [name for name in names if name not in existing]
    if not missing:
        return None

    if import_idx is not None:
        merged = sorted(set(existing + missing))
        lines[import_idx] = "from fastapi import " + ", ".join(merged)
    else:
        insert_at = _find_insertion_index(lines)
        lines.insert(insert_at, "from fastapi import " + ", ".join(missing))

    return "\n".join(lines) + "\n"


def _ensure_cors_middleware(path: Path) -> Optional[str]:
    content = path.read_text(encoding="utf-8")
    if "CORSMiddleware" in content and "allow_origin_regex" in content:
        return None

    lines = content.splitlines()
    if "CORSMiddleware" not in content:
        insert_at = _find_insertion_index(lines)
        lines.insert(insert_at, "from fastapi.middleware.cors import CORSMiddleware")

    if "app.add_middleware" in content and "CORSMiddleware" in content:
        updated_lines: list[str] = []
        inserted = False
        for line in lines:
            updated_lines.append(line)
            if not inserted and "CORSMiddleware" in line and "allow_origin_regex" not in content:
                updated_lines.append(f"    allow_origin_regex=\"{CORS_REGEX}\",")
                inserted = True
        return "\n".join(updated_lines) + "\n"

    block = [
        "",
        "app.add_middleware(",
        "    CORSMiddleware,",
        f"    allow_origin_regex=\"{CORS_REGEX}\",",
        "    allow_credentials=False,",
        "    allow_methods=[\"*\"],",
        "    allow_headers=[\"*\"],",
        ")",
    ]
    lines.extend(block)
    return "\n".join(lines) + "\n"


def _ensure_defects_router(project_dir: Path) -> Optional[str]:
    router_path = project_dir / "app" / "api" / "router.py"
    if not router_path.exists():
        return None

    content = router_path.read_text(encoding="utf-8")
    if "include_router(defects_router" in content:
        return None

    lines = content.splitlines()
    new_lines: list[str] = []
    import_added = False
    for line in lines:
        new_lines.append(line)
        if line.startswith("from app.api.routers.health") and "defects" not in content:
            new_lines.append("from app.api.routers.defects import router as defects_router")
            import_added = True

    if not import_added and "defects_router" not in content:
        new_lines.insert(0, "from app.api.routers.defects import router as defects_router")

    include_added = False
    for idx, line in enumerate(list(new_lines)):
        if "include_router" in line and "health_router" in line:
            new_lines.insert(idx + 1, "api_router.include_router(defects_router)")
            include_added = True
            break
    if not include_added:
        new_lines.append("api_router.include_router(defects_router)")

    return "\n".join(new_lines) + "\n"


def _make_diff(project_dir: Path, target: Path, new_text: str) -> str:
    old_text = target.read_text(encoding="utf-8") if target.exists() else ""
    old_lines = old_text.splitlines(keepends=True)
    new_lines = new_text.splitlines(keepends=True)
    rel = target.resolve().relative_to(project_dir.resolve())
    diff = difflib.unified_diff(
        old_lines,
        new_lines,
        fromfile=f"a/{rel.as_posix()}",
        tofile=f"b/{rel.as_posix()}",
    )
    return "".join(diff)


def apply_plan(plan: dict[str, Any], project_dir: Path, apply_changes: bool) -> tuple[bool, list[str]]:
    changes = plan.get("changes") or plan.get("actions") or []
    diffs: list[str] = []

    for change in changes:
        rule = change.get("rule")
        names = change.get("names", [])
        files_hint = change.get("files_hint", [])
        target_path = change.get("path")
        new_text: Optional[str] = None

        if rule == "fastapi_imports":
            candidate = _find_candidate_file(project_dir, files_hint, (".py",))
            if candidate:
                new_text = _ensure_fastapi_imports(candidate, names)
                target_path = candidate
        elif rule == "cors_middleware":
            candidate = project_dir / "app" / "main.py"
            if not candidate.exists():
                candidate = project_dir / "main.py"
            if candidate.exists():
                new_text = _ensure_cors_middleware(candidate)
                target_path = candidate
        elif rule == "defects_router":
            new_text = _ensure_defects_router(project_dir)
            target_path = project_dir / "app" / "api" / "router.py"

        if new_text is None or target_path is None:
            continue

        diff = _make_diff(project_dir, Path(target_path), new_text)
        if not diff:
            continue

        diffs.append(diff)
        if apply_changes:
            apply_unified_diff(project_dir, diff)

    return bool(diffs), diffs


def apply_rules(plan: dict[str, Any], project_dir: Path, apply_changes: bool) -> tuple[bool, list[str]]:
    applied, diffs = apply_plan(plan, project_dir, apply_changes)
    actions = plan.get("actions") or []
    if actions:
        for action in actions:
            action["applied"] = applied if apply_changes else False
    return applied, diffs


def fix_loop(
    project_dir: Path,
    max_iterations: int,
    apply_changes: bool,
    dry_run: bool,
    timeout_s: int,
    scope: str,
    command: Optional[str],
) -> int:
    log_dir = project_dir / ".archmind" / "run_logs"
    log_dir.mkdir(parents=True, exist_ok=True)
    last_run_result: Optional[RunResult] = None
    last_timestamp: Optional[str] = None
    last_iteration = 0
    last_applied = False

    for iteration in range(1, max_iterations + 1):
        run_result = run_and_collect(project_dir, timeout_s=timeout_s, scope=scope)
        last_run_result = run_result
        last_iteration = iteration
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        last_timestamp = timestamp
        if run_result.overall_exit_code == 0:
            _write_fix_summary(
                log_dir,
                timestamp,
                command or f"archmind fix --path {project_dir}",
                project_dir,
                0,
                run_result,
                dry_run,
                False,
                iteration,
            )
            print(f"[OK] fixed in {iteration - 1} iterations")
            return 0

        log_tail = read_tail(run_result.log_path, n=120)
        summary_lines = _read_summary_lines(run_result.summary_path)
        key_errors = _collect_key_errors(summary_lines + log_tail)
        files_hint = extract_files_hint(log_tail)

        diagnosis = {
            "key_errors": key_errors,
            "files_hint": files_hint,
        }

        plan = build_plan(diagnosis, scope=scope, iteration=iteration, project_dir=project_dir)
        plan["key_errors"] = key_errors
        plan["files_hint"] = files_hint

        plan["scope"] = scope
        plan["files"] = files_hint
        plan["commands_to_verify"] = ["python -m pytest -q"]
        timestamp = plan["meta"]["timestamp"]
        last_timestamp = timestamp
        plan_json_path = log_dir / f"fix_{timestamp}.plan.json"
        plan_md_path = log_dir / f"fix_{timestamp}.plan.md"
        plan_json_path.write_text(json.dumps(plan, indent=2), encoding="utf-8")
        plan_md_path.write_text(_plan_to_markdown(plan), encoding="utf-8")

        if key_errors:
            print(f"[ITER {iteration}/{max_iterations}] detected: {key_errors[0]}")
        else:
            print(f"[ITER {iteration}/{max_iterations}] detected: no key errors")

        if dry_run:
            print(f"[ITER {iteration}/{max_iterations}] dry-run: plan written")
            _write_fix_prompt(
                log_dir,
                timestamp,
                command or f"archmind fix --path {project_dir}",
                run_result,
                log_tail,
            )
            _write_fix_summary(
                log_dir,
                timestamp,
                command or f"archmind fix --path {project_dir}",
                project_dir,
                2,
                run_result,
                dry_run,
                False,
                iteration,
            )
            return 2
        if not apply_changes:
            print(f"[ITER {iteration}/{max_iterations}] apply disabled: no changes applied")
            _write_fix_prompt(
                log_dir,
                timestamp,
                command or f"archmind fix --path {project_dir}",
                run_result,
                log_tail,
            )
            _write_fix_summary(
                log_dir,
                timestamp,
                command or f"archmind fix --path {project_dir}",
                project_dir,
                1,
                run_result,
                dry_run,
                False,
                iteration,
            )
            return 1

        applied, diffs = apply_rules(plan, project_dir, apply_changes=True)
        last_applied = applied
        if not applied:
            print(f"[ITER {iteration}/{max_iterations}] no changes applied")
            _write_fix_prompt(
                log_dir,
                timestamp,
                command or f"archmind fix --path {project_dir}",
                run_result,
                log_tail,
            )
            patch_path = log_dir / f"fix_{timestamp}.patch.diff"
            patch_path.write_text("", encoding="utf-8")
            _write_fix_summary(
                log_dir,
                timestamp,
                command or f"archmind fix --path {project_dir}",
                project_dir,
                1,
                run_result,
                dry_run,
                False,
                iteration,
            )
            return 1

        if plan.get("actions"):
            first = plan["actions"][0]
            target_path = first.get("path") or "auto"
            print(
                f"[ITER {iteration}/{max_iterations}] patched {target_path}"
            )

        patch_path = log_dir / f"fix_{timestamp}.patch.diff"
        patch_text = "\n".join(diffs)
        patch_path.write_text(patch_text, encoding="utf-8")

        rerun = run_and_collect(project_dir, timeout_s=timeout_s, scope=scope)
        if rerun.overall_exit_code == 0:
            _write_fix_summary(
                log_dir,
                timestamp,
                command or f"archmind fix --path {project_dir}",
                project_dir,
                0,
                rerun,
                dry_run,
                True,
                iteration,
            )
            print(f"[OK] fixed in {iteration} iterations")
            return 0

        time.sleep(0.1)

    print(f"[FAIL] could not fix after {max_iterations} iterations")
    if last_run_result is not None and last_timestamp is not None:
        log_tail = read_tail(last_run_result.log_path, n=120)
        _write_fix_prompt(
            log_dir,
            last_timestamp,
            command or f"archmind fix --path {project_dir}",
            last_run_result,
            log_tail,
        )
        _write_fix_summary(
            log_dir,
            last_timestamp,
            command or f"archmind fix --path {project_dir}",
            project_dir,
            1,
            last_run_result,
            dry_run,
            last_applied,
            last_iteration,
        )
    return 1


def run_fix_loop(
    project_dir: Path,
    max_iterations: int,
    model: str,
    dry_run: bool,
    timeout_s: int,
    scope: str,
    apply_changes: bool,
    command: Optional[str] = None,
) -> int:
    del model
    return fix_loop(
        project_dir,
        max_iterations=max_iterations,
        apply_changes=apply_changes,
        dry_run=dry_run,
        timeout_s=timeout_s,
        scope=scope,
        command=command,
    )


def build_diagnosis(summary: dict[str, Any], log_lines: list[str]) -> dict[str, Any]:
    backend_summary = summary.get("backend", {}).get("summary_lines") or []
    frontend_summary = summary.get("frontend", {}).get("summary_lines") or []
    key_errors = _collect_key_errors(backend_summary + frontend_summary + log_lines)
    files_hint = extract_files_hint(log_lines)
    return {
        "backend": {"status": summary.get("backend", {}).get("status"), "summary_lines": backend_summary},
        "frontend": {"status": summary.get("frontend", {}).get("status"), "summary_lines": frontend_summary},
        "key_errors": key_errors,
        "files_hint": files_hint,
    }
