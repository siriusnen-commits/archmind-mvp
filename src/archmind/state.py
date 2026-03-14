from __future__ import annotations

import json
import re
from datetime import datetime
from pathlib import Path
from typing import Any, Optional

from archmind.decision import decide_next_action
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

AGENT_STATES = (
    "IDLE",
    "PLANNING",
    "RUNNING",
    "FIXING",
    "RETRYING",
    "NOT_DONE",
    "STUCK",
    "DONE",
    "FAILED",
    "BLOCKED",
    "UNKNOWN",
)

HEALTHCHECK_STATUSES = ("SUCCESS", "FAIL", "SKIPPED")
SERVICE_DEPLOY_STATUSES = ("SUCCESS", "FAIL", "SKIPPED")


def derive_task_label_from_failure_signature(signature: str) -> str:
    raw = (signature or "").strip().lower()
    if not raw:
        return ""
    head = raw.split(":", 1)[0]
    parts = [item.strip() for item in head.split("+") if item.strip()]
    key = "+".join(sorted(set(parts)))
    if key == "backend-pytest":
        return "backend pytest failure 분석"
    if key == "frontend-lint-warning":
        return "frontend lint warning 확인"
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


def _now_iso() -> str:
    return datetime.now().isoformat(timespec="seconds")


def _safe_status(value: str) -> str:
    status = (value or "").upper()
    return status if status in LAST_STATUSES else "UNKNOWN"


def _safe_optional_status(value: str) -> str:
    status = (value or "").upper()
    return status if status in LAST_STATUSES else ""


def _safe_healthcheck_status(value: str) -> str:
    status = (value or "").upper()
    return status if status in HEALTHCHECK_STATUSES else ""


def _safe_service_deploy_status(value: str) -> str:
    status = (value or "").upper()
    return status if status in SERVICE_DEPLOY_STATUSES else ""


def _safe_agent_state(value: str) -> str:
    state = (value or "").upper()
    return state if state in AGENT_STATES else "UNKNOWN"


def _agent_state_from_eval_status(value: str) -> str:
    status = _safe_status(value)
    if status == "DONE":
        return "DONE"
    if status == "STUCK":
        return "STUCK"
    if status == "BLOCKED":
        return "BLOCKED"
    if status == "NOT_DONE":
        return "NOT_DONE"
    return "UNKNOWN"


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


def _is_fix_action(action: str) -> bool:
    normalized = (action or "").strip().lower()
    if not normalized:
        return False
    if normalized.startswith("pipeline fix iteration"):
        return True
    return bool(re.search(r"\barchmind\s+fix\b", normalized))


def _is_countable_fix_history_event(item: dict[str, Any]) -> bool:
    action = str(item.get("action") or "")
    if not _is_fix_action(action):
        return False
    status = _safe_status(str(item.get("status") or "UNKNOWN"))
    if status not in ("SUCCESS", "FAIL", "SKIP"):
        return False
    summary = str(item.get("summary") or "").lower()
    if "started" in summary:
        return False
    return True


def _history_fix_attempts(payload: dict[str, Any]) -> int:
    history = payload.get("history")
    if not isinstance(history, list):
        return 0
    count = 0
    for item in history:
        if not isinstance(item, dict):
            continue
        if _is_countable_fix_history_event(item):
            count += 1
    return count


def _sync_summary_fields_from_history(payload: dict[str, Any]) -> None:
    history = payload.get("history")
    if not isinstance(history, list):
        return
    latest_fix: Optional[dict[str, Any]] = None
    for item in reversed(history):
        if not isinstance(item, dict):
            continue
        if _is_countable_fix_history_event(item):
            latest_fix = item
            break
    if not latest_fix:
        return
    latest_class = str(latest_fix.get("failure_class") or "").strip()
    if latest_class:
        payload["last_failure_class"] = latest_class
    latest_sig = str(latest_fix.get("failure_signature") or "").strip()
    if latest_sig:
        payload["last_failure_signature"] = latest_sig
        payload["derived_task_label"] = derive_task_label_from_failure_signature(latest_sig)


