from __future__ import annotations

import re
from typing import Any


def _normalize_status(value: Any) -> str:
    raw = str(value or "").strip().upper()
    if raw == "RUNNING":
        return "RUNNING"
    if raw in {"FAIL", "FAILED", "ERROR"}:
        return "FAIL"
    if raw in {"WARNING"}:
        return "WARNING"
    if raw in {"ABSENT"}:
        return "ABSENT"
    if raw in {"STOPPED", "NOT RUNNING", "IDLE", "SKIPPED", "SUCCESS"}:
        return "NOT RUNNING"
    return "NOT RUNNING"


def _runtime_urls_from_state(component: str, state_payload: dict[str, Any]) -> list[str]:
    runtime_block = state_payload.get("runtime") if isinstance(state_payload.get("runtime"), dict) else {}
    services = runtime_block.get("services") if isinstance(runtime_block.get("services"), dict) else {}
    service = services.get(component) if isinstance(services.get(component), dict) else {}
    deploy = state_payload.get("deploy") if isinstance(state_payload.get("deploy"), dict) else {}

    if component == "backend":
        candidates = [
            service.get("url"),
            runtime_block.get("backend_url"),
            deploy.get("backend_url"),
            state_payload.get("backend_deploy_url"),
            state_payload.get("deploy_url"),
        ]
    else:
        candidates = [
            service.get("url"),
            runtime_block.get("frontend_url"),
            deploy.get("frontend_url"),
            state_payload.get("frontend_deploy_url"),
        ]

    out: list[str] = []
    seen: set[str] = set()
    for candidate in candidates:
        url = str(candidate or "").strip()
        if not url or url in seen:
            continue
        seen.add(url)
        out.append(url)
    return out


def _runtime_pid_from_state(component: str, state_payload: dict[str, Any]) -> int | None:
    runtime_block = state_payload.get("runtime") if isinstance(state_payload.get("runtime"), dict) else {}
    services = runtime_block.get("services") if isinstance(runtime_block.get("services"), dict) else {}
    service = services.get(component) if isinstance(services.get(component), dict) else {}
    key = f"{component}_pid"
    for raw in (service.get("pid"), runtime_block.get(key), state_payload.get(key)):
        try:
            pid = int(raw)
        except Exception:
            continue
        if pid > 0:
            return pid
    return None


def _runtime_state_from_payload(component: str, runtime_payload: dict[str, Any], state_payload: dict[str, Any]) -> str:
    live = runtime_payload.get(component) if isinstance(runtime_payload.get(component), dict) else {}
    runtime_block = state_payload.get("runtime") if isinstance(state_payload.get("runtime"), dict) else {}
    services = runtime_block.get("services") if isinstance(runtime_block.get("services"), dict) else {}
    service = services.get(component) if isinstance(services.get(component), dict) else {}
    state_key = f"{component}_status"
    source = (
        live.get("status"),
        service.get("status"),
        runtime_block.get(state_key),
        state_payload.get(state_key),
    )
    for raw in source:
        if str(raw or "").strip():
            return _normalize_status(raw)
    return "NOT RUNNING"


def _runtime_component_snapshot(component: str, runtime_payload: dict[str, Any], state_payload: dict[str, Any]) -> dict[str, Any]:
    live = runtime_payload.get(component) if isinstance(runtime_payload.get(component), dict) else {}
    status = _runtime_state_from_payload(component, runtime_payload, state_payload)

    live_url = str(live.get("url") or "").strip()
    state_urls = _runtime_urls_from_state(component, state_payload)
    last_known_url = live_url or (state_urls[0] if state_urls else "")
    current_url = last_known_url if status == "RUNNING" else ""

    pid = None
    raw_live_pid = live.get("pid")
    try:
        candidate_pid = int(raw_live_pid)
    except Exception:
        candidate_pid = None
    if candidate_pid and candidate_pid > 0:
        pid = candidate_pid
    else:
        pid = _runtime_pid_from_state(component, state_payload)

    reason, reason_detail = _runtime_reason_snapshot(component, status, runtime_payload, state_payload)

    return {
        "status": status,
        "pid": pid,
        "url": current_url,
        "last_known_url": last_known_url,
        "reason": reason,
        "reason_detail": reason_detail,
    }


def _compact_detail(text: str, max_len: int = 140) -> str:
    cleaned = " ".join(str(text or "").strip().split())
    if not cleaned:
        return ""
    return cleaned[: max_len - 1] + "..." if len(cleaned) > max_len else cleaned


