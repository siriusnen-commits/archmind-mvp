from __future__ import annotations

import json
import os
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from archmind.command_executor import execute_command


_STATUS_VALUES = {"pending", "running", "completed", "failed"}
_STEP_STATUS_VALUES = {"pending", "running", "done", "failed"}
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


def _normalize_step(step: dict[str, Any], idx: int) -> dict[str, Any]:
    step_id = str(step.get("id") or f"step_{idx + 1}").strip() or f"step_{idx + 1}"
    return {
        "id": step_id,
        "title": str(step.get("title") or "Plan step").strip() or "Plan step",
        "command": str(step.get("command") or "").strip(),
        "depends_on": [str(x).strip() for x in (step.get("depends_on") or []) if str(x).strip()],
        "status": _normalize_step_status(step.get("status") or "pending"),
    }


def _normalize_flow_execution(payload: dict[str, Any] | None) -> dict[str, Any]:
    row = payload if isinstance(payload, dict) else {}
    steps_raw = row.get("steps") if isinstance(row.get("steps"), list) else []
    steps = [_normalize_step(step, idx) for idx, step in enumerate(steps_raw) if isinstance(step, dict)]
    return {
        "project_id": str(row.get("project_id") or "").strip(),
        "flow_name": str(row.get("flow_name") or "").strip(),
        "status": _normalize_status(row.get("status") or "pending"),
        "current_step": str(row.get("current_step") or "").strip(),
        "steps": steps,
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
    return {
        "project_id": str(project_id or "").strip(),
        "flow_name": str(flow_name or "").strip(),
        "status": "running",
        "current_step": current_step,
        "steps": normalized_steps,
        "updated_at": _utc_now_iso(),
    }


def _set_step_status(execution: dict[str, Any], step_id: str, status: str) -> None:
    normalized = _normalize_step_status(status)
    for item in (execution.get("steps") or []):
        if not isinstance(item, dict):
            continue
        if str(item.get("id") or "").strip() != str(step_id or "").strip():
            continue
        item["status"] = normalized
        return


def _run_flow_execution(project_dir: Path, project_id: str) -> None:
    lock = _flow_lock(project_dir)
    with lock:
        execution = load_flow_execution(project_dir)
        if not execution or execution.get("status") != "running":
            return

        steps = execution.get("steps") if isinstance(execution.get("steps"), list) else []
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
                _persist_flow_execution(project_dir, execution)
                return

            execution["status"] = "running"
            execution["current_step"] = step_id
            _set_step_status(execution, step_id, "running")
            _persist_flow_execution(project_dir, execution)

            result = execute_command(command, project_id, source="ui-flow-run")
            ok = bool(result.get("ok"))
            if ok:
                _set_step_status(execution, step_id, "done")
                _persist_flow_execution(project_dir, execution)
                continue

            _set_step_status(execution, step_id, "failed")
            execution["status"] = "failed"
            execution["current_step"] = step_id
            _persist_flow_execution(project_dir, execution)
            return

        execution["status"] = "completed"
        execution["current_step"] = ""
        _persist_flow_execution(project_dir, execution)


def start_flow_execution(
    project_dir: Path,
    *,
    project_id: str,
    flow_name: str,
    steps: list[dict[str, Any]],
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

    if str(os.getenv("ARCHMIND_FLOW_EXEC_SYNC", "") or "").strip() == "1":
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
