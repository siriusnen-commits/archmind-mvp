from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from .reasoning import try_generate_reasoning_json


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


def suggest_project_spec(
    idea: str,
    reasoning: dict[str, Any],
    *,
    provider_project_dir: Path | None = None,
) -> dict[str, Any]:
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

    fallback_spec = {
        "entities": entities[:3],
        "api_endpoints": api_endpoints[:6],
        "frontend_pages": pages[:6],
    }
    provider_prompt = (
        "Suggest a compact project spec JSON for the idea.\n"
        "Return JSON object with keys: entities, api_endpoints, frontend_pages.\n"
        "entities: list of {name, fields:[{name,type}]}\n"
        "api_endpoints: list of '<METHOD> /path'\n"
        "frontend_pages: list of page paths without leading slash.\n"
        f"Idea: {idea}\n"
        f"Reasoning: {reasoning}\n"
        f"Fallback: {fallback_spec}"
    )
    provider_spec = try_generate_reasoning_json(
        provider_prompt,
        timeout_s=90,
        temperature=0.1,
        project_dir=provider_project_dir,
    )
    if not isinstance(provider_spec, dict):
        return fallback_spec

    out = dict(fallback_spec)
    raw_entities = provider_spec.get("entities")
    if isinstance(raw_entities, list):
        normalized_entities: list[dict[str, Any]] = []
        seen_entities: set[str] = set()
        for raw_entity in raw_entities:
            if not isinstance(raw_entity, dict):
                continue
            name = str(raw_entity.get("name") or "").strip()
            key = name.lower()
            if not name or key in seen_entities:
                continue
            seen_entities.add(key)
            raw_fields = raw_entity.get("fields") if isinstance(raw_entity.get("fields"), list) else []
            normalized_fields: list[dict[str, str]] = []
            seen_fields: set[str] = set()
            for raw_field in raw_fields:
                if not isinstance(raw_field, dict):
                    continue
                field_name = str(raw_field.get("name") or "").strip()
                field_type = str(raw_field.get("type") or "").strip().lower()
                field_key = field_name.lower()
                if not field_name or not field_type or field_key in seen_fields:
                    continue
                seen_fields.add(field_key)
                normalized_fields.append({"name": field_name, "type": field_type})
            normalized_entities.append({"name": name, "fields": normalized_fields[:6]})
        if normalized_entities:
            out["entities"] = normalized_entities[:3]

    raw_apis = provider_spec.get("api_endpoints")
    if isinstance(raw_apis, list):
        normalized_apis: list[str] = []
        seen_apis: set[str] = set()
        for raw_api in raw_apis:
            endpoint = str(raw_api or "").strip()
            if not endpoint:
                continue
            key = endpoint.lower()
            if key in seen_apis:
                continue
            seen_apis.add(key)
            normalized_apis.append(endpoint)
        if normalized_apis:
            out["api_endpoints"] = normalized_apis[:6]

    raw_pages = provider_spec.get("frontend_pages")
    if isinstance(raw_pages, list):
        normalized_pages: list[str] = []
        seen_pages: set[str] = set()
        for raw_page in raw_pages:
            page = str(raw_page or "").strip().strip("/")
            if not page:
                continue
            key = page.lower()
            if key in seen_pages:
                continue
            seen_pages.add(key)
            normalized_pages.append(page)
        if normalized_pages:
            out["frontend_pages"] = normalized_pages[:6]

    return out
