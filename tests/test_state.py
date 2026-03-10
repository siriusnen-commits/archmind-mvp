from __future__ import annotations

import json
from pathlib import Path

from archmind.cli import main
from archmind.state import derive_task_label_from_failure_signature
from archmind.state import ensure_state, format_state_text, load_state, update_after_fix, update_state_event


def _write_backend_project(root: Path, *, failing: bool = False) -> None:
    root.joinpath("pytest.ini").write_text("[pytest]\naddopts = -q\n", encoding="utf-8")
    if failing:
        root.joinpath("test_fail.py").write_text("def test_fail():\n    assert False\n", encoding="utf-8")
    else:
        root.joinpath("test_ok.py").write_text("def test_ok():\n    assert True\n", encoding="utf-8")


def test_state_created_and_updated_after_run(tmp_path: Path) -> None:
    _write_backend_project(tmp_path, failing=False)
    exit_code = main(["run", "--path", str(tmp_path), "--backend-only"])
    assert exit_code == 0

    state = load_state(tmp_path)
    assert state is not None
    assert state["iterations"] >= 1
    assert "archmind run" in state["last_action"]
    assert state["last_status"] in {"SUCCESS", "SKIP", "FAIL", "STUCK"}


def test_run_invokes_environment_readiness_check(tmp_path: Path, monkeypatch) -> None:
    _write_backend_project(tmp_path, failing=False)
    calls = {"n": 0}

    def fake_readiness(project_dir):  # type: ignore[no-untyped-def]
        assert project_dir == tmp_path.resolve()
        calls["n"] += 1
        return {"issue": "env-readiness-ok", "reason": "ok", "actions": []}

    monkeypatch.setattr("archmind.environment.ensure_environment_readiness", fake_readiness)
    exit_code = main(["run", "--path", str(tmp_path), "--backend-only"])
    assert exit_code == 0
    assert calls["n"] >= 1


def test_state_history_added_after_fix(tmp_path: Path, monkeypatch) -> None:
    _write_backend_project(tmp_path, failing=True)
    monkeypatch.setattr("archmind.fixer.run_fix_loop", lambda **_: 1)
    ensure_state(tmp_path)
    before = load_state(tmp_path)
    assert before is not None
    before_iterations = int(before.get("iterations") or 0)
    before_fix_attempts = int(before.get("fix_attempts") or 0)

    exit_code = main(["fix", "--path", str(tmp_path), "--scope", "backend", "--model", "none"])
    assert exit_code == 1

    state = load_state(tmp_path)
    assert state is not None
    history = state.get("history") or []
    assert history
    assert "fix" in history[-1]["action"]
    assert int(state.get("iterations") or 0) == before_iterations
    assert int(state.get("fix_attempts") or 0) == before_fix_attempts + 1


def test_fix_attempts_are_cumulative_across_multiple_fix_updates(tmp_path: Path) -> None:
    _write_backend_project(tmp_path, failing=True)
    ensure_state(tmp_path)
    update_after_fix(tmp_path, action="archmind fix --path p --apply", exit_code=1)
    update_after_fix(tmp_path, action="archmind fix --path p --apply", exit_code=1)
    state = load_state(tmp_path)
    assert state is not None
    assert int(state.get("fix_attempts") or 0) == 2


def test_fix_attempts_recovered_from_history_when_field_missing(tmp_path: Path) -> None:
    _write_backend_project(tmp_path, failing=True)
    state_path = tmp_path / ".archmind" / "state.json"
    state_path.parent.mkdir(parents=True, exist_ok=True)
    state_path.write_text(
        json.dumps(
            {
                "project_dir": str(tmp_path.resolve()),
                "updated_at": "20260101_000000",
                "iterations": 0,
                "history": [
                    {"timestamp": "20260101_000001", "action": "archmind fix --path p --apply", "status": "FAIL"},
                    {"timestamp": "20260101_000002", "action": "pipeline fix iteration 1", "status": "FAIL"},
                ],
            }
        ),
        encoding="utf-8",
    )
    loaded = load_state(tmp_path)
    assert loaded is not None
    assert int(loaded.get("fix_attempts") or 0) == 2


