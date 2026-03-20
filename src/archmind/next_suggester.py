from __future__ import annotations

import re
from typing import Any


def _entity_slug(name: str) -> str:
    value = str(name or "").strip()
    if not value:
        return ""
    return re.sub(r"(?<!^)(?=[A-Z])", "_", value).lower()


def _entity_name_list(spec: dict[str, Any]) -> list[str]:
    out: list[str] = []
    for entity in spec.get("entities") or []:
        if not isinstance(entity, dict):
            continue
        name = str(entity.get("name") or "").strip()
        if name:
            out.append(name)
    return out


def _normalized_api_endpoints(values: Any) -> set[str]:
    out: set[str] = set()
    if not isinstance(values, list):
        return out
    for raw in values:
        text = str(raw or "").strip()
        if not text:
            continue
        parts = text.split(maxsplit=1)
        if len(parts) != 2:
            continue
        method, path = parts
        out.add(f"{method.upper()} {path.strip()}")
    return out


def suggest_next_commands(spec: dict[str, Any], limit: int = 5) -> list[dict[str, str]]:
    modules = [str(x).strip().lower() for x in (spec.get("modules") or []) if str(x).strip()]
    shape = str(spec.get("shape") or "").strip().lower()
    entities = spec.get("entities") if isinstance(spec.get("entities"), list) else []
    api_endpoints = _normalized_api_endpoints(spec.get("api_endpoints"))
    frontend_pages = {str(x).strip() for x in (spec.get("frontend_pages") or []) if str(x).strip()}
    entity_names = _entity_name_list(spec)
    lower_entity_names = {name.lower() for name in entity_names}

    suggestions: list[dict[str, str]] = []
    seen_commands: set[str] = set()

    def add(command: str, reason: str) -> None:
        if len(suggestions) >= limit:
            return
        if command in seen_commands:
            return
        seen_commands.add(command)
        suggestions.append({"command": command, "reason": reason})

    if not entity_names:
        add("/add_entity Note", "no entities defined yet")

    if "auth" in modules and "user" not in lower_entity_names:
        add("/add_entity User", "auth module present but User entity missing")

    for entity in entities:
        if not isinstance(entity, dict):
            continue
        name = str(entity.get("name") or "").strip()
        fields = entity.get("fields") if isinstance(entity.get("fields"), list) else []
        if name and not fields:
            add(f"/add_field {name} title:string", f"{name} entity has no fields yet")

    # Domain-specific field quality rules
    for entity in entities:
        if not isinstance(entity, dict):
            continue
        name = str(entity.get("name") or "").strip()
        fields = entity.get("fields") if isinstance(entity.get("fields"), list) else []
        field_names = {str(item.get("name") or "").strip().lower() for item in fields if isinstance(item, dict)}
        lower_name = name.lower()
        if lower_name == "defect":
            if "title" not in field_names:
                add("/add_field Defect title:string", "Defect entity missing title field")
            if "status" not in field_names:
                add("/add_field Defect status:string", "Defect entity missing status field")
        if lower_name == "device":
            if "firmware_version" not in field_names:
                add("/add_field Device firmware_version:string", "Device entity missing firmware_version field")
            if "model_name" not in field_names:
                add("/add_field Device model_name:string", "Device entity missing model_name field")
        if lower_name == "testrun":
            if "result" not in field_names:
                add("/add_field TestRun result:string", "TestRun entity missing result field")
            if "executed_at" not in field_names:
                add("/add_field TestRun executed_at:datetime", "TestRun entity missing executed_at field")

    if "dashboard" in modules and "dashboard/home" not in frontend_pages:
        add("/add_page dashboard/home", "dashboard module present but dashboard page missing")

    if shape == "fullstack" and not frontend_pages:
        for name in entity_names:
            slug = _entity_slug(name)
            plural = f"{slug}s"
            if not slug:
                continue
            add(f"/add_page {plural}/list", f"{name} entity exists but list page missing")
            add(f"/add_page {plural}/detail", f"{name} entity exists but detail page missing")

    for entity in entities:
        if not isinstance(entity, dict):
            continue
        name = str(entity.get("name") or "").strip()
        slug = _entity_slug(name)
        plural = f"{slug}s"
        if not name or not slug:
            continue

        list_api = f"GET /{plural}"
        create_api = f"POST /{plural}"
        if list_api not in api_endpoints:
            add(f"/add_api GET /{plural}", f"{name} entity exists but list API missing")
        if create_api not in api_endpoints:
            add(f"/add_api POST /{plural}", f"{name} entity exists but create API missing")

        expected_apis = [
            ("GET", f"/{plural}/{{id}}", "read API missing"),
            ("DELETE", f"/{plural}/{{id}}", "delete API missing"),
        ]
        for method, path, reason in expected_apis:
            endpoint = f"{method} {path}"
            if endpoint not in api_endpoints:
                add(f"/add_api {method} {path}", f"{name} entity exists but {reason}")

        update_paths = {
            f"PUT /{plural}/{{id}}",
            f"PATCH /{plural}/{{id}}",
        }
        has_update = any(ep in api_endpoints for ep in update_paths)
        if not has_update:
            add(f"/add_api PUT /{plural}/{{id}}", f"{name} entity exists but update API missing")

        fields = entity.get("fields") if isinstance(entity.get("fields"), list) else []
        field_names = {str(item.get("name") or "").strip().lower() for item in fields if isinstance(item, dict)}
        if "created_at" not in field_names:
            add(f"/add_field {name} created_at:datetime", f"{name} entity missing created_at timestamp")
        if "updated_at" not in field_names:
            add(f"/add_field {name} updated_at:datetime", f"{name} entity missing updated_at timestamp")

    frontend_enabled = shape == "fullstack" or bool(frontend_pages)
    if frontend_enabled:
        for name in entity_names:
            slug = _entity_slug(name)
            plural = f"{slug}s"
            if not slug:
                continue
            list_page = f"{plural}/list"
            detail_page = f"{plural}/detail"
            if list_page not in frontend_pages:
                add(f"/add_page {list_page}", f"{name} entity exists but list page missing")
            if detail_page not in frontend_pages:
                add(f"/add_page {detail_page}", f"{name} entity exists but detail page missing")

    for entity in entities:
        if not isinstance(entity, dict):
            continue
        name = str(entity.get("name") or "").strip()
        fields = entity.get("fields") if isinstance(entity.get("fields"), list) else []
        if name and len(fields) <= 1:
            add(f"/add_field {name} description:string", f"{name} entity has few fields")

    return suggestions
