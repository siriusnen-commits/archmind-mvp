from __future__ import annotations

import json
import re
from datetime import datetime
from pathlib import Path
from typing import Any, Optional

from archmind.failure import classify_failure, extract_failure_excerpt

LAST_STATUSES = (
    "SUCCESS",
    "FAIL",
    "SKIP",
    "DONE",
    "NOT_DONE",
    "BLOCKED",
    "STUCK",
    "UNKNOWN",
)


def derive_task_label_from_failure_signature(signature: str) -> str:
    raw = (signature or "").strip().lower()
    if not raw:
        return ""
    head = raw.split(":", 1)[0]
    parts = [item.strip() for item in head.split("+") if item.strip()]
    key = "+".join(sorted(set(parts)))
    if key == "backend-pytest":
        return "backend pytest failure 분석"
    if key == "frontend-lint":
        return "frontend lint failure 수정"
    if key == "frontend-build":
        return "frontend build failure 수정"
    if key == "backend-pytest+frontend-lint":
        return "backend pytest / frontend lint failure 분석"
    return "반복 실패 원인 분석"


def _state_path(project_dir: Path) -> Path:
    return project_dir.expanduser().resolve() / ".archmind" / "state.json"


def state_path(project_dir: Path) -> Path:
    return _state_path(project_dir)


def _now() -> str:
    return datetime.now().strftime("%Y%m%d_%H%M%S")


def _safe_status(value: str) -> str:
    status = (value or "").upper()
    return status if status in LAST_STATUSES else "UNKNOWN"


def _sanitize_line(text: str, project_dir: Path) -> str:
    value = (text or "").strip()
    if not value:
        return ""
    proj = str(project_dir.expanduser().resolve())
    value = value.replace(proj, "<project>")
    return value[:220]


def _load_json(path: Path) -> Optional[dict[str, Any]]:
    if not path.exists():
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None
    return payload if isinstance(payload, dict) else None


def _safe_int(value: Any, default: int = 0) -> int:
    try:
        return int(value)
    except Exception:
        return default


def _history_fix_attempts(payload: dict[str, Any]) -> int:
    history = payload.get("history")
    if not isinstance(history, list):
        return 0
    count = 0
    for item in history:
        if not isinstance(item, dict):
            continue
        action = str(item.get("action") or "").lower()
        if "fix" in action:
            count += 1
    return count


def _normalize_loaded_state(project_dir: Path, payload: dict[str, Any]) -> dict[str, Any]:
    base = _default_state(project_dir)
    normalized = dict(base)
    normalized.update(payload)
    normalized["iterations"] = _safe_int(normalized.get("iterations"), 0)
    fix_attempts_raw = normalized.get("fix_attempts")
    fix_attempts = _safe_int(fix_attempts_raw, -1)
    if fix_attempts < 0:
        fix_attempts = 0
    fix_attempts = max(fix_attempts, _history_fix_attempts(normalized))
    normalized["fix_attempts"] = fix_attempts
    return normalized


def _tasks_snapshot(project_dir: Path) -> tuple[Optional[int], list[int], list[int]]:
    tasks_payload = _load_json(project_dir / ".archmind" / "tasks.json")
    if not tasks_payload:
        return None, [], []
    raw = tasks_payload.get("tasks")
    if not isinstance(raw, list):
        return None, [], []

    current_task_id: Optional[int] = None
    completed: list[int] = []
    blocked: list[int] = []
    first_todo: Optional[int] = None

    for item in raw:
        if not isinstance(item, dict):
            continue
        task_id = int(item.get("id") or 0)
        if task_id <= 0:
            continue
        status = str(item.get("status") or "").lower()
        if status == "done":
            completed.append(task_id)
        elif status == "blocked":
            blocked.append(task_id)
        elif status == "doing" and current_task_id is None:
            current_task_id = task_id
        elif status == "todo" and first_todo is None:
            first_todo = task_id

    if current_task_id is None:
        current_task_id = first_todo
    return current_task_id, sorted(set(completed)), sorted(set(blocked))