def _sync_summary_fields_from_latest_fix_summary(project_dir: Path, payload: dict[str, Any]) -> None:
    latest_fix = _latest_fix_summary_json(project_dir)
    if latest_fix is None:
        return
    fix_payload = _load_json(latest_fix)
    meta = fix_payload.get("meta") if isinstance(fix_payload, dict) else None
    if not isinstance(meta, dict):
        return
    failure_class = str(meta.get("failure_class") or "").strip()
    if failure_class:
        payload["last_failure_class"] = failure_class
    fix_strategy = str(meta.get("fix_strategy") or "").strip()
    if fix_strategy:
        payload["last_fix_strategy"] = fix_strategy
    before = str(meta.get("failure_signature_before_fix") or "").strip()
    if before:
        payload["last_failure_signature_before_fix"] = before
    after = str(meta.get("failure_signature_after_fix") or "").strip()
    if after:
        payload["last_failure_signature_after_fix"] = after
        payload["last_failure_signature"] = after
        payload["derived_task_label"] = derive_task_label_from_failure_signature(after)
    targets = meta.get("repair_targets")
    if isinstance(targets, list):
        payload["last_repair_targets"] = [str(x)[:120] for x in targets[:5]]


def _sync_template_fields_from_result(project_dir: Path, payload: dict[str, Any]) -> None:
    result_payload = _load_json(project_dir / ".archmind" / "result.json") or {}
    project_type = str(result_payload.get("project_type") or "").strip()
    if project_type:
        payload["project_type"] = project_type
    selected_template = str(result_payload.get("selected_template") or "").strip()
    if selected_template:
        payload["selected_template"] = selected_template
    effective_template = str(result_payload.get("effective_template") or "").strip()
    if effective_template:
        payload["effective_template"] = effective_template
    fallback_reason = str(result_payload.get("template_fallback_reason") or "").strip()
    if fallback_reason:
        payload["template_fallback_reason"] = fallback_reason


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
    normalized["agent_state"] = _safe_agent_state(str(normalized.get("agent_state") or "IDLE"))
    _sync_summary_fields_from_history(normalized)
    _sync_summary_fields_from_latest_fix_summary(project_dir, normalized)
    _sync_template_fields_from_result(project_dir, normalized)
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
        "agent_state": "IDLE",
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
        "environment_issue": "env-readiness-ok",
        "environment_issue_reason": "",
        "last_bootstrap_actions": [],
        "next_action": "STOP",
        "next_action_reason": "",
        "github_repo_url": "",
        "deploy_target": "",
        "deploy_kind": "",
        "last_deploy_status": "",
        "deploy_url": "",
        "last_deploy_detail": "",
        "backend_deploy_url": "",
        "backend_deploy_status": "",
        "backend_deploy_detail": "",
        "frontend_deploy_url": "",
        "frontend_deploy_status": "",
        "frontend_deploy_detail": "",
        "backend_smoke_url": "",
        "backend_smoke_status": "",
        "backend_smoke_detail": "",
        "frontend_smoke_url": "",
        "frontend_smoke_status": "",
        "frontend_smoke_detail": "",
        "healthcheck_url": "",
        "healthcheck_status": "",
        "healthcheck_detail": "",
        "current_step_key": "",
        "current_step_label": "",
        "current_step_status": "",
        "current_step_detail": "",
        "last_progress_at": "",
        "project_type": "unknown",
        "selected_template": "unknown",
        "effective_template": "unknown",
        "template_fallback_reason": "",
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
    _sync_summary_fields_from_history(payload)
    _sync_summary_fields_from_latest_fix_summary(project_dir, payload)
    _sync_template_fields_from_result(project_dir, payload)
    evaluation_payload = _load_json(project_dir / ".archmind" / "evaluation.json") or {}
    result_payload = _load_json(project_dir / ".archmind" / "result.json") or {}
    decision = decide_next_action(payload, evaluation_payload, result_payload)
    payload["next_action"] = str(decision.get("action") or "STOP").strip()[:20]
    payload["next_action_reason"] = str(decision.get("reason") or "").strip()[:220]
    payload["project_dir"] = str(project_dir)
    payload["updated_at"] = _now()
    payload["last_status"] = _safe_status(str(payload.get("last_status") or "UNKNOWN"))
    payload["agent_state"] = _safe_agent_state(str(payload.get("agent_state") or "IDLE"))
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
    payload["environment_issue"] = str(payload.get("environment_issue") or "env-readiness-ok").strip()[:80]
    payload["environment_issue_reason"] = str(payload.get("environment_issue_reason") or "").strip()[:220]
    bootstrap_actions = payload.get("last_bootstrap_actions")
    if not isinstance(bootstrap_actions, list):
        payload["last_bootstrap_actions"] = []
    else:
        payload["last_bootstrap_actions"] = [str(x)[:160] for x in bootstrap_actions[:5]]
    payload["derived_task_label"] = str(payload.get("derived_task_label") or "").strip()[:120]
    payload["project_type"] = str(payload.get("project_type") or "unknown").strip()[:40] or "unknown"
    payload["selected_template"] = str(payload.get("selected_template") or "unknown").strip()[:60] or "unknown"
    payload["effective_template"] = str(payload.get("effective_template") or "unknown").strip()[:60] or "unknown"
    payload["template_fallback_reason"] = str(payload.get("template_fallback_reason") or "").strip()[:220]
    payload["next_action"] = str(payload.get("next_action") or "STOP").strip()[:20]
    payload["next_action_reason"] = str(payload.get("next_action_reason") or "").strip()[:220]
    payload["github_repo_url"] = str(payload.get("github_repo_url") or "").strip()[:300]
    payload["deploy_target"] = str(payload.get("deploy_target") or "").strip()[:40]
    payload["deploy_kind"] = str(payload.get("deploy_kind") or "").strip()[:20]
    payload["last_deploy_status"] = _safe_optional_status(str(payload.get("last_deploy_status") or ""))
    payload["deploy_url"] = str(payload.get("deploy_url") or "").strip()[:300]
    payload["last_deploy_detail"] = str(payload.get("last_deploy_detail") or "").strip()[:220]
    payload["backend_deploy_url"] = str(payload.get("backend_deploy_url") or "").strip()[:300]
    payload["backend_deploy_status"] = _safe_service_deploy_status(str(payload.get("backend_deploy_status") or ""))
    payload["backend_deploy_detail"] = str(payload.get("backend_deploy_detail") or "").strip()[:220]
    payload["frontend_deploy_url"] = str(payload.get("frontend_deploy_url") or "").strip()[:300]
    payload["frontend_deploy_status"] = _safe_service_deploy_status(str(payload.get("frontend_deploy_status") or ""))
    payload["frontend_deploy_detail"] = str(payload.get("frontend_deploy_detail") or "").strip()[:220]
    payload["backend_smoke_url"] = str(payload.get("backend_smoke_url") or "").strip()[:300]
    payload["backend_smoke_status"] = _safe_service_deploy_status(str(payload.get("backend_smoke_status") or ""))
    payload["backend_smoke_detail"] = str(payload.get("backend_smoke_detail") or "").strip()[:220]
    payload["frontend_smoke_url"] = str(payload.get("frontend_smoke_url") or "").strip()[:300]
    payload["frontend_smoke_status"] = _safe_service_deploy_status(str(payload.get("frontend_smoke_status") or ""))
    payload["frontend_smoke_detail"] = str(payload.get("frontend_smoke_detail") or "").strip()[:220]
    payload["healthcheck_url"] = str(payload.get("healthcheck_url") or "").strip()[:300]
    payload["healthcheck_status"] = _safe_healthcheck_status(str(payload.get("healthcheck_status") or ""))
    payload["healthcheck_detail"] = str(payload.get("healthcheck_detail") or "").strip()[:220]
    payload["current_step_key"] = str(payload.get("current_step_key") or "").strip()[:40]
    payload["current_step_label"] = str(payload.get("current_step_label") or "").strip()[:120]
    payload["current_step_status"] = str(payload.get("current_step_status") or "").strip()[:20]
    payload["current_step_detail"] = str(payload.get("current_step_detail") or "").strip()[:220]
    payload["last_progress_at"] = str(payload.get("last_progress_at") or "").strip()[:40]
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


