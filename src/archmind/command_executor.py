from __future__ import annotations

import re
from pathlib import Path
from typing import Any


ADD_FIELD_RE = re.compile(r"^/add_field\s+(\S+)\s+([^:\s]+)\s*:\s*(\S+)\s*$")
ADD_API_RE = re.compile(r"^/add_api\s+(GET|POST|PUT|DELETE)\s+(\S+)\s*$", re.IGNORECASE)
ADD_PAGE_RE = re.compile(r"^/add_page\s+(.+)$")


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


def execute_command(command: str, project_name: str) -> dict:
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

    try:
        from archmind.telegram_bot import add_api_to_project, add_field_to_project, add_page_to_project

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
                return {
                    "ok": False,
                    "command": normalized_command,
                    "project_name": key,
                    "message": "",
                    "error": "Usage: /add_page <path>",
                }
            result = add_page_to_project(project_dir, page_path, auto_restart_backend=True)
        else:
            return {
                "ok": False,
                "command": normalized_command,
                "project_name": key,
                "message": "",
                "error": "Unsupported command. Supported: /add_field, /add_api, /add_page",
            }
    except Exception as exc:
        return {
            "ok": False,
            "command": normalized_command,
            "project_name": key,
            "message": "",
            "error": str(exc),
        }

    if not isinstance(result, dict):
        return {
            "ok": False,
            "command": normalized_command,
            "project_name": key,
            "message": "",
            "error": "Command execution failed",
        }

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
    return payload
