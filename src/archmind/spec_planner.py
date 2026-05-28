from __future__ import annotations

import copy
import re
from typing import Any


def _has_word(text: str, word: str) -> bool:
    return bool(re.search(rf"\b{re.escape(str(word or '').strip().lower())}\b", str(text or "").strip().lower()))


def _field(name: str, field_type: str = "string") -> dict[str, str]:
    return {"name": name, "type": field_type}


def _entity_slug_and_plural(entity_name: str) -> tuple[str, str]:
    value = str(entity_name or "").strip()
    if not value:
        return "", ""
    slug = re.sub(r"(?<!^)(?=[A-Z])", "_", value).lower()
    if slug.endswith("y") and len(slug) > 1 and slug[-2] not in "aeiou":
        return slug, f"{slug[:-1]}ies"
    if slug.endswith(("s", "x", "z", "ch", "sh")):
        return slug, f"{slug}es"
    return slug, f"{slug}s"


DOMAIN_MODEL_PLANS: list[dict[str, Any]] = [
    {
        "type": "support_ticket",
        "signals": ("support ticket", "ticket manager", "support desk", "help desk", "helpdesk"),
        "entities": [
            {"name": "Ticket", "fields": [_field("title"), _field("description"), _field("status"), _field("priority"), _field("customer_id", "int"), _field("agent_id", "int")]},
            {"name": "Customer", "fields": [_field("name"), _field("email")]},
            {"name": "Agent", "fields": [_field("name"), _field("email")]},
            {"name": "Comment", "fields": [_field("body"), _field("ticket_id", "int"), _field("created_at", "datetime")]},
        ],
        "relationships": [
            {"from_entity": "Ticket", "to_entity": "Customer", "field": "customer_id", "type": "many_to_one"},
            {"from_entity": "Ticket", "to_entity": "Agent", "field": "agent_id", "type": "many_to_one"},
            {"from_entity": "Comment", "to_entity": "Ticket", "field": "ticket_id", "type": "many_to_one"},
        ],
    },
    {
        "type": "project_management",
        "signals": ("project management", "project manager", "project tracker", "project planning"),
        "entities": [
            {"name": "Project", "fields": [_field("name"), _field("description")]},
            {"name": "Task", "fields": [_field("title"), _field("status"), _field("project_id", "int"), _field("assignee_id", "int")]},
            {"name": "Member", "fields": [_field("name"), _field("email")]},
        ],
        "relationships": [
            {"from_entity": "Task", "to_entity": "Project", "field": "project_id", "type": "many_to_one"},
            {"from_entity": "Task", "to_entity": "Member", "field": "assignee_id", "type": "many_to_one"},
        ],
    },
    {
        "type": "asset_inventory",
        "signals": ("asset tracker", "asset management", "inventory management", "inventory manager", "stock management", "warehouse inventory"),
        "entities": [
            {"name": "Asset", "fields": [_field("name"), _field("quantity", "int"), _field("category_id", "int"), _field("location_id", "int")]},
            {"name": "Category", "fields": [_field("name")]},
            {"name": "Location", "fields": [_field("name")]},
        ],
        "relationships": [
            {"from_entity": "Asset", "to_entity": "Category", "field": "category_id", "type": "many_to_one"},
            {"from_entity": "Asset", "to_entity": "Location", "field": "location_id", "type": "many_to_one"},
        ],
    },
    {
        "type": "crm_pipeline",
        "signals": ("crm", "customer pipeline", "sales pipeline", "deal tracker"),
        "entities": [
            {"name": "Customer", "fields": [_field("name"), _field("email")]},
            {"name": "Deal", "fields": [_field("title"), _field("status"), _field("value", "float"), _field("customer_id", "int")]},
            {"name": "Contact", "fields": [_field("name"), _field("email"), _field("customer_id", "int")]},
            {"name": "Activity", "fields": [_field("title"), _field("date", "datetime"), _field("customer_id", "int")]},
        ],
        "relationships": [
            {"from_entity": "Deal", "to_entity": "Customer", "field": "customer_id", "type": "many_to_one"},
            {"from_entity": "Activity", "to_entity": "Customer", "field": "customer_id", "type": "many_to_one"},
        ],
    },
    {
        "type": "vendor_directory",
        "signals": ("vendor directory", "vendor manager", "supplier directory"),
        "entities": [
            {"name": "Vendor", "fields": [_field("name"), _field("email"), _field("website"), _field("category_id", "int")]},
            {"name": "Contact", "fields": [_field("name"), _field("email"), _field("vendor_id", "int")]},
            {"name": "Category", "fields": [_field("name")]},
        ],
        "relationships": [
            {"from_entity": "Contact", "to_entity": "Vendor", "field": "vendor_id", "type": "many_to_one"},
            {"from_entity": "Vendor", "to_entity": "Category", "field": "category_id", "type": "many_to_one"},
        ],
    },
    {
        "type": "habit_fitness",
        "signals": ("habit tracker", "fitness tracker", "workout tracker"),
        "entities": [
            {"name": "Habit", "fields": [_field("name"), _field("category")]},
            {"name": "HabitLog", "fields": [_field("date", "datetime"), _field("status"), _field("habit_id", "int")]},
            {"name": "Goal", "fields": [_field("title"), _field("target", "float")]},
        ],
        "relationships": [
            {"from_entity": "HabitLog", "to_entity": "Habit", "field": "habit_id", "type": "many_to_one"},
        ],
    },
]

