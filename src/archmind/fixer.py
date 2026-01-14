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
        "actions": actions,
        "changes": changes,
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
) -> int:
    plan_dir = project_dir / ".archmind" / "fix_plans"
    plan_dir.mkdir(parents=True, exist_ok=True)

    for iteration in range(1, max_iterations + 1):
        run_result = run_and_collect(project_dir, timeout_s=timeout_s, scope="backend")
        if run_result.overall_exit_code == 0:
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

        plan = build_plan(diagnosis, scope="backend", iteration=iteration, project_dir=project_dir)
        plan["key_errors"] = key_errors
        plan["files_hint"] = files_hint

        timestamp = plan["meta"]["timestamp"]
        plan_json_path = plan_dir / f"fix_{timestamp}.plan.json"
        plan_md_path = plan_dir / f"fix_{timestamp}.plan.md"
        plan_json_path.write_text(json.dumps(plan, indent=2), encoding="utf-8")
        plan_md_path.write_text(_plan_to_markdown(plan), encoding="utf-8")

        if key_errors:
            print(f"[ITER {iteration}/{max_iterations}] detected: {key_errors[0]}")
        else:
            print(f"[ITER {iteration}/{max_iterations}] detected: no key errors")

        if dry_run or not apply_changes:
            print(f"[ITER {iteration}/{max_iterations}] dry-run: plan written")
            return 1

        applied, _ = apply_rules(plan, project_dir, apply_changes=True)
        if not applied:
            print(f"[ITER {iteration}/{max_iterations}] no changes applied")
            return 1

        if plan.get("actions"):
            first = plan["actions"][0]
            target_path = first.get("path") or "auto"
            print(
                f"[ITER {iteration}/{max_iterations}] patched {target_path}"
            )

        rerun = run_and_collect(project_dir, timeout_s=timeout_s, scope="backend")
        if rerun.overall_exit_code == 0:
            print(f"[OK] fixed in {iteration} iterations")
            return 0

        time.sleep(0.1)

    print(f"[FAIL] could not fix after {max_iterations} iterations")
    return 1


def run_fix_loop(
    project_dir: Path,
    max_iterations: int,
    model: str,
    dry_run: bool,
    timeout_s: int,
    scope: str,
    apply_changes: bool,
) -> int:
    del model, scope
    return fix_loop(
        project_dir,
        max_iterations=max_iterations,
        apply_changes=apply_changes,
        dry_run=dry_run,
        timeout_s=timeout_s,
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
