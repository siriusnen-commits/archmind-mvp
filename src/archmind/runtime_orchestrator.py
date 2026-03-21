from __future__ import annotations

from pathlib import Path
from typing import Any
from datetime import datetime
import socket

from archmind.deploy import (
    deploy_frontend_local,
    detect_deploy_kind,
    find_free_port,
    get_local_runtime_status,
    run_backend_local_with_health,
    verify_frontend_smoke,
)
from archmind.frontend_runtime import detect_frontend_runtime_entry, frontend_runtime_port_hint


def _service_payload(
    *,
    status: str,
    pid: int | None = None,
    port: int | None = None,
    url: str = "",
    log_path: str = "",
    detail: str = "",
    health: str = "",
    framework: str = "",
) -> dict[str, Any]:
    return {
        "status": str(status or "").strip().upper() or "UNKNOWN",
        "pid": pid,
        "port": port,
        "url": str(url or "").strip(),
        "log_path": str(log_path or "").strip(),
        "detail": str(detail or "").strip(),
        "health": str(health or "").strip().upper(),
        "framework": str(framework or "").strip(),
        "last_checked_at": datetime.now().isoformat(timespec="seconds"),
    }


def _safe_port(value: Any) -> int | None:
    try:
        port = int(value)
    except Exception:
        return None
    return port if port > 0 else None


def _is_port_available(port: int) -> bool:
    if int(port) <= 0:
        return False
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        try:
            sock.bind(("127.0.0.1", int(port)))
        except OSError:
            return False
    return True


def _pick_frontend_port(
    *,
    frontend_entry: dict[str, Any],
    before_frontend: dict[str, Any],
    backend_port: int | None,
) -> int:
    candidates: list[int] = []
    previous_port = _safe_port(before_frontend.get("port")) or frontend_runtime_port_hint(str(before_frontend.get("url") or ""))
    detected_port = _safe_port(frontend_entry.get("frontend_port"))
    if previous_port is not None:
        candidates.append(previous_port)
    if detected_port is not None and detected_port not in candidates:
        candidates.append(detected_port)

    disallowed = {int(backend_port)} if backend_port is not None else set()
    for candidate in candidates:
        if candidate in disallowed:
            continue
        if _is_port_available(candidate):
            return candidate

    attempts = 0
    fallback = find_free_port()
    while (fallback in disallowed or not _is_port_available(fallback)) and attempts < 20:
        fallback = find_free_port()
        attempts += 1
    return int(fallback)


