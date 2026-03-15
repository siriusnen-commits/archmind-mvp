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


def suggest_next_commands(spec: dict[str, Any], limit: int = 5) -> list[dict[str, str]]:
    modules = [str(x).strip().lower() for x in (spec.get("modules") or []) if str(x).strip()]
    shape = str(spec.get("shape") or "").strip().lower()
    entities = spec.get("entities") if isinstance(spec.get("entities"), list) else []
    api_endpoints = {str(x).strip() for x in (spec.get("api_endpoints") or []) if str(x).strip()}
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

    if "auth" in modules and "user" not in lower_entity_names:
        add("/add_entity User", "auth module present but User entity missing")

    for name in entity_names:
        slug = _entity_slug(name)
        plural = f"{slug}s"
        if not slug:
            continue
        read_api = f"GET /{plural}/{{id}}"
        if read_api not in api_endpoints:
            add(f"/add_api GET /{plural}/{{id}}", f"{name} entity exists but read API missing")

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

    if "dashboard" in modules and "dashboard/home" not in frontend_pages:
        add("/add_page dashboard/home", "dashboard module present but dashboard page missing")

    for entity in entities:
        if not isinstance(entity, dict):
            continue
        name = str(entity.get("name") or "").strip()
        fields = entity.get("fields") if isinstance(entity.get("fields"), list) else []
        if name and len(fields) <= 1:
            add(f"/add_field {name} description:string", f"{name} entity has few fields")

    return suggestions

