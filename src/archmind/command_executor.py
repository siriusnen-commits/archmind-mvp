from __future__ import annotations

from pathlib import Path
from typing import Any


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

    try:
        from archmind.telegram_bot import _resolve_target_project

        candidate = _resolve_target_project()
        if candidate is not None and str(candidate.name or "").strip() == key:
            return candidate
    except Exception:
        pass
    return None


def _error_payload(command: str, project_name: str, error: str) -> dict[str, Any]:
    return {
        "ok": False,
        "command": str(command or "").strip(),
        "project_name": str(project_name or "").strip(),
        "message": "",
        "error": error,
    }


def execute_command(command: str, project_name: str) -> dict:
    normalized_command = str(command or "").strip()
    key = str(project_name or "").strip()
    if not normalized_command:
        return _error_payload(normalized_command, key, "Command is required")
    if not key:
        return _error_payload(normalized_command, key, "project_name is required")

    project_dir = _resolve_project_dir(key)
    if project_dir is None:
        return _error_payload(normalized_command, key, "Project not found")

    parts = normalized_command.split()
    if not parts:
        return _error_payload(normalized_command, key, "Command is required")
    cmd = parts[0].strip().lower()

    try:
        from archmind.telegram_bot import add_api_to_project, add_field_to_project, add_page_to_project, implement_page_in_project

        result: dict[str, Any]
        if cmd == "/add_field":
            if len(parts) != 3 or ":" not in parts[2]:
                return _error_payload(normalized_command, key, "Usage: /add_field <Entity> <field_name>:<field_type>")
            entity_name = str(parts[1] or "").strip()
            field_name, field_type = [str(x).strip() for x in str(parts[2]).split(":", 1)]
            if not entity_name or not field_name or not field_type:
                return _error_payload(normalized_command, key, "Usage: /add_field <Entity> <field_name>:<field_type>")
            result = add_field_to_project(
                project_dir,
                entity_name,
                field_name,
                str(field_type).lower(),
                auto_restart_backend=True,
            )
        elif cmd == "/add_api":
            if len(parts) != 3:
                return _error_payload(normalized_command, key, "Usage: /add_api <METHOD> <path>")
            method = str(parts[1] or "").strip().upper()
            path = str(parts[2] or "").strip()
            if not method or not path:
                return _error_payload(normalized_command, key, "Usage: /add_api <METHOD> <path>")
            result = add_api_to_project(project_dir, method, path, auto_restart_backend=True)
        elif cmd == "/add_page":
            if len(parts) != 2:
                return _error_payload(normalized_command, key, "Usage: /add_page <path>")
            page_path = str(parts[1] or "").strip()
            if not page_path:
                return _error_payload(normalized_command, key, "Usage: /add_page <path>")
            result = add_page_to_project(project_dir, page_path, auto_restart_backend=True)
        elif cmd == "/implement_page":
            if len(parts) != 2:
                return _error_payload(normalized_command, key, "Usage: /implement_page <path>")
            page_path = str(parts[1] or "").strip()
            if not page_path:
                return _error_payload(normalized_command, key, "Usage: /implement_page <path>")
            result = implement_page_in_project(project_dir, page_path, auto_restart_backend=True)
        else:
            return _error_payload(
                normalized_command,
                key,
                "Unsupported command. Supported: /add_field, /add_api, /add_page, /implement_page",
            )
    except Exception as exc:
        return _error_payload(normalized_command, key, str(exc))

    if not isinstance(result, dict):
        return _error_payload(normalized_command, key, "Command execution failed")

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