SIMPLE_IDEA_SIGNALS = (
    "memo app",
    "simple memo",
    "simple todo",
    "todo app",
    "bookmark manager",
    "diary app",
    "journal app",
)


def _is_simple_idea(text: str) -> bool:
    return any(signal in text for signal in SIMPLE_IDEA_SIGNALS)


def _select_plan(idea: str | None, reasoning: dict[str, Any] | None = None) -> dict[str, Any]:
    text = str(idea or "").strip().lower()
    domains = {
        str(item).strip().lower()
        for item in ((reasoning or {}).get("domains") if isinstance(reasoning, dict) else []) or []
        if str(item).strip()
    }
    if not text and not domains:
        return {}
    if _is_simple_idea(text):
        return {}

    for plan in DOMAIN_MODEL_PLANS:
        signals = tuple(str(item).strip().lower() for item in plan.get("signals", ()) if str(item).strip())
        if any(signal in text or _has_word(text, signal) or signal in domains for signal in signals):
            return plan
    return {}


def _normalize_relationship(row: dict[str, Any]) -> dict[str, str]:
    from_entity = str(row.get("from_entity") or row.get("source_entity") or row.get("child_entity") or row.get("from") or "").strip()
    to_entity = str(row.get("to_entity") or row.get("target_entity") or row.get("parent_entity") or row.get("to") or "").strip()
    field = str(row.get("field") or "").strip()
    rel_type = str(row.get("type") or "many_to_one").strip() or "many_to_one"
    if not from_entity or not to_entity:
        return {}
    return {
        "from_entity": from_entity,
        "to_entity": to_entity,
        "source_entity": from_entity,
        "target_entity": to_entity,
        "field": field,
        "type": rel_type,
        "cardinality": rel_type,
    }


def _merge_entity(out: dict[str, Any], planned: dict[str, Any], *, max_entities: int) -> None:
    entity_rows = [row for row in (out.get("entities") if isinstance(out.get("entities"), list) else []) if isinstance(row, dict)]
    by_name = {
        str(row.get("name") or "").strip().lower(): row
        for row in entity_rows
        if str(row.get("name") or "").strip()
    }
    entity_name = str(planned.get("name") or "").strip()
    if not entity_name:
        return
    row = by_name.get(entity_name.lower())
    if not isinstance(row, dict):
        if len(entity_rows) >= max_entities:
            return
        row = {"name": entity_name, "fields": []}
        entity_rows.append(row)
        by_name[entity_name.lower()] = row
    fields = row.get("fields") if isinstance(row.get("fields"), list) else []
    seen_fields = {
        str(field.get("name") or "").strip().lower()
        for field in fields
        if isinstance(field, dict) and str(field.get("name") or "").strip()
    }
    for field in planned.get("fields") if isinstance(planned.get("fields"), list) else []:
        if not isinstance(field, dict):
            continue
        field_name = str(field.get("name") or "").strip()
        field_type = str(field.get("type") or "string").strip().lower() or "string"
        if not field_name or field_name.lower() in seen_fields:
            continue
        fields.append({"name": field_name, "type": field_type})
        seen_fields.add(field_name.lower())
    row["fields"] = fields[:8]
    out["entities"] = entity_rows


