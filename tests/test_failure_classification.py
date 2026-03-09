from __future__ import annotations

from pathlib import Path

from archmind.failure import (
    classify_failure,
    extract_failure_location_context,
    extract_core_failure_lines,
    extract_failure_excerpt,
    filter_secondary_noise,
    filter_noise_lines,
    fix_strategy_for_class,
    is_safe_repair_target,
    select_primary_failure_class,
    select_repair_targets,
)
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
        repair_targets=["requirements.txt"],
    )
    assert "Failure Classification" in prompt
    assert "class: backend-pytest:module-not-found" in prompt
    assert "누락된 import/module/dependency를 먼저 해결하라" in prompt
    assert "Repair targets: requirements.txt" in prompt
    assert "표준 라이브러리/외부 환경 파일은 수정하지 말라." in prompt


def test_module_not_found_excerpt_removes_frontend_noise_and_targets_requirements() -> None:
    excerpt = extract_failure_excerpt(
        [
            "ModuleNotFoundError: No module named 'fastapi'",
            "Base",
            "Cancel",
            "ESLint: Parsing error in frontend/app/page.tsx",
            "Traceback:",
            "FAILED tests/test_api.py::test_create",
        ],
        failure_class="backend-pytest:module-not-found",
        max_lines=6,
    )
    assert "ModuleNotFoundError: No module named 'fastapi'" in excerpt
    assert "ESLint" not in excerpt
    assert "Base" not in excerpt
    assert "Traceback:" not in excerpt
    targets = select_repair_targets(
        "backend-pytest:module-not-found",
        excerpt,
        Path("/tmp/project"),
        files_hint=["tests/test_api.py", "app/main.py"],
    )
    assert "requirements.txt" in targets
    assert "tests/test_api.py" not in targets


def test_frontend_lint_excerpt_removes_backend_noise_and_targets_frontend_file() -> None:
    excerpt = extract_failure_excerpt(
        [
            "AssertionError: expected 200 got 500",
            "ESLint: Parsing error",
            "frontend/app/page.tsx:12:1",
            "Traceback:",
        ],
        failure_class="frontend-lint",
        max_lines=6,
    )
    assert "ESLint: Parsing error" in excerpt
    assert "AssertionError" not in excerpt
    targets = select_repair_targets(
        "frontend-lint",
        excerpt,
        Path("/tmp/project"),
        files_hint=["frontend/app/page.tsx", "tests/test_api.py"],
    )
    assert any(t.startswith("frontend/") for t in targets)
    assert "tests/test_api.py" not in targets


def test_backend_assertion_prefers_implementation_not_test_file() -> None:
    targets = select_repair_targets(
        "backend-pytest:assertion",
        "AssertionError: expected 200 got 500\nFAILED tests/test_api.py::test_create",
        Path("/tmp/project"),
        files_hint=["tests/test_api.py", "app/api/routes/todo.py"],
    )
    assert "app/api/routes/todo.py" in targets
    assert "tests/test_api.py" not in targets


def test_primary_failure_class_prefers_backend_when_mixed_signature() -> None:
    primary = select_primary_failure_class(
        "backend-pytest+frontend-lint:FAIL",
        "unknown",
    )
    assert primary == "backend-pytest:other"


def test_excerpt_keeps_core_error_body_for_fastapi_module_not_found() -> None:
    excerpt = extract_failure_excerpt(
        [
            "Traceback:",
            "=========================== short test summary info ============================",
            "E ModuleNotFoundError: No module named 'fastapi'",
            "tests/test_defects.py:1: in <module>",
            "from fastapi.testclient import TestClient",
            "Base",
            "Cancel",
        ],
        failure_class="backend-pytest:module-not-found",
        max_lines=6,
    )
    assert "E ModuleNotFoundError: No module named 'fastapi'" in excerpt
    assert "tests/test_defects.py:1: in <module>" in excerpt
    assert "short test summary info" not in excerpt.lower()
    assert "Traceback:" not in excerpt


def test_is_safe_repair_target_blocks_external_system_paths() -> None:
    root = Path("/tmp/project")
    assert is_safe_repair_target("requirements.txt", root) is True
    assert is_safe_repair_target("../../.pyenv/versions/3.11.7/lib/python3.11/importlib/__init__.py", root) is False
    assert is_safe_repair_target("/usr/lib/python3.11/importlib/__init__.py", root) is False
    assert is_safe_repair_target("/opt/homebrew/lib/python3.11/site-packages/fastapi/__init__.py", root) is False


def test_select_repair_targets_excludes_pyenv_path() -> None:
    targets = select_repair_targets(
        "backend-pytest:import",
        "ImportError: cannot import name Query",
        Path("/tmp/project"),
        files_hint=[
            "../../.pyenv/versions/3.11.7/lib/python3.11/importlib/__init__.py",
            "app/main.py",
        ],
    )
    assert "app/main.py" in targets
    assert "requirements.txt" in targets
    assert not any(".pyenv" in t for t in targets)


def test_backend_failure_excerpt_drops_frontend_base_cancel_noise() -> None:
    excerpt = extract_failure_excerpt(
        [
            "E ModuleNotFoundError: No module named 'fastapi'",
            "Base",
            "Cancel",
            "How would you like to configure ESLint?",
            "ESLint: Parsing error ...",
        ],
        failure_class="backend-pytest:module-not-found",
        max_lines=6,
    )
    assert "ModuleNotFoundError" in excerpt
    assert "ESLint" not in excerpt
    assert "Base" not in excerpt
    assert "Cancel" not in excerpt