def load_agent_state(project_dir: Path) -> str:
    payload = ensure_state(project_dir.expanduser().resolve())
    return _safe_agent_state(str(payload.get("agent_state") or "UNKNOWN"))


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
        warning_lines = result.get("warning_summary")
        if isinstance(warning_lines, list):
            for item in warning_lines:
                line = _sanitize_line(str(item), project_dir)
                if line and line not in out:
                    out.append(line)
    if out:
        return out[:max_items]
    run_logs = project_dir / ".archmind" / "run_logs"
    if run_logs.exists():
        summaries = sorted(run_logs.glob("run_*.summary.txt"), key=lambda p: p.stat().st_mtime, reverse=True)
        if summaries:
            lines = summaries[0].read_text(encoding="utf-8", errors="replace").splitlines()
            for line in lines:
                lower = line.lower()
                if (
                    "FAILED" in line
                    or "AssertionError" in line
                    or "failed" in line
                    or "warning" in lower
                ):
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
            if status == "WARNING":
                name = _normalize_step_name(str(step.get("name") or ""))
                if "frontend-lint" in name:
                    names.append("frontend-lint-warning")
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
                if frontend_status == "WARNING":
                    names.append("frontend-lint-warning")
    return sorted(set(names))


def _extract_failure_step_names_from_run_summary(payload: dict[str, Any]) -> list[str]:
    names: list[str] = []
    backend = payload.get("backend")
    frontend = payload.get("frontend")
    if isinstance(backend, dict) and str(backend.get("status") or "").upper() == "FAIL":
        names.append("backend-pytest")
    if isinstance(frontend, dict):
        frontend_status = str(frontend.get("status") or "").upper()
        if frontend_status == "FAIL":
            names.append("frontend-lint")
        if frontend_status == "WARNING":
            names.append("frontend-lint-warning")
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
    level = "WARNING" if all(name.endswith("-warning") for name in step_names) else "FAIL"
    return f"{'+'.join(sorted(step_names))}:{level}"


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
            "agent_state": _safe_agent_state(str(payload.get("agent_state") or "UNKNOWN")),
            "summary": _sanitize_line(summary, project_dir)[:160],
            "current_task_id": str(current_task_id or ""),
            "current_task_title": _sanitize_line(_task_title(project_dir, current_task_id) or "", project_dir),
            "failure_signature": normalized_signature[:220],
            "failure_class": normalized_class,
        },
    )
    write_state(project_dir, payload)
    return payload


