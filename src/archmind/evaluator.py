from __future__ import annotations

import json
import re
from datetime import datetime
from pathlib import Path
from typing import Any, Optional

from archmind.state import load_state
from archmind.state import update_after_evaluation
from archmind.tasks import auto_update_task_completion, load_tasks

EVAL_STATUSES = ("DONE", "NOT_DONE", "BLOCKED", "STUCK")
RUN_STATUSES = ("SUCCESS", "FAIL", "SKIP", "MISSING")


def _archmind_dir(project_dir: Path) -> Path:
    return project_dir.expanduser().resolve() / ".archmind"


def _evaluation_path(project_dir: Path) -> Path:
    return _archmind_dir(project_dir) / "evaluation.json"


def _latest_run_summary_json(project_dir: Path) -> Optional[Path]:
    run_logs = _archmind_dir(project_dir) / "run_logs"
    if not run_logs.exists():
        return None
    matches = sorted(run_logs.glob("run_*.summary.json"), key=lambda p: p.stat().st_mtime, reverse=True)
    return matches[0] if matches else None


def _load_json(path: Path) -> Optional[dict[str, Any]]:
    if not path.exists():
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None
    if not isinstance(payload, dict):
        return None
    return payload


def _has_acceptance(project_dir: Path) -> bool:
    archmind = _archmind_dir(project_dir)
    plan_json = _load_json(archmind / "plan.json")
    if plan_json:
        acceptance = plan_json.get("acceptance")
        if isinstance(acceptance, list) and any(str(item).strip() for item in acceptance):
            return True
    plan_md = archmind / "plan.md"
    if not plan_md.exists():
        return False
    text = plan_md.read_text(encoding="utf-8", errors="replace").lower()
    return ("done 정의" in text) or ("acceptance" in text) or ("완료 조건" in text)


def _compute_tasks_flags(project_dir: Path) -> tuple[bool, bool, bool]:
    payload = load_tasks(project_dir)
    if not payload:
        return False, False, False
    raw_tasks = payload.get("tasks")
    if not isinstance(raw_tasks, list) or not raw_tasks:
        return False, False, False
    statuses = [str(item.get("status") or "") for item in raw_tasks if isinstance(item, dict)]
    if not statuses:
        return False, False, False
    tasks_complete = all(status == "done" for status in statuses)
    pending_exists = any(status in ("todo", "doing") for status in statuses)
    all_blocked = all(status == "blocked" for status in statuses)
    return tasks_complete, pending_exists, all_blocked


def _extract_run_status(project_dir: Path) -> str:
    archmind = _archmind_dir(project_dir)
    result_payload = _load_json(archmind / "result.json")
    if result_payload:
        status = str(result_payload.get("status") or "").upper()
        if status == "SUCCESS":
            return "SUCCESS"
        if status in ("FAIL", "PARTIAL"):
            return "FAIL"

    summary_path = _latest_run_summary_json(project_dir)
    summary_payload = _load_json(summary_path) if summary_path else None
    if summary_payload is not None:
        overall_exit = summary_payload.get("overall_exit_code")
        if overall_exit == 0:
            return "SUCCESS"
        if isinstance(overall_exit, int) and overall_exit != 0:
            return "FAIL"
        backend = summary_payload.get("backend", {})
        frontend = summary_payload.get("frontend", {})
        backend_status = str((backend or {}).get("status") or "").upper()
        frontend_status = str((frontend or {}).get("status") or "").upper()
        if backend_status == "SKIPPED" and frontend_status == "SKIPPED":
            return "SKIP"
    return "MISSING"


def normalize_failure_summary(text: str) -> str:
    value = (text or "").lower()
    value = value.replace("\\", "/")
    value = re.sub(r"/[^ ]+", "<path>", value)
    value = re.sub(r"\b20\d{2}[01]\d[0-3]\d[_ -]?\d{2}:?\d{2}:?\d{2}\b", "<ts>", value)
    value = re.sub(r"\bpid[:= ]\d+\b", "pid", value)
    value = re.sub(r"command:.*", "command", value)
    value = re.sub(r"\s+", " ", value).strip()
    return value[:220]


def _recent_not_done_or_fail_count(state: dict[str, Any], max_n: int = 3) -> int:
    history = state.get("history")
    if not isinstance(history, list):
        return 0
    recent = history[-max_n:]
    count = 0
    for item in recent:
        if not isinstance(item, dict):
            continue
        status = str(item.get("status") or "").upper()
        if status in ("NOT_DONE", "FAIL"):
            count += 1
    return count


