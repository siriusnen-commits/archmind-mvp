from __future__ import annotations

import json
import os
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from archmind.command_executor import execute_command
from archmind.deploy import get_local_runtime_status
from archmind.execution_history import load_recent_execution_events
from archmind.state import load_state


_STATUS_VALUES = {"pending", "running", "completed", "failed"}
_STEP_STATUS_VALUES = {"pending", "running", "done", "failed"}
_RECOVERY_STATUS_VALUES = {"running", "completed", "failed"}
_FLOW_LOCKS: dict[str, threading.Lock] = {}
_FLOW_THREADS: dict[str, threading.Thread] = {}
_GUARD = threading.Lock()


def _flow_key(project_dir: Path) -> str:
    return str(project_dir.expanduser().resolve())


def _flow_lock(project_dir: Path) -> threading.Lock:
    key = _flow_key(project_dir)
    with _GUARD:
        lock = _FLOW_LOCKS.get(key)
        if lock is None:
            lock = threading.Lock()
            _FLOW_LOCKS[key] = lock
        return lock


def _flow_execution_path(project_dir: Path) -> Path:
    return (project_dir / ".archmind" / "flow_execution.json").expanduser().resolve()


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _normalize_status(value: Any) -> str:
    text = str(value or "").strip().lower()
    if text in _STATUS_VALUES:
        return text
    return "pending"


def _normalize_step_status(value: Any) -> str:
    text = str(value or "").strip().lower()
    if text in _STEP_STATUS_VALUES:
        return text
    return "pending"


def _normalize_recovery_status(value: Any) -> str:
    text = str(value or "").strip().lower()
    if text in _RECOVERY_STATUS_VALUES:
        return text
    return "failed"


def _normalize_step(step: dict[str, Any], idx: int) -> dict[str, Any]:
    step_id = str(step.get("id") or f"step_{idx + 1}").strip() or f"step_{idx + 1}"
    return {
        "id": step_id,
        "title": str(step.get("title") or "Plan step").strip() or "Plan step",
        "command": str(step.get("command") or "").strip(),
        "depends_on": [str(x).strip() for x in (step.get("depends_on") or []) if str(x).strip()],
        "status": _normalize_step_status(step.get("status") or "pending"),
    }


def _normalize_timeline_event(event: dict[str, Any], idx: int) -> dict[str, Any]:
    row = event if isinstance(event, dict) else {}
    event_type = str(row.get("type") or "").strip().lower() or "event"
    status_raw = str(row.get("status") or "").strip().lower()
    status = _normalize_step_status(status_raw) if status_raw else ""
    return {
        "id": str(row.get("id") or f"event_{idx + 1}").strip() or f"event_{idx + 1}",
        "type": event_type,
        "status": status,
        "step_id": str(row.get("step_id") or "").strip(),
        "command": str(row.get("command") or "").strip(),
        "detail": str(row.get("detail") or "").strip(),
        "at": str(row.get("at") or _utc_now_iso()).strip() or _utc_now_iso(),
    }


def _normalize_recovery(payload: dict[str, Any] | None) -> dict[str, Any]:
    row = payload if isinstance(payload, dict) else {}
    steps_raw = row.get("steps") if isinstance(row.get("steps"), list) else []
    steps: list[dict[str, str]] = []
    for item in steps_raw:
        if not isinstance(item, dict):
            continue
        command = str(item.get("command") or "").strip()
        if not command:
            continue
        steps.append(
            {
                "command": command,
                "status": _normalize_step_status(item.get("status") or "pending"),
            }
        )
    triggered = bool(row.get("triggered"))
    default_status = "failed" if triggered else "completed"
    return {
        "triggered": triggered,
        "reason": str(row.get("reason") or "").strip(),
        "steps": steps,
        "status": _normalize_recovery_status(row.get("status") or default_status),
    }