def set_agent_state(
    project_dir: Path,
    agent_state: str,
    *,
    action: str = "",
    summary: str = "",
    record_history: bool = True,
) -> dict[str, Any]:
    project_dir = project_dir.expanduser().resolve()
    payload = ensure_state(project_dir)
    payload["agent_state"] = _safe_agent_state(agent_state)
    if action:
        payload["last_action"] = _sanitize_line(action, project_dir)
    if record_history:
        _append_history(
            payload,
            {
                "timestamp": _now(),
                "action": _sanitize_line(action or f"set agent state {agent_state}", project_dir),
                "status": _safe_status(str(payload.get("last_status") or "UNKNOWN")),
                "agent_state": _safe_agent_state(agent_state),
                "summary": _sanitize_line(summary or f"agent state -> {agent_state}", project_dir)[:160],
                "current_task_id": str(payload.get("current_task_id") or ""),
                "current_task_title": _sanitize_line(
                    _task_title(project_dir, _safe_int(payload.get("current_task_id"), 0))
                    if _safe_int(payload.get("current_task_id"), 0) > 0
                    else "",
                    project_dir,
                ),
                "failure_signature": str(payload.get("last_failure_signature") or "")[:220],
                "failure_class": str(payload.get("last_failure_class") or "")[:80],
            },
        )
    write_state(project_dir, payload)
    return payload


def set_progress_step(
    project_dir: Path,
    step_key: str,
    step_label: str,
    *,
    status: str = "RUNNING",
    detail: Optional[str] = None,
) -> dict[str, Any]:
    payload = ensure_state(project_dir.expanduser().resolve())
    payload["current_step_key"] = str(step_key or "").strip()
    payload["current_step_label"] = str(step_label or "").strip()
    payload["current_step_status"] = str(status or "RUNNING").strip().upper()
    payload["current_step_detail"] = str(detail or "").strip()
    payload["last_progress_at"] = _now_iso()
    write_state(project_dir, payload)
    return payload


