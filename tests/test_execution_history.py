from __future__ import annotations

from pathlib import Path

from archmind.execution_history import (
    append_execution_event,
    execution_history_path,
    load_recent_execution_events,
)


def test_append_execution_event_creates_history_file(tmp_path: Path) -> None:
    project_dir = tmp_path / "demo_project"
    ok = append_execution_event(
        project_dir,
        project_name="demo_project",
        source="manual-command",
        command="/add_api GET /tasks",
        status="ok",
        message="API added",
    )
    assert ok is True
    history_file = execution_history_path(project_dir)
    assert history_file.exists()
    events = load_recent_execution_events(project_dir, limit=10)
    assert len(events) == 1
    assert events[0]["project_name"] == "demo_project"
    assert events[0]["source"] == "manual-command"
    assert events[0]["command"] == "/add_api GET /tasks"
    assert events[0]["status"] == "ok"


def test_load_recent_execution_events_respects_limit_and_ignores_broken_lines(tmp_path: Path) -> None:
    project_dir = tmp_path / "demo_project"
    for idx in range(5):
        append_execution_event(
            project_dir,
            project_name="demo_project",
            source="telegram-auto",
            command=f"/add_page tasks/{idx}",
            status="ok",
            message="done",
            step_no=idx + 1,
        )
    history_file = execution_history_path(project_dir)
    history_file.write_text(history_file.read_text(encoding="utf-8") + "{broken\n", encoding="utf-8")
    events = load_recent_execution_events(project_dir, limit=2)
    assert len(events) == 2
    assert events[0]["step_no"] == 4
    assert events[1]["step_no"] == 5