def detect_stuck(
    state: dict[str, Any],
    evaluation: Optional[dict[str, Any]] = None,
    result: Optional[dict[str, Any]] = None,
) -> tuple[bool, str]:
    del evaluation, result
    if int(state.get("iterations") or 0) < 3:
        return False, ""

    history = state.get("history")
    if not isinstance(history, list):
        return False, ""

    recent_fail_events: list[dict[str, Any]] = []
    for item in history[-10:]:
        if not isinstance(item, dict):
            continue
        status = str(item.get("status") or "").upper()
        signature = str(item.get("failure_signature") or "").strip()
        if status in ("FAIL", "NOT_DONE") and signature:
            recent_fail_events.append(item)
    if len(recent_fail_events) < 3:
        return False, ""

    last_three = recent_fail_events[-3:]
    signatures = [str(event.get("failure_signature") or "").strip() for event in last_three]
    if not signatures[0] or len(set(signatures)) != 1:
        return False, ""

    task_markers: list[str] = []
    for event in last_three:
        raw_id = str(event.get("current_task_id") or "").strip()
        if raw_id:
            task_markers.append(f"id:{raw_id}")
            continue
        title = str(event.get("current_task_title") or "").strip()
        if title:
            task_markers.append(f"title:{normalize_failure_summary(title)}")
            continue
        task_markers.append("")

    if not task_markers[0] or len(set(task_markers)) != 1:
        return False, ""

    reason = f"same failure repeated 3 times: {signatures[0]}"
    return True, reason
    return False, ""


def evaluate_project(project_dir: Path) -> dict[str, Any]:
    project_dir = project_dir.expanduser().resolve()
    archmind = _archmind_dir(project_dir)
    state_payload = load_state(project_dir) or {}
    result_payload = _load_json(archmind / "result.json")
    previous_eval = _load_json(archmind / "evaluation.json") or {}
    auto_update_task_completion(
        project_dir,
        state=state_payload,
        evaluation=previous_eval,
        result=result_payload or {},
    )
    tasks_complete, pending_exists, all_blocked = _compute_tasks_flags(project_dir)
    run_status = _extract_run_status(project_dir)
    acceptance_defined = _has_acceptance(project_dir)
    build_status = run_status

    reasons: list[str] = []
    next_actions: list[str] = []

    if all_blocked:
        status = "BLOCKED"
        reasons.append("all tasks are blocked")
        next_actions.append("unblock at least one task and update task status")
    else:
        done_ready = tasks_complete and run_status in ("SUCCESS", "SKIP") and acceptance_defined
        if done_ready:
            status = "DONE"
            reasons.append("all tasks complete")
            reasons.append("latest run successful")
        else:
            status = "NOT_DONE"
            if pending_exists:
                reasons.append("pending tasks remain")
                next_actions.append("complete pending tasks")
            if not tasks_complete and not pending_exists:
                reasons.append("tasks are missing or incomplete")
                next_actions.append("initialize tasks and mark progress")
            if run_status == "FAIL":
                reasons.append("latest run failed")
                next_actions.append("run archmind fix --scope backend")
            elif run_status == "MISSING":
                reasons.append("latest run missing")
                next_actions.append("run archmind pipeline --path <project>")
            if not acceptance_defined:
                reasons.append("acceptance criteria missing")
                next_actions.append("define acceptance criteria in plan")

    if status == "NOT_DONE":
        stuck, stuck_reason = detect_stuck(state_payload, None, result_payload)
        if stuck:
            status = "STUCK"
            reasons.insert(0, stuck_reason)
            next_actions = [
                "inspect backend failure details",
                "revise current task",
                "run /fix after adjusting plan",
            ]

    payload = {
        "project_dir": str(project_dir),
        "timestamp": datetime.now().strftime("%Y%m%d_%H%M%S"),
        "status": status,
        "checks": {
            "tasks_complete": tasks_complete,
            "run_status": run_status if run_status in RUN_STATUSES else "MISSING",
            "build_status": build_status if build_status in RUN_STATUSES else "MISSING",
            "acceptance_defined": acceptance_defined,
        },
        "reasons": reasons,
        "next_actions": next_actions,
    }
    return payload


def write_evaluation(project_dir: Path) -> tuple[dict[str, Any], Path]:
    project_dir = project_dir.expanduser().resolve()
    payload = evaluate_project(project_dir)
    path = _evaluation_path(project_dir)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    stuck_reason = ""
    reasons = payload.get("reasons") or []
    if str(payload.get("status") or "").upper() == "STUCK" and reasons:
        stuck_reason = str(reasons[0])
    update_after_evaluation(project_dir, str(payload.get("status") or "UNKNOWN"), stuck_reason=stuck_reason)
    return payload, path


def format_evaluation_summary(payload: dict[str, Any]) -> str:
    lines = [f"STATUS: {payload.get('status', 'NOT_DONE')}"]
    reasons = payload.get("reasons") or []
    for reason in reasons:
        lines.append(f"- {reason}")
    actions = payload.get("next_actions") or []
    if actions:
        lines.append("NEXT:")
        for action in actions:
            lines.append(f"- {action}")
    return "\n".join(lines)


def read_evaluation_status(project_dir: Path) -> str:
    payload = _load_json(_evaluation_path(project_dir))
    if not payload:
        return "MISSING"
    status = str(payload.get("status") or "MISSING").upper()
    return status if status in EVAL_STATUSES else "MISSING"
