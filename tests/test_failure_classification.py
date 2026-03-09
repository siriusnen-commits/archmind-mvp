from __future__ import annotations

from archmind.failure import classify_failure, fix_strategy_for_class
from archmind.fixer import _build_fix_prompt


def test_classify_assertion_error() -> None:
    excerpt = "FAILED tests/test_api.py::test_create\nAssertionError: expected 200 got 500"
    assert classify_failure(excerpt, "backend-pytest:FAIL") == "backend-pytest:assertion"


def test_classify_module_not_found() -> None:
    excerpt = "ModuleNotFoundError: No module named 'app.services.todo'"
    assert classify_failure(excerpt, "backend-pytest:FAIL") == "backend-pytest:module-not-found"


def test_classify_import_error() -> None:
    excerpt = "ImportError: cannot import name 'Query' from 'fastapi'"
    assert classify_failure(excerpt, "backend-pytest:FAIL") == "backend-pytest:import"


def test_classify_frontend_lint() -> None:
    excerpt = "ESLint: Parsing error in frontend/app/page.tsx"
    assert classify_failure(excerpt, "frontend-lint:FAIL") == "frontend-lint"


def test_classify_frontend_typescript() -> None:
    excerpt = "TS2322: Type 'string' is not assignable to type 'number'"
    assert classify_failure(excerpt, "frontend-typescript:FAIL") == "frontend-typescript"


def test_classify_frontend_build() -> None:
    excerpt = "next build failed to compile"
    assert classify_failure(excerpt, "frontend-build:FAIL") == "frontend-build"


def test_fix_prompt_specializes_by_failure_class() -> None:
    failure_class = classify_failure(
        "ModuleNotFoundError: No module named 'app.core.settings'",
        "backend-pytest:FAIL",
    )
    prompt = _build_fix_prompt(
        command="archmind fix --path /tmp/project --scope backend",
        plan_lines=["- step: fix import"],
        task_line="[1] doing API test fix",
        evaluation_status="NOT_DONE",
        state_lines=["- last_status: FAIL"],
        summary_lines=["- ModuleNotFoundError: No module named app.core.settings"],
        failure_details={"test_name": None, "file_path": "tests/test_api.py", "stack_top": [], "stack_bottom": []},
        files_hint=["tests/test_api.py"],
        scope="backend",
        frontend_error_lines=[],
        failure_class=failure_class,
        fix_strategy=fix_strategy_for_class(failure_class),
        failure_excerpt="ModuleNotFoundError: No module named app.core.settings",
    )
    assert "Failure Classification" in prompt
    assert "class: backend-pytest:module-not-found" in prompt
    assert "누락된 import/module/dependency를 먼저 해결하라" in prompt
