from __future__ import annotations

import re
from typing import Any


def _entity_slug(name: str) -> str:
    value = str(name or "").strip()
    if not value:
        return ""
    return re.sub(r"(?<!^)(?=[A-Z])", "_", value).lower()


def _normalized_entities(spec: dict[str, Any]) -> list[dict[str, Any]]:
    entities_raw = spec.get("entities") if isinstance(spec.get("entities"), list) else []
    entities: list[dict[str, Any]] = []
    for item in entities_raw:
        if not isinstance(item, dict):
            continue
        name = str(item.get("name") or "").strip()
        if not name:
            continue
        fields_raw = item.get("fields") if isinstance(item.get("fields"), list) else []
        fields: list[dict[str, str]] = []
        for field in fields_raw:
            if not isinstance(field, dict):
                continue
            field_name = str(field.get("name") or "").strip()
            field_type = str(field.get("type") or "").strip().lower()
            if field_name and field_type:
                fields.append({"name": field_name, "type": field_type})
        entities.append({"name": name, "fields": fields})
    return entities


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
        normalized_path = path.strip()
        if not normalized_path:
            continue
        if not normalized_path.startswith("/"):
            normalized_path = "/" + normalized_path
        out.add(f"{method.upper()} {normalized_path}")
    return out


def _normalized_frontend_pages(values: Any) -> set[str]:
    out: set[str] = set()
    if not isinstance(values, list):
        return out
    for raw in values:
        page = str(raw or "").strip().replace("\\", "/")
        page = re.sub(r"/{2,}", "/", page).strip("/")
        if not page or " " in page:
            continue
        out.add(page)
    return out


def _entity_name_list(entities: list[dict[str, Any]]) -> list[str]:
    return [str(entity.get("name") or "").strip() for entity in entities if str(entity.get("name") or "").strip()]


def analyze_spec_progression(spec: dict[str, Any]) -> dict[str, Any]:
    entities = _normalized_entities(spec)
    api_endpoints = _normalized_api_endpoints(spec.get("api_endpoints"))
    frontend_pages = _normalized_frontend_pages(spec.get("frontend_pages"))
    entity_names = _entity_name_list(entities)
    first_entity = entity_names[0] if entity_names else ""
    first_entity_without_fields = ""
    for entity in entities:
        fields = entity.get("fields") if isinstance(entity.get("fields"), list) else []
        if not fields:
            first_entity_without_fields = str(entity.get("name") or "").strip()
            break

    frontend_expected = str(spec.get("shape") or "").strip().lower() == "fullstack" or bool(frontend_pages)

    if not entities and not api_endpoints and not frontend_pages:
        stage = 0
    elif entities and first_entity_without_fields:
        stage = 1
    elif entities and not api_endpoints:
        stage = 2
    elif entities and api_endpoints and not frontend_pages and frontend_expected:
        stage = 3
    else:
        stage = 4

    return {
        "stage": stage,
        "stage_label": f"Stage {stage}",
        "entities_count": len(entities),
        "apis_count": len(api_endpoints),
        "pages_count": len(frontend_pages),
        "entities": entities,
        "entity_names": entity_names,
        "first_entity": first_entity,
        "first_entity_without_fields": first_entity_without_fields,
        "api_endpoints": api_endpoints,
        "frontend_pages": frontend_pages,
        "shape": str(spec.get("shape") or "").strip().lower(),
        "modules": [str(x).strip().lower() for x in (spec.get("modules") or []) if str(x).strip()],
    }


def suggest_spec_progression_commands(spec: dict[str, Any], limit: int = 2) -> list[dict[str, str]]:
    analysis = analyze_spec_progression(spec)
    stage = int(analysis.get("stage") or 0)
    first_entity = str(analysis.get("first_entity") or "").strip()
    entity_without_fields = str(analysis.get("first_entity_without_fields") or "").strip()
    commands: list[dict[str, str]] = []

    if stage == 0:
        commands.append({"command": "/add_entity Note", "reason": "no entities defined yet"})
    elif stage == 1 and entity_without_fields:
        commands.append(
            {
                "command": f"/add_field {entity_without_fields} title:string",
                "reason": f"{entity_without_fields} entity has no fields yet",
            }
        )
    elif stage == 2 and first_entity:
        slug = _entity_slug(first_entity)
        plural = f"{slug}s" if slug else "notes"
        commands.append({"command": f"/add_api GET /{plural}", "reason": f"{first_entity} entity exists but APIs are missing"})
        commands.append({"command": f"/add_api POST /{plural}", "reason": f"{first_entity} entity exists but create API is missing"})
    elif stage == 3 and first_entity:
        slug = _entity_slug(first_entity)
        plural = f"{slug}s" if slug else "notes"
        commands.append({"command": f"/add_page {plural}/list", "reason": f"{first_entity} entity exists but list page is missing"})
        commands.append(
            {"command": f"/add_page {plural}/detail", "reason": f"{first_entity} entity exists but detail page is missing"}
        )

    return commands[: max(1, limit)]