def _default_state(project_dir: Path) -> dict[str, Any]:
    current_task_id, completed, blocked = _tasks_snapshot(project_dir)
    return {
        "project_dir": str(project_dir.expanduser().resolve()),
        "updated_at": _now(),
        "iterations": 0,
        "fix_attempts": 0,
        "current_task_id": current_task_id,
        "last_action": "",
        "last_status": "UNKNOWN",
        "completed_tasks": completed,
        "blocked_tasks": blocked,
        "stuck": False,
        "stuck_reason": "",
        "last_failure_signature": "",
        "last_failure_class": "",
        "last_fix_strategy": "",
        "last_failure_signature_before_fix": "",
        "last_failure_signature_after_fix": "",
        "last_repair_targets": [],
        "derived_task_label": "",
        "recent_failures": [],
        "history": [],
    }


def load_state(project_dir: Path) -> Optional[dict[str, Any]]:
    project_dir = project_dir.expanduser().resolve()
    payload = _load_json(_state_path(project_dir))
    if payload is None:
        return None
    return _normalize_loaded_state(project_dir, payload)


def ensure_state(project_dir: Path) -> dict[str, Any]:
    project_dir = project_dir.expanduser().resolve()
    payload = load_state(project_dir)
    if payload is not None:
        return payload
    payload = _default_state(project_dir)
    write_state(project_dir, payload)
    return payload


def write_state(project_dir: Path, payload: dict[str, Any]) -> Path:
    project_dir = project_dir.expanduser().resolve()
    path = _state_path(project_dir)
    path.parent.mkdir(parents=True, exist_ok=True)
    payload["project_dir"] = str(project_dir)
    payload["updated_at"] = _now()
    payload["last_status"] = _safe_status(str(payload.get("last_status") or "UNKNOWN"))
    payload["iterations"] = _safe_int(payload.get("iterations"), 0)
    payload["fix_attempts"] = max(_safe_int(payload.get("fix_attempts"), 0), _history_fix_attempts(payload))
    payload["last_failure_signature"] = str(payload.get("last_failure_signature") or "").strip()[:220]
    payload["last_failure_class"] = str(payload.get("last_failure_class") or "").strip()[:80]
    payload["last_fix_strategy"] = str(payload.get("last_fix_strategy") or "").strip()[:80]
    payload["last_failure_signature_before_fix"] = str(payload.get("last_failure_signature_before_fix") or "").strip()[:220]
    payload["last_failure_signature_after_fix"] = str(payload.get("last_failure_signature_after_fix") or "").strip()[:220]
    repair_targets = payload.get("last_repair_targets")
    if not isinstance(repair_targets, list):
        payload["last_repair_targets"] = []
    else:
        payload["last_repair_targets"] = [str(x)[:120] for x in repair_targets[:5]]
    payload["derived_task_label"] = str(payload.get("derived_task_label") or "").strip()[:120]
    history = payload.get("history")
    if not isinstance(history, list):
        payload["history"] = []
    if len(payload["history"]) > 20:
        payload["history"] = payload["history"][-20:]
    failures = payload.get("recent_failures")
    if not isinstance(failures, list):
        payload["recent_failures"] = []
    if len(payload["recent_failures"]) > 10:
        payload["recent_failures"] = payload["recent_failures"][:10]
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    return path


def _append_history(payload: dict[str, Any], event: dict[str, str]) -> None:
    history = payload.get("history")
    if not isinstance(history, list):
        history = []
        payload["history"] = history
    history.append(event)
    if len(history) > 20:
        payload["history"] = history[-20:]


def _collect_result_failures(project_dir: Path, max_items: int = 10) -> list[str]:
    result = _load_json(project_dir / ".archmind" / "result.json")
    out: list[str] = []
    if result:
        lines = result.get("failure_summary")
        if isinstance(lines, list):
            for item in lines:
                line = _sanitize_line(str(item), project_dir)
                if line:
                    out.append(line)
    if out:
        return out[:max_items]
    run_logs = project_dir / ".archmind" / "run_logs"
    if run_logs.exists():
        summaries = sorted(run_logs.glob("run_*.summary.txt"), key=lambda p: p.stat().st_mtime, reverse=True)
        if summaries:
            lines = summaries[0].read_text(encoding="utf-8", errors="replace").splitlines()
            for line in lines:
                if "FAILED" in line or "AssertionError" in line or "failed" in line:
                    cleaned = _sanitize_line(line, project_dir)
                    if cleaned:
                        out.append(cleaned)
                if len(out) >= max_items:
                    break
    return out[:max_items]


