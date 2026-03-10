from __future__ import annotations

import json
from pathlib import Path

from archmind.state import format_state_text
from archmind.template_selector import select_template_for_project_type


def test_select_template_backend_api() -> None:
    assert select_template_for_project_type("backend-api") == "fastapi"


def test_select_template_frontend_web() -> None:
    assert select_template_for_project_type("frontend-web") == "nextjs"


def test_select_template_fullstack_web() -> None:
    assert select_template_for_project_type("fullstack-web") == "fullstack-ddd"


def test_select_template_cli_tool() -> None:
    assert select_template_for_project_type("cli-tool") == "cli"


def test_select_template_automation_script() -> None:
    assert select_template_for_project_type("automation-script") == "automation"


def test_select_template_unknown_uses_default(monkeypatch) -> None:
    monkeypatch.setenv("ARCHMIND_DEFAULT_TEMPLATE", "fastapi-ddd")
    assert select_template_for_project_type("unknown") == "fastapi-ddd"


def test_state_shows_selected_template_from_result(tmp_path: Path) -> None:
    archmind = tmp_path / ".archmind"
    archmind.mkdir(parents=True, exist_ok=True)
    (archmind / "result.json").write_text(
        json.dumps(
            {
                "status": "SUCCESS",
                "project_type": "backend-api",
                "selected_template": "fastapi",
            }
        ),
        encoding="utf-8",
    )
    output = format_state_text(tmp_path)
    assert "Project type: backend-api" in output
    assert "Selected template: fastapi" in output
