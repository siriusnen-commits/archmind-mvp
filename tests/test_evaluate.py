from __future__ import annotations

import json
from pathlib import Path

from archmind.cli import main
from archmind.evaluator import evaluate_project, normalize_failure_summary


def _write_tasks(root: Path, statuses: list[str]) -> None:
    archmind_dir = root / ".archmind"
    archmind_dir.mkdir(parents=True, exist_ok=True)
    payload = {
        "project_dir": str(root.resolve()),
        "created_at": "20260101_000000",
        "tasks": [
            {"id": i + 1, "title": f"task {i+1}", "status": status, "source": "plan", "notes": ""}
            for i, status in enumerate(statuses)
        ],
    }
    (archmind_dir / "tasks.json").write_text(json.dumps(payload), encoding="utf-8")


def _write_plan_with_acceptance(root: Path) -> None:
    archmind_dir = root / ".archmind"
    archmind_dir.mkdir(parents=True, exist_ok=True)
    (archmind_dir / "plan.json").write_text(
        json.dumps({"acceptance": ["python -m pytest -q passes"], "steps": ["step 1"]}),
        encoding="utf-8",
    )


def _write_coarse_plan(root: Path) -> None:
    archmind_dir = root / ".archmind"
    archmind_dir.mkdir(parents=True, exist_ok=True)
    (archmind_dir / "plan.json").write_text(
        json.dumps(
            {
                "acceptance": ["python -m pytest -q passes"],
                "steps": [
                    {"title": "현행 코드베이스 파악", "status": "todo"},
                    {"title": "핵심 수정 구현", "status": "todo"},
                    {"title": "회귀 검증", "status": "todo"},
                    {"title": "결과 정리", "status": "todo"},
                ],
            }
        ),
        encoding="utf-8",
    )


def _write_result(root: Path, status: str) -> None:
    archmind_dir = root / ".archmind"
    archmind_dir.mkdir(parents=True, exist_ok=True)
    (archmind_dir / "result.json").write_text(json.dumps({"status": status}), encoding="utf-8")


def _write_state(root: Path, payload: dict) -> None:
    archmind_dir = root / ".archmind"
    archmind_dir.mkdir(parents=True, exist_ok=True)
    (archmind_dir / "state.json").write_text(json.dumps(payload), encoding="utf-8")


def test_evaluate_done_when_all_conditions_met(tmp_path: Path) -> None:
    _write_tasks(tmp_path, ["done", "done"])
    _write_plan_with_acceptance(tmp_path)
    _write_result(tmp_path, "SUCCESS")

    payload = evaluate_project(tmp_path)
    assert payload["status"] == "DONE"
    assert payload["checks"]["tasks_complete"] is True
    assert payload["checks"]["run_status"] == "SUCCESS"
    assert payload["checks"]["acceptance_defined"] is True


def test_evaluate_not_done_when_pending_task_exists(tmp_path: Path) -> None:
    _write_tasks(tmp_path, ["done", "todo"])
    _write_plan_with_acceptance(tmp_path)
    _write_result(tmp_path, "SUCCESS")

    payload = evaluate_project(tmp_path)
    assert payload["status"] == "NOT_DONE"
    assert "pending tasks remain" in payload["reasons"]


def test_evaluate_reasons_include_failure_type_and_incomplete_task(tmp_path: Path) -> None:
    _write_tasks(tmp_path, ["done", "todo"])
    _write_plan_with_acceptance(tmp_path)
    _write_result(tmp_path, "FAIL")
    _write_state(
        tmp_path,
        {
            "project_dir": str(tmp_path.resolve()),
            "updated_at": "20260101_000000",
            "last_status": "NOT_DONE",
            "last_failure_signature": "frontend-lint:FAIL",
        },
    )

    payload = evaluate_project(tmp_path)
    assert payload["status"] == "NOT_DONE"
    assert "frontend lint failed" in payload["reasons"]
    assert "task 2 not complete" in payload["reasons"]


def test_evaluate_blocked_when_all_tasks_blocked(tmp_path: Path) -> None:
    _write_tasks(tmp_path, ["blocked", "blocked"])
    _write_plan_with_acceptance(tmp_path)
    _write_result(tmp_path, "FAIL")

    payload = evaluate_project(tmp_path)
    assert payload["status"] == "BLOCKED"
    assert "all tasks are blocked" in payload["reasons"]


def test_pipeline_creates_evaluation_json(tmp_path: Path) -> None:
    tmp_path.joinpath("pytest.ini").write_text("[pytest]\naddopts = -q\n", encoding="utf-8")
    tmp_path.joinpath("test_ok.py").write_text("def test_ok():\n    assert True\n", encoding="utf-8")

    exit_code = main(
        [
            "pipeline",
            "--path",
            str(tmp_path),
            "--backend-only",
            "--max-iterations",
            "1",
            "--model",
            "none",
        ]
    )
    assert exit_code == 0
    evaluation_path = tmp_path / ".archmind" / "evaluation.json"
    assert evaluation_path.exists()
    payload = json.loads(evaluation_path.read_text(encoding="utf-8"))
    assert payload["status"] in {"DONE", "NOT_DONE", "BLOCKED", "STUCK"}