def suggest_spec_improvements(spec: dict[str, Any], limit: int = 3) -> list[dict[str, str]]:
    analysis = analyze_spec_progression(spec)
    stage = int(analysis.get("stage") or 0)
    first_entity = str(analysis.get("first_entity") or "").strip() or "Note"
    entity_without_fields = str(analysis.get("first_entity_without_fields") or "").strip() or first_entity
    slug = _entity_slug(first_entity) or "note"
    plural = f"{slug}s"
    items: list[dict[str, str]] = []

    if stage == 0:
        items.append(
            {
                "title": "Define your first entity",
                "reason": "No entities are defined yet.",
                "command": "/add_entity Note",
            }
        )
    elif stage == 1:
        items.append(
            {
                "title": f"Add fields to {entity_without_fields}",
                "reason": f"Entity {entity_without_fields} has no fields yet.",
                "command": f"/add_field {entity_without_fields} title:string",
            }
        )
    elif stage == 2:
        items.append(
            {
                "title": f"Add an API for {first_entity}",
                "reason": "No API endpoints are defined yet.",
                "command": f"/add_api GET /{plural}",
            }
        )
    elif stage == 3:
        items.append(
            {
                "title": f"Add a page for {first_entity}",
                "reason": "No frontend pages are defined yet.",
                "command": f"/add_page {plural}/list",
            }
        )
    return items[: max(1, limit)]


def suggest_next_commands(spec: dict[str, Any], limit: int = 5) -> list[dict[str, str]]:
    analysis = analyze_spec_progression(spec)
    modules = list(analysis.get("modules") or [])
    stage = int(analysis.get("stage") or 0)
    entities = list(analysis.get("entities") or [])
    api_endpoints = set(analysis.get("api_endpoints") or set())
    frontend_pages = set(analysis.get("frontend_pages") or set())
    entity_names = list(analysis.get("entity_names") or [])
    lower_entity_names = {name.lower() for name in entity_names}
    shape = str(analysis.get("shape") or "")

    suggestions: list[dict[str, str]] = []
    seen_commands: set[str] = set()

    def add(command: str, reason: str) -> None:
        if len(suggestions) >= limit:
            return
        if command in seen_commands:
            return
        seen_commands.add(command)
        suggestions.append({"command": command, "reason": reason})

    for item in suggest_spec_progression_commands(spec, limit=min(limit, 2)):
        add(str(item.get("command") or "").strip(), str(item.get("reason") or "").strip())

    if "auth" in modules and "user" not in lower_entity_names:
        add("/add_entity User", "auth module present but User entity missing")
    if "dashboard" in modules and "dashboard/home" not in frontend_pages:
        add("/add_page dashboard/home", "dashboard module present but dashboard page missing")

    # Domain-specific field quality hints remain available across stages.
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

    if stage >= 4:
        for entity in entities:
            if not isinstance(entity, dict):
                continue
            name = str(entity.get("name") or "").strip()
            slug = _entity_slug(name)
            plural = f"{slug}s"
            if not name or not slug:
                continue

            read_endpoint = f"GET /{plural}/{{id}}"
            if read_endpoint not in api_endpoints:
                add(f"/add_api GET /{plural}/{{id}}", f"{name} entity exists but read API missing")

            delete_endpoint = f"DELETE /{plural}/{{id}}"
            if delete_endpoint not in api_endpoints:
                add(f"/add_api DELETE /{plural}/{{id}}", f"{name} entity exists but delete API missing")

            update_paths = {f"PUT /{plural}/{{id}}", f"PATCH /{plural}/{{id}}"}
            has_update = any(ep in api_endpoints for ep in update_paths)
            if not has_update:
                add(f"/add_api PUT /{plural}/{{id}}", f"{name} entity exists but update API missing")

            list_page = f"{plural}/list"
            detail_page = f"{plural}/detail"
            if (shape == "fullstack" or frontend_pages) and list_page not in frontend_pages:
                add(f"/add_page {list_page}", f"{name} entity exists but list page missing")
            if (shape == "fullstack" or frontend_pages) and detail_page not in frontend_pages:
                add(f"/add_page {detail_page}", f"{name} entity exists but detail page missing")

            fields = entity.get("fields") if isinstance(entity.get("fields"), list) else []
            field_names = {str(item.get("name") or "").strip().lower() for item in fields if isinstance(item, dict)}
            if "created_at" not in field_names:
                add(f"/add_field {name} created_at:datetime", f"{name} entity missing created_at timestamp")
            if "updated_at" not in field_names:
                add(f"/add_field {name} updated_at:datetime", f"{name} entity missing updated_at timestamp")

    return suggestions