def test_fix_attempts_recovered_from_history_when_top_level_is_stale(tmp_path: Path) -> None:
    _write_backend_project(tmp_path, failing=True)
    state_path = tmp_path / ".archmind" / "state.json"
    state_path.parent.mkdir(parents=True, exist_ok=True)
    state_path.write_text(
        json.dumps(
            {
                "project_dir": str(tmp_path.resolve()),
                "updated_at": "20260101_000000",
                "iterations": 5,
                "fix_attempts": 1,
                "history": [
                    {"timestamp": "20260101_000001", "action": "archmind fix --path p --apply", "status": "FAIL"},
                    {"timestamp": "20260101_000002", "action": "pipeline fix iteration 1", "status": "FAIL"},
                    {"timestamp": "20260101_000003", "action": "archmind fix --path p --apply", "status": "FAIL"},
                ],
            }
        ),
        encoding="utf-8",
    )
    loaded = load_state(tmp_path)
    assert loaded is not None
    assert int(loaded.get("fix_attempts") or 0) == 3


def test_state_syncs_top_level_fix_summary_fields_from_latest_fix_meta(tmp_path: Path) -> None:
    _write_backend_project(tmp_path, failing=True)
    archmind = tmp_path / ".archmind"
    run_logs = archmind / "run_logs"
    run_logs.mkdir(parents=True, exist_ok=True)
    (archmind / "state.json").write_text(
        json.dumps(
            {
                "project_dir": str(tmp_path.resolve()),
                "updated_at": "20260101_000000",
                "iterations": 1,
                "fix_attempts": 1,
                "last_failure_class": "unknown",
                "last_fix_strategy": "",
                "last_failure_signature_before_fix": "",
                "last_failure_signature_after_fix": "",
                "last_repair_targets": [],
                "history": [
                    {
                        "timestamp": "20260101_000001",
                        "action": "archmind fix --path p --apply",
                        "status": "FAIL",
                        "failure_class": "backend-pytest:module-not-found",
                        "failure_signature": "backend-pytest:FAIL",
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    (run_logs / "fix_20260101_000002.summary.json").write_text(
        json.dumps(
            {
                "meta": {
                    "failure_class": "backend-pytest:module-not-found",
                    "fix_strategy": "backend-import-resolution",
                    "failure_signature_before_fix": "backend-pytest:FAIL",
                    "failure_signature_after_fix": "backend-pytest:FAIL",
                    "repair_targets": ["requirements.txt", "app/main.py"],
                }
            }
        ),
        encoding="utf-8",
    )

    loaded = load_state(tmp_path)
    assert loaded is not None
    assert loaded.get("last_failure_class") == "backend-pytest:module-not-found"
    assert loaded.get("last_fix_strategy") == "backend-import-resolution"
    assert loaded.get("last_failure_signature_before_fix") == "backend-pytest:FAIL"
    assert loaded.get("last_failure_signature_after_fix") == "backend-pytest:FAIL"
    assert loaded.get("last_repair_targets") == ["requirements.txt", "app/main.py"]


def test_state_stores_failure_signature_after_failed_run(tmp_path: Path) -> None:
    _write_backend_project(tmp_path, failing=True)
    exit_code = main(["run", "--path", str(tmp_path), "--backend-only"])
    assert exit_code == 1

    state = load_state(tmp_path)
    assert state is not None
    assert state.get("last_failure_signature") == "backend-pytest:FAIL"
    history = state.get("history") or []
    assert history
    assert history[-1].get("failure_signature") == "backend-pytest:FAIL"


def test_state_reflects_evaluate_status(tmp_path: Path) -> None:
    archmind = tmp_path / ".archmind"
    archmind.mkdir(parents=True, exist_ok=True)
    archmind.joinpath("tasks.json").write_text(
        json.dumps(
            {
                "project_dir": str(tmp_path.resolve()),
                "created_at": "20260101_000000",
                "tasks": [{"id": 1, "title": "t1", "status": "done", "source": "plan", "notes": ""}],
            }
        ),
        encoding="utf-8",
    )
    archmind.joinpath("plan.json").write_text(
        json.dumps({"acceptance": ["pytest passes"], "steps": ["s1"]}),
        encoding="utf-8",
    )
    archmind.joinpath("result.json").write_text(json.dumps({"status": "SUCCESS"}), encoding="utf-8")

    assert main(["evaluate", "--path", str(tmp_path)]) == 0
    state = load_state(tmp_path)
    assert state is not None
    assert state["last_status"] == "DONE"
    assert state["agent_state"] == "DONE"


def test_state_history_is_capped_at_20(tmp_path: Path) -> None:
    ensure_state(tmp_path)
    for i in range(25):
        update_state_event(tmp_path, action=f"action-{i}", status="UNKNOWN", summary=f"summary-{i}")
    state = load_state(tmp_path)
    assert state is not None
    assert len(state["history"]) == 20


def test_state_cli_output(tmp_path: Path, capsys) -> None:
    _write_backend_project(tmp_path, failing=False)
    ensure_state(tmp_path)
    exit_code = main(["state", "--path", str(tmp_path)])
    assert exit_code == 0
    output = capsys.readouterr().out
    assert "Project status:" in output
    assert "Agent state:" in output
    assert "Last status:" in output
    assert "Iterations:" in output
    assert "Fix attempts:" in output
    assert "Environment issue:" in output
    assert "Bootstrap actions:" in output
    assert "Next action:" in output
    assert "Reason:" in output
    assert "Recent failures:" in output


def test_state_project_status_stuck(tmp_path: Path) -> None:
    archmind = tmp_path / ".archmind"
    archmind.mkdir(parents=True, exist_ok=True)
    (archmind / "state.json").write_text(
        json.dumps(
            {
                "project_dir": str(tmp_path.resolve()),
                "updated_at": "20260101_000000",
                "agent_state": "IDLE",
                "last_status": "FAIL",
                "stuck": True,
                "iterations": 14,
                "fix_attempts": 17,
                "recent_failures": ["Traceback:", "ModuleNotFoundError: No module named 'fastapi'"],
            }
        ),
        encoding="utf-8",
    )
    output = format_state_text(tmp_path)
    assert "Project status: STUCK" in output


def test_state_project_status_done(tmp_path: Path) -> None:
    archmind = tmp_path / ".archmind"
    archmind.mkdir(parents=True, exist_ok=True)
    (archmind / "state.json").write_text(
        json.dumps(
            {
                "project_dir": str(tmp_path.resolve()),
                "updated_at": "20260101_000000",
                "agent_state": "IDLE",
                "last_status": "SUCCESS",
                "stuck": False,
                "iterations": 3,
                "fix_attempts": 1,
                "recent_failures": [],
            }
        ),
        encoding="utf-8",
    )
    output = format_state_text(tmp_path)
    assert "Project status: DONE" in output


def test_state_project_status_not_done_and_failure_noise_filtered(tmp_path: Path) -> None:
    archmind = tmp_path / ".archmind"
    archmind.mkdir(parents=True, exist_ok=True)
    (archmind / "state.json").write_text(
        json.dumps(
            {
                "project_dir": str(tmp_path.resolve()),
                "updated_at": "20260101_000000",
                "agent_state": "IDLE",
                "last_status": "FAIL",
                "stuck": False,
                "iterations": 3,
                "fix_attempts": 2,
                "recent_failures": [
                    "Traceback:",
                    "========================",
                    "Base",
                    "Cancel",
                    "info  - Need to disable some ESLint rules?",
                    "Learn more here: https://nextjs.org/docs/app/api-reference/config/eslint#disabling-rules",
                    "frontend lint failed",
                ],
            }
        ),
        encoding="utf-8",
    )
    output = format_state_text(tmp_path)
    assert "Project status: NOT_DONE" in output
    assert "Traceback:" not in output
    assert "Base" not in output
    assert "Cancel" not in output
    assert "Need to disable some ESLint rules" not in output
    assert "nextjs.org/docs/app/api-reference/config/eslint#disabling-rules" not in output
    assert "frontend lint failed" in output


def test_pipeline_path_increments_iterations(tmp_path: Path) -> None:
    _write_backend_project(tmp_path, failing=False)
    ensure_state(tmp_path)
    s0 = load_state(tmp_path)
    assert s0 is not None
    i0 = int(s0.get("iterations") or 0)

    assert main(["pipeline", "--path", str(tmp_path), "--backend-only", "--max-iterations", "1", "--model", "none"]) == 0
    s1 = load_state(tmp_path)
    assert s1 is not None
    i1 = int(s1.get("iterations") or 0)
    assert i1 >= i0 + 1


def test_derive_task_label_from_failure_signature_mapping() -> None:
    assert derive_task_label_from_failure_signature("backend-pytest:FAIL") == "backend pytest failure 분석"
    assert derive_task_label_from_failure_signature("frontend-lint-warning:WARNING") == "frontend lint warning 확인"
    assert derive_task_label_from_failure_signature("frontend-lint:FAIL") == "frontend lint failure 수정"
    assert derive_task_label_from_failure_signature("frontend-build:FAIL") == "frontend build failure 수정"
    assert (
        derive_task_label_from_failure_signature("backend-pytest+frontend-lint:FAIL")
        == "backend pytest / frontend lint failure 분석"
    )
    assert derive_task_label_from_failure_signature("unknown-step:FAIL") == "반복 실패 원인 분석"
