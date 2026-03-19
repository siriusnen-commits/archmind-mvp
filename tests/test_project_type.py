from __future__ import annotations

import json
from pathlib import Path

from archmind.project_type import detect_project_type
from archmind.state import format_state_text


def test_detect_project_type_backend_api() -> None:
    assert detect_project_type("simple fastapi notes api") == "backend-api"


def test_detect_project_type_frontend_web() -> None:
    assert detect_project_type("simple nextjs counter dashboard") == "frontend-web"


def test_detect_project_type_fullstack_web() -> None:
    idea = "fullstack todo app with fastapi backend and nextjs frontend"
    assert detect_project_type(idea) == "fullstack-web"


def test_detect_project_type_cli_tool() -> None:
    assert detect_project_type("python cli tool for csv merge") == "cli-tool"


def test_detect_project_type_automation_script() -> None:
    assert detect_project_type("telegram automation script for reminders") == "automation-script"


def test_detect_project_type_internal_tool() -> None:
    assert detect_project_type("internal admin dashboard for device status") == "internal-tool"


def test_detect_project_type_worker_api() -> None:
    assert detect_project_type("background batch processing api") == "worker-api"


def test_detect_project_type_data_tool() -> None:
    assert detect_project_type("inventory management tool for small business") == "data-tool"


def test_detect_project_type_unknown() -> None:
    assert detect_project_type("something helpful for teams") == "unknown"


def test_detect_project_type_webapp_keywords_force_fullstack() -> None:
    idea = "개인용 블로그형식의 다이어리 webapp"
    assert detect_project_type(idea) == "fullstack-web"


def test_state_shows_project_type_from_result(tmp_path: Path) -> None:
    archmind = tmp_path / ".archmind"
    archmind.mkdir(parents=True, exist_ok=True)
    (archmind / "result.json").write_text(
        json.dumps({"status": "SUCCESS", "project_type": "backend-api"}),
        encoding="utf-8",
    )
    output = format_state_text(tmp_path)
    assert "Project type: backend-api" in output
