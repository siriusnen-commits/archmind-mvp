from __future__ import annotations

from archmind.brain import reason_architecture_from_idea


def test_reason_architecture_backend_fastapi() -> None:
    out = reason_architecture_from_idea("simple notes api with fastapi")
    assert out["app_shape"] == "backend"
    assert out["backend_needed"] is True
    assert out["recommended_template"] in ("fastapi", "fastapi-ddd")


def test_reason_architecture_fullstack_task_tracker() -> None:
    out = reason_architecture_from_idea("fullstack simple task tracker with fastapi backend and nextjs frontend")
    assert out["app_shape"] == "fullstack"
    assert out["backend_needed"] is True
    assert out["frontend_needed"] is True
    assert "tasks" in out["domains"]
    assert out["recommended_template"] == "fullstack-ddd"


def test_reason_architecture_expense_tracker_dashboard() -> None:
    out = reason_architecture_from_idea("expense tracker dashboard")
    assert "expenses" in out["domains"]
    assert out["frontend_needed"] is True or out["app_shape"] == "fullstack"


def test_reason_architecture_realtime_multiplayer() -> None:
    out = reason_architecture_from_idea("realtime multiplayer web game")
    assert out["realtime_needed"] is True


def test_reason_architecture_unknown_fallback() -> None:
    out = reason_architecture_from_idea("hello")
    assert out["app_shape"] == "unknown"
    assert out["recommended_template"] == "fastapi"
