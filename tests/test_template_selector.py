from __future__ import annotations

import json
from pathlib import Path

from archmind.state import format_state_text
from archmind.template_selector import (
    get_supported_templates,
    resolve_effective_template,
    select_template_for_project_type,
)


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


def test_supported_template_keeps_effective_equal_selected() -> None:
    effective, reason = resolve_effective_template("fastapi", "fullstack-ddd")
    assert effective == "fastapi"
    assert reason is None


def test_unsupported_template_falls_back_to_default_with_reason() -> None:
    effective, reason = resolve_effective_template("cli", "fastapi-ddd")
    assert effective == "fastapi-ddd"
    assert reason is not None
    assert "cli template not supported" in reason
    assert "using default template 'fastapi-ddd'" in reason


def test_supported_templates_truthy() -> None:
    supported = get_supported_templates()
    assert "fastapi" in supported
    assert "fastapi-ddd" in supported
    assert "fullstack-ddd" in supported
    assert "nextjs" in supported


def test_state_shows_selected_template_from_result(tmp_path: Path) -> None:
    archmind = tmp_path / ".archmind"
    archmind.mkdir(parents=True, exist_ok=True)
    (archmind / "result.json").write_text(
        json.dumps(
            {
                "status": "SUCCESS",
                "project_type": "backend-api",
                "selected_template": "fastapi",
                "effective_template": "fastapi-ddd",
                "template_fallback_reason": "fastapi template not supported; using default template 'fastapi-ddd'",
            }
        ),
        encoding="utf-8",
    )
    output = format_state_text(tmp_path)
    assert "Project type: backend-api" in output
    assert "Selected template: fastapi" in output
    assert "Effective template: fastapi-ddd" in output
    assert "Template fallback: fastapi template not supported; using default template 'fastapi-ddd'" in output