def test_frontend_failure_excerpt_drops_backend_traceback_noise() -> None:
    excerpt = extract_failure_excerpt(
        [
            "Traceback:",
            "AssertionError: expected 200 got 500",
            "ESLint: Parsing error ...",
            "frontend/app/page.tsx:12:1",
        ],
        failure_class="frontend-lint",
        max_lines=6,
    )
    assert "ESLint: Parsing error" in excerpt
    assert "AssertionError" not in excerpt
    assert "Traceback:" not in excerpt


def test_assertion_excerpt_keeps_assertion_and_failed_lines() -> None:
    excerpt = extract_failure_excerpt(
        [
            "Traceback:",
            "E AssertionError: expected 200 got 500",
            "FAILED tests/test_api.py::test_create_todo - assert 500 == 200",
            "=========================== short test summary info ============================",
        ],
        failure_class="backend-pytest:assertion",
        max_lines=4,
    )
    assert "AssertionError" in excerpt
    assert "FAILED tests/test_api.py::test_create_todo" in excerpt


def test_frontend_typescript_excerpt_drops_backend_noise() -> None:
    excerpt = extract_failure_excerpt(
        [
            "Traceback:",
            "ModuleNotFoundError: No module named 'fastapi'",
            "TS2322: Type 'string' is not assignable to type 'number'",
            "frontend/app/page.tsx:18:5",
        ],
        failure_class="frontend-typescript",
        max_lines=4,
    )
    assert "TS2322" in excerpt
    assert "frontend/app/page.tsx:18:5" in excerpt
    assert "ModuleNotFoundError" not in excerpt


def test_core_line_extractor_prefers_real_errors() -> None:
    lines = extract_core_failure_lines(
        "Traceback:\nE ModuleNotFoundError: No module named 'fastapi'\nFAILED tests/test_defects.py::test_x\n",
        failure_class="backend-pytest:module-not-found",
        max_lines=3,
    )
    joined = "\n".join(lines)
    assert "ModuleNotFoundError" in joined
    assert "FAILED tests/test_defects.py::test_x" in joined


def test_filter_noise_lines_removes_frontend_prompt_for_backend() -> None:
    lines = filter_noise_lines(
        [
            "How would you like to configure ESLint?",
            "Base",
            "Cancel",
            "E ModuleNotFoundError: No module named 'fastapi'",
        ],
        failure_class="backend-pytest:module-not-found",
    )
    joined = "\n".join(lines)
    assert "ModuleNotFoundError" in joined
    assert "How would you like to configure ESLint?" not in joined
    assert "Base" not in joined
    assert "Cancel" not in joined


def test_extract_failure_location_context_backend_removes_frontend_noise() -> None:
    text = "\n".join(
        [
            "E   ModuleNotFoundError: No module named 'fastapi'",
            "tests/test_defects.py:1: in <module>",
            "from fastapi.testclient import TestClient",
            "? How would you like to configure ESLint?",
            "Strict (recommended)",
            "Base",
            "Cancel",
            "If you set up ESLint yourself, we recommend adding the Next.js ESLint plugin",
        ]
    )
    lines = extract_failure_location_context(text, failure_class="backend-pytest:module-not-found", max_lines=8)
    joined = "\n".join(lines)
    assert "ModuleNotFoundError" in joined
    assert "tests/test_defects.py:1: in <module>" in joined
    assert "How would you like to configure ESLint" not in joined
    assert "Base" not in joined
    assert "Cancel" not in joined


def test_extract_failure_location_context_backend_assertion_compact() -> None:
    text = "\n".join(
        [
            "Traceback:",
            "E   AssertionError: expected 200 got 500",
            "FAILED tests/test_api.py::test_create_todo - assert 500 == 200",
            "=========================== short test summary info ============================",
        ]
    )
    lines = extract_failure_location_context(text, failure_class="backend-pytest:assertion", max_lines=6)
    joined = "\n".join(lines)
    assert "AssertionError" in joined
    assert "FAILED tests/test_api.py::test_create_todo" in joined
    assert "short test summary info" not in joined.lower()


def test_extract_failure_location_context_frontend_removes_backend_trace() -> None:
    text = "\n".join(
        [
            "Traceback:",
            "E   ModuleNotFoundError: No module named 'fastapi'",
            "tests/test_defects.py:1: in <module>",
            "ESLint: Parsing error ...",
            "frontend/app/page.tsx:12:1",
        ]
    )
    lines = extract_failure_location_context(text, failure_class="frontend-lint", max_lines=6)
    joined = "\n".join(lines)
    assert "ESLint: Parsing error" in joined
    assert "frontend/app/page.tsx:12:1" in joined
    assert "ModuleNotFoundError" not in joined


def test_fix_prompt_failure_location_section_is_primary_specific() -> None:
    prompt = _build_fix_prompt(
        command="archmind fix --path /tmp/project --scope backend",
        plan_lines=["- step: fix import"],
        task_line="[1] doing API test fix",
        evaluation_status="NOT_DONE",
        state_lines=["- last_status: FAIL"],
        summary_lines=["- backend pytest failed"],
        failure_details={
            "test_name": "tests/test_defects.py",
            "file_path": "tests/test_defects.py",
            "stack_top": [
                "tests/test_defects.py:1: in <module>",
                "E   ModuleNotFoundError: No module named 'fastapi'",
            ],
            "stack_bottom": [],
        },
        files_hint=["tests/test_defects.py"],
        scope="backend",
        frontend_error_lines=[],
        failure_class="backend-pytest:module-not-found",
        fix_strategy="backend-import-resolution",
        failure_excerpt="E ModuleNotFoundError: No module named 'fastapi'",
        repair_targets=["requirements.txt"],
    )
    assert "# 실패 지점" in prompt
    assert "실패한 테스트: tests/test_defects.py" in prompt
    assert "ModuleNotFoundError: No module named 'fastapi'" in prompt
    assert "How would you like to configure ESLint" not in prompt
