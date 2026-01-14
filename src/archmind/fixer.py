from __future__ import annotations

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
NAME_ERROR_RE = re.compile(r"NameError: name '([^']+)' is not defined")
IMPORT_ERROR_RE = re.compile(r"(ImportError|ModuleNotFoundError):\s+(.*)")

BACKEND_ERROR_KEYS = [
    "Traceback",
    "ModuleNotFoundError",
    "NameError",
    "AssertionError",
    "ImportError",
    "FAILED",
]

FRONTEND_ERROR_KEYS = [
    "npm ERR!",
    "TypeError",
    "build failed",
    "CORS",
    "ERR_",
    "Failed to fetch",
]

CORS_REGEX = (
    "https?://(localhost|127\\.0\\.0\\.1|192\\.168\\..*|10\\..*|"
    "172\\.(1[6-9]|2\\d|3[0-1])\\..*)"
)


@dataclass
class FixPlan:
    data: dict[str, Any]
    plan_json_path: Path
    plan_md_path: Path


@dataclass
class FixIterationResult:
    status: str
    run_result: RunResult
    plan: Optional[FixPlan]
    applied: bool
    message: str


def load_latest_summary(project_dir: Path) -> Optional[dict[str, Any]]:
    log_dir = project_dir / ".archmind" / "run_logs"
    if not log_dir.exists():
        return None
    candidates = sorted(log_dir.glob("run_*.summary.json"), key=lambda p: p.stat().st_mtime, reverse=True)
    if not candidates:
        return None
    return json.loads(candidates[0].read_text(encoding="utf-8"))


def read_log_tail(log_path: Path, n_lines: int = 120) -> list[str]:
    if not log_path.exists():
        return []
    lines = log_path.read_text(encoding="utf-8", errors="replace").splitlines()
    return lines[-n_lines:]


def _extract_files_from_log(lines: list[str]) -> list[str]:
    files: list[str] = []
    text = "\n".join(lines)
    for match in LOG_PY_TRACE_RE.findall(text):
        files.append(match[0])
    for match in LOG_PYTEST_RE.findall(text):
        files.append(match[0])
    return list(dict.fromkeys(files))


def _collect_key_errors(summary_lines: list[str], log_lines: list[str], keys: list[str]) -> list[str]:
    key_errors: list[str] = []
    for line in summary_lines:
        if any(key in line for key in keys):
            key_errors.append(line)
    for line in log_lines:
        if any(key in line for key in keys):
            key_errors.append(line)
    return list(dict.fromkeys(key_errors))[:10]


def build_diagnosis(summary: dict[str, Any], log_lines: list[str]) -> dict[str, Any]:
    backend_summary = summary.get("backend", {}).get("summary_lines") or []
    frontend_summary = summary.get("frontend", {}).get("summary_lines") or []

    backend_errors = _collect_key_errors(backend_summary, log_lines, BACKEND_ERROR_KEYS)
    frontend_errors = _collect_key_errors(frontend_summary, log_lines, FRONTEND_ERROR_KEYS)

    files_hint = _extract_files_from_log(log_lines)

    return {
        "backend": {
            "status": summary.get("backend", {}).get("status", "UNKNOWN"),
            "key_errors": backend_errors,
            "files_hint": files_hint,
        },
        "frontend": {
            "status": summary.get("frontend", {}).get("status", "UNKNOWN"),
            "key_errors": frontend_errors,
            "files_hint": files_hint,
        },
    }


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
    lines = content.splitlines()

    existing = []
    for line in lines:
        if line.startswith("from fastapi import"):
            existing = [part.strip() for part in line.split("import", 1)[1].split(",")]
            break

    missing = [name for name in names if name not in existing]
    if not missing:
        return None

    if existing:
        new_line = "from fastapi import " + ", ".join(sorted(set(existing + missing)))
        new_lines = [new_line if line.startswith("from fastapi import") else line for line in lines]
    else:
        insert_at = _find_insertion_index(lines)
        new_lines = list(lines)
        new_lines.insert(insert_at, "from fastapi import " + ", ".join(missing))

    return "\n".join(new_lines) + "\n"


