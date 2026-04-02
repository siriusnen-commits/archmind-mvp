from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def execution_history_path(project_dir: Path) -> Path:
    return Path(project_dir) / ".archmind" / "execution_history.jsonl"


def append_execution_event(
    project_dir: Path,
    *,
    project_name: str,
    source: str,
    command: str,
    status: str,
    message: str,
    run_id: str | None = None,
    step_no: int | None = None,
    stop_reason: str | None = None,
    timestamp: str | None = None,
    verification: dict[str, Any] | None = None,
) -> bool:
    event: dict[str, Any] = {
        "timestamp": str(timestamp or datetime.now(timezone.utc).isoformat()),
        "project_name": str(project_name or "").strip(),
        "source": str(source or "").strip(),
        "command": str(command or "").strip(),
        "status": str(status or "").strip(),
        "message": str(message or "").strip(),
    }
    if run_id:
        event["run_id"] = str(run_id)
    if step_no is not None:
        event["step_no"] = int(step_no)
    if stop_reason:
        event["stop_reason"] = str(stop_reason)
    if isinstance(verification, dict) and verification:
        event["verification"] = verification

    try:
        history_file = execution_history_path(project_dir)
        history_file.parent.mkdir(parents=True, exist_ok=True)
        with history_file.open("a", encoding="utf-8") as f:
            f.write(json.dumps(event, ensure_ascii=False) + "\n")
        return True
    except Exception:
        # Best-effort logging only; never break execution flow.
        return False


def load_recent_execution_events(project_dir: Path, limit: int = 20) -> list[dict[str, Any]]:
    history_file = execution_history_path(project_dir)
    if not history_file.exists():
        return []
    try:
        lines = history_file.read_text(encoding="utf-8").splitlines()
    except Exception:
        return []

    events: list[dict[str, Any]] = []
    for raw in lines:
        line = str(raw or "").strip()
        if not line:
            continue
        try:
            item = json.loads(line)
        except Exception:
            continue
        if isinstance(item, dict):
            events.append(item)
    if limit <= 0:
        return []
    return events[-int(limit):]
