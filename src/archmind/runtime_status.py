from __future__ import annotations

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

    return {
        "status": status,
        "pid": pid,
        "url": current_url,
        "last_known_url": last_known_url,
    }


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