def _ensure_cors_middleware(path: Path) -> Optional[str]:
    content = path.read_text(encoding="utf-8")
    if "CORSMiddleware" in content:
        if "allow_origin_regex" in content:
            return None
        return None

    if "FastAPI" not in content:
        return None

    lines = content.splitlines()
    insert_at = _find_insertion_index(lines)
    lines.insert(insert_at, "from fastapi.middleware.cors import CORSMiddleware")

    block = [
        "",
        f"app.add_middleware(",
        "    CORSMiddleware,",
        f"    allow_origin_regex=\"{CORS_REGEX}\",",
        "    allow_credentials=False,",
        "    allow_methods=[\"*\"],",
        "    allow_headers=[\"*\"],",
        ")",
    ]

    updated_lines: list[str] = []
    inserted = False
    for line in lines:
        updated_lines.append(line)
        if not inserted and "FastAPI" in line and "app" in line and "=" in line:
            updated_lines.extend(block)
            inserted = True

    if not inserted:
        updated_lines.extend(block)

    return "\n".join(updated_lines) + "\n"


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


def _ensure_defects_prefix(project_dir: Path) -> Optional[str]:
    path = project_dir / "app" / "api" / "routers" / "defects.py"
    if not path.exists():
        return None

    content = path.read_text(encoding="utf-8")
    if "APIRouter" not in content:
        return None
    if "prefix=" in content:
        return None

    new_content = re.sub(
        r"APIRouter\(",
        "APIRouter(prefix=\"/defects\", ",
        content,
        count=1,
    )
    return new_content


def _ensure_frontend_backend_url(project_dir: Path) -> Optional[str]:
    path = project_dir / "frontend" / "app" / "ui" / "DefectsPage.tsx"
    if not path.exists():
        return None

    content = path.read_text(encoding="utf-8")
    if "function getBackendUrl" not in content:
        return None

    replacement = (
        "function getBackendUrl() {\n"
        "  if (typeof window === \"undefined\") return ENV_BACKEND ?? \"http://127.0.0.1:8000\";\n"
        "  if (ENV_BACKEND && ENV_BACKEND.trim()) return ENV_BACKEND;\n"
        "  const host = window.location.hostname;\n"
        "  const protocol = window.location.protocol;\n"
        "  return `${protocol}//${host}:8000`;\n"
        "}\n"
    )

    new_content = re.sub(
        r"function getBackendUrl\(\)[\s\S]*?\n}\n",
        replacement,
        content,
        count=1,
    )

    return new_content


def _ensure_requirements(project_dir: Path) -> Optional[str]:
    path = project_dir / "requirements.txt"
    if not path.exists():
        return None

    content = path.read_text(encoding="utf-8")
    lines = content.splitlines()
    required = []
    if not any(line.startswith("fastapi") for line in lines):
        required.append("fastapi")
    if not any(line.startswith("uvicorn") for line in lines):
        required.append("uvicorn[standard]")

    if not required:
        return None

    return content.rstrip() + "\n" + "\n".join(required) + "\n"


