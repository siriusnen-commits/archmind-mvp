from __future__ import annotations

import json
from pathlib import Path

from archmind.cli import main
from archmind.evaluator import evaluate_project


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


def _write_result(root: Path, status: str) -> None:
    archmind_dir = root / ".archmind"
    archmind_dir.mkdir(parents=True, exist_ok=True)
    (archmind_dir / "result.json").write_text(json.dumps({"status": status}), encoding="utf-8")


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
    assert payload["status"] in {"DONE", "NOT_DONE", "BLOCKED"}

