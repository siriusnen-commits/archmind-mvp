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