def _normalize_flow_execution(payload: dict[str, Any] | None) -> dict[str, Any]:
    row = payload if isinstance(payload, dict) else {}
    steps_raw = row.get("steps") if isinstance(row.get("steps"), list) else []
    timeline_raw = row.get("timeline") if isinstance(row.get("timeline"), list) else []
    steps = [_normalize_step(step, idx) for idx, step in enumerate(steps_raw) if isinstance(step, dict)]
    timeline = [_normalize_timeline_event(item, idx) for idx, item in enumerate(timeline_raw) if isinstance(item, dict)]
    return {
        "project_id": str(row.get("project_id") or "").strip(),
        "flow_name": str(row.get("flow_name") or "").strip(),
        "status": _normalize_status(row.get("status") or "pending"),
        "current_step": str(row.get("current_step") or "").strip(),
        "steps": steps,
        "recovery": _normalize_recovery(row.get("recovery") if isinstance(row.get("recovery"), dict) else None),
        "timeline": timeline,
        "updated_at": str(row.get("updated_at") or _utc_now_iso()).strip() or _utc_now_iso(),
    }


def load_flow_execution(project_dir: Path) -> dict[str, Any]:
    path = _flow_execution_path(project_dir)
    if not path.exists():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}
    if not isinstance(payload, dict):
        return {}
    normalized = _normalize_flow_execution(payload)
    if not normalized.get("project_id") or not normalized.get("flow_name"):
        return {}
    return normalized


def _persist_flow_execution(project_dir: Path, payload: dict[str, Any]) -> None:
    path = _flow_execution_path(project_dir)
    row = _normalize_flow_execution(payload)
    row["updated_at"] = _utc_now_iso()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(row, ensure_ascii=False, indent=2), encoding="utf-8")


def _build_initial_execution(project_id: str, flow_name: str, steps: list[dict[str, Any]]) -> dict[str, Any]:
    normalized_steps = [_normalize_step(step, idx) for idx, step in enumerate(steps) if isinstance(step, dict)]
    current_step = ""
    for item in normalized_steps:
        command = str(item.get("command") or "").strip()
        if command:
            current_step = str(item.get("id") or "").strip()
            break
    execution = {
        "project_id": str(project_id or "").strip(),
        "flow_name": str(flow_name or "").strip(),
        "status": "running",
        "current_step": current_step,
        "steps": normalized_steps,
        "recovery": _normalize_recovery(None),
        "timeline": [],
        "updated_at": _utc_now_iso(),
    }
    append_timeline(
        execution,
        {
            "type": "flow_start",
            "status": "running",
            "detail": f"Flow {str(flow_name or '').strip() or 'Plan Flow'} started",
        },
    )
    return execution


def append_timeline(execution: dict[str, Any], event: dict[str, Any]) -> None:
    if not isinstance(execution, dict) or not isinstance(event, dict):
        return
    timeline = execution.get("timeline")
    if not isinstance(timeline, list):
        timeline = []
        execution["timeline"] = timeline
    normalized = _normalize_timeline_event(
        {
            **event,
            "id": str(event.get("id") or f"event_{len(timeline) + 1}").strip() or f"event_{len(timeline) + 1}",
            "at": str(event.get("at") or _utc_now_iso()).strip() or _utc_now_iso(),
        },
        len(timeline),
    )
    timeline.append(normalized)


def _set_step_status(execution: dict[str, Any], step_id: str, status: str) -> None:
    normalized = _normalize_step_status(status)
    for item in (execution.get("steps") or []):
        if not isinstance(item, dict):
            continue
        if str(item.get("id") or "").strip() != str(step_id or "").strip():
            continue
        item["status"] = normalized
        return


def _is_flow_worker_alive(project_dir: Path) -> bool:
    key = _flow_key(project_dir)
    with _GUARD:
        worker = _FLOW_THREADS.get(key)
        if worker is None:
            return False
        return worker.is_alive()