def _normalize_step_name(name: str) -> str:
    value = (name or "").strip().lower()
    if not value:
        return ""
    value = value.replace("\\", "/")
    value = re.sub(r"[^a-z0-9_./-]+", "-", value)
    value = re.sub(r"-+", "-", value).strip("-")
    value = value.replace("/", "-").replace(".", "-")
    return value[:80]


def _extract_failure_step_names_from_result(payload: dict[str, Any]) -> list[str]:
    names: list[str] = []
    steps = payload.get("steps")
    if isinstance(steps, list):
        for step in steps:
            if not isinstance(step, dict):
                continue
            status = str(step.get("status") or "").upper()
            if status in ("FAIL", "ERROR"):
                name = _normalize_step_name(str(step.get("name") or ""))
                if name:
                    names.append(name)
    elif isinstance(steps, dict):
        for section_name in ("run_before_fix", "run_after_fix"):
            section = steps.get(section_name)
            if not isinstance(section, dict):
                continue
            detail = section.get("detail")
            if isinstance(detail, dict):
                backend_status = str(detail.get("backend_status") or "").upper()
                frontend_status = str(detail.get("frontend_status") or "").upper()
                if backend_status == "FAIL":
                    names.append("backend-pytest")
                if frontend_status == "FAIL":
                    names.append("frontend-lint")
    return sorted(set(names))


def _extract_failure_step_names_from_run_summary(payload: dict[str, Any]) -> list[str]:
    names: list[str] = []
    backend = payload.get("backend")
    frontend = payload.get("frontend")
    if isinstance(backend, dict) and str(backend.get("status") or "").upper() == "FAIL":
        names.append("backend-pytest")
    if isinstance(frontend, dict):
        if str(frontend.get("status") or "").upper() == "FAIL":
            names.append("frontend-lint")
        steps = frontend.get("steps")
        if isinstance(steps, list):
            for step in steps:
                if not isinstance(step, dict):
                    continue
                exit_code = step.get("exit_code")
                if isinstance(exit_code, int) and exit_code != 0:
                    name = _normalize_step_name(f"frontend-{step.get('name') or ''}")
                    if name:
                        names.append(name)
    return sorted(set(names))


def _latest_run_summary_json(project_dir: Path) -> Optional[Path]:
    run_logs = project_dir / ".archmind" / "run_logs"
    if not run_logs.exists():
        return None
    matches = sorted(run_logs.glob("run_*.summary.json"), key=lambda p: p.stat().st_mtime, reverse=True)
    return matches[0] if matches else None


def _collect_failure_signature(project_dir: Path) -> str:
    result_payload = _load_json(project_dir / ".archmind" / "result.json") or {}
    step_names = _extract_failure_step_names_from_result(result_payload)
    if not step_names:
        summary_path = _latest_run_summary_json(project_dir)
        summary_payload = _load_json(summary_path) if summary_path else None
        if isinstance(summary_payload, dict):
            step_names = _extract_failure_step_names_from_run_summary(summary_payload)
    if not step_names:
        return ""
    return f"{'+'.join(sorted(step_names))}:FAIL"


def _collect_failure_class(project_dir: Path, failure_signature: str) -> str:
    result_payload = _load_json(project_dir / ".archmind" / "result.json") or {}
    lines = result_payload.get("failure_summary")
    excerpt = extract_failure_excerpt(lines if isinstance(lines, list) else [])
    if not excerpt:
        excerpt = extract_failure_excerpt(_collect_result_failures(project_dir, max_items=10))
    return classify_failure(excerpt, failure_signature)


def _latest_fix_summary_json(project_dir: Path) -> Optional[Path]:
    run_logs = project_dir / ".archmind" / "run_logs"
    if not run_logs.exists():
        return None
    matches = sorted(run_logs.glob("fix_*.summary.json"), key=lambda p: p.stat().st_mtime, reverse=True)
    return matches[0] if matches else None