def test_normalize_failure_summary_removes_path_noise() -> None:
    raw = "FAILED /Users/me/proj/tests/test_api.py::test_x at 20260309_120001 pid=1234"
    normalized = normalize_failure_summary(raw)
    assert "<path>" in normalized
    assert "pid" in normalized


def test_evaluate_detects_stuck_on_repeated_failure(tmp_path: Path) -> None:
    _write_tasks(tmp_path, ["doing", "todo"])
    _write_plan_with_acceptance(tmp_path)
    _write_result(tmp_path, "FAIL")
    _write_state(
        tmp_path,
        {
            "project_dir": str(tmp_path.resolve()),
            "updated_at": "20260101_000000",
            "iterations": 4,
            "current_task_id": 1,
            "last_action": "archmind continue",
            "last_status": "NOT_DONE",
            "last_failure_signature": "backend-pytest:FAIL",
            "recent_failures": [
                "Backend pytest failed: tests/test_api.py::test_create_item",
                "Backend pytest failed: tests/test_api.py::test_create_item",
                "Backend pytest failed: tests/test_api.py::test_create_item",
            ],
            "history": [
                {
                    "timestamp": "20260101_000001",
                    "action": "run",
                    "status": "NOT_DONE",
                    "summary": "backend pytest failed",
                    "current_task_id": "1",
                    "failure_signature": "backend-pytest:FAIL",
                },
                {
                    "timestamp": "20260101_000002",
                    "action": "fix",
                    "status": "FAIL",
                    "summary": "backend pytest failed",
                    "current_task_id": "1",
                    "failure_signature": "backend-pytest:FAIL",
                },
                {
                    "timestamp": "20260101_000003",
                    "action": "continue",
                    "status": "NOT_DONE",
                    "summary": "backend pytest failed",
                    "current_task_id": "1",
                    "failure_signature": "backend-pytest:FAIL",
                },
            ],
        },
    )
    payload = evaluate_project(tmp_path)
    assert payload["status"] == "STUCK"
    assert payload["reasons"][0] == "same failure repeated 3 times: backend-pytest:FAIL"


def test_evaluate_not_done_when_repeats_are_few(tmp_path: Path) -> None:
    _write_tasks(tmp_path, ["doing"])
    _write_plan_with_acceptance(tmp_path)
    _write_result(tmp_path, "FAIL")
    _write_state(
        tmp_path,
        {
            "project_dir": str(tmp_path.resolve()),
            "updated_at": "20260101_000000",
            "iterations": 2,
            "current_task_id": 1,
            "last_action": "continue",
            "last_status": "NOT_DONE",
            "last_failure_signature": "backend-pytest:FAIL",
            "recent_failures": ["backend pytest failed", "backend pytest failed"],
            "history": [
                {
                    "timestamp": "20260101_000001",
                    "action": "run",
                    "status": "NOT_DONE",
                    "summary": "backend pytest failed",
                    "current_task_id": "1",
                    "failure_signature": "backend-pytest:FAIL",
                },
                {
                    "timestamp": "20260101_000002",
                    "action": "fix",
                    "status": "FAIL",
                    "summary": "backend pytest failed",
                    "current_task_id": "1",
                    "failure_signature": "backend-pytest:FAIL",
                },
            ],
        },
    )
    payload = evaluate_project(tmp_path)
    assert payload["status"] == "NOT_DONE"


def test_evaluate_clears_stuck_when_failure_changes(tmp_path: Path) -> None:
    _write_tasks(tmp_path, ["doing"])
    _write_plan_with_acceptance(tmp_path)
    _write_result(tmp_path, "FAIL")
    _write_state(
        tmp_path,
        {
            "project_dir": str(tmp_path.resolve()),
            "updated_at": "20260101_000000",
            "iterations": 4,
            "current_task_id": 1,
            "last_action": "continue",
            "last_status": "NOT_DONE",
            "last_failure_signature": "frontend-lint:FAIL",
            "recent_failures": ["backend pytest failed", "frontend lint failed", "db migration failed"],
            "history": [
                {
                    "timestamp": "20260101_000001",
                    "action": "run",
                    "status": "NOT_DONE",
                    "summary": "backend pytest failed",
                    "current_task_id": "1",
                    "failure_signature": "backend-pytest:FAIL",
                },
                {
                    "timestamp": "20260101_000002",
                    "action": "fix",
                    "status": "FAIL",
                    "summary": "frontend lint failed",
                    "current_task_id": "1",
                    "failure_signature": "frontend-lint:FAIL",
                },
                {
                    "timestamp": "20260101_000003",
                    "action": "continue",
                    "status": "NOT_DONE",
                    "summary": "db migration failed",
                    "current_task_id": "1",
                    "failure_signature": "backend-pytest+frontend-lint:FAIL",
                },
            ],
        },
    )
    payload = evaluate_project(tmp_path)
    assert payload["status"] == "NOT_DONE"