def _prepare_execution_for_resume(execution: dict[str, Any]) -> tuple[dict[str, Any], str]:
    steps = execution.get("steps") if isinstance(execution.get("steps"), list) else []
    first_resume_step_id = ""
    first_resume_index = -1
    for idx, step in enumerate(steps):
        if not isinstance(step, dict):
            continue
        step_id = str(step.get("id") or "").strip()
        status = _normalize_step_status(step.get("status") or "pending")
        if status == "running":
            step["status"] = "pending"
            status = "pending"
        if first_resume_index >= 0:
            continue
        if status in {"failed", "pending"}:
            first_resume_index = idx
            first_resume_step_id = step_id
            if status == "failed":
                step["status"] = "pending"

    if first_resume_index < 0:
        execution["status"] = "completed"
        execution["current_step"] = ""
        return execution, ""

    for idx, step in enumerate(steps):
        if idx <= first_resume_index:
            continue
        if not isinstance(step, dict):
            continue
        if _normalize_step_status(step.get("status") or "pending") == "running":
            step["status"] = "pending"

    execution["status"] = "running"
    execution["current_step"] = first_resume_step_id
    return execution, first_resume_step_id


def _normalize_failure_class(value: Any) -> str:
    text = str(value or "").strip().lower()
    if "frontend-clean" in text:
        return "frontend-clean"
    if "runtime" in text:
        return "runtime-error"
    if "generation" in text:
        return "generation-error"
    return "default"


def _select_recovery_steps(failure_class: str) -> list[str]:
    key = _normalize_failure_class(failure_class)
    if key == "frontend-clean":
        return ["/restart"]
    if key == "runtime-error":
        return ["/restart", "/improve"]
    if key == "generation-error":
        return ["/improve"]
    return ["/improve"]


def _service_healthy(status: Any, health: Any) -> bool:
    normalized_status = str(status or "").strip().upper()
    normalized_health = str(health or "").strip().upper()
    return normalized_health == "SUCCESS" or normalized_status == "RUNNING"


def _detect_runtime_drift(project_dir: Path) -> bool:
    events = load_recent_execution_events(project_dir, limit=12)
    for event in reversed(events):
        if not isinstance(event, dict):
            continue
        verification = event.get("verification") if isinstance(event.get("verification"), dict) else {}
        if not isinstance(verification, dict):
            continue
        overall_status = str(verification.get("overall_status") or "").strip().upper()
        drift_summary = str(verification.get("drift_summary") or "").strip()
        runtime_reflection = str(verification.get("runtime_reflection") or "").strip()
        issues = verification.get("issues") if isinstance(verification.get("issues"), list) else []
        if overall_status in {"PARTIAL", "FAILED"}:
            return True
        if drift_summary or runtime_reflection or bool(issues):
            return True
    return False


def build_recovery_context(
    project: Path | str,
    execution: dict[str, Any],
    failure_result: dict[str, Any] | None = None,
) -> dict[str, Any]:
    project_dir = Path(project).expanduser().resolve()
    runtime_status = get_local_runtime_status(project_dir)
    services = runtime_status.get("services") if isinstance(runtime_status.get("services"), dict) else {}
    frontend_service = services.get("frontend") if isinstance(services.get("frontend"), dict) else {}
    backend_service = services.get("backend") if isinstance(services.get("backend"), dict) else {}
    state_payload = load_state(project_dir) or {}
    row = failure_result if isinstance(failure_result, dict) else {}
    raw_failure_class = str(row.get("failure_class") or row.get("error") or row.get("detail") or "").strip()
    recent_events = load_recent_execution_events(project_dir, limit=8)
    recent_command = ""
    for event in reversed(recent_events):
        if not isinstance(event, dict):
            continue
        command = str(event.get("command") or "").strip()
        if command:
            recent_command = command
            break
    if not recent_command:
        current_step_id = str(execution.get("current_step") or "").strip()
        for step in execution.get("steps") if isinstance(execution.get("steps"), list) else []:
            if not isinstance(step, dict):
                continue
            step_id = str(step.get("id") or "").strip()
            if step_id != current_step_id:
                continue
            recent_command = str(step.get("command") or "").strip()
            if recent_command:
                break

    return {
        "failure_class": _normalize_failure_class(raw_failure_class),
        "frontend_health": _service_healthy(frontend_service.get("status"), frontend_service.get("health")),
        "backend_health": _service_healthy(backend_service.get("status"), backend_service.get("health")),
        "drift": _detect_runtime_drift(project_dir),
        "recent_command": recent_command,
        "runtime_failure_class": str(state_payload.get("runtime_failure_class") or "").strip(),
        "last_failure_class": str(state_payload.get("last_failure_class") or "").strip(),
    }