def _append_unique(values: list[Any], additions: list[Any], key_fn) -> list[Any]:
    out = list(values)
    seen = {key_fn(item) for item in out}
    for item in additions:
        key = key_fn(item)
        if not key or key in seen:
            continue
        out.append(item)
        seen.add(key)
    return out


def _infer_patterns(entities: list[dict[str, Any]]) -> list[dict[str, Any]]:
    all_fields: list[str] = []
    for entity in entities:
        for field in entity.get("fields") if isinstance(entity.get("fields"), list) else []:
            if isinstance(field, dict):
                all_fields.append(str(field.get("name") or "").strip().lower())
    rules = [
        ("workflow_status", {"status", "state", "stage", "priority", "severity"}, "status/priority fields indicate workflow tracking"),
        ("metric_quantity", {"quantity", "count", "amount", "balance", "score", "value", "target"}, "numeric fields indicate measurable tracking"),
        ("timeline_date", {"date", "due_date", "deadline", "created_at", "updated_at", "scheduled_at"}, "date fields indicate timeline-oriented records"),
        ("classification", {"category", "category_id", "tag", "tags", "type", "group", "label"}, "category/tag fields indicate grouping"),
        ("reference_link", {"url", "website", "email", "contact_email"}, "url/email fields indicate references"),
        ("ownership", {"owner", "assignee", "assignee_id", "agent_id", "member_id"}, "assignee/owner fields indicate responsibility"),
    ]
    patterns: list[dict[str, Any]] = []
    for pattern_type, triggers, reason in rules:
        matched = sorted({field for field in all_fields if field in triggers or any(field.endswith(f"_{trigger}") for trigger in triggers)})
        if matched:
            patterns.append({"type": pattern_type, "confidence": "high" if len(matched) > 1 else "medium", "fields": matched, "reason": reason})
    return patterns


def _compose_patterns(patterns: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], list[str]]:
    pattern_types = {str(row.get("type") or "") for row in patterns if isinstance(row, dict)}
    rules = [
        ("workflow_tracking", {"workflow_status", "ownership", "timeline_date"}, ["show_summary_metrics", "show_status_filters", "show_recent_activity"]),
        ("measurable_collection", {"metric_quantity", "classification"}, ["show_summary_metrics", "metric_emphasis", "grouped_lists"]),
        ("knowledge_collection", {"classification", "reference_link", "timeline_date"}, ["compact_metadata_cards", "metadata_emphasis", "external_link_rendering"]),
        ("ownership_workflow", {"ownership", "workflow_status"}, ["ownership_grouping", "workflow_grouping"]),
    ]
    composed: list[dict[str, Any]] = []
    hints: list[str] = []
    for name, required, ui_hints in rules:
        if not required.issubset(pattern_types):
            continue
        composed.append({"type": name, "source_patterns": sorted(required), "confidence": "high", "reason": f"{' + '.join(sorted(required))} patterns compose {name}"})
        for hint in ui_hints:
            if hint not in hints:
                hints.append(hint)
    return composed, hints