def _likely_success_detail(text: str) -> bool:
    lowered = str(text or "").strip().lower()
    if not lowered:
        return False
    if any(token in lowered for token in ("fail", "error", "unable", "exception", "timeout")):
        return False
    return any(token in lowered for token in ("started", "completed", "success", "already running"))


def _reason_from_failure_signals(component: str, detail: str, failure_class: str) -> str:
    lowered = f"{failure_class}\n{detail}".lower()
    if "restart" in lowered:
        return "restart failed"
    if any(token in lowered for token in ("address already in use", "port in use", "eaddrinuse", "port conflict")):
        return "port conflict"
    if component == "frontend" and any(
        token in lowered
        for token in ("build failed", "vite build", "tsc", "compile", "compilation", "frontend deploy failed", "lint failed")
    ):
        return "build failed"
    if any(token in lowered for token in ("not started", "not detected", "not deployed", "missing entrypoint")):
        return "not started"
    if any(token in lowered for token in ("stopped", "terminated", "killed")):
        return "stopped"
    if any(token in lowered for token in ("runtime-execution-error", "health request failed", "health check failed", "startup failed")):
        return "startup failed"
    if failure_class:
        if failure_class == "runtime-entrypoint-error":
            return "startup failed"
        return "unknown failure"
    return "unknown failure"


def _runtime_reason_snapshot(
    component: str,
    status: str,
    runtime_payload: dict[str, Any],
    state_payload: dict[str, Any],
) -> tuple[str, str]:
    if status == "RUNNING":
        return "", ""

    runtime_block = state_payload.get("runtime") if isinstance(state_payload.get("runtime"), dict) else {}
    services_state = runtime_block.get("services") if isinstance(runtime_block.get("services"), dict) else {}
    service_state = services_state.get(component) if isinstance(services_state.get(component), dict) else {}
    service_live = runtime_payload.get("services") if isinstance(runtime_payload.get("services"), dict) else {}
    service_live_component = service_live.get(component) if isinstance(service_live.get(component), dict) else {}
    live_component = runtime_payload.get(component) if isinstance(runtime_payload.get(component), dict) else {}

    failure_class = str(
        live_component.get("failure_class")
        or runtime_payload.get("failure_class")
        or runtime_block.get("failure_class")
        or state_payload.get("runtime_failure_class")
        or state_payload.get("last_failure_class")
        or ""
    ).strip()

    raw_details = [
        str(live_component.get("detail") or "").strip(),
        str(service_live_component.get("detail") or "").strip(),
        str(runtime_payload.get("detail") or "").strip(),
        str(service_state.get("detail") or "").strip(),
        str(runtime_block.get("detail") or "").strip(),
    ]
    detail = ""
    for item in raw_details:
        if not item:
            continue
        detail = item
        break

    # Avoid presenting stale "started" history as current failure reason.
    if detail and _likely_success_detail(detail):
        detail = ""

    normalized_status = str(status or "").strip().upper()
    if normalized_status in {"NOT RUNNING", "ABSENT"} and not detail and not failure_class:
        return "not started", ""
    if normalized_status == "WARNING" and not detail and not failure_class:
        return "unknown failure", ""
    if normalized_status == "FAIL" or detail or failure_class:
        reason = _reason_from_failure_signals(component, detail, failure_class)
        detail_compact = _compact_detail(detail)
        if detail_compact and not re.search(re.escape(reason), detail_compact, flags=re.IGNORECASE):
            return reason, detail_compact
        return reason, ""
    if normalized_status == "STOPPED":
        return "stopped", ""
    return "", ""


def build_runtime_snapshot(runtime_payload: dict[str, Any] | None, state_payload: dict[str, Any] | None = None) -> dict[str, Any]:
    runtime = runtime_payload if isinstance(runtime_payload, dict) else {}
    state = state_payload if isinstance(state_payload, dict) else {}

    backend = _runtime_component_snapshot("backend", runtime, state)
    frontend = _runtime_component_snapshot("frontend", runtime, state)

    if backend.get("status") == "RUNNING" or frontend.get("status") == "RUNNING":
        overall = "RUNNING"
    elif backend.get("status") in {"FAIL", "WARNING"} or frontend.get("status") in {"FAIL", "WARNING"}:
        overall = "FAIL"
    else:
        overall = "STOPPED"

    return {
        "status": overall,
        "backend": backend,
        "frontend": frontend,
    }