def clear_progress_step(project_dir: Path) -> dict[str, Any]:
    payload = ensure_state(project_dir.expanduser().resolve())
    payload["current_step_key"] = ""
    payload["current_step_label"] = ""
    payload["current_step_status"] = ""
    payload["current_step_detail"] = ""
    payload["last_progress_at"] = _now_iso()
    write_state(project_dir, payload)
    return payload


def update_environment_readiness(
    project_dir: Path,
    *,
    issue: str,
    reason: str,
    bootstrap_actions: Optional[list[str]] = None,
) -> dict[str, Any]:
    project_dir = project_dir.expanduser().resolve()
    payload = ensure_state(project_dir)
    payload["environment_issue"] = str(issue or "unknown-environment-issue").strip()
    payload["environment_issue_reason"] = _sanitize_line(reason or "", project_dir)
    actions = [str(x).strip() for x in (bootstrap_actions or []) if str(x).strip()]
    payload["last_bootstrap_actions"] = actions[:5]
    if actions:
        _append_history(
            payload,
            {
                "timestamp": _now(),
                "action": "bootstrap environment readiness",
                "status": "SUCCESS",
                "agent_state": _safe_agent_state(str(payload.get("agent_state") or "UNKNOWN")),
                "summary": _sanitize_line("; ".join(actions), project_dir)[:160],
                "current_task_id": str(payload.get("current_task_id") or ""),
                "current_task_title": _sanitize_line(
                    _task_title(project_dir, _safe_int(payload.get("current_task_id"), 0))
                    if _safe_int(payload.get("current_task_id"), 0) > 0
                    else "",
                    project_dir,
                ),
                "failure_signature": str(payload.get("last_failure_signature") or "")[:220],
                "failure_class": str(payload.get("last_failure_class") or "")[:80],
            },
        )
    write_state(project_dir, payload)
    return payload


def update_after_run(project_dir: Path, action: str, run_status: str, summary: str) -> dict[str, Any]:
    failures = _collect_result_failures(project_dir, max_items=10)
    failure_signature = _collect_failure_signature(project_dir)
    failure_class = _collect_failure_class(project_dir, failure_signature)
    payload = update_state_event(
        project_dir,
        action,
        run_status,
        summary,
        increment_iterations=True,
        recent_failures=failures,
        failure_signature=failure_signature,
        failure_class=failure_class,
    )
    payload["agent_state"] = "NOT_DONE" if run_status in ("FAIL", "SKIP", "SUCCESS") else "UNKNOWN"
    write_state(project_dir, payload)
    return payload


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
    payload["agent_state"] = "NOT_DONE"
    write_state(project_dir, payload)
    return payload


def update_after_evaluation(project_dir: Path, evaluation_status: str, stuck_reason: str = "") -> dict[str, Any]:
    status = _safe_status(evaluation_status)
    payload = update_state_event(project_dir, "evaluate", status, f"evaluation status {status}")
    payload["agent_state"] = _agent_state_from_eval_status(status)
    payload["stuck"] = status == "STUCK"
    payload["stuck_reason"] = stuck_reason if status == "STUCK" else ""
    write_state(project_dir, payload)
    return payload


