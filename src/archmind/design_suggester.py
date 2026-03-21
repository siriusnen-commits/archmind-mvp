from __future__ import annotations

from pathlib import Path
from typing import Any

from .reasoning import try_generate_reasoning_json

ENTITY_DEFAULT_FIELDS: dict[str, list[dict[str, str]]] = {
    "Defect": [
        {"name": "title", "type": "string"},
        {"name": "status", "type": "string"},
        {"name": "severity", "type": "string"},
        {"name": "firmware_version", "type": "string"},
    ],
    "Device": [
        {"name": "model_name", "type": "string"},
        {"name": "firmware_version", "type": "string"},
    ],
    "TestRun": [
        {"name": "result", "type": "string"},
        {"name": "executed_at", "type": "datetime"},
    ],
    "Team": [{"name": "name", "type": "string"}],
}


def _unique(values: list[str]) -> list[str]:
    out: list[str] = []
    seen: set[str] = set()
    for raw in values:
        value = str(raw or "").strip()
        if not value:
            continue
        key = value.lower()
        if key in seen:
            continue
        seen.add(key)
        out.append(value)
    return out


def _normalize_domain_name(value: str) -> str:
    v = str(value or "").strip().replace("_", " ").replace("-", " ")
    if not v:
        return ""
    return " ".join(v.split())


def _augment_domains(base_domains: list[str], idea: str) -> list[str]:
    domains = [_normalize_domain_name(x) for x in base_domains]
    text = str(idea or "").lower()
    if any(k in text for k in ("device", "hardware", "firmware")):
        domains.append("devices")
    if any(k in text for k in ("test run", "test history", "execution")) or (
        "qa" in text and any(k in text for k in ("hardware", "defect", "bug", "issue", "tracker"))
    ):
        domains.append("test runs")
    if any(k in text for k in ("defect", "bug", "issue")):
        domains.append("defects")
    if any(k in text for k in ("team", "collaboration")):
        domains.append("teams")
    return _unique(domains)


def _entity_name_set(entities: list[dict[str, Any]]) -> set[str]:
    names: set[str] = set()
    for entity in entities:
        if not isinstance(entity, dict):
            continue
        name = str(entity.get("name") or "").strip()
        if name:
            names.add(name.lower())
    return names


def _build_relationships(entities: list[dict[str, Any]]) -> list[str]:
    names = _entity_name_set(entities)
    rels: list[str] = []
    if "device" in names and "testrun" in names:
        rels.append("Device has many TestRuns")
    if "testrun" in names and "defect" in names:
        rels.append("TestRun may have many Defects")
    if "team" in names and "defect" in names:
        rels.append("Team manages Defects")
    if "project" in names and "defect" in names:
        rels.append("Project groups Defects")
    return rels


def _keyword_entities(idea: str) -> list[str]:
    text = str(idea or "").lower()
    out: list[str] = []
    if any(k in text for k in ("defect", "bug", "issue")):
        out.append("Defect")
    if any(k in text for k in ("device", "hardware", "firmware")):
        out.append("Device")
    if any(k in text for k in ("test run", "test history", "execution")) or (
        "qa" in text and any(k in text for k in ("hardware", "defect", "bug", "issue", "tracker"))
    ):
        out.append("TestRun")
    if any(k in text for k in ("team", "collaboration")):
        out.append("Team")
    return _unique(out)


def _ensure_keyword_entities(entities: list[dict[str, Any]], idea: str) -> list[dict[str, Any]]:
    out = list(entities)
    seen = _entity_name_set(out)
    for entity_name in _keyword_entities(idea):
        key = entity_name.lower()
        if key in seen:
            continue
        seen.add(key)
        out.append({"name": entity_name, "fields": ENTITY_DEFAULT_FIELDS.get(entity_name, [])})
    return out


