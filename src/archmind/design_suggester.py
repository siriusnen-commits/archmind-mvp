from __future__ import annotations

from typing import Any

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


def build_architecture_design(idea: str, reasoning: dict[str, Any], suggestion: dict[str, Any]) -> dict[str, Any]:
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

    for entity_name in _keyword_entities(idea):
        key = entity_name.lower()
        if key in seen_entities:
            continue
        seen_entities.add(key)
        normalized_entities.append({"name": entity_name, "fields": ENTITY_DEFAULT_FIELDS.get(entity_name, [])})

    return {
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
