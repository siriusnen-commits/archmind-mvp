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
