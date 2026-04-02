from __future__ import annotations

from pathlib import Path
from typing import Any

from archmind.deploy import get_local_runtime_status
from archmind.runtime_status import build_runtime_snapshot


def verify_runtime_restart(project_dir: Path, runtime_recovery: dict[str, Any] | None) -> tuple[bool, str, str]:
    recovery = runtime_recovery if isinstance(runtime_recovery, dict) else {}
    attempted = bool(recovery.get("attempted"))
    failed = bool(recovery.get("failed"))
    if not attempted:
        return False, "runtime restart was not attempted", "missing_restart"
    if failed:
        return False, str(recovery.get("reason") or "runtime restart failed").strip() or "runtime restart failed", "restart_failed"

    try:
        runtime_payload = get_local_runtime_status(project_dir)
        snapshot = build_runtime_snapshot(runtime_payload if isinstance(runtime_payload, dict) else {}, {})
        backend = snapshot.get("backend") if isinstance(snapshot.get("backend"), dict) else {}
        frontend = snapshot.get("frontend") if isinstance(snapshot.get("frontend"), dict) else {}
        backend_status = str(backend.get("status") or "").strip().upper()
        frontend_status = str(frontend.get("status") or "").strip().upper()
        if backend_status == "RUNNING" or frontend_status == "RUNNING":
            return True, "runtime restart reflected in running service status", "running"
        return True, "runtime restart attempted but service not running yet", "restarted_not_running"
    except Exception as exc:
        return True, f"runtime restart attempted (status read failed: {exc})", "restarted_status_unknown"