def plan_project_spec_from_idea(idea: str, base_spec: dict[str, Any] | None = None) -> dict[str, Any]:
    out: dict[str, Any] = copy.deepcopy(base_spec) if isinstance(base_spec, dict) else {}
    plan = _select_plan(idea, out)
    if not plan:
        return out

    max_entities = 4
    for entity in plan.get("entities") if isinstance(plan.get("entities"), list) else []:
        if isinstance(entity, dict):
            _merge_entity(out, entity, max_entities=max_entities)

    entity_rows = [row for row in (out.get("entities") if isinstance(out.get("entities"), list) else []) if isinstance(row, dict)]
    entity_names = {str(row.get("name") or "").strip().lower() for row in entity_rows if str(row.get("name") or "").strip()}

    relationships = [rel for rel in (out.get("relationships") if isinstance(out.get("relationships"), list) else []) if isinstance(rel, dict)]
    normalized_relationships = [_normalize_relationship(rel) for rel in relationships]
    seen_rels = {
        (rel.get("from_entity", "").lower(), rel.get("to_entity", "").lower(), rel.get("field", "").lower())
        for rel in normalized_relationships
        if rel
    }
    for raw_rel in plan.get("relationships") if isinstance(plan.get("relationships"), list) else []:
        if not isinstance(raw_rel, dict):
            continue
        rel = _normalize_relationship(raw_rel)
        if not rel:
            continue
        if rel["from_entity"].lower() not in entity_names or rel["to_entity"].lower() not in entity_names:
            continue
        key = (rel["from_entity"].lower(), rel["to_entity"].lower(), rel["field"].lower())
        if key in seen_rels:
            continue
        normalized_relationships.append(rel)
        seen_rels.add(key)
    if normalized_relationships:
        out["relationships"] = normalized_relationships[:12]

    resources = []
    api_endpoints = []
    frontend_pages = []
    apis = []
    pages = []
    for entity in entity_rows:
        entity_name = str(entity.get("name") or "").strip()
        _, plural = _entity_slug_and_plural(entity_name)
        if not plural:
            continue
        resources.append(plural)
        for method, path in (
            ("GET", f"/{plural}"),
            ("POST", f"/{plural}"),
            ("GET", f"/{plural}/{{id}}"),
            ("PATCH", f"/{plural}/{{id}}"),
            ("DELETE", f"/{plural}/{{id}}"),
        ):
            endpoint = f"{method} {path}"
            api_endpoints.append(endpoint)
            apis.append({"method": method, "path": path})
        for rel in ("list", "new", "detail"):
            frontend_pages.append(f"{plural}/{rel}")
        pages.extend({"path": path} for path in (plural, f"{plural}/new", f"{plural}/[id]"))

    out["resources"] = _append_unique(out.get("resources") if isinstance(out.get("resources"), list) else [], resources, lambda item: str(item).strip().lower())
    out["api_endpoints"] = _append_unique(out.get("api_endpoints") if isinstance(out.get("api_endpoints"), list) else [], api_endpoints, lambda item: str(item).strip().lower())[:24]
    out["frontend_pages"] = _append_unique(out.get("frontend_pages") if isinstance(out.get("frontend_pages"), list) else [], frontend_pages, lambda item: str(item).strip().lower())[:24]
    out["apis"] = _append_unique(out.get("apis") if isinstance(out.get("apis"), list) else [], apis, lambda item: f"{str(item.get('method') or '').upper()} {str(item.get('path') or '').lower()}" if isinstance(item, dict) else "")[:24]
    out["pages"] = _append_unique(out.get("pages") if isinstance(out.get("pages"), list) else [], pages, lambda item: str(item.get("path") or "").lower() if isinstance(item, dict) else "")[:24]

    patterns = _infer_patterns(entity_rows)
    composed_patterns, ui_hints = _compose_patterns(patterns)
    if patterns:
        out["patterns"] = patterns
    if composed_patterns:
        out["composed_patterns"] = composed_patterns
    if ui_hints:
        out["ui_hints"] = ui_hints
    return out


def infer_domain_model(idea: str | None, reasoning: dict[str, Any] | None = None) -> dict[str, Any]:
    plan = _select_plan(idea, reasoning)
    if not plan:
        return {"entities": [], "relationships": []}
    planned = plan_project_spec_from_idea(str(idea or ""), {"domains": list((reasoning or {}).get("domains") or []) if isinstance(reasoning, dict) else []})
    return {
        "entities": [row for row in (planned.get("entities") or []) if isinstance(row, dict)],
        "relationships": [row for row in (planned.get("relationships") or []) if isinstance(row, dict)],
    }
