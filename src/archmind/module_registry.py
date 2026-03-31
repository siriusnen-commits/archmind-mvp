from __future__ import annotations

import re
from copy import deepcopy
from typing import Any


TAGGING_SIGNAL_WORDS = ("tag", "tags", "tagging", "label", "labels", "category", "categories")
SEARCH_SIGNAL_WORDS = ("search", "searchable", "find", "filter", "filtering", "keyword", "keywords")


MODULE_REGISTRY: dict[str, dict[str, Any]] = {
    "tagging": {
        "signals": TAGGING_SIGNAL_WORDS,
        "supported_families": {"diary_entries_v2", "bookmark_links", "memo_notes"},
    },
    "search": {
        "signals": SEARCH_SIGNAL_WORDS,
        "supported_families": {"diary_entries_v2", "bookmark_links", "memo_notes", "todo_tasks", "board_kanban"},
    },
}


def _has_word(text: str, word: str) -> bool:
    return bool(re.search(rf"\b{re.escape(str(word or '').strip().lower())}\b", str(text or "").strip().lower()))


def _has_any_word(text: str, words: tuple[str, ...]) -> bool:
    return any(_has_word(text, token) for token in words)


def _extend_unique(rows: list[str], incoming: list[str]) -> list[str]:
    out = [str(item).strip() for item in rows if str(item).strip()]
    seen = {item.lower() for item in out}
    for item in incoming:
        value = str(item).strip()
        if not value:
            continue
        key = value.lower()
        if key in seen:
            continue
        seen.add(key)
        out.append(value)
    return out


def _merge_entity_fields(
    base: dict[str, list[dict[str, str]]],
    incoming: dict[str, list[dict[str, str]]],
) -> dict[str, list[dict[str, str]]]:
    merged: dict[str, list[dict[str, str]]] = {
        str(name).strip(): [dict(field) for field in (rows or []) if isinstance(field, dict)]
        for name, rows in base.items()
        if str(name).strip()
    }
    for name, rows in incoming.items():
        entity_name = str(name).strip()
        if not entity_name:
            continue
        target_rows = merged.setdefault(entity_name, [])
        seen_fields = {
            str(field.get("name") or "").strip().lower()
            for field in target_rows
            if isinstance(field, dict) and str(field.get("name") or "").strip()
        }
        for row in rows if isinstance(rows, list) else []:
            if not isinstance(row, dict):
                continue
            field_name = str(row.get("name") or "").strip()
            field_type = str(row.get("type") or "").strip().lower()
            if not field_name or not field_type or field_name.lower() in seen_fields:
                continue
            target_rows.append({"name": field_name, "type": field_type})
            seen_fields.add(field_name.lower())
    return merged


def detect_modules(text: str, starter_family: str) -> list[str]:
    normalized = str(text or "").strip().lower()
    family = str(starter_family or "").strip().lower()
    selected: list[str] = []
    for module_name in ("tagging", "search"):
        definition = MODULE_REGISTRY.get(module_name) if isinstance(MODULE_REGISTRY.get(module_name), dict) else {}
        supported = {
            str(item).strip().lower()
            for item in (definition.get("supported_families") or set())
            if str(item).strip()
        }
        if family not in supported:
            continue
        signals = tuple(str(item).strip().lower() for item in (definition.get("signals") or ()) if str(item).strip())
        if signals and _has_any_word(normalized, signals):
            selected.append(module_name)
    return selected


def apply_modules_to_starter_profile(
    starter_profile: dict[str, Any],
    *,
    idea_text: str,
    frontend_needed: bool,
) -> dict[str, Any]:
    if not isinstance(starter_profile, dict) or not starter_profile:
        return {}

    profile = deepcopy(starter_profile)
    family = str(profile.get("family") or "").strip().lower()
    selected_modules = detect_modules(idea_text, family)
    profile["modules"] = selected_modules

    entities = [str(item).strip() for item in (profile.get("entities") or []) if str(item).strip()]
    entity_fields = profile.get("entity_fields") if isinstance(profile.get("entity_fields"), dict) else {}
    required_api_endpoints = [str(item).strip() for item in (profile.get("required_api_endpoints") or []) if str(item).strip()]
    required_frontend_pages = [str(item).strip() for item in (profile.get("required_frontend_pages") or []) if str(item).strip()]
    frontend_expectations = [
        str(item).strip() for item in (profile.get("required_frontend_expectations") or []) if str(item).strip()
    ]

    if "tagging" in selected_modules:
        if family == "diary_entries_v2":
            entities = _extend_unique(entities, ["Tag"])
            entity_fields = _merge_entity_fields(
                entity_fields,
                {"Tag": [{"name": "name", "type": "string"}, {"name": "entry_id", "type": "int"}]},
            )
            required_api_endpoints = _extend_unique(
                required_api_endpoints,
                [
                    "GET /tags",
                    "POST /tags",
                    "GET /tags/{id}",
                    "PATCH /tags/{id}",
                    "DELETE /tags/{id}",
                    "GET /entries/{id}/tags",
                ],
            )
            if frontend_needed:
                required_frontend_pages = _extend_unique(
                    required_frontend_pages,
                    ["tags/list", "tags/new", "tags/detail", "tags/by_entry"],
                )
        elif family == "bookmark_links":
            entities = _extend_unique(entities, ["Category"])
            entity_fields = _merge_entity_fields(
                entity_fields,
                {"Category": [{"name": "name", "type": "string"}, {"name": "bookmark_id", "type": "string"}]},
            )
            required_api_endpoints = _extend_unique(
                required_api_endpoints,
                [
                    "GET /categories",
                    "POST /categories",
                    "GET /categories/{id}",
                    "PATCH /categories/{id}",
                    "DELETE /categories/{id}",
                    "GET /bookmarks/{id}/categories",
                ],
            )
            if frontend_needed:
                required_frontend_pages = _extend_unique(
                    required_frontend_pages,
                    ["categories/list", "categories/new", "categories/detail", "categories/by_bookmark"],
                )
        elif family == "memo_notes":
            entities = _extend_unique(entities, ["Tag"])
            entity_fields = _merge_entity_fields(
                entity_fields,
                {"Tag": [{"name": "name", "type": "string"}, {"name": "note_id", "type": "string"}]},
            )
            required_api_endpoints = _extend_unique(
                required_api_endpoints,
                [
                    "GET /tags",
                    "POST /tags",
                    "GET /tags/{id}",
                    "PATCH /tags/{id}",
                    "DELETE /tags/{id}",
                    "GET /notes/{id}/tags",
                ],
            )
            if frontend_needed:
                required_frontend_pages = _extend_unique(
                    required_frontend_pages,
                    ["tags/list", "tags/new", "tags/detail", "tags/by_note"],
                )

    if "search" in selected_modules and frontend_needed:
        frontend_expectations = _extend_unique(
            frontend_expectations,
            [
                "list_search_input",
                "search_empty_state",
                "search_readable_list",
            ],
        )

    profile["entities"] = entities
    profile["entity_fields"] = entity_fields
    profile["required_api_endpoints"] = required_api_endpoints
    profile["required_frontend_pages"] = required_frontend_pages if frontend_needed else []
    profile["required_frontend_expectations"] = frontend_expectations
    return profile
