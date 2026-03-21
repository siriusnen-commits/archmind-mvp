from __future__ import annotations

from archmind.next_suggester import analyze_spec_progression
from archmind.telegram_bot import (
    _ensure_evolution_block,
    _normalize_api_endpoint,
    _normalize_api_endpoint_text,
    _normalize_entities,
    _normalize_frontend_page_path,
    summarize_recent_evolution,
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


def test_analyze_spec_progression_stage_0() -> None:
    p = analyze_spec_progression({"entities": [], "api_endpoints": [], "frontend_pages": []})
    assert p["stage"] == 0
    assert p["entities_count"] == 0
    assert p["apis_count"] == 0
    assert p["pages_count"] == 0


def test_analyze_spec_progression_stage_1() -> None:
    p = analyze_spec_progression({"entities": [{"name": "Note", "fields": []}], "api_endpoints": [], "frontend_pages": []})
    assert p["stage"] == 1
    assert p["first_entity_without_fields"] == "Note"


def test_analyze_spec_progression_stage_2() -> None:
    p = analyze_spec_progression(
        {
            "entities": [{"name": "Note", "fields": [{"name": "title", "type": "string"}]}],
            "api_endpoints": [],
            "frontend_pages": [],
        }
    )
    assert p["stage"] == 2


def test_analyze_spec_progression_stage_3() -> None:
    p = analyze_spec_progression(
        {
            "shape": "fullstack",
            "entities": [{"name": "Note", "fields": [{"name": "title", "type": "string"}]}],
            "api_endpoints": ["GET /notes", "POST /notes"],
            "frontend_pages": [],
        }
    )
    assert p["stage"] == 3


def test_analyze_spec_progression_stage_4() -> None:
    p = analyze_spec_progression(
        {
            "shape": "fullstack",
            "entities": [{"name": "Note", "fields": [{"name": "title", "type": "string"}]}],
            "api_endpoints": ["GET /notes", "POST /notes"],
            "frontend_pages": ["notes/list", "notes/detail"],
        }
    )
    assert p["stage"] == 4


def test_analyze_spec_progression_stage_0_even_with_api_and_pages() -> None:
    p = analyze_spec_progression(
        {
            "shape": "fullstack",
            "entities": [],
            "api_endpoints": ["GET /notes", "POST /notes"],
            "frontend_pages": ["notes/list", "notes/detail"],
        }
    )
    assert p["stage"] == 0


def test_analyze_spec_progression_stage_1_even_with_api_and_pages() -> None:
    p = analyze_spec_progression(
        {
            "shape": "fullstack",
            "entities": [{"name": "Note", "fields": []}],
            "api_endpoints": ["GET /notes", "POST /notes"],
            "frontend_pages": ["notes/list", "notes/detail"],
        }
    )
    assert p["stage"] == 1


def test_summarize_recent_evolution_formats_primitive_actions() -> None:
    history = [
        {"action": "add_entity", "entity": "Note"},
        {"action": "add_field", "entity": "Note", "field": "title", "type": "string"},
        {"action": "add_api", "method": "GET", "path": "/notes"},
        {"action": "add_page", "page": "notes/list"},
    ]
    lines = summarize_recent_evolution({"evolution": {"history": history}}, limit=5)
    assert lines == [
        "add_entity Note",
        "add_field Note title:string",
        "add_api GET /notes",
        "add_page notes/list",
    ]


def test_summarize_recent_evolution_applies_limit_to_latest_entries() -> None:
    history = [
        {"action": "add_entity", "entity": "Task"},
        {"action": "add_field", "entity": "Task", "field": "title", "type": "string"},
        {"action": "add_api", "method": "GET", "path": "/tasks"},
        {"action": "add_page", "page": "tasks/list"},
    ]
    lines = summarize_recent_evolution({"evolution": {"history": history}}, limit=2)
    assert lines == [
        "add_api GET /tasks",
        "add_page tasks/list",
    ]


def test_summarize_recent_evolution_returns_empty_for_missing_history() -> None:
    assert summarize_recent_evolution({"evolution": {"history": []}}, limit=5) == []