def update_after_deploy(
    project_dir: Path,
    result: dict[str, Any],
    *,
    action: str = "archmind deploy",
) -> dict[str, Any]:
    project_dir = project_dir.expanduser().resolve()
    payload = ensure_state(project_dir)

    target = str(result.get("target") or "").strip()
    kind = str(result.get("kind") or "").strip().lower() or "backend"
    status = _safe_optional_status(str(result.get("status") or ""))
    detail = _sanitize_line(str(result.get("detail") or ""), project_dir)
    raw_url = result.get("url")
    deploy_url = str(raw_url).strip() if raw_url is not None else ""
    raw_health_url = result.get("healthcheck_url")
    healthcheck_url = str(raw_health_url).strip() if raw_health_url is not None else ""
    healthcheck_status = _safe_healthcheck_status(str(result.get("healthcheck_status") or ""))
    healthcheck_detail = _sanitize_line(str(result.get("healthcheck_detail") or ""), project_dir)
    backend_smoke_url = str(result.get("backend_smoke_url") or "").strip()
    backend_smoke_status = _safe_service_deploy_status(str(result.get("backend_smoke_status") or ""))
    backend_smoke_detail = _sanitize_line(str(result.get("backend_smoke_detail") or ""), project_dir)
    frontend_smoke_url = str(result.get("frontend_smoke_url") or "").strip()
    frontend_smoke_status = _safe_service_deploy_status(str(result.get("frontend_smoke_status") or ""))
    frontend_smoke_detail = _sanitize_line(str(result.get("frontend_smoke_detail") or ""), project_dir)

    payload["deploy_target"] = target[:40]
    payload["deploy_kind"] = kind[:20]
    payload["last_deploy_status"] = status
    payload["deploy_url"] = deploy_url[:300]
    payload["last_deploy_detail"] = detail[:220]
    payload["healthcheck_url"] = healthcheck_url[:300]
    payload["healthcheck_status"] = healthcheck_status
    payload["healthcheck_detail"] = healthcheck_detail[:220]
    payload["backend_smoke_url"] = backend_smoke_url[:300]
    payload["backend_smoke_status"] = backend_smoke_status
    payload["backend_smoke_detail"] = backend_smoke_detail[:220]
    payload["frontend_smoke_url"] = frontend_smoke_url[:300]
    payload["frontend_smoke_status"] = frontend_smoke_status
    payload["frontend_smoke_detail"] = frontend_smoke_detail[:220]
    backend = result.get("backend")
    if isinstance(backend, dict):
        payload["backend_deploy_url"] = str(backend.get("url") or "").strip()[:300]
        payload["backend_deploy_status"] = _safe_service_deploy_status(str(backend.get("status") or ""))
        payload["backend_deploy_detail"] = _sanitize_line(str(backend.get("detail") or ""), project_dir)[:220]
    elif kind == "backend":
        payload["backend_deploy_url"] = deploy_url[:300]
        payload["backend_deploy_status"] = _safe_service_deploy_status(status or "SUCCESS")
        payload["backend_deploy_detail"] = detail[:220]

    frontend = result.get("frontend")
    if isinstance(frontend, dict):
        payload["frontend_deploy_url"] = str(frontend.get("url") or "").strip()[:300]
        payload["frontend_deploy_status"] = _safe_service_deploy_status(str(frontend.get("status") or ""))
        payload["frontend_deploy_detail"] = _sanitize_line(str(frontend.get("detail") or ""), project_dir)[:220]
    elif kind == "frontend":
        payload["frontend_deploy_url"] = deploy_url[:300]
        payload["frontend_deploy_status"] = _safe_service_deploy_status(status or "SUCCESS")
        payload["frontend_deploy_detail"] = detail[:220]

    payload["last_action"] = _sanitize_line(action, project_dir)

    _append_history(
        payload,
        {
            "timestamp": _now(),
            "action": _sanitize_line(action, project_dir),
            "status": status or "UNKNOWN",
            "agent_state": _safe_agent_state(str(payload.get("agent_state") or "UNKNOWN")),
            "summary": _sanitize_line(f"deploy {target} {status or 'UNKNOWN'}", project_dir)[:160],
            "current_task_id": str(payload.get("current_task_id") or ""),
            "current_task_title": _sanitize_line(_task_title(project_dir, payload.get("current_task_id")) or "", project_dir),
            "failure_signature": "",
            "failure_class": "",
        },
    )
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
    agent_state = payload.get("agent_state", "UNKNOWN")
    iterations = int(payload.get("iterations") or 0)
    fix_attempts = int(payload.get("fix_attempts") or 0)
    current_task_id = payload.get("current_task_id")
    derived_label = str(payload.get("derived_task_label") or "").strip()
    task_title = _task_title(project_dir, int(current_task_id)) if current_task_id else None
    task_title = derived_label or task_title
    current_line = task_title or "none"

    project_status = "NOT_DONE"
    evaluation_payload = _load_json(project_dir / ".archmind" / "evaluation.json") or {}
    evaluation_status = str(evaluation_payload.get("status") or "").upper()
    if evaluation_status in ("DONE", "STUCK", "BLOCKED", "NOT_DONE"):
        project_status = evaluation_status
    elif bool(payload.get("stuck")):
        project_status = "STUCK"
    elif str(status).upper() in ("SUCCESS", "DONE"):
        project_status = "DONE"

    def _is_failure_noise(text: str) -> bool:
        line = str(text or "").strip()
        if not line:
            return True
        lower = line.lower()
        if lower.startswith("traceback"):
            return True
        if "========================" in line:
            return True
        if lower in ("base", "cancel"):
            return True
        if lower.startswith("command:"):
            return True
        if lower.startswith("cwd:"):
            return True
        if lower.startswith("duration"):
            return True
        if lower.startswith("timestamp:"):
            return True
        if "how would you like to configure eslint" in lower:
            return True
        if "need to disable some eslint rules" in lower:
            return True
        if "learn more here: https://nextjs.org/docs/app/api-reference/config/eslint#disabling-rules" in lower:
            return True
        if "next.js eslint plugin" in lower:
            return True
        if "strict (recommended)" in lower:
            return True
        if "stacktrace" in lower and "header" in lower:
            return True
        return False

    result_payload = _load_json(project_dir / ".archmind" / "result.json") or {}
    decision = decide_next_action(payload, evaluation_payload, result_payload)
    next_action = str(decision.get("action") or payload.get("next_action") or "STOP")
    next_reason = str(decision.get("reason") or payload.get("next_action_reason") or "")
    env_issue = str(payload.get("environment_issue") or "env-readiness-ok")
    env_reason = str(payload.get("environment_issue_reason") or "").strip()
    progress_label = str(payload.get("current_step_label") or "").strip()
    progress_status = str(payload.get("current_step_status") or "").strip()
    progress_detail = str(payload.get("current_step_detail") or "").strip()
    progress_text = progress_label or "(none)"
    if progress_detail:
        progress_text = f"{progress_text} ({progress_detail})"
    if progress_status:
        progress_text = f"{progress_text} [{progress_status}]"
    bootstrap_actions = payload.get("last_bootstrap_actions")
    if not isinstance(bootstrap_actions, list):
        bootstrap_actions = []

    lines = [
        f"Project status: {project_status}",
        f"Project type: {payload.get('project_type') or 'unknown'}",
        f"Selected template: {payload.get('selected_template') or 'unknown'}",
        f"Effective template: {payload.get('effective_template') or 'unknown'}",
        f"Template fallback: {payload.get('template_fallback_reason') or '(none)'}",
        f"Agent state: {agent_state}",
        f"Last status: {status}",
        f"Iterations: {iterations}",
        f"Fix attempts: {fix_attempts}",
        f"Current task: {current_line}",
        f"Failure class: {payload.get('last_failure_class') or 'unknown'}",
        f"Environment issue: {env_issue}",
        f"Environment reason: {env_reason or '(none)'}",
        f"GitHub repo: {payload.get('github_repo_url') or '(none)'}",
        f"Deploy target: {payload.get('deploy_target') or '(none)'}",
        f"Deploy kind: {payload.get('deploy_kind') or '(none)'}",
        f"Deploy status: {payload.get('last_deploy_status') or '(none)'}",
        f"Deploy URL: {payload.get('deploy_url') or '(none)'}",
        f"Deploy detail: {payload.get('last_deploy_detail') or '(none)'}",
        f"Backend deploy status: {payload.get('backend_deploy_status') or '(none)'}",
        f"Backend deploy URL: {payload.get('backend_deploy_url') or '(none)'}",
        f"Frontend deploy status: {payload.get('frontend_deploy_status') or '(none)'}",
        f"Frontend deploy URL: {payload.get('frontend_deploy_url') or '(none)'}",
        f"Backend smoke status: {payload.get('backend_smoke_status') or '(none)'}",
        f"Backend smoke URL: {payload.get('backend_smoke_url') or '(none)'}",
        f"Frontend smoke status: {payload.get('frontend_smoke_status') or '(none)'}",
        f"Frontend smoke URL: {payload.get('frontend_smoke_url') or '(none)'}",
        f"Health URL: {payload.get('healthcheck_url') or '(none)'}",
        f"Health status: {payload.get('healthcheck_status') or '(none)'}",
        f"Health detail: {payload.get('healthcheck_detail') or '(none)'}",
        f"Progress: {progress_text}",
        f"Next action: {next_action}",
        f"Reason: {next_reason or '(none)'}",
        "Bootstrap actions:",
    ]
    if bootstrap_actions:
        for action in bootstrap_actions[:3]:
            lines.append(f"- {action}")
    else:
        lines.append("- (none)")
    lines.extend(
        [
        "Recent failures:",
        ]
    )
    failures = payload.get("recent_failures") or []
    if failures:
        shown = 0
        for line in failures:
            if _is_failure_noise(str(line)):
                continue
            lines.append(f"- {line}")
            shown += 1
            if shown >= 3:
                break
        if shown == 0:
            lines.append("- (none)")
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
    evaluation_payload = _load_json(project_dir / ".archmind" / "evaluation.json") or {}
    result_payload = _load_json(project_dir / ".archmind" / "result.json") or {}
    decision = decide_next_action(payload, evaluation_payload, result_payload)
    lines = [
        f"- agent_state: {payload.get('agent_state', 'UNKNOWN')}",
        f"- last_status: {payload.get('last_status', 'UNKNOWN')}",
        f"- project_type: {payload.get('project_type', 'unknown')}",
        f"- selected_template: {payload.get('selected_template', 'unknown')}",
        f"- effective_template: {payload.get('effective_template', 'unknown')}",
        f"- template_fallback_reason: {payload.get('template_fallback_reason', '')}",
        f"- fix_attempts: {payload.get('fix_attempts', 0)}",
        f"- current_task: {current_line}",
        f"- failure_class: {payload.get('last_failure_class', 'unknown')}",
        f"- environment_issue: {payload.get('environment_issue', 'env-readiness-ok')}",
        f"- next_action: {decision.get('action', payload.get('next_action', 'STOP'))}",
        f"- next_action_reason: {decision.get('reason', payload.get('next_action_reason', ''))}",
        f"- github_repo_url: {payload.get('github_repo_url', '')}",
        f"- deploy_target: {payload.get('deploy_target', '')}",
        f"- deploy_kind: {payload.get('deploy_kind', '')}",
        f"- last_deploy_status: {payload.get('last_deploy_status', '')}",
        f"- deploy_url: {payload.get('deploy_url', '')}",
        f"- last_deploy_detail: {payload.get('last_deploy_detail', '')}",
        f"- backend_deploy_status: {payload.get('backend_deploy_status', '')}",
        f"- backend_deploy_url: {payload.get('backend_deploy_url', '')}",
        f"- backend_deploy_detail: {payload.get('backend_deploy_detail', '')}",
        f"- frontend_deploy_status: {payload.get('frontend_deploy_status', '')}",
        f"- frontend_deploy_url: {payload.get('frontend_deploy_url', '')}",
        f"- frontend_deploy_detail: {payload.get('frontend_deploy_detail', '')}",
        f"- backend_smoke_status: {payload.get('backend_smoke_status', '')}",
        f"- backend_smoke_url: {payload.get('backend_smoke_url', '')}",
        f"- backend_smoke_detail: {payload.get('backend_smoke_detail', '')}",
        f"- frontend_smoke_status: {payload.get('frontend_smoke_status', '')}",
        f"- frontend_smoke_url: {payload.get('frontend_smoke_url', '')}",
        f"- frontend_smoke_detail: {payload.get('frontend_smoke_detail', '')}",
        f"- healthcheck_url: {payload.get('healthcheck_url', '')}",
        f"- healthcheck_status: {payload.get('healthcheck_status', '')}",
        f"- healthcheck_detail: {payload.get('healthcheck_detail', '')}",
        "- recent_failures:",
    ]
    if failures:
        for line in failures[:3]:
            lines.append(f"  - {line}")
    else:
        lines.append("  - (none)")
    return lines[:10]
