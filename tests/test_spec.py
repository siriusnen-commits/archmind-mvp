from __future__ import annotations

from archmind.telegram_bot import _ensure_evolution_block, _normalize_entities


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
