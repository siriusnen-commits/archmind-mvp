from __future__ import annotations

import pytest

from archmind.brain import reason_architecture_from_idea
from tests.brain_cases import BRAIN_CASES


@pytest.mark.parametrize("case", BRAIN_CASES, ids=[case["idea"] for case in BRAIN_CASES])
def test_reason_architecture_cases(case: dict[str, object]) -> None:
    idea = str(case["idea"])
    expected_shape = str(case["expected_shape"])
    expected_template = str(case["expected_template"])
    expected_domains = [str(x) for x in (case.get("expected_domains") or [])]

    out = reason_architecture_from_idea(idea)

    assert out["app_shape"] == expected_shape, (
        f"idea={idea}\nexpected_shape={expected_shape}\nactual_shape={out.get('app_shape')}"
    )
    assert out["recommended_template"] == expected_template, (
        f"idea={idea}\nexpected_template={expected_template}\nactual_template={out.get('recommended_template')}"
    )
    if expected_domains:
        actual_domains = [str(x) for x in out.get("domains", [])]
        assert any(domain in actual_domains for domain in expected_domains), (
            f"idea={idea}\nexpected_domains(any)={expected_domains}\nactual_domains={actual_domains}"
        )


def test_reason_architecture_realtime_signal() -> None:
    out = reason_architecture_from_idea("realtime multiplayer web game")
    assert out["realtime_needed"] is True


def test_reason_architecture_modules_auth_db_dashboard() -> None:
    out = reason_architecture_from_idea("team task tracker with login dashboard")
    modules = list(out.get("modules") or [])
    assert "auth" in modules
    assert "db" in modules
    assert "dashboard" in modules


def test_reason_architecture_modules_file_upload_and_internal_tool_signal() -> None:
    out = reason_architecture_from_idea("document upload admin tool")
    modules = list(out.get("modules") or [])
    assert "file-upload" in modules
    assert ("dashboard" in modules) or bool(out.get("internal_tool"))


def test_reason_architecture_modules_worker() -> None:
    out = reason_architecture_from_idea("background batch processing api")
    modules = list(out.get("modules") or [])
    assert "worker" in modules


def test_reason_architecture_recommends_internal_tool_template() -> None:
    out = reason_architecture_from_idea("internal admin dashboard for device status")
    assert out["recommended_template"] == "internal-tool"


def test_reason_architecture_recommends_worker_api_template() -> None:
    out = reason_architecture_from_idea("background batch processing api")
    assert out["recommended_template"] == "worker-api"


def test_reason_architecture_recommends_data_tool_template() -> None:
    out = reason_architecture_from_idea("inventory management tool for small business")
    assert out["recommended_template"] == "data-tool"


def test_reason_architecture_unknown_fallback_defaults() -> None:
    out = reason_architecture_from_idea("hello")
    assert out["app_shape"] == "backend"
    assert out["recommended_template"] == "fastapi"
    assert out["modules"] == []
    assert out["db_needed"] is False
    assert out["dashboard_needed"] is False


def test_reason_architecture_simple_todo_app_defaults_to_fullstack() -> None:
    out = reason_architecture_from_idea("simple todo app")
    assert out["app_shape"] == "fullstack"
    assert out["recommended_template"] == "fullstack-ddd"
    assert out["frontend_needed"] is True
