from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from archmind.execution_history import append_execution_event

ADD_FIELD_RE = re.compile(r"^/add_field\s+(\S+)\s+([^:\s]+)\s*:\s*(\S+)\s*$")
ADD_API_RE = re.compile(r"^/add_api\s+(GET|POST|PUT|DELETE)\s+(\S+)\s*$", re.IGNORECASE)
ADD_PAGE_RE = re.compile(r"^/add_page\s+(.+)$")
ADD_IMPLEMENT_PAGE_RE = re.compile(r"^/implement_page\s+(.+)$")


def _resolve_project_dir(project_name: str) -> Path | None:
    key = str(project_name or "").strip()
    if not key:
        return None
    try:
        from archmind.project_query import find_project_by_name

        resolved = find_project_by_name(key)
        if resolved is not None:
            return resolved
    except Exception:
        pass

    # Telegram tests often resolve projects via patched _resolve_target_project without
    # ARCHMIND_PROJECTS_DIR wiring, so keep this fallback.
    try:
        from archmind.telegram_bot import _resolve_target_project

        candidate = _resolve_target_project()
        if candidate is not None and str(candidate.name or "").strip() == key:
            return candidate
    except Exception:
        pass
    return None


def _write_execution_event(
    project_dir: Path | None,
    *,
    project_name: str,
    source: str,
    command: str,
    status: str,
    message: str,
    run_id: str | None = None,
    step_no: int | None = None,
    stop_reason: str | None = None,
) -> None:
    if project_dir is None:
        return
    append_execution_event(
        project_dir,
        project_name=project_name,
        source=source,
        command=command,
        status=status,
        message=message,
        run_id=run_id,
        step_no=step_no,
        stop_reason=stop_reason,
    )


def execute_command(
    command: str,
    project_name: str,
    *,
    source: str = "manual-command",
    run_id: str | None = None,
    step_no: int | None = None,
) -> dict:
    normalized_command = str(command or "").strip()
    key = str(project_name or "").strip()
    if not normalized_command:
        return {
            "ok": False,
            "command": normalized_command,
            "project_name": key,
            "message": "",
            "error": "Command is required",
        }
    if not key:
        return {
            "ok": False,
            "command": normalized_command,
            "project_name": key,
            "message": "",
            "error": "project_name is required",
        }

    project_dir = _resolve_project_dir(key)
    if project_dir is None:
        return {
            "ok": False,
            "command": normalized_command,
            "project_name": key,
            "message": "",
            "error": "Project not found",
        }

    field_match = ADD_FIELD_RE.match(normalized_command)
    api_match = ADD_API_RE.match(normalized_command)
    page_match = ADD_PAGE_RE.match(normalized_command)
    implement_page_match = ADD_IMPLEMENT_PAGE_RE.match(normalized_command)

    try:
        from archmind.telegram_bot import (
            add_api_to_project,
            add_field_to_project,
            add_page_to_project,
            implement_page_in_project,
        )

        result: dict[str, Any]
        if field_match:
            entity_name = str(field_match.group(1) or "").strip()
            field_name = str(field_match.group(2) or "").strip()
            field_type = str(field_match.group(3) or "").strip().lower()
            result = add_field_to_project(project_dir, entity_name, field_name, field_type, auto_restart_backend=True)
        elif api_match:
            method = str(api_match.group(1) or "").strip().upper()
            path = str(api_match.group(2) or "").strip()
            result = add_api_to_project(project_dir, method, path, auto_restart_backend=True)
        elif page_match:
            page_path = str(page_match.group(1) or "").strip()
            if not page_path:
                payload = {
                    "ok": False,
                    "command": normalized_command,
                    "project_name": key,
                    "message": "",
                    "error": "Usage: /add_page <path>",
                }
                _write_execution_event(
                    project_dir,
                    project_name=key,
                    source=source,
                    command=normalized_command,
                    status="fail",
                    message=str(payload.get("error") or ""),
                    run_id=run_id,
                    step_no=step_no,
                )
                return payload
            result = add_page_to_project(project_dir, page_path, auto_restart_backend=True)
        elif implement_page_match:
            page_path = str(implement_page_match.group(1) or "").strip()
            if not page_path:
                payload = {
                    "ok": False,
                    "command": normalized_command,
                    "project_name": key,
                    "message": "",
                    "error": "Usage: /implement_page <path>",
                }
                _write_execution_event(
                    project_dir,
                    project_name=key,
                    source=source,
                    command=normalized_command,
                    status="fail",
                    message=str(payload.get("error") or ""),
                    run_id=run_id,
                    step_no=step_no,
                )
                return payload
            result = implement_page_in_project(project_dir, page_path, auto_restart_backend=True)
        else:
            payload = {
                "ok": False,
                "command": normalized_command,
                "project_name": key,
                "message": "",
                "error": "Unsupported command. Supported: /add_field, /add_api, /add_page, /implement_page",
            }
            _write_execution_event(
                project_dir,
                project_name=key,
                source=source,
                command=normalized_command,
                status="fail",
                message=str(payload.get("error") or ""),
                run_id=run_id,
                step_no=step_no,
            )
            return payload
    except Exception as exc:
        payload = {
            "ok": False,
            "command": normalized_command,
            "project_name": key,
            "message": "",
            "error": str(exc),
        }
        _write_execution_event(
            project_dir,
            project_name=key,
            source=source,
            command=normalized_command,
            status="fail",
            message=str(payload.get("error") or ""),
            run_id=run_id,
            step_no=step_no,
        )
        return payload

    if not isinstance(result, dict):
        payload = {
            "ok": False,
            "command": normalized_command,
            "project_name": key,
            "message": "",
            "error": "Command execution failed",
        }
        _write_execution_event(
            project_dir,
            project_name=key,
            source=source,
            command=normalized_command,
            status="fail",
            message=str(payload.get("error") or ""),
            run_id=run_id,
            step_no=step_no,
        )
        return payload

    message = str(result.get("message_text") or result.get("detail") or "").strip()
    error = str(result.get("error") or "").strip() or None
    payload = dict(result)
    payload.update(
        {
            "ok": bool(result.get("ok")),
            "command": normalized_command,
            "project_name": str(result.get("project_name") or key),
            "message": message,
            "error": error,
        }
    )
    _write_execution_event(
        project_dir,
        project_name=str(payload.get("project_name") or key),
        source=source,
        command=normalized_command,
        status="ok" if bool(payload.get("ok")) else "fail",
        message=str(payload.get("message") or payload.get("error") or ""),
        run_id=run_id,
        step_no=step_no,
    )
    return payload
