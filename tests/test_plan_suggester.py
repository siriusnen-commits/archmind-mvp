from __future__ import annotations

from archmind.plan_suggester import build_plan_from_project_spec, build_plan_from_suggestion


def test_build_plan_from_suggestion_includes_all_core_phases() -> None:
    suggestion = {
        "entities": [
            {"name": "Defect", "fields": [{"name": "title", "type": "string"}, {"name": "status", "type": "string"}]},
            {"name": "Device", "fields": [{"name": "model_name", "type": "string"}]},
        ],
        "api_endpoints": ["GET /defects", "POST /defects"],
        "frontend_pages": ["defects/list", "defects/detail"],
    }
    out = build_plan_from_suggestion("defect tracker", {"app_shape": "fullstack"}, suggestion)
    phases = out.get("phases") or []
    titles = [p.get("title") for p in phases]
    assert "Core entities" in titles
    assert "Core fields" in titles
    assert "APIs" in titles
    assert "Frontend" in titles


def test_build_plan_from_project_spec_recommends_missing_steps() -> None:
    spec = {
        "shape": "fullstack",
        "modules": ["auth", "dashboard"],
        "entities": [{"name": "Task", "fields": [{"name": "title", "type": "string"}]}],
        "api_endpoints": ["GET /tasks"],
        "frontend_pages": [],
    }
    out = build_plan_from_project_spec(spec)
    all_steps = [step for phase in (out.get("phases") or []) for step in (phase.get("steps") or [])]
    assert "/add_entity User" in all_steps
    assert "/add_api GET /tasks/{id}" in all_steps
    assert "/add_page tasks/list" in all_steps
    assert "/add_page dashboard/home" in all_steps
    assert any(step.startswith("/add_field Task ") for step in all_steps)


def test_build_plan_from_project_spec_limits_total_steps() -> None:
    entities = [{"name": f"Entity{i}", "fields": [{"name": "name", "type": "string"}]} for i in range(20)]
    spec = {"shape": "fullstack", "modules": ["auth"], "entities": entities, "api_endpoints": [], "frontend_pages": []}
    out = build_plan_from_project_spec(spec)
    all_steps = [step for phase in (out.get("phases") or []) for step in (phase.get("steps") or [])]
    assert len(all_steps) <= 15

