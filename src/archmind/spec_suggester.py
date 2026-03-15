from __future__ import annotations

import re
from typing import Any


DOMAIN_ENTITY_MAP: dict[str, str] = {
    "tasks": "Task",
    "defects": "Defect",
    "teams": "Team",
    "documents": "Document",
    "expenses": "Expense",
    "inventory": "Item",
    "notes": "Note",
}

ENTITY_FIELD_MAP: dict[str, list[dict[str, str]]] = {
    "Task": [{"name": "title", "type": "string"}, {"name": "status", "type": "string"}],
    "Defect": [{"name": "title", "type": "string"}, {"name": "status", "type": "string"}],
    "Device": [{"name": "model_name", "type": "string"}, {"name": "firmware_version", "type": "string"}],
    "TestRun": [{"name": "result", "type": "string"}, {"name": "executed_at", "type": "datetime"}],
    "Team": [{"name": "name", "type": "string"}],
    "Project": [{"name": "name", "type": "string"}],
    "Document": [{"name": "title", "type": "string"}],
    "Expense": [{"name": "amount", "type": "float"}, {"name": "category", "type": "string"}],
    "Item": [{"name": "name", "type": "string"}, {"name": "quantity", "type": "int"}],
    "Note": [{"name": "title", "type": "string"}, {"name": "content", "type": "string"}],
}


def _entity_slug_and_plural(entity_name: str) -> tuple[str, str]:
    value = str(entity_name or "").strip()
    if not value:
        return "", ""
    slug = re.sub(r"(?<!^)(?=[A-Z])", "_", value).lower()
    return slug, f"{slug}s"


def suggest_project_spec(idea: str, reasoning: dict[str, Any]) -> dict[str, Any]:
    text = str(idea or "").strip().lower()
    domains = [str(x).strip().lower() for x in (reasoning.get("domains") or []) if str(x).strip()]
    selected_entities: list[str] = []
    seen: set[str] = set()

    for domain in domains:
        entity = DOMAIN_ENTITY_MAP.get(domain)
        if not entity or entity in seen:
            continue
        seen.add(entity)
        selected_entities.append(entity)

    has_team = "teams" in domains
    has_work = any(x in domains for x in ("tasks", "defects"))
    if has_team and has_work and "Project" not in seen:
        seen.add("Project")
        selected_entities.append("Project")

    # Keyword inference for QA/hardware ideas.
    if any(k in text for k in ("device", "hardware", "firmware")) and "Device" not in seen:
        seen.add("Device")
        selected_entities.append("Device")
    if any(k in text for k in ("test run", "test history", "execution")) and "TestRun" not in seen:
        seen.add("TestRun")
        selected_entities.append("TestRun")
    if "qa" in text and any(k in text for k in ("hardware", "defect", "bug", "issue", "tracker")) and "TestRun" not in seen:
        seen.add("TestRun")
        selected_entities.append("TestRun")
    if any(k in text for k in ("defect", "bug", "issue")) and "Defect" not in seen:
        seen.add("Defect")
        selected_entities.append("Defect")

    selected_entities = selected_entities[:3]

    entities: list[dict[str, Any]] = []
    for entity_name in selected_entities:
        fields = ENTITY_FIELD_MAP.get(entity_name, [])[:2]
        entities.append({"name": entity_name, "fields": fields})

    api_endpoints: list[str] = []
    pages: list[str] = []
    frontend_needed = bool(reasoning.get("frontend_needed"))
    for entity in entities:
        _, plural = _entity_slug_and_plural(str(entity.get("name") or ""))
        if not plural:
            continue
        api_endpoints.append(f"GET /{plural}")
        api_endpoints.append(f"POST /{plural}")
        if frontend_needed:
            pages.append(f"{plural}/list")
            pages.append(f"{plural}/detail")

    return {
        "entities": entities[:3],
        "api_endpoints": api_endpoints[:6],
        "frontend_pages": pages[:6],
    }