def select_recovery_steps(context: dict[str, Any]) -> list[str]:
    row = context if isinstance(context, dict) else {}
    failure_class = _normalize_failure_class(row.get("failure_class"))
    frontend_healthy = bool(row.get("frontend_health"))
    has_drift = bool(row.get("drift"))

    if failure_class == "generation-error":
        return ["/improve"]
    if failure_class == "frontend-clean" and frontend_healthy and not has_drift:
        return []

    steps: list[str] = []
    if not frontend_healthy:
        steps.append("/restart")
    if has_drift:
        steps.append("/improve")
    if failure_class == "runtime-error" and "/improve" not in steps:
        steps.append("/improve")
    if not steps:
        steps.append("/improve")

    deduped: list[str] = []
    seen: set[str] = set()
    for command in steps:
        cmd = str(command or "").strip()
        if not cmd or cmd in seen:
            continue
        seen.add(cmd)
        deduped.append(cmd)
    return deduped


def handle_failure_with_recovery(
    project_dir: Path,
    project_id: str,
    execution: dict[str, Any],
    *,
    failed_step_id: str,
    failure_result: dict[str, Any] | None = None,
) -> dict[str, Any]:
    context = build_recovery_context(project_dir, execution, failure_result)
    normalized_failure_class = _normalize_failure_class(context.get("failure_class"))
    recovery_steps = select_recovery_steps(context)
    executed_recovery_steps: list[str] = []
    if not recovery_steps:
        execution["recovery"] = {
            "triggered": False,
            "reason": normalized_failure_class,
            "steps": [],
            "status": "completed",
        }
        prepared, resume_step_id = _prepare_execution_for_resume(execution)
        append_timeline(
            prepared,
            {
                "type": "resume",
                "status": "running",
                "step_id": str(resume_step_id or "").strip(),
                "detail": "Resume without recovery steps",
            },
        )
        return {
            "ok": True,
            "failure_class": normalized_failure_class,
            "recovery_steps": [],
            "executed_recovery_steps": [],
            "resume_step_id": resume_step_id,
            "flow_execution": prepared,
            "failed_step_id": str(failed_step_id or "").strip(),
        }
    recovery_log: dict[str, Any] = {
        "triggered": True,
        "reason": normalized_failure_class,
        "steps": [],
        "status": "running",
    }
    execution["recovery"] = recovery_log
    append_timeline(
        execution,
        {
            "type": "recovery_start",
            "status": "running",
            "step_id": str(failed_step_id or "").strip(),
            "detail": normalized_failure_class,
        },
    )
    for command in recovery_steps:
        cmd = str(command or "").strip()
        if not cmd:
            continue
        recovery_step = {"command": cmd, "status": "running"}
        recovery_log["steps"].append(recovery_step)
        append_timeline(
            execution,
            {
                "type": "recovery_step",
                "status": "running",
                "command": cmd,
                "detail": "Recovery step running",
            },
        )
        recovery_result = execute_command(cmd, project_id, source="ui-flow-recovery")
        if not bool(recovery_result.get("ok")):
            recovery_step["status"] = "failed"
            recovery_log["status"] = "failed"
            append_timeline(
                execution,
                {
                    "type": "recovery_step",
                    "status": "failed",
                    "command": cmd,
                    "detail": str(recovery_result.get("error") or recovery_result.get("detail") or "recovery failed").strip(),
                },
            )
            return {
                "ok": False,
                "failure_class": normalized_failure_class,
                "recovery_steps": recovery_steps,
                "executed_recovery_steps": executed_recovery_steps,
                "error": str(recovery_result.get("error") or recovery_result.get("detail") or "recovery failed").strip(),
                "flow_execution": execution,
            }
        recovery_step["status"] = "done"
        executed_recovery_steps.append(cmd)
        append_timeline(
            execution,
            {
                "type": "recovery_step",
                "status": "done",
                "command": cmd,
                "detail": "Recovery step done",
            },
        )
    recovery_log["status"] = "completed"
    prepared, resume_step_id = _prepare_execution_for_resume(execution)
    append_timeline(
        prepared,
        {
            "type": "resume",
            "status": "running",
            "step_id": str(resume_step_id or "").strip(),
            "detail": "Resume after recovery",
        },
    )
    if not resume_step_id:
        return {
            "ok": True,
            "failure_class": normalized_failure_class,
            "recovery_steps": recovery_steps,
            "executed_recovery_steps": executed_recovery_steps,
            "resume_step_id": "",
            "flow_execution": prepared,
        }
    return {
        "ok": True,
        "failure_class": normalized_failure_class,
        "recovery_steps": recovery_steps,
        "executed_recovery_steps": executed_recovery_steps,
        "resume_step_id": resume_step_id,
        "flow_execution": prepared,
        "failed_step_id": str(failed_step_id or "").strip(),
    }


