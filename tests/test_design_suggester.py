from __future__ import annotations

from archmind.design_suggester import build_architecture_design


def test_build_architecture_design_infers_domains_entities_and_relationships() -> None:
    idea = "tv hardware qa defect tracker with dashboard and team collaboration"
    reasoning = {
        "app_shape": "fullstack",
        "recommended_template": "fullstack-ddd",
        "modules": ["db", "dashboard"],
        "domains": ["defects", "teams"],
        "dashboard_needed": True,
        "frontend_needed": True,
        "reason_summary": "fullstack app for defects, teams with db, dashboard",
    }
    suggestion = {
        "entities": [
            {"name": "Device", "fields": [{"name": "model_name", "type": "string"}]},
            {"name": "TestRun", "fields": [{"name": "result", "type": "string"}]},
            {"name": "Defect", "fields": [{"name": "title", "type": "string"}]},
            {"name": "Team", "fields": [{"name": "name", "type": "string"}]},
        ],
        "api_endpoints": ["GET /devices", "POST /devices", "GET /defects", "POST /defects"],
        "frontend_pages": ["defects/list", "devices/list"],
    }
    out = build_architecture_design(idea, reasoning, suggestion)

    assert out["shape"] == "fullstack"
    assert out["template"] == "fullstack-ddd"
    assert "devices" in out["domains"]
    assert "test runs" in out["domains"]
    assert "defects" in out["domains"]
    assert "teams" in out["domains"]
    assert "Device has many TestRuns" in out["relationships"]
    assert "TestRun may have many Defects" in out["relationships"]
    assert "Team manages Defects" in out["relationships"]
    assert "dashboard/home" in out["frontend_pages"]


def test_build_architecture_design_keeps_frontend_empty_for_backend_only() -> None:
    idea = "simple defect api"
    reasoning = {
        "app_shape": "backend",
        "recommended_template": "fastapi",
        "modules": ["db"],
        "domains": ["defects"],
        "dashboard_needed": False,
        "frontend_needed": False,
        "reason_summary": "backend api for defects",
    }
    suggestion = {
        "entities": [{"name": "Defect", "fields": [{"name": "title", "type": "string"}]}],
        "api_endpoints": ["GET /defects", "POST /defects"],
        "frontend_pages": [],
    }
    out = build_architecture_design(idea, reasoning, suggestion)

    assert out["frontend_pages"] == []
    assert out["api_endpoints"] == ["GET /defects", "POST /defects"]


def test_build_architecture_design_diary_keeps_conventions_and_avoids_unjustified_user() -> None:
    idea = "personal diary app"
    reasoning = {
        "app_shape": "fullstack",
        "recommended_template": "fullstack-ddd",
        "modules": ["db"],
        "domains": ["entries"],
        "frontend_needed": True,
        "auth_needed": False,
        "reason_summary": "fullstack diary app with persistence",
    }
    suggestion = {
        "entities": [
            {"name": "Entry", "fields": [{"name": "title", "type": "string"}]},
            {"name": "User", "fields": [{"name": "email", "type": "string"}]},
        ],
        "api_endpoints": ["get /entry", "POST /entry"],
        "frontend_pages": ["entry/list", "entry/create"],
    }
    out = build_architecture_design(idea, reasoning, suggestion)

    names = [str(entity.get("name")) for entity in (out.get("entities") or []) if isinstance(entity, dict)]
    assert "Entry" in names
    assert "User" not in names
    assert "GET /entries" in (out.get("api_endpoints") or [])
    assert "POST /entries" in (out.get("api_endpoints") or [])
    assert "entries/list" in (out.get("frontend_pages") or [])
    assert "entries/new" in (out.get("frontend_pages") or [])