def update_state_event(
    project_dir: Path,
    action: str,
    status: str,
    summary: str,
    *,
    increment_iterations: bool = False,
    increment_fix_attempts: bool = False,
    recent_failures: Optional[list[str]] = None,
    failure_signature: Optional[str] = None,
    failure_class: Optional[str] = None,
) -> dict[str, Any]:
    project_dir = project_dir.expanduser().resolve()
    payload = ensure_state(project_dir)

    if increment_iterations:
        payload["iterations"] = _safe_int(payload.get("iterations"), 0) + 1
    if increment_fix_attempts:
        payload["fix_attempts"] = _safe_int(payload.get("fix_attempts"), 0) + 1

    payload["last_action"] = _sanitize_line(action, project_dir)
    payload["last_status"] = _safe_status(status)

    current_task_id, completed, blocked = _tasks_snapshot(project_dir)
    payload["current_task_id"] = current_task_id
    payload["completed_tasks"] = completed
    payload["blocked_tasks"] = blocked

    normalized_signature = str(failure_signature or "").strip()
    if _safe_status(status) in ("FAIL", "NOT_DONE", "BLOCKED", "STUCK") and not normalized_signature:
        normalized_signature = str(payload.get("last_failure_signature") or "").strip()
    payload["last_failure_signature"] = normalized_signature[:220]
    normalized_class = str(failure_class or "").strip()[:80]
    if not normalized_class and normalized_signature:
        normalized_class = str(payload.get("last_failure_class") or "").strip()[:80]
    payload["last_failure_class"] = normalized_class
    payload["derived_task_label"] = derive_task_label_from_failure_signature(normalized_signature)

    merged_failures: list[str] = []
    for line in recent_failures or []:
        cleaned = _sanitize_line(line, project_dir)
        if cleaned and cleaned not in merged_failures:
            merged_failures.append(cleaned)
    old_failures = payload.get("recent_failures")
    if isinstance(old_failures, list):
        for line in old_failures:
            cleaned = _sanitize_line(str(line), project_dir)
            if cleaned and cleaned not in merged_failures:
                merged_failures.append(cleaned)
    payload["recent_failures"] = merged_failures[:10]

    _append_history(
        payload,
        {
            "timestamp": _now(),
            "action": _sanitize_line(action, project_dir),
            "status": _safe_status(status),
            "summary": _sanitize_line(summary, project_dir)[:160],
            "current_task_id": str(current_task_id or ""),
            "current_task_title": _sanitize_line(_task_title(project_dir, current_task_id) or "", project_dir),
            "failure_signature": normalized_signature[:220],
            "failure_class": normalized_class,
        },
    )
    write_state(project_dir, payload)
    return payload


def update_after_run(project_dir: Path, action: str, run_status: str, summary: str) -> dict[str, Any]:
    failures = _collect_result_failures(project_dir, max_items=10)
    failure_signature = _collect_failure_signature(project_dir)
    failure_class = _collect_failure_class(project_dir, failure_signature)
    return update_state_event(
        project_dir,
        action,
        run_status,
        summary,
        increment_iterations=True,
        recent_failures=failures,
        failure_signature=failure_signature,
        failure_class=failure_class,
    )


def update_after_fix(project_dir: Path, action: str, exit_code: int) -> dict[str, Any]:
    status = "SUCCESS" if exit_code == 0 else "FAIL"
    summary = "fix loop completed" if exit_code == 0 else "fix loop failed"
    run_logs = project_dir / ".archmind" / "run_logs"
    prompts = sorted(run_logs.glob("fix_*.prompt.md"), key=lambda p: p.stat().st_mtime, reverse=True)
    if prompts:
        head = prompts[0].read_text(encoding="utf-8", errors="replace").splitlines()[:2]
        if any("# SKIP" in line for line in head):
            status = "SKIP"
            summary = "fix loop skipped"
    failures = _collect_result_failures(project_dir, max_items=10) if status == "FAIL" else []
    failure_signature = _collect_failure_signature(project_dir) if status == "FAIL" else ""
    failure_class = _collect_failure_class(project_dir, failure_signature) if status == "FAIL" else ""
    payload = update_state_event(
        project_dir,
        action,
        status,
        summary,
        increment_fix_attempts=True,
        recent_failures=failures,
        failure_signature=failure_signature,
        failure_class=failure_class,
    )
    latest_fix = _latest_fix_summary_json(project_dir)
    fix_payload = _load_json(latest_fix) if latest_fix else None
    meta = fix_payload.get("meta") if isinstance(fix_payload, dict) else None
    if isinstance(meta, dict):
        payload["last_fix_strategy"] = str(meta.get("fix_strategy") or payload.get("last_fix_strategy") or "")
        payload["last_failure_signature_before_fix"] = str(meta.get("failure_signature_before_fix") or "")
        payload["last_failure_signature_after_fix"] = str(meta.get("failure_signature_after_fix") or "")
        targets = meta.get("repair_targets")
        if isinstance(targets, list):
            payload["last_repair_targets"] = [str(x)[:120] for x in targets[:5]]
        if meta.get("failure_class"):
            payload["last_failure_class"] = str(meta.get("failure_class"))
        before = str(payload.get("last_failure_signature_before_fix") or "")
        after = str(payload.get("last_failure_signature_after_fix") or "")
        if before and after and before == after:
            hint = "fix did not change the failure signature"
            failures_now = payload.get("recent_failures")
            if isinstance(failures_now, list) and hint not in failures_now:
                payload["recent_failures"] = [hint] + failures_now[:9]
    write_state(project_dir, payload)
    return payload


