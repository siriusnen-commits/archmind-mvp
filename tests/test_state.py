from __future__ import annotations

import json
from pathlib import Path

from archmind.cli import main
from archmind.state import derive_task_label_from_failure_signature
from archmind.state import ensure_state, load_state, update_state_event


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


def test_state_history_added_after_fix(tmp_path: Path, monkeypatch) -> None:
    _write_backend_project(tmp_path, failing=True)
    monkeypatch.setattr("archmind.fixer.run_fix_loop", lambda **_: 1)

    exit_code = main(["fix", "--path", str(tmp_path), "--scope", "backend", "--model", "none"])
    assert exit_code == 1

    state = load_state(tmp_path)
    assert state is not None
    history = state.get("history") or []
    assert history
    assert "fix" in history[-1]["action"]


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
    assert "STATE:" in output
    assert "Iterations:" in output
    assert "Recent failures:" in output


def test_derive_task_label_from_failure_signature_mapping() -> None:
    assert derive_task_label_from_failure_signature("backend-pytest:FAIL") == "backend pytest failure 분석"
    assert derive_task_label_from_failure_signature("frontend-lint:FAIL") == "frontend lint failure 수정"
    assert derive_task_label_from_failure_signature("frontend-build:FAIL") == "frontend build failure 수정"
    assert (
        derive_task_label_from_failure_signature("backend-pytest+frontend-lint:FAIL")
        == "backend pytest / frontend lint failure 분석"
    )
    assert derive_task_label_from_failure_signature("unknown-step:FAIL") == "반복 실패 원인 분석"
