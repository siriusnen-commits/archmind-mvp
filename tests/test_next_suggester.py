from __future__ import annotations

from archmind.next_suggester import suggest_next_commands


def _commands(spec: dict) -> list[str]:
    return [str(item.get("command") or "") for item in suggest_next_commands(spec, limit=5)]


def test_next_suggester_recommends_defect_title_and_status() -> None:
    spec = {
        "shape": "fullstack",
        "modules": [],
        "entities": [{"name": "Defect", "fields": [{"name": "severity", "type": "string"}]}],
        "api_endpoints": [],
        "frontend_pages": [],
    }
    cmds = _commands(spec)
    assert "/add_field Defect title:string" in cmds
    assert "/add_field Defect status:string" in cmds


def test_next_suggester_recommends_device_fields() -> None:
    spec = {
        "shape": "backend",
        "modules": [],
        "entities": [{"name": "Device", "fields": []}],
        "api_endpoints": [],
        "frontend_pages": [],
    }
    cmds = _commands(spec)
    assert "/add_field Device firmware_version:string" in cmds
    assert "/add_field Device model_name:string" in cmds


def test_next_suggester_recommends_testrun_fields() -> None:
    spec = {
        "shape": "backend",
        "modules": [],
        "entities": [{"name": "TestRun", "fields": []}],
        "api_endpoints": [],
        "frontend_pages": [],
    }
    cmds = _commands(spec)
    assert "/add_field TestRun result:string" in cmds
    assert "/add_field TestRun executed_at:datetime" in cmds


def test_next_suggester_recommends_missing_crud_and_timestamp_for_partial_note_api() -> None:
    spec = {
        "shape": "backend",
        "modules": [],
        "entities": [{"name": "Note", "fields": [{"name": "title", "type": "string"}]}],
        "api_endpoints": ["GET /notes", "POST /notes"],
        "frontend_pages": [],
    }
    cmds = _commands(spec)
    assert "/add_api PUT /notes/{id}" in cmds
    assert "/add_api DELETE /notes/{id}" in cmds
    assert "/add_field Note created_at:datetime" in cmds


def test_next_suggester_does_not_recommend_put_when_patch_update_exists() -> None:
    spec = {
        "shape": "backend",
        "modules": [],
        "entities": [{"name": "Task", "fields": [{"name": "title", "type": "string"}]}],
        "api_endpoints": ["PATCH /tasks/{id}"],
        "frontend_pages": [],
    }
    cmds = _commands(spec)
    assert "/add_api PUT /tasks/{id}" not in cmds