def update_after_evaluation(project_dir: Path, evaluation_status: str, stuck_reason: str = "") -> dict[str, Any]:
    status = _safe_status(evaluation_status)
    payload = update_state_event(project_dir, "evaluate", status, f"evaluation status {status}")
    payload["stuck"] = status == "STUCK"
    payload["stuck_reason"] = stuck_reason if status == "STUCK" else ""
    write_state(project_dir, payload)
    return payload


def sync_from_tasks(project_dir: Path, action: str = "tasks update", status: str = "UNKNOWN") -> dict[str, Any]:
    return update_state_event(project_dir, action, status, "task status updated")


def _task_title(project_dir: Path, task_id: Optional[int]) -> Optional[str]:
    if task_id is None:
        return None
    tasks_payload = _load_json(project_dir / ".archmind" / "tasks.json")
    if not tasks_payload:
        return None
    raw = tasks_payload.get("tasks")
    if not isinstance(raw, list):
        return None
    for item in raw:
        if not isinstance(item, dict):
            continue
        if int(item.get("id") or 0) == task_id:
            return str(item.get("title") or "")
    return None


def format_state_text(project_dir: Path) -> str:
    project_dir = project_dir.expanduser().resolve()
    payload = ensure_state(project_dir)
    status = payload.get("last_status", "UNKNOWN")
    iterations = int(payload.get("iterations") or 0)
    fix_attempts = int(payload.get("fix_attempts") or 0)
    current_task_id = payload.get("current_task_id")
    derived_label = str(payload.get("derived_task_label") or "").strip()
    task_title = _task_title(project_dir, int(current_task_id)) if current_task_id else None
    task_title = derived_label or task_title
    current_line = f"[{current_task_id}] {task_title}" if current_task_id and task_title else "none"
    lines = [
        f"STATE: {status}",
        f"Iterations: {iterations}",
        f"Fix attempts: {fix_attempts}",
        f"Current task: {current_line}",
        f"Failure class: {payload.get('last_failure_class') or 'unknown'}",
        "Recent failures:",
    ]
    failures = payload.get("recent_failures") or []
    if failures:
        for line in failures[:3]:
            lines.append(f"- {line}")
    else:
        lines.append("- (none)")
    return "\n".join(lines)


def state_prompt_summary(project_dir: Path) -> list[str]:
    project_dir = project_dir.expanduser().resolve()
    payload = ensure_state(project_dir)
    current_task_id = payload.get("current_task_id")
    derived_label = str(payload.get("derived_task_label") or "").strip()
    task_title = _task_title(project_dir, int(current_task_id)) if current_task_id else None
    task_title = derived_label or task_title
    current_line = f"[{current_task_id}] {task_title}" if current_task_id and task_title else "none"
    failures = payload.get("recent_failures") or []
    lines = [
        f"- last_status: {payload.get('last_status', 'UNKNOWN')}",
        f"- fix_attempts: {payload.get('fix_attempts', 0)}",
        f"- current_task: {current_line}",
        f"- failure_class: {payload.get('last_failure_class', 'unknown')}",
        "- recent_failures:",
    ]
    if failures:
        for line in failures[:3]:
            lines.append(f"  - {line}")
    else:
        lines.append("  - (none)")
    return lines[:10]
