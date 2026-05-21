from __future__ import annotations

import re
from typing import Any


PATTERN_FIELD_RULES: dict[str, tuple[set[str], str]] = {
    "workflow_status": (
        {"status", "state", "stage", "priority", "severity"},
        "status/priority fields indicate workflow tracking",
    ),
    "metric_quantity": (
        {"quantity", "qty", "stock", "stock_count", "count", "amount", "balance", "score", "value", "price", "cost", "unit_price"},
        "numeric metric fields indicate measurable tracking",
    ),
    "timeline_date": (
        {"date", "due_date", "deadline", "created_at", "updated_at", "scheduled_at", "started_at", "ended_at"},
        "date fields indicate timeline-oriented records",
    ),
    "classification": (
        {"category", "tag", "tags", "type", "group", "label", "labels"},
        "category/tag fields indicate grouping/filtering",
    ),
    "reference_link": (
        {"url", "link", "website", "email", "contact_email"},
        "url/email fields indicate external references or contacts",
    ),
    "ownership": (
        {"owner", "assignee", "created_by", "responsible", "contact"},
        "owner/assignee fields indicate responsibility tracking",
    ),
}

COMPOSED_PATTERN_RULES: list[dict[str, Any]] = [
    {
        "type": "workflow_tracking",
        "source_patterns": ["workflow_status", "ownership", "timeline_date"],
        "reason": "status + ownership + date fields imply workflow tracking",
        "ui_hints": ["show_summary_metrics", "show_status_filters", "show_recent_activity", "workflow_badges"],
    },
    {
        "type": "measurable_collection",
        "source_patterns": ["metric_quantity", "classification"],
        "reason": "metric + classification fields imply a measurable collection",
        "ui_hints": ["show_summary_metrics", "metric_emphasis", "grouped_lists"],
    },
    {
        "type": "knowledge_collection",
        "source_patterns": ["classification", "reference_link", "timeline_date"],
        "reason": "classification + reference + date fields imply a knowledge collection",
        "ui_hints": ["compact_metadata_cards", "metadata_emphasis", "external_link_rendering", "tags_chips"],
    },
    {
        "type": "ownership_workflow",
        "source_patterns": ["ownership", "workflow_status"],
        "reason": "ownership + status fields imply assigned workflow records",
        "ui_hints": ["assignee_emphasis", "ownership_grouping", "workflow_grouping"],
    },
]


def _field_key(value: Any) -> str:
    text = str(value or "").strip()
    if not text:
        return ""
    text = re.sub(r"(?<!^)(?=[A-Z])", "_", text)
    text = re.sub(r"[^a-zA-Z0-9]+", "_", text).strip("_").lower()
    return text


def _extract_entity_fields(spec: dict[str, Any]) -> list[tuple[str, list[str]]]:
    entities = spec.get("entities") if isinstance(spec.get("entities"), list) else []
    out: list[tuple[str, list[str]]] = []
    for entity in entities:
        if isinstance(entity, str):
            name = str(entity).strip()
            fields: list[str] = []
        elif isinstance(entity, dict):
            name = str(entity.get("name") or entity.get("entity") or "").strip()
            raw_fields = entity.get("fields") if isinstance(entity.get("fields"), list) else []
            fields = []
            for raw_field in raw_fields:
                if isinstance(raw_field, str):
                    field_name = raw_field.split(":", 1)[0].strip()
                elif isinstance(raw_field, dict):
                    field_name = str(raw_field.get("name") or raw_field.get("field") or "").strip()
                else:
                    field_name = ""
                key = _field_key(field_name)
                if key:
                    fields.append(key)
        else:
            continue
        if name:
            out.append((name, fields))
    return out


def _pattern_rows_for_fields(fields: list[str]) -> list[dict[str, Any]]:
    field_set = set(fields)
    rows: list[dict[str, Any]] = []
    for pattern_type, (triggers, reason) in PATTERN_FIELD_RULES.items():
        matched = [field for field in fields if field in triggers or any(field.endswith(f"_{trigger}") for trigger in triggers)]
        if not matched:
            continue
        confidence = "high" if len(set(matched)) >= 2 or pattern_type in {"timeline_date", "reference_link"} else "medium"
        if pattern_type == "workflow_status" and {"status", "state", "stage"} & field_set:
            confidence = "high"
        rows.append(
            {
                "type": pattern_type,
                "confidence": confidence,
                "fields": sorted(set(matched)),
                "reason": reason,
            }
        )
    return rows


def infer_app_patterns(spec: dict[str, Any], idea: str | None = None) -> list[dict[str, Any]]:
    del idea
    if not isinstance(spec, dict):
        return []
    entity_fields = _extract_entity_fields(spec)
    all_fields: list[str] = []
    for _, fields in entity_fields:
        all_fields.extend(fields)
    return _pattern_rows_for_fields(all_fields)


def infer_entity_patterns(entity: dict[str, Any]) -> list[dict[str, Any]]:
    if not isinstance(entity, dict):
        return []
    raw_fields = entity.get("fields") if isinstance(entity.get("fields"), list) else []
    fields: list[str] = []
    for raw_field in raw_fields:
        if isinstance(raw_field, str):
            field_name = raw_field.split(":", 1)[0].strip()
        elif isinstance(raw_field, dict):
            field_name = str(raw_field.get("name") or raw_field.get("field") or "").strip()
        else:
            field_name = ""
        key = _field_key(field_name)
        if key:
            fields.append(key)
    return _pattern_rows_for_fields(fields)


def _pattern_types(patterns: list[dict[str, Any]]) -> set[str]:
    return {
        str(pattern.get("type") or "").strip()
        for pattern in patterns
        if isinstance(pattern, dict) and str(pattern.get("type") or "").strip()
    }


def compose_app_patterns(
    patterns: list[dict[str, Any]],
    entities: list[dict[str, Any]],
    idea: str | None = None,
) -> dict[str, Any]:
    del idea
    if not isinstance(patterns, list):
        patterns = []
    if not isinstance(entities, list):
        entities = []

    app_pattern_types = _pattern_types(patterns)
    entity_patterns: dict[str, list[str]] = {}
    for entity in entities:
        if not isinstance(entity, dict):
            continue
        entity_name = str(entity.get("name") or entity.get("entity") or "").strip()
        if not entity_name:
            continue
        raw_entity_patterns = entity.get("patterns") if isinstance(entity.get("patterns"), list) else infer_entity_patterns(entity)
        entity_pattern_types = sorted(_pattern_types(raw_entity_patterns))
        if entity_pattern_types:
            entity_patterns[entity_name] = entity_pattern_types

    composed: list[dict[str, Any]] = []
    ui_hints: list[str] = []
    for rule in COMPOSED_PATTERN_RULES:
        source_patterns = [str(item) for item in rule.get("source_patterns", []) if str(item)]
        if not set(source_patterns).issubset(app_pattern_types):
            continue
        composed.append(
            {
                "type": str(rule.get("type") or ""),
                "source_patterns": source_patterns,
                "confidence": "high",
                "reason": str(rule.get("reason") or ""),
            }
        )
        for hint in rule.get("ui_hints", []):
            hint_text = str(hint or "").strip()
            if hint_text and hint_text not in ui_hints:
                ui_hints.append(hint_text)

    return {
        "app_patterns": composed,
        "entity_patterns": entity_patterns,
        "ui_hints": ui_hints,
    }