def run_all_local_services(project_dir: Path) -> dict[str, Any]:
    root = project_dir.expanduser().resolve()
    kind = detect_deploy_kind(root)
    has_backend = kind in {"backend", "fullstack"}
    has_frontend = kind in {"frontend", "fullstack"}
    runtime_before = get_local_runtime_status(root)
    before_backend = runtime_before.get("backend") if isinstance(runtime_before.get("backend"), dict) else {}
    before_frontend = runtime_before.get("frontend") if isinstance(runtime_before.get("frontend"), dict) else {}

    backend_service = _service_payload(status="ABSENT", detail="backend not detected")
    frontend_service = _service_payload(status="ABSENT", detail="frontend not detected")
    backend_result: dict[str, Any] = {}
    frontend_smoke: dict[str, Any] = {"status": "SKIPPED", "url": "", "detail": "frontend not started"}
    failure_class = ""

    if has_backend:
        if str(before_backend.get("status") or "").strip().upper() == "RUNNING":
            backend_service = _service_payload(
                status="RUNNING",
                pid=before_backend.get("pid"),
                port=frontend_runtime_port_hint(str(before_backend.get("url") or "")),
                url=str(before_backend.get("url") or ""),
                detail="already running",
                health="SUCCESS",
                framework="fastapi",
            )
        else:
            backend_result = run_backend_local_with_health(root)
            backend_ok = str(backend_result.get("status") or "").strip().upper() == "SUCCESS"
            backend_url = str(backend_result.get("url") or "").strip()
            backend_service = _service_payload(
                status="RUNNING" if backend_ok else "FAIL",
                pid=backend_result.get("backend_pid"),
                port=backend_result.get("backend_port"),
                url=backend_url,
                log_path=str(backend_result.get("backend_log_path") or ""),
                detail=str(backend_result.get("detail") or ""),
                health=str(backend_result.get("backend_smoke_status") or backend_result.get("healthcheck_status") or ""),
                framework="fastapi",
            )
            if not backend_ok:
                failure_class = str(backend_result.get("failure_class") or "").strip() or "runtime-execution-error"

    backend_url_for_frontend = str(backend_service.get("url") or "").strip()
    if not backend_url_for_frontend:
        backend_url_for_frontend = str(before_backend.get("url") or "").strip()

    if has_frontend:
        if str(before_frontend.get("status") or "").strip().upper() == "RUNNING":
            frontend_service = _service_payload(
                status="RUNNING",
                pid=before_frontend.get("pid"),
                port=frontend_runtime_port_hint(str(before_frontend.get("url") or "")),
                url=str(before_frontend.get("url") or ""),
                detail="already running",
                health="SUCCESS",
                framework="nextjs",
            )
            frontend_smoke = {"status": "SUCCESS", "url": str(before_frontend.get("url") or ""), "detail": "frontend already running"}
        else:
            frontend_entry = detect_frontend_runtime_entry(root)
            if not bool(frontend_entry.get("ok")):
                frontend_service = _service_payload(
                    status="FAIL",
                    detail=str(frontend_entry.get("failure_reason") or "frontend runtime detection failed"),
                    framework=str(frontend_entry.get("framework") or "").strip(),
                )
                if not failure_class:
                    failure_class = str(frontend_entry.get("failure_class") or "").strip() or "runtime-execution-error"
            else:
                frontend_port = _pick_frontend_port(
                    frontend_entry=frontend_entry,
                    before_frontend=before_frontend,
                    backend_port=_safe_port(backend_service.get("port")),
                )
                frontend_result = deploy_frontend_local(
                    root,
                    port=int(frontend_port),
                    backend_base_url=backend_url_for_frontend or None,
                )
                frontend_ok = str(frontend_result.get("status") or "").strip().upper() == "SUCCESS"
                frontend_url = str(frontend_result.get("url") or "").strip()
                frontend_service = _service_payload(
                    status="RUNNING" if frontend_ok else "FAIL",
                    pid=frontend_result.get("pid"),
                    port=frontend_runtime_port_hint(frontend_url) or int(frontend_port),
                    url=frontend_url,
                    log_path=str(root / ".archmind" / "frontend.log"),
                    detail=str(frontend_result.get("detail") or ""),
                    framework=str(frontend_result.get("framework") or frontend_entry.get("framework") or "").strip(),
                )
                frontend_smoke = verify_frontend_smoke(frontend_url) if frontend_ok else {
                    "status": "SKIPPED",
                    "url": frontend_url,
                    "detail": "frontend deploy failed",
                }
                if frontend_ok:
                    frontend_service["health"] = str(frontend_smoke.get("status") or "").strip().upper()
                if not frontend_ok and not failure_class:
                    failure_class = "runtime-execution-error"

    backend_status = str(backend_service.get("status") or "").strip().upper()
    frontend_status = str(frontend_service.get("status") or "").strip().upper()
    any_fail = backend_status == "FAIL" or frontend_status == "FAIL"
    started_any = backend_status == "RUNNING" or frontend_status == "RUNNING"
    top_status = "FAIL" if any_fail else ("SUCCESS" if started_any else "SKIP")
    top_detail = "services started" if top_status == "SUCCESS" else "service start failed"

    result: dict[str, Any] = {
        "ok": top_status == "SUCCESS",
        "target": "local",
        "mode": "real",
        "kind": kind,
        "status": top_status,
        "url": str(backend_service.get("url") or "") or str(frontend_service.get("url") or ""),
        "backend_url": str(backend_service.get("url") or ""),
        "frontend_url": str(frontend_service.get("url") or ""),
        "detail": top_detail,
        "failure_class": failure_class if top_status != "SUCCESS" else "",
        "services": {
            "backend": backend_service,
            "frontend": frontend_service,
        },
        "backend_status": backend_status,
        "backend_pid": backend_service.get("pid"),
        "backend_port": backend_service.get("port"),
        "backend_log_path": backend_service.get("log_path"),
        "frontend_status": frontend_status,
        "frontend_pid": frontend_service.get("pid"),
        "frontend_port": frontend_service.get("port"),
        "frontend_log_path": frontend_service.get("log_path"),
        "backend_smoke_url": str(backend_result.get("backend_smoke_url") or backend_result.get("healthcheck_url") or ""),
        "backend_smoke_status": str(backend_result.get("backend_smoke_status") or backend_result.get("healthcheck_status") or "SKIPPED"),
        "backend_smoke_detail": str(backend_result.get("backend_smoke_detail") or backend_result.get("healthcheck_detail") or ""),
        "frontend_smoke_url": str(frontend_smoke.get("url") or ""),
        "frontend_smoke_status": str(frontend_smoke.get("status") or "SKIPPED"),
        "frontend_smoke_detail": str(frontend_smoke.get("detail") or ""),
        "backend_entry": str(backend_result.get("backend_entry") or ""),
        "backend_run_mode": str(backend_result.get("backend_run_mode") or ""),
        "run_cwd": str(backend_result.get("run_cwd") or ""),
        "run_command": str(backend_result.get("run_command") or ""),
        "preflight": backend_result.get("preflight") if isinstance(backend_result.get("preflight"), dict) else {},
    }
    return result