def build_architecture_design(
    idea: str,
    reasoning: dict[str, Any],
    suggestion: dict[str, Any],
    *,
    provider_project_dir: Path | None = None,
) -> dict[str, Any]:
    shape = str(reasoning.get("app_shape") or "unknown").strip() or "unknown"
    template = str(reasoning.get("recommended_template") or "unknown").strip() or "unknown"
    modules = [str(x).strip() for x in (reasoning.get("modules") or []) if str(x).strip()]
    domains = [str(x).strip() for x in (reasoning.get("domains") or []) if str(x).strip()]
    entities = suggestion.get("entities") if isinstance(suggestion.get("entities"), list) else []
    api_endpoints = [str(x).strip() for x in (suggestion.get("api_endpoints") or []) if str(x).strip()]
    frontend_pages = [str(x).strip().strip("/") for x in (suggestion.get("frontend_pages") or []) if str(x).strip()]

    if (bool(reasoning.get("dashboard_needed")) or "dashboard" in [x.lower() for x in modules]) and bool(
        reasoning.get("frontend_needed")
    ):
        frontend_pages = _unique(["dashboard/home"] + frontend_pages)
    else:
        frontend_pages = _unique(frontend_pages)

    normalized_entities: list[dict[str, Any]] = []
    seen_entities: set[str] = set()
    for entity in entities:
        if not isinstance(entity, dict):
            continue
        name = str(entity.get("name") or "").strip()
        if not name:
            continue
        key = name.lower()
        if key in seen_entities:
            continue
        seen_entities.add(key)
        fields: list[dict[str, str]] = []
        raw_fields = entity.get("fields") if isinstance(entity.get("fields"), list) else []
        for field in raw_fields:
            if not isinstance(field, dict):
                continue
            field_name = str(field.get("name") or "").strip()
            field_type = str(field.get("type") or "").strip().lower()
            if field_name and field_type:
                fields.append({"name": field_name, "type": field_type})
        normalized_entities.append({"name": name, "fields": fields})

    normalized_entities = _ensure_keyword_entities(normalized_entities, idea)

    fallback_design = {
        "overview": str(idea or "").strip(),
        "shape": shape,
        "template": template,
        "modules": modules,
        "domains": _augment_domains(domains, idea),
        "entities": normalized_entities,
        "relationships": _build_relationships(normalized_entities),
        "api_endpoints": _unique(api_endpoints)[:10],
        "frontend_pages": frontend_pages[:10],
        "reasoning": str(reasoning.get("reason_summary") or "").strip(),
    }
    provider_prompt = (
        "Produce architecture design JSON.\n"
        "Return JSON object with keys: overview, shape, template, modules, domains, entities, relationships, api_endpoints, frontend_pages, reasoning.\n"
        f"Idea: {idea}\n"
        f"Reasoning: {reasoning}\n"
        f"Suggestion: {suggestion}\n"
        f"Fallback: {fallback_design}"
    )
    provider_design = try_generate_reasoning_json(
        provider_prompt,
        timeout_s=120,
        temperature=0.1,
        project_dir=provider_project_dir,
    )
    if not isinstance(provider_design, dict):
        return fallback_design

    out = dict(fallback_design)
    for key in ("overview", "shape", "template", "reasoning"):
        if key in provider_design:
            value = str(provider_design.get(key) or "").strip()
            if value:
                out[key] = value

    for key in ("modules", "domains", "relationships", "api_endpoints", "frontend_pages"):
        raw = provider_design.get(key)
        if isinstance(raw, list):
            values = [str(x).strip() for x in raw if str(x).strip()]
            if key == "frontend_pages":
                values = [x.strip("/") for x in values]
            unique = _unique(values)
            if unique:
                out[key] = unique[:10]

    raw_entities = provider_design.get("entities")
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
            normalized_fields: list[dict[str, str]] = []
            raw_fields = raw_entity.get("fields")
            if isinstance(raw_fields, list):
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
            normalized_entities.append({"name": name, "fields": normalized_fields})
        normalized_entities = _ensure_keyword_entities(normalized_entities, idea)
        if normalized_entities:
            out["entities"] = normalized_entities[:10]

    inferred_relationships = _build_relationships(out.get("entities") if isinstance(out.get("entities"), list) else [])
    existing_relationships = out.get("relationships") if isinstance(out.get("relationships"), list) else []
    merged_relationships = _unique([str(x).strip() for x in existing_relationships if str(x).strip()] + inferred_relationships)
    if merged_relationships:
        out["relationships"] = merged_relationships[:10]

    return out
