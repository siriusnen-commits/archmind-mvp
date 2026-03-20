from __future__ import annotations

from archmind.telegram_bot import (
    _ensure_evolution_block,
    _normalize_api_endpoint,
    _normalize_api_endpoint_text,
    _normalize_entities,
    _normalize_frontend_page_path,
)


def test_normalize_entities_deduplicates_entities_and_fields_case_insensitive() -> None:
    normalized = _normalize_entities(
        [
            {"name": "note", "fields": [{"name": "Title", "type": "STRING"}, {"name": "title", "type": "string"}]},
            {"name": "Note", "fields": [{"name": "content", "type": "text"}]},
            "Task",
            "task",
        ]
    )
    assert normalized == [
        {"name": "Note", "fields": [{"name": "Title", "type": "string"}]},
        {"name": "Task", "fields": []},
    ]


def test_normalize_entities_skips_invalid_field_items() -> None:
    normalized = _normalize_entities(
        [
            {"name": "Note", "fields": [{"name": "", "type": "string"}, {"name": "title", "type": ""}, {"name": "ok", "type": "int"}]}
        ]
    )
    assert normalized == [{"name": "Note", "fields": [{"name": "ok", "type": "int"}]}]


def test_ensure_evolution_block_normalizes_defaults() -> None:
    spec: dict[str, object] = {"evolution": {"version": 0, "added_modules": ["db", "db"], "history": "bad"}}
    evolution = _ensure_evolution_block(spec)
    assert evolution["version"] == 1
    assert evolution["added_modules"] == ["db"]
    assert evolution["history"] == []


def test_normalize_api_endpoint_text_normalizes_method_and_path() -> None:
    assert _normalize_api_endpoint_text("get notes") == "GET /notes"
    assert _normalize_api_endpoint_text("POST   /notes") == "POST /notes"
    assert _normalize_api_endpoint_text("BAD /notes") == ""
    assert _normalize_api_endpoint_text("GET") == ""


def test_normalize_api_endpoint_returns_tuple() -> None:
    method, path, endpoint = _normalize_api_endpoint("patch", "notes/{id}")
    assert method == "PATCH"
    assert path == "/notes/{id}"
    assert endpoint == "PATCH /notes/{id}"


def test_normalize_frontend_page_path_trims_and_cleans() -> None:
    assert _normalize_frontend_page_path("/notes//list/") == "notes/list"
    assert _normalize_frontend_page_path("notes\\detail") == "notes/detail"
    assert _normalize_frontend_page_path("  ") == ""