def build_plan(diagnosis: dict[str, Any], scope: str, iteration: int, project_dir: Path) -> dict[str, Any]:
    changes: list[dict[str, Any]] = []
    backend = diagnosis.get("backend", {})
    frontend = diagnosis.get("frontend", {})

    backend_errors = backend.get("key_errors", [])
    frontend_errors = frontend.get("key_errors", [])
    files_hint = backend.get("files_hint", []) or frontend.get("files_hint", [])

    if scope in ("backend", "all"):
        if any("Query" in err for err in backend_errors):
            changes.append(
                {
                    "path": None,
                    "action": "edit",
                    "diff_hint": "Add missing fastapi Query import",
                    "reason": "Query referenced but not imported.",
                    "rule": "fastapi_imports",
                    "names": ["Query"],
                    "files_hint": files_hint,
                }
            )
        if any("Depends" in err for err in backend_errors):
            changes.append(
                {
                    "path": None,
                    "action": "edit",
                    "diff_hint": "Add missing fastapi Depends import",
                    "reason": "Depends referenced but not imported.",
                    "rule": "fastapi_imports",
                    "names": ["Depends"],
                    "files_hint": files_hint,
                }
            )
        if any("CORS" in err for err in backend_errors):
            changes.append(
                {
                    "path": None,
                    "action": "edit",
                    "diff_hint": "Ensure CORSMiddleware configured with allow_origin_regex",
                    "reason": "CORS errors detected in logs.",
                    "rule": "cors_middleware",
                }
            )
        if any("/defects" in err and "404" in err for err in backend_errors):
            changes.append(
                {
                    "path": "app/api/router.py",
                    "action": "edit",
                    "diff_hint": "Ensure defects_router is included",
                    "reason": "defects endpoint returned 404.",
                    "rule": "defects_router",
                }
            )
            changes.append(
                {
                    "path": "app/api/routers/defects.py",
                    "action": "edit",
                    "diff_hint": "Ensure defects router has /defects prefix",
                    "reason": "defects endpoint returned 404.",
                    "rule": "defects_prefix",
                }
            )
        if any("uvicorn" in err.lower() for err in backend_errors):
            changes.append(
                {
                    "path": "requirements.txt",
                    "action": "edit",
                    "diff_hint": "Ensure fastapi/uvicorn requirements",
                    "reason": "uvicorn missing in environment.",
                    "rule": "requirements",
                }
            )

    if scope in ("frontend", "all"):
        if any("BACKEND_URL" in err or "fetch" in err.lower() for err in frontend_errors):
            changes.append(
                {
                    "path": "frontend/app/ui/DefectsPage.tsx",
                    "action": "edit",
                    "diff_hint": "Fix backend URL inference",
                    "reason": "Frontend cannot resolve backend URL.",
                    "rule": "frontend_backend_url",
                }
            )

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")

    return {
        "meta": {
            "timestamp": timestamp,
            "project_dir": str(project_dir),
        },
        "iteration": iteration,
        "scope": scope,
        "diagnosis": diagnosis,
        "changes": changes,
        "commands_after": [],
    }


def _plan_to_markdown(plan: dict[str, Any], project_dir: Path) -> str:
    lines: list[str] = []
    lines.append(f"- project_dir: {project_dir}")
    lines.append(f"- iteration: {plan.get('iteration')}")
    lines.append(f"- scope: {plan.get('scope')}")
    lines.append("- changes:")
    changes = plan.get("changes", [])
    if not changes:
        lines.append("  - (none)")
    else:
        for change in changes:
            lines.append(f"  - {change.get('path') or 'auto'}: {change.get('reason')}")
    return "\n".join(lines) + "\n"


def _make_diff(project_dir: Path, target: Path, new_text: str) -> str:
    old_text = target.read_text(encoding="utf-8") if target.exists() else ""
    old_lines = old_text.splitlines(keepends=True)
    new_lines = new_text.splitlines(keepends=True)
    rel = target.resolve().relative_to(project_dir.resolve())
    diff = list(
        __import__("difflib").unified_diff(
            old_lines,
            new_lines,
            fromfile=f"a/{rel.as_posix()}",
            tofile=f"b/{rel.as_posix()}",
        )
    )
    return "".join(diff)


