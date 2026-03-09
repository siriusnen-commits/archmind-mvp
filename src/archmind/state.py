from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any, Optional

LAST_STATUSES = (
    "SUCCESS",
    "FAIL",
    "SKIP",
    "DONE",
    "NOT_DONE",
    "BLOCKED",
    "UNKNOWN",
)


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
        "current_task_id": current_task_id,
        "last_action": "",
        "last_status": "UNKNOWN",
        "completed_tasks": completed,
        "blocked_tasks": blocked,
        "recent_failures": [],
        "history": [],
    }


def load_state(project_dir: Path) -> Optional[dict[str, Any]]:
    return _load_json(_state_path(project_dir))


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


def update_state_event(
    project_dir: Path,
    action: str,
    status: str,
    summary: str,
    *,
    increment_iterations: bool = False,
    recent_failures: Optional[list[str]] = None,
) -> dict[str, Any]:
    project_dir = project_dir.expanduser().resolve()
    payload = ensure_state(project_dir)

    if increment_iterations:
        payload["iterations"] = int(payload.get("iterations") or 0) + 1

    payload["last_action"] = _sanitize_line(action, project_dir)
    payload["last_status"] = _safe_status(status)

    current_task_id, completed, blocked = _tasks_snapshot(project_dir)
    payload["current_task_id"] = current_task_id
    payload["completed_tasks"] = completed
    payload["blocked_tasks"] = blocked

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
        },
    )
    write_state(project_dir, payload)
    return payload


def update_after_run(project_dir: Path, action: str, run_status: str, summary: str) -> dict[str, Any]:
    failures = _collect_result_failures(project_dir, max_items=10)
    return update_state_event(
        project_dir,
        action,
        run_status,
        summary,
        increment_iterations=True,
        recent_failures=failures,
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
    return update_state_event(project_dir, action, status, summary, recent_failures=failures)


def update_after_evaluation(project_dir: Path, evaluation_status: str) -> dict[str, Any]:
    status = _safe_status(evaluation_status)
    return update_state_event(project_dir, "evaluate", status, f"evaluation status {status}")


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
    current_task_id = payload.get("current_task_id")
    task_title = _task_title(project_dir, int(current_task_id)) if current_task_id else None
    current_line = f"[{current_task_id}] {task_title}" if current_task_id and task_title else "none"
    lines = [
        f"STATE: {status}",
        f"Iterations: {iterations}",
        f"Current task: {current_line}",
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
    task_title = _task_title(project_dir, int(current_task_id)) if current_task_id else None
    current_line = f"[{current_task_id}] {task_title}" if current_task_id and task_title else "none"
    failures = payload.get("recent_failures") or []
    lines = [
        f"- last_status: {payload.get('last_status', 'UNKNOWN')}",
        f"- current_task: {current_line}",
        "- recent_failures:",
    ]
    if failures:
        for line in failures[:3]:
            lines.append(f"  - {line}")
    else:
        lines.append("  - (none)")
    return lines[:10]