def _run_flow_execution(project_dir: Path, project_id: str) -> None:
    lock = _flow_lock(project_dir)
    with lock:
        recovery_attempted_steps: set[str] = set()
        while True:
            execution = load_flow_execution(project_dir)
            if not execution or execution.get("status") != "running":
                return

            steps = execution.get("steps") if isinstance(execution.get("steps"), list) else []
            failure_handled = False
            for step in steps:
                if not isinstance(step, dict):
                    continue
                step_id = str(step.get("id") or "").strip()
                command = str(step.get("command") or "").strip()
                current_status = _normalize_step_status(step.get("status") or "pending")
                if current_status in {"done", "failed"}:
                    continue
                if not command:
                    _set_step_status(execution, step_id, "failed")
                    execution["status"] = "failed"
                    execution["current_step"] = step_id
                    append_timeline(
                        execution,
                        {
                            "type": "step",
                            "status": "failed",
                            "step_id": step_id,
                            "detail": "Missing command",
                        },
                    )
                    _persist_flow_execution(project_dir, execution)
                    return

                execution["status"] = "running"
                execution["current_step"] = step_id
                _set_step_status(execution, step_id, "running")
                append_timeline(
                    execution,
                    {
                        "type": "step",
                        "status": "running",
                        "step_id": step_id,
                        "command": command,
                        "detail": "Step running",
                    },
                )
                _persist_flow_execution(project_dir, execution)

                result = execute_command(command, project_id, source="ui-flow-run")
                ok = bool(result.get("ok"))
                if ok:
                    _set_step_status(execution, step_id, "done")
                    append_timeline(
                        execution,
                        {
                            "type": "step",
                            "status": "done",
                            "step_id": step_id,
                            "command": command,
                            "detail": "Step done",
                        },
                    )
                    _persist_flow_execution(project_dir, execution)
                    continue

                _set_step_status(execution, step_id, "failed")
                execution["status"] = "failed"
                execution["current_step"] = step_id
                append_timeline(
                    execution,
                    {
                        "type": "step",
                        "status": "failed",
                        "step_id": step_id,
                        "command": command,
                        "detail": str(result.get("error") or result.get("detail") or "step failed").strip(),
                    },
                )
                _persist_flow_execution(project_dir, execution)

                if step_id in recovery_attempted_steps:
                    return
                recovery_attempted_steps.add(step_id)
                recovery = handle_failure_with_recovery(
                    project_dir,
                    project_id,
                    execution,
                    failed_step_id=step_id,
                    failure_result=result if isinstance(result, dict) else {},
                )
                if not bool(recovery.get("ok")):
                    return
                resumed = recovery.get("flow_execution") if isinstance(recovery.get("flow_execution"), dict) else execution
                _persist_flow_execution(project_dir, resumed if isinstance(resumed, dict) else execution)
                failure_handled = True
                break

            if failure_handled:
                continue

            execution["status"] = "completed"
            execution["current_step"] = ""
            append_timeline(
                execution,
                {
                    "type": "flow_complete",
                    "status": "done",
                    "detail": "Flow completed",
                },
            )
            _persist_flow_execution(project_dir, execution)
            return


