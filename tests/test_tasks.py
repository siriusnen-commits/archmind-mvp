from __future__ import annotations

import json
from pathlib import Path

from archmind.cli import main
from archmind.tasks import ensure_tasks, next_task, update_task_status


def test_tasks_init_from_plan_json(tmp_path: Path) -> None:
    archmind_dir = tmp_path / ".archmind"
    archmind_dir.mkdir(parents=True, exist_ok=True)
    (archmind_dir / "plan.json").write_text(
        json.dumps(
            {
                "steps": [
                    {"title": "create backend skeleton"},
                    {"title": "add API endpoints"},
                ]
            }
        ),
        encoding="utf-8",
    )

    payload = ensure_tasks(tmp_path)
    assert (archmind_dir / "tasks.json").exists()
    assert len(payload["tasks"]) == 2
    assert payload["tasks"][0]["title"] == "create backend skeleton"
    assert payload["tasks"][0]["status"] == "todo"


def test_tasks_init_from_plan_md(tmp_path: Path) -> None:
    archmind_dir = tmp_path / ".archmind"
    archmind_dir.mkdir(parents=True, exist_ok=True)
    (archmind_dir / "plan.md").write_text(
        "\n".join(
            [
                "# plan",
                "1. create backend skeleton",
                "2. add API endpoints",
                "- add tests",
            ]
        )
        + "\n",
        encoding="utf-8",
    )

    payload = ensure_tasks(tmp_path)
    assert len(payload["tasks"]) >= 3
    assert payload["tasks"][0]["title"] == "create backend skeleton"


def test_next_returns_first_todo(tmp_path: Path) -> None:
    archmind_dir = tmp_path / ".archmind"
    archmind_dir.mkdir(parents=True, exist_ok=True)
    (archmind_dir / "tasks.json").write_text(
        json.dumps(
            {
                "project_dir": str(tmp_path.resolve()),
                "created_at": "20260101_000000",
                "tasks": [
                    {"id": 1, "title": "t1", "status": "done", "source": "manual", "notes": ""},
                    {"id": 2, "title": "t2", "status": "todo", "source": "manual", "notes": ""},
                    {"id": 3, "title": "t3", "status": "todo", "source": "manual", "notes": ""},
                ],
            }
        ),
        encoding="utf-8",
    )

    task = next_task(tmp_path)
    assert task is not None
    assert task.id == 2
    assert task.title == "t2"


def test_complete_updates_statuses(tmp_path: Path) -> None:
    archmind_dir = tmp_path / ".archmind"
    archmind_dir.mkdir(parents=True, exist_ok=True)
    (archmind_dir / "tasks.json").write_text(
        json.dumps(
            {
                "project_dir": str(tmp_path.resolve()),
                "created_at": "20260101_000000",
                "tasks": [
                    {"id": 1, "title": "t1", "status": "todo", "source": "manual", "notes": ""},
                ],
            }
        ),
        encoding="utf-8",
    )

    assert main(["complete", "--path", str(tmp_path), "--id", "1"]) == 0
    payload = json.loads((archmind_dir / "tasks.json").read_text(encoding="utf-8"))
    assert payload["tasks"][0]["status"] == "done"

    assert main(["complete", "--path", str(tmp_path), "--id", "1", "--doing"]) == 0
    payload = json.loads((archmind_dir / "tasks.json").read_text(encoding="utf-8"))
    assert payload["tasks"][0]["status"] == "doing"

    assert main(["complete", "--path", str(tmp_path), "--id", "1", "--blocked"]) == 0
    payload = json.loads((archmind_dir / "tasks.json").read_text(encoding="utf-8"))
    assert payload["tasks"][0]["status"] == "blocked"


def test_tasks_cli_output_and_next(tmp_path: Path, capsys) -> None:
    archmind_dir = tmp_path / ".archmind"
    archmind_dir.mkdir(parents=True, exist_ok=True)
    (archmind_dir / "tasks.json").write_text(
        json.dumps(
            {
                "project_dir": str(tmp_path.resolve()),
                "created_at": "20260101_000000",
                "tasks": [
                    {"id": 1, "title": "create backend skeleton", "status": "todo", "source": "plan", "notes": ""},
                    {"id": 2, "title": "add API endpoints", "status": "doing", "source": "plan", "notes": ""},
                    {"id": 3, "title": "add tests", "status": "done", "source": "plan", "notes": ""},
                ],
            }
        ),
        encoding="utf-8",
    )

    assert main(["tasks", "--path", str(tmp_path)]) == 0
    out = capsys.readouterr().out
    assert "[1] todo" in out
    assert "[2] doing" in out
    assert "[3] done" in out

    assert main(["next", "--path", str(tmp_path)]) == 0
    out = capsys.readouterr().out
    assert "NEXT: [1] create backend skeleton" in out