def apply_plan(plan: dict[str, Any], project_dir: Path, apply_changes: bool) -> tuple[bool, list[str]]:
    changes = plan.get("changes", [])
    if not changes:
        return False, []

    diffs: list[str] = []
    for change in changes:
        rule = change.get("rule")
        target_path = change.get("path")
        new_text: Optional[str] = None

        if rule == "fastapi_imports":
            names = change.get("names", [])
            hint_files = change.get("files_hint", [])
            candidate = _find_candidate_file(project_dir, hint_files, (".py",))
            if candidate:
                new_text = _ensure_fastapi_imports(candidate, names)
                target_path = candidate
        elif rule == "cors_middleware":
            candidates = [
                project_dir / "app" / "main.py",
                project_dir / "main.py",
            ]
            for candidate in candidates:
                if candidate.exists():
                    new_text = _ensure_cors_middleware(candidate)
                    target_path = candidate
                    break
        elif rule == "defects_router":
            new_text = _ensure_defects_router(project_dir)
            target_path = project_dir / "app" / "api" / "router.py"
        elif rule == "defects_prefix":
            new_text = _ensure_defects_prefix(project_dir)
            target_path = project_dir / "app" / "api" / "routers" / "defects.py"
        elif rule == "frontend_backend_url":
            new_text = _ensure_frontend_backend_url(project_dir)
            target_path = project_dir / "frontend" / "app" / "ui" / "DefectsPage.tsx"
        elif rule == "requirements":
            new_text = _ensure_requirements(project_dir)
            target_path = project_dir / "requirements.txt"

        if new_text is None or target_path is None:
            continue

        diff = _make_diff(project_dir, Path(target_path), new_text)
        if not diff:
            continue

        diffs.append(diff)
        if apply_changes:
            apply_unified_diff(project_dir, diff)

    return bool(diffs), diffs


def _scope_passed(scope: str, result: RunResult) -> bool:
    if scope == "backend":
        return result.backend.status == "PASS"
    if scope == "frontend":
        return result.frontend.status in ("PASS", "SKIPPED", "ABSENT")
    return result.backend.status == "PASS" and result.frontend.status in ("PASS", "SKIPPED", "ABSENT")


def run_iteration(
    project_dir: Path,
    scope: str,
    timeout_s: int,
    iteration: int,
    max_iterations: int,
    apply_changes: bool,
    dry_run: bool,
) -> FixIterationResult:
    run_args = ["archmind", "run", "--path", str(project_dir), "--json-summary"]
    if scope == "backend":
        run_args.append("--backend-only")
    elif scope == "frontend":
        run_args.append("--frontend-only")
    else:
        run_args.append("--all")

    run_config = RunConfig(
        project_dir=project_dir,
        run_all=(scope == "all"),
        backend_only=(scope == "backend"),
        frontend_only=(scope == "frontend"),
        no_install=False,
        timeout_s=timeout_s,
        log_dir=project_dir / ".archmind" / "run_logs",
        json_summary=True,
        command=" ".join(run_args),
    )
    run_result = run_pipeline(run_config)

    if _scope_passed(scope, run_result):
        return FixIterationResult(
            status="PASS",
            run_result=run_result,
            plan=None,
            applied=False,
            message="Already passing.",
        )

    summary_path = run_result.json_summary_path
    if summary_path is None or not summary_path.exists():
        return FixIterationResult(
            status="FAIL",
            run_result=run_result,
            plan=None,
            applied=False,
            message="summary.json not found.",
        )

    summary_data = json.loads(summary_path.read_text(encoding="utf-8"))
    log_lines = read_log_tail(run_result.log_path, n_lines=120)
    diagnosis = build_diagnosis(summary_data, log_lines)

    plan = build_plan(diagnosis, scope, iteration, project_dir)
    plan["commands_after"] = [
        {
            "cmd": run_args,
            "cwd": str(project_dir),
            "timeout_s": timeout_s,
        }
    ]
    plan_dir = project_dir / ".archmind" / "fix_plans"
    plan_dir.mkdir(parents=True, exist_ok=True)
    timestamp = plan["meta"]["timestamp"]
    plan_json_path = plan_dir / f"fix_{timestamp}.plan.json"
    plan_md_path = plan_dir / f"fix_{timestamp}.plan.md"
    plan_json_path.write_text(json.dumps(plan, indent=2), encoding="utf-8")
    plan_md_path.write_text(_plan_to_markdown(plan, project_dir), encoding="utf-8")

    fix_plan = FixPlan(plan, plan_json_path, plan_md_path)

    if dry_run or not apply_changes:
        return FixIterationResult(
            status="DRY_RUN",
            run_result=run_result,
            plan=fix_plan,
            applied=False,
            message="Dry-run: plan generated without applying changes.",
        )

    applied, diffs = apply_plan(plan, project_dir, apply_changes=True)
    if not applied:
        return FixIterationResult(
            status="FAIL",
            run_result=run_result,
            plan=fix_plan,
            applied=False,
            message="No applicable changes found.",
        )

    return FixIterationResult(
        status="APPLIED",
        run_result=run_result,
        plan=fix_plan,
        applied=True,
        message=f"Applied {len(diffs)} changes.",
    )