def start_flow_execution(
    project_dir: Path,
    *,
    project_id: str,
    flow_name: str,
    steps: list[dict[str, Any]],
    sync: bool | None = None,
) -> dict[str, Any]:
    lock = _flow_lock(project_dir)
    with lock:
        current = load_flow_execution(project_dir)
        if current and str(current.get("status") or "").strip().lower() == "running":
            return {
                "ok": True,
                "started": False,
                "detail": "Flow execution already running",
                "error": "",
                "flow_execution": current,
            }

        initial = _build_initial_execution(project_id=project_id, flow_name=flow_name, steps=steps)
        _persist_flow_execution(project_dir, initial)

    force_sync = bool(sync) if isinstance(sync, bool) else (str(os.getenv("ARCHMIND_FLOW_EXEC_SYNC", "") or "").strip() == "1")
    if force_sync:
        _run_flow_execution(project_dir, project_id)
        latest = load_flow_execution(project_dir)
        return {
            "ok": True,
            "started": True,
            "detail": "Flow execution completed",
            "error": "",
            "flow_execution": latest if latest else initial,
        }

    key = _flow_key(project_dir)
    worker = threading.Thread(
        target=_run_flow_execution,
        args=(project_dir, project_id),
        daemon=True,
        name=f"archmind-flow-exec:{project_id}",
    )
    with _GUARD:
        _FLOW_THREADS[key] = worker
    worker.start()
    return {
        "ok": True,
        "started": True,
        "detail": "Flow execution started",
        "error": "",
        "flow_execution": initial,
    }


def resume_flow_execution(
    project_dir: Path,
    *,
    project_id: str,
    sync: bool | None = None,
) -> dict[str, Any]:
    lock = _flow_lock(project_dir)
    with lock:
        current = load_flow_execution(project_dir)
        if not current:
            return {
                "ok": False,
                "started": False,
                "detail": "No existing flow execution to resume",
                "error": "flow execution not found",
                "flow_execution": {},
            }
        status = str(current.get("status") or "").strip().lower()
        if status == "running" and _is_flow_worker_alive(project_dir):
            return {
                "ok": True,
                "started": False,
                "detail": "Flow execution already running",
                "error": "",
                "flow_execution": current,
            }
        prepared, resume_step_id = _prepare_execution_for_resume(current)
        if resume_step_id:
            append_timeline(
                prepared,
                {
                    "type": "resume",
                    "status": "running",
                    "step_id": resume_step_id,
                    "detail": "Manual resume requested",
                },
            )
        _persist_flow_execution(project_dir, prepared)

    if not resume_step_id:
        latest = load_flow_execution(project_dir)
        return {
            "ok": True,
            "started": False,
            "detail": "No remaining step to resume",
            "error": "",
            "flow_execution": latest if latest else prepared,
        }

    force_sync = bool(sync) if isinstance(sync, bool) else (str(os.getenv("ARCHMIND_FLOW_EXEC_SYNC", "") or "").strip() == "1")
    if force_sync:
        _run_flow_execution(project_dir, project_id)
        latest = load_flow_execution(project_dir)
        return {
            "ok": True,
            "started": True,
            "detail": "Flow resume completed",
            "error": "",
            "flow_execution": latest if latest else prepared,
        }

    key = _flow_key(project_dir)
    worker = threading.Thread(
        target=_run_flow_execution,
        args=(project_dir, project_id),
        daemon=True,
        name=f"archmind-flow-resume:{project_id}",
    )
    with _GUARD:
        _FLOW_THREADS[key] = worker
    worker.start()
    return {
        "ok": True,
        "started": True,
        "detail": "Flow resume started",
        "error": "",
        "flow_execution": prepared,
    }