def test_evaluate_auto_marks_task1_task2_done_after_run_fix_signals(tmp_path: Path) -> None:
    _write_coarse_plan(tmp_path)
    _write_tasks(tmp_path, ["todo", "todo", "todo", "todo"])
    _write_result(tmp_path, "FAIL")
    _write_state(
        tmp_path,
        {
            "project_dir": str(tmp_path.resolve()),
            "updated_at": "20260101_000000",
            "iterations": 1,
            "fix_attempts": 1,
            "last_failure_class": "backend-pytest:module-not-found",
            "last_repair_targets": ["requirements.txt"],
            "last_status": "FAIL",
        },
    )
    payload = evaluate_project(tmp_path)
    tasks_payload = json.loads((tmp_path / ".archmind" / "tasks.json").read_text(encoding="utf-8"))
    statuses = [item["status"] for item in tasks_payload["tasks"]]
    assert statuses[0] == "done"
    assert statuses[1] == "done"
    assert payload["checks"]["tasks_complete"] is False


def test_evaluate_auto_marks_regression_task_done_on_success(tmp_path: Path) -> None:
    _write_coarse_plan(tmp_path)
    _write_tasks(tmp_path, ["done", "done", "todo", "todo"])
    _write_result(tmp_path, "SUCCESS")
    _write_state(
        tmp_path,
        {
            "project_dir": str(tmp_path.resolve()),
            "updated_at": "20260101_000000",
            "iterations": 2,
            "fix_attempts": 1,
            "last_status": "SUCCESS",
            "last_failure_class": "backend-pytest:assertion",
            "last_repair_targets": ["app/main.py"],
        },
    )
    payload = evaluate_project(tmp_path)
    tasks_payload = json.loads((tmp_path / ".archmind" / "tasks.json").read_text(encoding="utf-8"))
    statuses = [item["status"] for item in tasks_payload["tasks"]]
    assert statuses[2] == "done"
    assert payload["status"] in {"DONE", "NOT_DONE"}


def test_evaluate_done_when_all_auto_tasks_done_and_success(tmp_path: Path) -> None:
    _write_coarse_plan(tmp_path)
    _write_tasks(tmp_path, ["todo", "todo", "todo", "todo"])
    _write_result(tmp_path, "SUCCESS")
    _write_state(
        tmp_path,
        {
            "project_dir": str(tmp_path.resolve()),
            "updated_at": "20260101_000000",
            "iterations": 3,
            "fix_attempts": 2,
            "last_status": "SUCCESS",
            "last_failure_class": "backend-pytest:assertion",
            "last_repair_targets": ["app/main.py"],
            "next_action": "DONE",
            "next_action_reason": "evaluation marked project complete",
        },
    )
    payload = evaluate_project(tmp_path)
    assert payload["checks"]["tasks_complete"] is True
    assert payload["status"] == "DONE"


def test_evaluate_done_for_direct_success_without_fix_attempts(tmp_path: Path) -> None:
    _write_coarse_plan(tmp_path)
    _write_tasks(tmp_path, ["todo", "todo", "todo", "todo"])
    _write_result(tmp_path, "SUCCESS")
    _write_state(
        tmp_path,
        {
            "project_dir": str(tmp_path.resolve()),
            "updated_at": "20260101_000000",
            "iterations": 1,
            "fix_attempts": 0,
            "last_status": "SUCCESS",
            "next_action": "DONE",
            "next_action_reason": "direct scaffold run succeeded",
        },
    )
    payload = evaluate_project(tmp_path)
    tasks_payload = json.loads((tmp_path / ".archmind" / "tasks.json").read_text(encoding="utf-8"))
    statuses = [item["status"] for item in tasks_payload["tasks"]]
    assert statuses == ["done", "done", "done", "done"]
    assert payload["checks"]["tasks_complete"] is True
    assert payload["status"] == "DONE"


def test_evaluate_syncs_plan_step_status(tmp_path: Path) -> None:
    _write_coarse_plan(tmp_path)
    _write_tasks(tmp_path, ["todo", "todo", "todo", "todo"])
    _write_result(tmp_path, "FAIL")
    _write_state(
        tmp_path,
        {
            "project_dir": str(tmp_path.resolve()),
            "updated_at": "20260101_000000",
            "iterations": 1,
            "fix_attempts": 1,
            "last_status": "FAIL",
            "last_failure_class": "backend-pytest:module-not-found",
            "last_repair_targets": ["requirements.txt"],
        },
    )
    evaluate_project(tmp_path)
    plan_payload = json.loads((tmp_path / ".archmind" / "plan.json").read_text(encoding="utf-8"))
    steps = plan_payload.get("steps") or []
    assert isinstance(steps, list)
    assert steps[0].get("status") == "done"
    assert steps[1].get("status") == "done"