def run_fix_loop(
    project_dir: Path,
    max_iterations: int,
    model: str,
    dry_run: bool,
    timeout_s: int,
    scope: str,
    apply_changes: bool,
) -> int:
    del model  # reserved for future LLM integrations

    for iteration in range(1, max_iterations + 1):
        iter_result = run_iteration(
            project_dir=project_dir,
            scope=scope,
            timeout_s=timeout_s,
            iteration=iteration,
            max_iterations=max_iterations,
            apply_changes=apply_changes,
            dry_run=dry_run,
        )

        diagnosis = None
        if iter_result.plan:
            diagnosis = iter_result.plan.data.get("diagnosis", {})

        key_errors = []
        if diagnosis:
            key_errors = (diagnosis.get("backend", {}).get("key_errors", []) +
                          diagnosis.get("frontend", {}).get("key_errors", []))

        print(f"[ITER {iteration}/{max_iterations}] run result: {iter_result.run_result.overall_exit_code}")
        if key_errors:
            for err in key_errors[:3]:
                print(f"[ITER {iteration}/{max_iterations}] key_error: {err}")
        if iter_result.plan:
            changes = iter_result.plan.data.get("changes", [])
            if changes:
                change_paths = [str(change.get("path") or "auto") for change in changes]
                print(f"[ITER {iteration}/{max_iterations}] changes: {', '.join(change_paths)}")
            else:
                print(f"[ITER {iteration}/{max_iterations}] changes: none")

        if iter_result.status == "PASS":
            print(f"[OK] fixed in {iteration} iterations")
            if iter_result.plan:
                print(f"plan: {iter_result.plan.plan_json_path}")
            return 0

        if iter_result.status == "DRY_RUN":
            print("[DRY-RUN] plan generated")
            if iter_result.plan:
                print(f"plan: {iter_result.plan.plan_json_path}")
            return 1

        if iter_result.status == "FAIL":
            print(f"[FAIL] {iter_result.message}")
            if iter_result.plan:
                print(f"plan: {iter_result.plan.plan_json_path}")
            return 1

        rerun_args = ["archmind", "run", "--path", str(project_dir), "--json-summary"]
        if scope == "backend":
            rerun_args.append("--backend-only")
        elif scope == "frontend":
            rerun_args.append("--frontend-only")
        else:
            rerun_args.append("--all")

        rerun_config = RunConfig(
            project_dir=project_dir,
            run_all=(scope == "all"),
            backend_only=(scope == "backend"),
            frontend_only=(scope == "frontend"),
            no_install=False,
            timeout_s=timeout_s,
            log_dir=project_dir / ".archmind" / "run_logs",
            json_summary=True,
            command=" ".join(rerun_args),
        )
        rerun_result = run_pipeline(rerun_config)
        if _scope_passed(scope, rerun_result):
            print(f"[OK] fixed in {iteration} iterations")
            return 0

    print(f"[FAIL] could not fix after {max_iterations} iterations")
    return 1
