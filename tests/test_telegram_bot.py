from __future__ import annotations

import asyncio
import json
import re
from dataclasses import dataclass, field
from pathlib import Path

import pytest
import archmind.current_project as current_project_state
import archmind.telegram_bot as telegram_bot
from archmind.execution_history import append_execution_event, load_recent_execution_events
from archmind.telegram_bot import (
    build_completion_message,
    build_finished_message,
    build_continue_command,
    build_fix_command,
    build_pipeline_command,
    build_retry_commands,
    command_idea_local,
    command_logs,
    command_running,
    command_continue,
    command_fix,
    command_current,
    command_history,
    command_diff,
    command_open,
    command_tree,
    command_use,
    command_projects,
    command_status,
    command_deploy,
    command_run,
    command_delete_project,
    command_restart,
    command_stop,
    command_help,
    command_inspect,
    command_improve,
    command_add_module,
    command_add_entity,
    command_add_field,
    command_add_api,
    command_add_page,
    command_implement_page,
    command_apply_suggestion,
    command_apply_plan,
    command_next,
    command_auto,
    command_suggestion_callback,
    command_plan,
    command_retry,
    command_preview,
    command_suggest,
    command_design,
    command_unknown,
    command_state,
    extract_idea,
    load_last_project_path,
    load_valid_last_project_path,
    make_project_name,
    planned_project_dir,
    read_recent_backend_logs,
    read_recent_frontend_logs,
    read_recent_last_logs,
    extract_key_error_lines,
    build_log_focus,
    build_logs_message,
    resolve_template_for_idea,
    run_state_command,
    resolve_project_selection,
    sanitize_log_excerpt,
    save_last_project_path,
    set_current_project,
    clear_current_project,
    get_template_suggestions,
    get_current_project,
    start_pipeline_process,
    format_projects_list,
    format_project_tree,
    format_file_preview,
    format_recent_diff,
    format_status_text,
    list_recent_projects,
    watch_pipeline_and_notify,
    watch_retry_and_notify,
)


@pytest.fixture(autouse=True)
def _reset_running_job() -> None:
    telegram_bot._clear_running_job()
    telegram_bot._clear_pending_delete()
    telegram_bot.clear_current_project()
    yield
    telegram_bot._clear_running_job()
    telegram_bot._clear_pending_delete()
    telegram_bot.clear_current_project()


def test_extract_idea_parsing() -> None:
    assert extract_idea(["build", "notes", "app"]) == "build notes app"
    assert extract_idea([]) == ""


def _mark_archmind_project(path: Path) -> None:
    (path / ".archmind").mkdir(parents=True, exist_ok=True)


def test_last_project_path_save_and_load(tmp_path: Path) -> None:
    path_file = tmp_path / "last_project"
    project_path = tmp_path / "demo_project"
    save_last_project_path(project_path, file_path=path_file)
    loaded = load_last_project_path(file_path=path_file)
    assert loaded == project_path.resolve()


def test_load_valid_last_project_path_rejects_stale_target_and_clears_file(tmp_path: Path) -> None:
    path_file = tmp_path / "last_project"
    stale_project = tmp_path / "beta"
    # stale target intentionally does not exist
    save_last_project_path(stale_project, file_path=path_file)

    loaded = load_valid_last_project_path(file_path=path_file)
    assert loaded is None
    assert not path_file.exists()


def test_load_valid_last_project_path_rejects_non_archmind_directory(tmp_path: Path) -> None:
    path_file = tmp_path / "last_project"
    non_archmind = tmp_path / "beta"
    non_archmind.mkdir(parents=True, exist_ok=True)
    save_last_project_path(non_archmind, file_path=path_file)

    loaded = load_valid_last_project_path(file_path=path_file)
    assert loaded is None
    assert not path_file.exists()


def test_build_pipeline_command() -> None:
    base_dir = Path("/tmp/projects")
    project_name = "20260309_notes_app"
    cmd = build_pipeline_command(
        idea="notes app",
        base_dir=base_dir,
        project_name=project_name,
    )
    assert cmd[:2] == ["archmind", "pipeline"]
    assert "--apply" in cmd
    assert cmd[cmd.index("--out") + 1] == str(base_dir)
    assert cmd[cmd.index("--name") + 1] == project_name
    assert "--template" not in cmd


def test_build_pipeline_command_for_idea_local_enables_auto_deploy() -> None:
    base_dir = Path("/tmp/projects")
    cmd = build_pipeline_command(
        idea="notes app",
        base_dir=base_dir,
        project_name="20260315_notes_app",
        auto_deploy=True,
        deploy_target="local",
    )
    assert "--auto-deploy" in cmd
    assert "--deploy-target" in cmd
    assert cmd[cmd.index("--deploy-target") + 1] == "local"


def test_resolve_template_for_idea_backend_routes_to_fastapi() -> None:
    assert resolve_template_for_idea("simple fastapi notes api") == "fastapi"


def test_resolve_template_for_idea_frontend_routes_to_nextjs() -> None:
    assert resolve_template_for_idea("simple nextjs counter dashboard") == "nextjs"


def test_planned_project_dir_does_not_create_folder(tmp_path: Path) -> None:
    project_dir = planned_project_dir(tmp_path, "notes app", ts="20260309_120000")
    assert project_dir.name == "20260309_120000_notes_app"
    assert not project_dir.exists()
    assert make_project_name("notes app", ts="20260309_120000") == "20260309_120000_notes_app"


def test_run_state_command_uses_safe_list_args(monkeypatch, tmp_path: Path) -> None:
    captured: dict[str, object] = {}

    class DummyResult:
        returncode = 0
        stdout = "STATE: NOT_DONE"
        stderr = ""

    def fake_run(cmd, **kwargs):  # type: ignore[no-untyped-def]
        captured["cmd"] = cmd
        captured["kwargs"] = kwargs
        return DummyResult()

    monkeypatch.setattr("archmind.telegram_bot.subprocess.run", fake_run)
    ok, output = run_state_command(tmp_path)
    assert ok is True
    assert output == "STATE: NOT_DONE"
    assert captured["cmd"] == ["archmind", "state", "--path", str(tmp_path)]
    assert captured["kwargs"]["shell"] is False


def test_build_continue_command() -> None:
    path = Path("/tmp/archmind/demo")
    assert build_continue_command(path) == ["archmind", "pipeline", "--path", str(path.resolve())]


def test_build_fix_command() -> None:
    path = Path("/tmp/archmind/demo")
    assert build_fix_command(path) == ["archmind", "fix", "--path", str(path.resolve()), "--apply"]


def test_build_retry_commands_order() -> None:
    path = Path("/tmp/archmind/demo")
    cmds = build_retry_commands(path)
    assert cmds[0] == ["archmind", "fix", "--path", str(path.resolve()), "--apply"]
    assert cmds[1] == ["archmind", "pipeline", "--path", str(path.resolve())]


def test_start_pipeline_process_writes_temp_log_in_base_dir(monkeypatch, tmp_path: Path) -> None:
    class DummyPopen:
        def __init__(self, cmd, **kwargs):  # type: ignore[no-untyped-def]
            self.pid = 1234
            self.cmd = cmd
            self.kwargs = kwargs

    captured: dict[str, object] = {}

    def fake_popen(cmd, **kwargs):  # type: ignore[no-untyped-def]
        captured["cmd"] = cmd
        captured["kwargs"] = kwargs
        return DummyPopen(cmd, **kwargs)

    monkeypatch.setattr("archmind.telegram_bot.subprocess.Popen", fake_popen)
    proc, log_path = start_pipeline_process(
        ["archmind", "pipeline", "--idea", "notes"],
        base_dir=tmp_path,
        project_name="20260309_notes",
    )
    assert proc.pid == 1234
    assert log_path == (tmp_path / "20260309_notes.telegram.log")
    assert log_path.exists()
    assert not (tmp_path / "20260309_notes").exists()
    assert captured["kwargs"]["shell"] is False


def test_build_completion_message_reads_result_state_json(tmp_path: Path) -> None:
    project_dir = tmp_path / "p1"
    archmind = project_dir / ".archmind"
    archmind.mkdir(parents=True, exist_ok=True)
    (archmind / "result.json").write_text(json.dumps({"status": "FAIL"}), encoding="utf-8")
    (archmind / "state.json").write_text(
        json.dumps(
            {
                "last_status": "NOT_DONE",
                "iterations": 2,
                "fix_attempts": 1,
                "current_task_id": 2,
                "last_failure_signature": "backend-pytest:FAIL",
                "derived_task_label": "backend pytest failure 분석",
            }
        ),
        encoding="utf-8",
    )
    (archmind / "tasks.json").write_text(
        json.dumps(
            {
                "tasks": [
                    {"id": 2, "title": "add API endpoints", "status": "doing", "source": "plan", "notes": ""}
                ]
            }
        ),
        encoding="utf-8",
    )
    (archmind / "result.txt").write_text(
        "ArchMind Pipeline Result\n- Backend: FAIL\n- Frontend: FAIL\n- further work remains\n",
        encoding="utf-8",
    )
    temp_log = tmp_path / "fallback.telegram.log"
    message = build_completion_message(project_dir, temp_log)
    assert "ArchMind finished" in message
    assert f"Project:\n{project_dir.name}" in message
    assert str(project_dir) not in message
    assert "Status: NOT_DONE" in message
    assert "Iterations: 2" in message
    assert "Fix attempts: 1" in message
    assert "Current task: backend pytest failure 분석" in message
    assert "Backend tests are still failing" in message
    assert "Further work remains" in message
    assert "Next:" in message
    assert "- /fix" in message
    assert "- /logs backend" in message


def test_build_completion_message_includes_github_repo_url_when_present(tmp_path: Path) -> None:
    project_dir = tmp_path / "repo_msg"
    archmind = project_dir / ".archmind"
    archmind.mkdir(parents=True, exist_ok=True)
    (archmind / "result.json").write_text(
        json.dumps({"status": "SUCCESS", "github_repo_url": "https://github.com/siriusnen-commits/repo_msg"}),
        encoding="utf-8",
    )
    (archmind / "state.json").write_text(
        json.dumps(
            {
                "last_status": "DONE",
                "iterations": 1,
                "fix_attempts": 0,
                "github_repo_url": "https://github.com/siriusnen-commits/repo_msg",
                "repository": {"status": "CREATED", "url": "https://github.com/siriusnen-commits/repo_msg", "attempted": True},
            }
        ),
        encoding="utf-8",
    )
    msg = build_completion_message(project_dir, tmp_path / "unused.log")
    assert "GitHub Repo:" in msg
    assert "CREATED" in msg
    assert "https://github.com/siriusnen-commits/repo_msg" in msg


def test_build_completion_message_shows_repository_failed_independently_of_runtime(tmp_path: Path) -> None:
    project_dir = tmp_path / "repo_failed_runtime_not_done"
    archmind = project_dir / ".archmind"
    archmind.mkdir(parents=True, exist_ok=True)
    (archmind / "state.json").write_text(
        json.dumps(
            {
                "last_status": "NOT_DONE",
                "last_failure_class": "runtime-execution-error",
                "repository": {
                    "status": "FAILED",
                    "url": "",
                    "name": "repo_failed_runtime_not_done",
                    "reason": "gh auth missing",
                    "attempted": True,
                },
            }
        ),
        encoding="utf-8",
    )
    msg = build_completion_message(project_dir, tmp_path / "unused.log")
    assert "Status: NOT_DONE" in msg
    assert "GitHub Repo:" in msg
    assert "FAILED" in msg
    assert "Reason: gh auth missing" in msg


def test_build_completion_message_includes_auto_deploy_success_summary(tmp_path: Path) -> None:
    project_dir = tmp_path / "auto_deploy_done"
    archmind = project_dir / ".archmind"
    archmind.mkdir(parents=True, exist_ok=True)
    (archmind / "evaluation.json").write_text(json.dumps({"status": "DONE"}), encoding="utf-8")
    (archmind / "result.json").write_text(json.dumps({"status": "SUCCESS"}), encoding="utf-8")
    (archmind / "state.json").write_text(
        json.dumps(
            {
                "last_status": "DONE",
                "iterations": 1,
                "fix_attempts": 0,
                "auto_deploy_enabled": True,
                "auto_deploy_target": "local",
                "auto_deploy_status": "SUCCESS",
                "backend_deploy_url": "http://127.0.0.1:8011",
                "backend_smoke_status": "SUCCESS",
                "backend_smoke_url": "http://127.0.0.1:8011/health",
                "frontend_deploy_url": "http://127.0.0.1:3011",
                "frontend_smoke_status": "SUCCESS",
                "frontend_smoke_url": "http://127.0.0.1:3011",
            }
        ),
        encoding="utf-8",
    )
    msg = build_completion_message(project_dir, tmp_path / "unused.log")
    assert "Auto deploy: local SUCCESS" in msg
    assert "Backend URL:" in msg
    assert "http://127.0.0.1:8011" in msg
    assert "Frontend URL:" in msg
    assert "http://127.0.0.1:3011" in msg


def test_build_completion_message_separates_auto_deploy_fail_from_done(tmp_path: Path) -> None:
    project_dir = tmp_path / "auto_deploy_fail_done"
    archmind = project_dir / ".archmind"
    archmind.mkdir(parents=True, exist_ok=True)
    (project_dir / "app").mkdir(parents=True, exist_ok=True)
    (project_dir / "app" / "main.py").write_text(
        "from fastapi import FastAPI\napp = FastAPI()\n",
        encoding="utf-8",
    )
    (project_dir / "requirements.txt").write_text("fastapi\nuvicorn\n", encoding="utf-8")
    (archmind / "evaluation.json").write_text(json.dumps({"status": "DONE"}), encoding="utf-8")
    (archmind / "result.json").write_text(json.dumps({"status": "SUCCESS"}), encoding="utf-8")
    (archmind / "state.json").write_text(
        json.dumps(
            {
                "last_status": "DONE",
                "iterations": 1,
                "fix_attempts": 0,
                "auto_deploy_enabled": True,
                "auto_deploy_target": "local",
                "auto_deploy_status": "FAIL",
                "last_deploy_detail": "local backend start failed",
            }
        ),
        encoding="utf-8",
    )
    msg = build_completion_message(project_dir, tmp_path / "unused.log")
    assert "Status: DONE" in msg
    assert "Auto deploy: local FAIL" in msg
    assert "Auto deploy detail:" in msg
    assert "local backend start failed" in msg


def test_build_completion_message_fallbacks_to_temp_log(tmp_path: Path) -> None:
    project_dir = tmp_path / "p2"
    project_dir.mkdir(parents=True, exist_ok=True)
    temp_log = tmp_path / "p2.telegram.log"
    temp_log.write_text("\n".join([f"log line {i}" for i in range(30)]), encoding="utf-8")
    message = build_completion_message(project_dir, temp_log)
    assert "Status: UNKNOWN" in message
    assert "Summary:" in message
    assert "log line 29" in message


def test_build_completion_message_hides_raw_command_lines(tmp_path: Path) -> None:
    project_dir = tmp_path / "pcmd"
    archmind = project_dir / ".archmind"
    archmind.mkdir(parents=True, exist_ok=True)
    (archmind / "result.txt").write_text(
        "ArchMind Pipeline Result\n- command: archmind pipeline --path /tmp/demo\n- Backend: FAIL\n",
        encoding="utf-8",
    )
    msg = build_completion_message(project_dir, tmp_path / "unused.log")
    assert "command:" not in msg.lower()
    assert "/tmp/demo" not in msg


def test_build_completion_message_truncates_to_1200_chars(tmp_path: Path) -> None:
    project_dir = tmp_path / "p3"
    archmind = project_dir / ".archmind"
    archmind.mkdir(parents=True, exist_ok=True)
    long_lines = "\n".join([f"- detail {i} " + ("x" * 80) for i in range(40)])
    (archmind / "result.txt").write_text(long_lines, encoding="utf-8")
    msg = build_completion_message(project_dir, tmp_path / "unused.log", max_len=1200)
    assert len(msg) <= 1200


def test_build_completion_message_not_done_after_fix_recommends_continue(tmp_path: Path) -> None:
    project_dir = tmp_path / "p4"
    archmind = project_dir / ".archmind"
    archmind.mkdir(parents=True, exist_ok=True)
    (archmind / "state.json").write_text(
        json.dumps(
            {
                "last_status": "NOT_DONE",
                "iterations": 3,
                "last_action": "archmind fix --path <project> --apply",
            }
        ),
        encoding="utf-8",
    )
    (archmind / "result.txt").write_text(
        "ArchMind Pipeline Result\n- Backend: FAIL\n- further work remains\n",
        encoding="utf-8",
    )
    msg = build_completion_message(project_dir, tmp_path / "unused.log")
    assert "Status: NOT_DONE" in msg
    assert "Next:" in msg
    assert "- /continue" in msg


def test_build_completion_message_suppresses_stale_failure_when_detect_ok(tmp_path: Path, monkeypatch) -> None:
    project_dir = tmp_path / "completion_detect_ok"
    archmind = project_dir / ".archmind"
    archmind.mkdir(parents=True, exist_ok=True)
    (project_dir / "app").mkdir(parents=True, exist_ok=True)
    (project_dir / "app" / "main.py").write_text("from fastapi import FastAPI\napp = FastAPI()\n", encoding="utf-8")
    (project_dir / "requirements.txt").write_text("fastapi\nuvicorn\n", encoding="utf-8")
    (archmind / "state.json").write_text(
        json.dumps(
            {
                "last_status": "NOT_DONE",
                "runtime_failure_class": "environment-python",
                "last_failure_class": "environment-python",
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(
        "archmind.telegram_bot.detect_backend_runtime_entry",
        lambda _p, port=8000: {"ok": True, "backend_entry": "app.main:app", "backend_run_mode": "asgi-direct"},
    )
    msg = build_completion_message(project_dir, tmp_path / "unused.log")
    assert "Failure class: environment-python" not in msg


def test_build_completion_message_marks_done_and_avoids_retry_when_detect_ok_without_actionable_failure(
    tmp_path: Path, monkeypatch
) -> None:
    project_dir = tmp_path / "summary_no_retry"
    archmind = project_dir / ".archmind"
    archmind.mkdir(parents=True, exist_ok=True)
    (project_dir / "app").mkdir(parents=True, exist_ok=True)
    (project_dir / "app" / "main.py").write_text("from fastapi import FastAPI\napp = FastAPI()\n", encoding="utf-8")
    (project_dir / "requirements.txt").write_text("fastapi\nuvicorn\n", encoding="utf-8")
    (archmind / "state.json").write_text(
        json.dumps(
            {
                "last_status": "NOT_DONE",
                "fix_attempts": 2,
                "runtime": {"backend_status": "RUNNING", "failure_class": ""},
            }
        ),
        encoding="utf-8",
    )
    (archmind / "evaluation.json").write_text(json.dumps({"status": "NOT_DONE"}), encoding="utf-8")
    monkeypatch.setattr(
        "archmind.telegram_bot.detect_backend_runtime_entry",
        lambda _p, port=8000: {"ok": True, "backend_entry": "app.main:app", "backend_run_mode": "asgi-direct"},
    )
    msg = build_completion_message(project_dir, tmp_path / "unused.log")
    assert "Status: DONE" in msg
    assert "run /retry" not in msg
    assert "run /fix" not in msg


def test_build_completion_message_overrides_stale_not_done_final_status_when_detect_ok(tmp_path: Path, monkeypatch) -> None:
    project_dir = tmp_path / "summary_stale_final_status"
    archmind = project_dir / ".archmind"
    archmind.mkdir(parents=True, exist_ok=True)
    (project_dir / "app").mkdir(parents=True, exist_ok=True)
    (project_dir / "app" / "main.py").write_text("from fastapi import FastAPI\napp = FastAPI()\n", encoding="utf-8")
    (project_dir / "requirements.txt").write_text("fastapi\nuvicorn\n", encoding="utf-8")
    (archmind / "result.json").write_text(json.dumps({"status": "SUCCESS", "final_status": "NOT_DONE"}), encoding="utf-8")
    (archmind / "state.json").write_text(
        json.dumps(
            {
                "final_status": "NOT_DONE",
                "runtime": {"backend_status": "RUNNING", "failure_class": ""},
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(
        "archmind.telegram_bot.detect_backend_runtime_entry",
        lambda _p, port=8000: {"ok": True, "backend_entry": "app.main:app", "backend_run_mode": "asgi-direct"},
    )
    msg = build_completion_message(project_dir, tmp_path / "unused.log")
    assert "Status: DONE" in msg
    assert "run /retry" not in msg


def test_build_completion_message_includes_stuck_reason_and_next(tmp_path: Path) -> None:
    project_dir = tmp_path / "p5"
    archmind = project_dir / ".archmind"
    archmind.mkdir(parents=True, exist_ok=True)
    (archmind / "evaluation.json").write_text(
        json.dumps(
            {
                "status": "STUCK",
                "reasons": ["same failure repeated 3 times: backend-pytest:FAIL"],
                "next_actions": ["inspect backend failure details"],
            }
        ),
        encoding="utf-8",
    )
    (archmind / "state.json").write_text(
        json.dumps(
            {
                "last_status": "STUCK",
                "iterations": 4,
                "fix_attempts": 6,
                "current_task_id": 3,
                "last_failure_signature": "backend-pytest:FAIL",
                "derived_task_label": "backend pytest failure 분석",
            }
        ),
        encoding="utf-8",
    )
    (archmind / "tasks.json").write_text(
        json.dumps({"tasks": [{"id": 3, "title": "backend pytest failure 분석", "status": "doing"}]}),
        encoding="utf-8",
    )
    (archmind / "result.txt").write_text(
        "ArchMind Pipeline Result\n- Backend tests still failing\n- Same failure repeated across retries\n",
        encoding="utf-8",
    )
    msg = build_completion_message(project_dir, tmp_path / "unused.log")
    assert "Status: STUCK" in msg
    assert "Fix attempts: 6" in msg
    assert "Current task: backend pytest failure 분석" in msg
    assert "Reason: same failure repeated 3 times: backend-pytest:FAIL" in msg
    assert "Automatic retries are no longer making progress" in msg
    assert "Next:" in msg
    assert "inspect backend failure details" in msg


def test_build_finished_message_hides_internal_dump_and_uses_basename() -> None:
    msg = build_finished_message(
        evaluation={"status": "NOT_DONE"},
        state={
            "iterations": 3,
            "last_failure_signature": "backend-pytest+frontend-lint:FAIL",
            "last_action": "archmind fix --path /tmp/sample",
        },
        result={
            "status": "FAIL",
            "failure_summary": [
                "project_dir: /Users/user/proj",
                "timestamp: 20260309_120001",
                "command: archmind pipeline --path /Users/user/proj",
            ],
        },
        project_name="simple_todo_web_app_with_api",
        status="NOT_DONE",
        fallback_summary_lines=["project_dir: /Users/user/proj", "generate: {'skipped': True}"],
    )
    assert "Project:\nsimple_todo_web_app_with_api" in msg
    assert "project_dir:" not in msg
    assert "command:" not in msg.lower()
    assert "Backend tests are still failing" in msg
    assert "Frontend lint is still failing" in msg


def test_done_finished_message_hides_internal_paths_and_failure_class() -> None:
    msg = build_finished_message(
        evaluation={"status": "DONE"},
        state={
            "iterations": 2,
            "fix_attempts": 1,
            "last_failure_class": "backend-pytest:module-not-found",
        },
        result={
            "status": "SUCCESS",
            "steps": {
                "run_before_fix": {
                    "detail": {
                        "backend_status": "SUCCESS",
                        "frontend_status": "SKIPPED",
                    }
                }
            },
            "artifacts": {
                "run_summary": "/Users/me/project/.archmind/run_logs/run_20260309.summary.txt",
                "run_prompt": "/Users/me/project/.archmind/run_logs/run_20260309.prompt.md",
            },
        },
        project_name="archmind_task_auto",
        status="DONE",
        fallback_summary_lines=[
            "run_summary: /Users/me/project/.archmind/run_logs/run_20260309.summary.txt",
            "fix_prompt: /Users/me/project/.archmind/run_logs/fix_20260309.prompt.md",
        ],
    )
    assert "Status: DONE" in msg
    assert "Failure class:" not in msg
    assert "run_summary:" not in msg
    assert ".archmind/run_logs" not in msg
    assert "Backend: SUCCESS" in msg
    assert "Frontend: SKIP" in msg
    assert "All tasks complete" in msg
    assert "Evaluation complete" in msg


def test_not_done_still_shows_failure_class() -> None:
    msg = build_finished_message(
        evaluation={"status": "NOT_DONE"},
        state={"last_failure_class": "backend-pytest:assertion"},
        result={"status": "FAIL"},
        project_name="demo",
        status="NOT_DONE",
        fallback_summary_lines=["Backend: FAIL"],
    )
    assert "Status: NOT_DONE" in msg
    assert "Failure class: backend-pytest:assertion" in msg


def test_build_finished_message_prefers_frontend_smoke_success_in_summary() -> None:
    msg = build_finished_message(
        evaluation={"status": "DONE"},
        state={
            "last_status": "DONE",
            "iterations": 1,
            "fix_attempts": 0,
            "auto_deploy_enabled": True,
            "frontend_smoke_status": "SUCCESS",
        },
        result={
            "status": "SUCCESS",
            "steps": {
                "run_after_fix": {
                    "detail": {"backend_status": "SUCCESS", "frontend_status": "WARNING"}
                }
            },
        },
        project_name="demo",
        status="DONE",
    )
    assert "- Frontend: SUCCESS" in msg


@dataclass
class DummyMessage:
    sent: list[str] = field(default_factory=list)
    sent_kwargs: list[dict[str, object]] = field(default_factory=list)

    async def reply_text(self, text: str, **kwargs) -> None:
        self.sent.append(text)
        self.sent_kwargs.append(dict(kwargs))


@dataclass
class DummyUpdate:
    message: DummyMessage
    effective_chat: object


@dataclass
class DummyCallbackQuery:
    data: str
    message: DummyMessage
    answered: bool = False

    async def answer(self) -> None:
        self.answered = True


@dataclass
class DummyChat:
    id: int = 1


@dataclass
class DummyContext:
    args: list[str] = field(default_factory=list)
    application: object = None


def test_continue_without_last_project_shows_help(monkeypatch) -> None:
    monkeypatch.setattr("archmind.telegram_bot.load_last_project_path", lambda: None)
    msg = DummyMessage()
    update = DummyUpdate(message=msg, effective_chat=DummyChat())
    ctx = DummyContext()
    asyncio.run(command_continue(update, ctx))
    assert msg.sent
    assert "No previous project found. Use /idea first." in msg.sent[-1]


def test_fix_without_last_project_shows_help(monkeypatch) -> None:
    monkeypatch.setattr("archmind.telegram_bot.load_last_project_path", lambda: None)
    msg = DummyMessage()
    update = DummyUpdate(message=msg, effective_chat=DummyChat())
    ctx = DummyContext()
    asyncio.run(command_fix(update, ctx))
    assert msg.sent
    assert "No previous project found. Use /idea first." in msg.sent[-1]


def test_fix_command_sets_fixing_state(monkeypatch, tmp_path: Path) -> None:
    project_dir = tmp_path / "proj_fix"
    project_dir.mkdir(parents=True, exist_ok=True)
    archmind_dir = project_dir / ".archmind"
    archmind_dir.mkdir(parents=True, exist_ok=True)
    (archmind_dir / "state.json").write_text("{}", encoding="utf-8")
    _mark_archmind_project(project_dir)
    monkeypatch.setattr("archmind.telegram_bot.load_last_project_path", lambda: project_dir)
    captured_states: list[str] = []

    def fake_set_agent_state(project_dir_arg, state, **kwargs):  # type: ignore[no-untyped-def]
        assert project_dir_arg == project_dir
        captured_states.append(state)
        return {}

    class DummyProc:
        pid = 321

    monkeypatch.setattr("archmind.telegram_bot.set_agent_state", fake_set_agent_state)
    monkeypatch.setattr("archmind.telegram_bot.start_background_process", lambda *a, **k: DummyProc())
    msg = DummyMessage()
    update = DummyUpdate(message=msg, effective_chat=DummyChat())
    ctx = DummyContext(application=None)
    asyncio.run(command_fix(update, ctx))
    assert captured_states and captured_states[-1] == "FIXING"
    assert any("state=FIXING" in text for text in msg.sent)


def test_sanitize_log_excerpt_removes_ansi_path_command() -> None:
    raw = (
        "\x1b[31mcommand: archmind pipeline --path /Users/me/proj\x1b[0m\n"
        "/Users/me/proj/tests/test_api.py::test_create_todo E   AssertionError\n"
        "   \n"
    )
    cleaned = sanitize_log_excerpt(raw)
    assert "command:" not in cleaned.lower()
    assert "/Users/me/proj" not in cleaned
    assert "AssertionError" in cleaned


def test_read_recent_backend_logs_prefers_backend_excerpt(tmp_path: Path) -> None:
    project_dir = tmp_path / "proj"
    run_logs = project_dir / ".archmind" / "run_logs"
    run_logs.mkdir(parents=True, exist_ok=True)
    (project_dir / ".archmind" / "result.json").write_text(
        json.dumps({"failure_summary": ["backend pytest failed: test_create_todo"]}),
        encoding="utf-8",
    )
    (run_logs / "run_20260309_120000.summary.txt").write_text(
        "backend: FAIL\nE   AssertionError: expected 200 got 500\nfrontend: SKIPPED\n",
        encoding="utf-8",
    )
    msg = read_recent_backend_logs(project_dir)
    assert "Logs: backend" in msg
    assert "Project:\nproj" in msg
    assert "Failure:" in msg
    assert "Key lines:" in msg
    assert "Focus:" in msg
    assert "AssertionError" in msg or "FAILED" in msg


def test_read_recent_frontend_logs_prefers_frontend_excerpt(tmp_path: Path) -> None:
    project_dir = tmp_path / "proj2"
    run_logs = project_dir / ".archmind" / "run_logs"
    run_logs.mkdir(parents=True, exist_ok=True)
    (project_dir / ".archmind" / "result.json").write_text(
        json.dumps({"failure_summary": ["frontend lint failed: app/page.tsx:12"]}),
        encoding="utf-8",
    )
    (run_logs / "run_20260309_120000.summary.txt").write_text(
        "frontend lint: FAIL\nESLint: Parsing error\napp/page.tsx:12:1\n",
        encoding="utf-8",
    )
    msg = read_recent_frontend_logs(project_dir)
    assert "Logs: frontend" in msg
    assert "Project:\nproj2" in msg
    assert "Failure:" in msg
    assert "Key lines:" in msg
    assert "Focus:" in msg
    assert "ESLint: Parsing error" in msg or "frontend lint failed" in msg


def test_read_recent_frontend_logs_focus_points_to_failing_file(tmp_path: Path) -> None:
    project_dir = tmp_path / "proj_focus_front"
    run_logs = project_dir / ".archmind" / "run_logs"
    run_logs.mkdir(parents=True, exist_ok=True)
    (project_dir / ".archmind" / "state.json").write_text(
        json.dumps({"last_failure_class": "frontend-lint"}),
        encoding="utf-8",
    )
    (run_logs / "run_20260309_120000.summary.txt").write_text(
        "frontend lint: FAIL\nESLint: Parsing error\napp/page.tsx:32: React Hook useEffect has missing dependency\n",
        encoding="utf-8",
    )
    msg = read_recent_frontend_logs(project_dir)
    assert "Failure:\nfrontend lint failed" in msg
    assert "inspect frontend file app/page.tsx" in msg


def test_read_recent_backend_logs_focus_mentions_pytest_failure(tmp_path: Path) -> None:
    project_dir = tmp_path / "proj_focus_back"
    run_logs = project_dir / ".archmind" / "run_logs"
    run_logs.mkdir(parents=True, exist_ok=True)
    (project_dir / ".archmind" / "state.json").write_text(
        json.dumps({"last_failure_class": "backend-pytest:other"}),
        encoding="utf-8",
    )
    (run_logs / "run_20260309_120000.summary.txt").write_text(
        "backend: FAIL\nFAILED tests/test_api.py::test_create_todo - assert 500 == 200\n",
        encoding="utf-8",
    )
    msg = read_recent_backend_logs(project_dir)
    assert "Failure:\nbackend pytest failed" in msg
    assert "inspect pytest failure" in msg


def test_read_recent_logs_fallback_when_missing(tmp_path: Path) -> None:
    project_dir = tmp_path / "none"
    project_dir.mkdir(parents=True, exist_ok=True)
    msg_last = read_recent_last_logs(project_dir, temp_log=None)
    msg_back = read_recent_backend_logs(project_dir)
    msg_front = read_recent_frontend_logs(project_dir)
    assert "No recent logs found." in msg_last
    assert "No backend logs found. Showing runtime diagnostics instead." in msg_back
    assert "Detected backend target:" in msg_back
    assert "Run command:" in msg_back
    assert "No frontend logs found." in msg_front
    assert "Focus:" in msg_last


def test_read_recent_backend_logs_detects_runtime_entry_when_state_missing(tmp_path: Path) -> None:
    project_dir = tmp_path / "proj_runtime_detect"
    (project_dir / "app").mkdir(parents=True, exist_ok=True)
    (project_dir / "app" / "main.py").write_text("from fastapi import FastAPI\napp = FastAPI()\n", encoding="utf-8")
    (project_dir / "requirements.txt").write_text("fastapi\nuvicorn\n", encoding="utf-8")

    msg_back = read_recent_backend_logs(project_dir)
    assert "Detected backend target: app.main:app" in msg_back
    assert "Backend run mode: asgi-direct" in msg_back
    assert "Run command: uvicorn app.main:app --host 0.0.0.0 --port 8000" in msg_back
    assert "Detected backend target: (unknown)" not in msg_back
    assert "environment-python" not in msg_back


def test_read_recent_backend_logs_clears_stale_runtime_failure_class_when_detection_ok(tmp_path: Path) -> None:
    project_dir = tmp_path / "proj_runtime_stale_class"
    (project_dir / ".archmind").mkdir(parents=True, exist_ok=True)
    (project_dir / ".archmind" / "state.json").write_text(
        json.dumps({"runtime_failure_class": "environment-python"}),
        encoding="utf-8",
    )
    (project_dir / "app").mkdir(parents=True, exist_ok=True)
    (project_dir / "app" / "main.py").write_text("from fastapi import FastAPI\napp = FastAPI()\n", encoding="utf-8")
    (project_dir / "requirements.txt").write_text("fastapi\nuvicorn\n", encoding="utf-8")

    msg_back = read_recent_backend_logs(project_dir)
    assert "Detected backend target: app.main:app" in msg_back
    assert "Failure class: (none)" in msg_back
    assert "environment-python" not in msg_back


def test_read_recent_backend_logs_prefers_runtime_block_not_deploy_block(tmp_path: Path) -> None:
    project_dir = tmp_path / "proj_runtime_vs_deploy"
    (project_dir / ".archmind").mkdir(parents=True, exist_ok=True)
    (project_dir / ".archmind" / "state.json").write_text(
        json.dumps(
            {
                "deploy": {"target": "railway", "status": "SUCCESS", "backend_url": "https://api.example.up.railway.app"},
                "runtime": {
                    "mode": "local",
                    "backend_status": "FAIL",
                    "backend_entry": "app.main:app",
                    "backend_run_mode": "asgi-direct",
                    "backend_run_cwd": str(project_dir / "backend"),
                    "backend_run_command": "uvicorn app.main:app --host 0.0.0.0 --port 8133",
                    "failure_class": "runtime-execution-error",
                    "detail": "runtime check failed",
                },
            }
        ),
        encoding="utf-8",
    )
    msg_back = read_recent_backend_logs(project_dir)
    assert "Failure class: runtime-execution-error" in msg_back
    assert "Last backend detail:" in msg_back
    assert "runtime check failed" in msg_back


def test_logs_command_without_last_project_shows_help(monkeypatch) -> None:
    monkeypatch.setattr("archmind.telegram_bot.load_last_project_path", lambda: None)
    msg = DummyMessage()
    update = DummyUpdate(message=msg, effective_chat=DummyChat())
    ctx = DummyContext(args=["backend"])
    asyncio.run(command_logs(update, ctx))
    assert msg.sent
    assert "No previous project found. Use /idea first." in msg.sent[-1]


def test_logs_local_shows_backend_and_frontend(monkeypatch, tmp_path: Path) -> None:
    project_dir = tmp_path / "local_logs_proj"
    (project_dir / ".archmind").mkdir(parents=True, exist_ok=True)
    set_current_project(project_dir)
    (project_dir / ".archmind" / "backend.log").write_text("b1\nb2\n", encoding="utf-8")
    (project_dir / ".archmind" / "frontend.log").write_text("f1\nf2\n", encoding="utf-8")

    msg = DummyMessage()
    update = DummyUpdate(message=msg, effective_chat=DummyChat())
    asyncio.run(command_logs(update, DummyContext(args=["local"])))
    out = msg.sent[-1]
    assert "Local logs" in out
    assert "Project:\nlocal_logs_proj" in out
    assert "Backend logs (last 20 lines):" in out
    assert "b1\nb2" in out
    assert "Frontend logs (last 20 lines):" in out
    assert "f1\nf2" in out


def test_logs_without_args_uses_local_logs(tmp_path: Path) -> None:
    project_dir = tmp_path / "local_logs_default"
    (project_dir / ".archmind").mkdir(parents=True, exist_ok=True)
    set_current_project(project_dir)
    (project_dir / ".archmind" / "backend.log").write_text("backend default\n", encoding="utf-8")
    (project_dir / ".archmind" / "frontend.log").write_text("frontend default\n", encoding="utf-8")

    msg = DummyMessage()
    update = DummyUpdate(message=msg, effective_chat=DummyChat())
    asyncio.run(command_logs(update, DummyContext()))
    out = msg.sent[-1]
    assert "Local logs" in out
    assert "backend default" in out
    assert "frontend default" in out


def test_logs_local_backend_only(tmp_path: Path) -> None:
    project_dir = tmp_path / "local_logs_backend"
    (project_dir / ".archmind").mkdir(parents=True, exist_ok=True)
    set_current_project(project_dir)
    (project_dir / ".archmind" / "backend.log").write_text("only backend\n", encoding="utf-8")

    msg = DummyMessage()
    update = DummyUpdate(message=msg, effective_chat=DummyChat())
    asyncio.run(command_logs(update, DummyContext(args=["local", "backend"])))
    out = msg.sent[-1]
    assert "Backend logs (last 20 lines):" in out
    assert "only backend" in out
    assert "Frontend logs (last 20 lines):" not in out


def test_logs_local_no_logs_available(tmp_path: Path) -> None:
    project_dir = tmp_path / "local_logs_empty"
    project_dir.mkdir(parents=True, exist_ok=True)
    (project_dir / ".archmind").mkdir(parents=True, exist_ok=True)
    set_current_project(project_dir)

    msg = DummyMessage()
    update = DummyUpdate(message=msg, effective_chat=DummyChat())
    asyncio.run(command_logs(update, DummyContext(args=["local"])))
    out = msg.sent[-1]
    assert "No log files found. Showing backend runtime diagnostics instead." in out
    assert "Detected backend target:" in out
    assert "Run command:" in out


def test_logs_frontend_uses_runtime_service_log_path(monkeypatch, tmp_path: Path) -> None:
    project_dir = tmp_path / "local_logs_frontend_runtime_service"
    (project_dir / ".archmind" / "logs").mkdir(parents=True, exist_ok=True)
    set_current_project(project_dir)
    frontend_log = project_dir / ".archmind" / "logs" / "frontend.custom.log"
    frontend_log.write_text("front-service-line\n", encoding="utf-8")

    monkeypatch.setattr(
        "archmind.deploy.get_local_runtime_status",
        lambda _p: {
            "services": {
                "backend": {"status": "NOT RUNNING", "log_path": "", "url": ""},
                "frontend": {"status": "RUNNING", "log_path": str(frontend_log), "url": "http://127.0.0.1:3000"},
            },
            "backend": {"status": "NOT RUNNING", "url": ""},
            "frontend": {"status": "RUNNING", "url": "http://127.0.0.1:3000"},
        },
    )

    msg = DummyMessage()
    update = DummyUpdate(message=msg, effective_chat=DummyChat())
    asyncio.run(command_logs(update, DummyContext(args=["frontend"])))
    out = msg.sent[-1]
    assert "Frontend logs (last 20 lines):" in out
    assert "front-service-line" in out


def test_extract_key_error_lines_backend_priority() -> None:
    raw = """
    project_dir: /tmp/demo
    AssertionError: expected 200 got 500
    FAILED tests/test_api.py::test_create_todo
    E   assert 500 == 200
    """
    lines = extract_key_error_lines(raw)
    joined = "\n".join(lines)
    assert "AssertionError" in joined
    assert "FAILED tests/test_api.py::test_create_todo" in joined


def test_extract_key_error_lines_frontend_priority() -> None:
    raw = """
    timestamp: 20260309_120000
    ESLint: Parsing error ...
    TS2322: Type 'string' is not assignable to type 'number'
    app/page.tsx:12
    """
    lines = extract_key_error_lines(raw)
    joined = "\n".join(lines)
    assert "ESLint: Parsing error" in joined
    assert "TS2322" in joined


def test_sanitize_removes_metadata_noise() -> None:
    raw = """
    project_dir: /Users/me/proj
    timestamp: 20260309_120000
    command: archmind pipeline --path /Users/me/proj
    cwd: /Users/me/proj
    duration_s: 1.2
    Base
    Cancel
    Traceback:
    AssertionError: expected 200 got 500
    """
    cleaned = sanitize_log_excerpt(raw)
    assert "project_dir" not in cleaned
    assert "timestamp" not in cleaned
    assert "command:" not in cleaned.lower()
    assert "cwd:" not in cleaned.lower()
    assert "duration" not in cleaned.lower()
    assert "Base" not in cleaned
    assert "Cancel" not in cleaned
    assert "Traceback:" not in cleaned
    assert "AssertionError" in cleaned


def test_sanitize_removes_eslint_interactive_noise() -> None:
    raw = """
    How would you like to configure ESLint?
    Strict (recommended)
    If you set up ESLint yourself, we recommend adding the Next.js ESLint plugin
    info  - Need to disable some ESLint rules?
    Learn more here: https://nextjs.org/docs/app/api-reference/config/eslint#disabling-rules
    ESLint: Parsing error
    app/page.tsx:12
    """
    cleaned = sanitize_log_excerpt(raw)
    assert "How would you like to configure ESLint?" not in cleaned
    assert "Strict (recommended)" not in cleaned
    assert "If you set up ESLint yourself" not in cleaned
    assert "Need to disable some ESLint rules" not in cleaned
    assert "nextjs.org/docs/app/api-reference/config/eslint#disabling-rules" not in cleaned
    assert "ESLint: Parsing error" in cleaned


def test_build_logs_message_structure() -> None:
    msg = build_logs_message(
        project_name="simple_todo_web_app_with_api",
        log_type="backend",
        failure="backend pytest failed",
        key_lines=["AssertionError: expected 200 got 500", "FAILED tests/test_api.py::test_create_todo"],
        focus=["inspect backend implementation", "compare API response with test expectations"],
    )
    assert "Project:\nsimple_todo_web_app_with_api" in msg
    assert "Failure:" in msg
    assert "Key lines:" in msg
    assert "Focus:" in msg


def test_read_recent_last_logs_combines_backend_frontend(tmp_path: Path) -> None:
    project_dir = tmp_path / "combo"
    run_logs = project_dir / ".archmind" / "run_logs"
    run_logs.mkdir(parents=True, exist_ok=True)
    (run_logs / "run_20260309_120000.summary.txt").write_text(
        "AssertionError: expected 200 got 500\n"
        "FAILED tests/test_api.py::test_create_todo\n"
        "ESLint: Parsing error in app/page.tsx:12\n",
        encoding="utf-8",
    )
    msg = read_recent_last_logs(project_dir)
    assert "Logs: last" in msg
    assert "Failure:" in msg
    assert "backend pytest failed" in msg.lower()
    assert "frontend lint failed" in msg.lower()
    assert "Key lines:" in msg
    assert "Focus:" in msg


def test_retry_without_last_project_shows_help(monkeypatch) -> None:
    monkeypatch.setattr("archmind.telegram_bot.load_last_project_path", lambda: None)
    msg = DummyMessage()
    update = DummyUpdate(message=msg, effective_chat=DummyChat())
    ctx = DummyContext()
    asyncio.run(command_retry(update, ctx))
    assert msg.sent
    assert "No previous project found. Use /idea first." in msg.sent[-1]


def test_continue_started_message_contains_running_state(monkeypatch, tmp_path: Path) -> None:
    project_dir = tmp_path / "cont_proj"
    project_dir.mkdir(parents=True, exist_ok=True)
    _mark_archmind_project(project_dir)
    monkeypatch.setattr("archmind.telegram_bot.load_last_project_path", lambda: project_dir)
    monkeypatch.setattr("archmind.telegram_bot.set_agent_state", lambda *a, **k: {})

    class DummyProc:
        pid = 555

    monkeypatch.setattr("archmind.telegram_bot.start_background_process", lambda *a, **k: DummyProc())
    msg = DummyMessage()
    update = DummyUpdate(message=msg, effective_chat=DummyChat())
    ctx = DummyContext(application=None)
    asyncio.run(command_continue(update, ctx))
    assert msg.sent
    assert "continuing: pid=555" in msg.sent[-1]
    assert "command=/continue" in msg.sent[-1]
    assert "state=RUNNING" in msg.sent[-1]
    assert "progress=Running checks" in msg.sent[-1]


def test_busy_message_when_long_running_command_already_running(monkeypatch, tmp_path: Path) -> None:
    project_dir = tmp_path / "busy_proj"
    project_dir.mkdir(parents=True, exist_ok=True)
    _mark_archmind_project(project_dir)
    monkeypatch.setattr("archmind.telegram_bot.load_last_project_path", lambda: project_dir)
    monkeypatch.setattr("archmind.telegram_bot.set_agent_state", lambda *a, **k: {})

    class DummyProc:
        pid = 777

        def poll(self) -> None:
            return None

    monkeypatch.setattr("archmind.telegram_bot.start_background_process", lambda *a, **k: DummyProc())
    msg = DummyMessage()
    update = DummyUpdate(message=msg, effective_chat=DummyChat())
    ctx = DummyContext(application=None)

    asyncio.run(command_continue(update, ctx))
    asyncio.run(command_fix(update, ctx))

    assert len(msg.sent) >= 2
    assert "ArchMind is already processing a command." in msg.sent[-1]
    assert "Current state: RUNNING" in msg.sent[-1]
    assert "Progress: Running checks" in msg.sent[-1]
    assert "Use /status to inspect current progress." in msg.sent[-1]


def test_retry_done_status_is_blocked_with_message(monkeypatch, tmp_path: Path) -> None:
    project_dir = tmp_path / "done_proj"
    project_dir.mkdir(parents=True, exist_ok=True)
    _mark_archmind_project(project_dir)
    monkeypatch.setattr("archmind.telegram_bot.load_last_project_path", lambda: project_dir)
    monkeypatch.setattr("archmind.telegram_bot._status_from_sources", lambda _p: "DONE")
    msg = DummyMessage()
    update = DummyUpdate(message=msg, effective_chat=DummyChat())
    ctx = DummyContext(application=None)
    asyncio.run(command_retry(update, ctx))
    assert msg.sent
    assert "Project already complete." in msg.sent[-1]


def test_retry_is_blocked_when_evaluation_not_done_but_runtime_detect_is_clean(monkeypatch, tmp_path: Path) -> None:
    project_dir = tmp_path / "retry_clean_runtime"
    archmind = project_dir / ".archmind"
    archmind.mkdir(parents=True, exist_ok=True)
    (project_dir / "app").mkdir(parents=True, exist_ok=True)
    (project_dir / "app" / "main.py").write_text("from fastapi import FastAPI\napp = FastAPI()\n", encoding="utf-8")
    (project_dir / "requirements.txt").write_text("fastapi\nuvicorn\n", encoding="utf-8")
    (archmind / "state.json").write_text(json.dumps({"last_status": "NOT_DONE", "runtime": {"failure_class": ""}}), encoding="utf-8")
    (archmind / "evaluation.json").write_text(json.dumps({"status": "NOT_DONE"}), encoding="utf-8")
    _mark_archmind_project(project_dir)
    monkeypatch.setattr("archmind.telegram_bot.load_last_project_path", lambda: project_dir)
    monkeypatch.setattr(
        "archmind.telegram_bot.detect_backend_runtime_entry",
        lambda _p, port=8000: {"ok": True, "backend_entry": "app.main:app"},
    )
    msg = DummyMessage()
    update = DummyUpdate(message=msg, effective_chat=DummyChat())
    asyncio.run(command_retry(update, DummyContext(application=None)))
    assert msg.sent
    assert "Project already complete." in msg.sent[-1]


def test_retry_sets_retrying_state_on_start(monkeypatch, tmp_path: Path) -> None:
    project_dir = tmp_path / "retry_proj"
    project_dir.mkdir(parents=True, exist_ok=True)
    _mark_archmind_project(project_dir)
    monkeypatch.setattr("archmind.telegram_bot.load_last_project_path", lambda: project_dir)
    monkeypatch.setattr("archmind.telegram_bot._status_from_sources", lambda _p: "NOT_DONE")
    states: list[str] = []

    def fake_set_agent_state(project_dir_arg, state, **kwargs):  # type: ignore[no-untyped-def]
        assert project_dir_arg == project_dir
        states.append(state)
        return {}

    monkeypatch.setattr("archmind.telegram_bot.set_agent_state", fake_set_agent_state)
    msg = DummyMessage()
    update = DummyUpdate(message=msg, effective_chat=DummyChat())
    ctx = DummyContext(application=object())
    asyncio.run(command_retry(update, ctx))
    assert "RETRYING" in states
    assert any("state=RETRYING" in text for text in msg.sent)


def test_build_completion_message_prefers_latest_evaluation_status(tmp_path: Path) -> None:
    project_dir = tmp_path / "fresh"
    archmind = project_dir / ".archmind"
    archmind.mkdir(parents=True, exist_ok=True)
    (archmind / "state.json").write_text(
        json.dumps({"last_status": "NOT_DONE", "iterations": 3, "fix_attempts": 2}),
        encoding="utf-8",
    )
    (archmind / "evaluation.json").write_text(
        json.dumps({"status": "DONE", "reasons": ["all tasks complete"]}),
        encoding="utf-8",
    )
    msg = build_completion_message(project_dir, tmp_path / "unused.log")
    assert "Status: DONE" in msg
    assert "Iterations: 3" in msg
    assert "Fix attempts: 2" in msg
    assert "Summary:" in msg
    assert "- All tasks complete" in msg
    assert "- Evaluation complete" in msg


def test_watch_retry_reads_latest_state_after_steps(monkeypatch, tmp_path: Path) -> None:
    project_dir = tmp_path / "retry_project"
    archmind = project_dir / ".archmind"
    archmind.mkdir(parents=True, exist_ok=True)
    (project_dir / "app").mkdir(parents=True, exist_ok=True)
    (project_dir / "app" / "main.py").write_text(
        "from fastapi import FastAPI\napp = FastAPI()\n",
        encoding="utf-8",
    )
    (project_dir / "requirements.txt").write_text("fastapi\nuvicorn\n", encoding="utf-8")
    temp_log = tmp_path / "retry.log"

    (archmind / "state.json").write_text(
        json.dumps({"last_status": "NOT_DONE", "iterations": 1, "fix_attempts": 0}),
        encoding="utf-8",
    )
    (archmind / "evaluation.json").write_text(json.dumps({"status": "NOT_DONE"}), encoding="utf-8")

    calls = {"n": 0}

    def fake_run_command(cmd, _temp_log):  # type: ignore[no-untyped-def]
        calls["n"] += 1
        state_payload = json.loads((archmind / "state.json").read_text(encoding="utf-8"))
        if cmd[:2] == ["archmind", "fix"]:
            state_payload["fix_attempts"] = int(state_payload.get("fix_attempts") or 0) + 1
        if cmd[:2] == ["archmind", "pipeline"]:
            state_payload["iterations"] = int(state_payload.get("iterations") or 0) + 1
            state_payload["last_status"] = "DONE"
            (archmind / "evaluation.json").write_text(json.dumps({"status": "DONE"}), encoding="utf-8")
        (archmind / "state.json").write_text(json.dumps(state_payload), encoding="utf-8")
        return 0

    monkeypatch.setattr("archmind.telegram_bot._run_command_to_log", fake_run_command)

    class DummyBot:
        def __init__(self) -> None:
            self.sent: list[str] = []

        async def send_message(self, chat_id: int, text: str) -> None:  # noqa: ARG002
            self.sent.append(text)

    class DummyApp:
        def __init__(self) -> None:
            self.bot = DummyBot()

    app = DummyApp()
    asyncio.run(watch_retry_and_notify(project_dir=project_dir, temp_log=temp_log, chat_id=1, application=app))
    assert calls["n"] == 2
    assert app.bot.sent
    final_msg = app.bot.sent[-1]
    assert "Status: DONE" in final_msg
    assert "Iterations: 2" in final_msg
    assert "Fix attempts: 1" in final_msg


def test_watch_retry_runs_fix_then_pipeline_order(monkeypatch, tmp_path: Path) -> None:
    project_dir = tmp_path / "retry_order"
    archmind = project_dir / ".archmind"
    archmind.mkdir(parents=True, exist_ok=True)
    temp_log = tmp_path / "retry_order.log"
    (archmind / "state.json").write_text(json.dumps({"last_status": "NOT_DONE"}), encoding="utf-8")
    order: list[str] = []

    def fake_run_command(cmd, _temp_log):  # type: ignore[no-untyped-def]
        order.append(cmd[1])
        return 0

    monkeypatch.setattr("archmind.telegram_bot._run_command_to_log", fake_run_command)
    monkeypatch.setattr("archmind.telegram_bot.set_agent_state", lambda *a, **k: {})

    class DummyBot:
        async def send_message(self, chat_id: int, text: str) -> None:  # noqa: ARG002
            return None

    class DummyApp:
        def __init__(self) -> None:
            self.bot = DummyBot()

    asyncio.run(watch_retry_and_notify(project_dir=project_dir, temp_log=temp_log, chat_id=1, application=DummyApp()))
    assert order == ["fix", "pipeline"]


def test_state_command_forwards_state_summary(monkeypatch, tmp_path: Path) -> None:
    project_dir = tmp_path / "state_proj"
    project_dir.mkdir(parents=True, exist_ok=True)
    _mark_archmind_project(project_dir)
    monkeypatch.setattr("archmind.telegram_bot.load_last_project_path", lambda: project_dir)
    state_text = "\n".join(
        [
            "Project status: STUCK",
            "Agent state: IDLE",
            "Fix attempts: 3",
            "Next action: STUCK",
        ]
    )
    monkeypatch.setattr("archmind.telegram_bot.run_state_command", lambda *_: (True, state_text))
    msg = DummyMessage()
    update = DummyUpdate(message=msg, effective_chat=DummyChat())
    ctx = DummyContext()
    asyncio.run(command_state(update, ctx))
    assert msg.sent
    assert "Project status: STUCK" in msg.sent[-1]
    assert "Agent state: IDLE" in msg.sent[-1]
    assert "Fix attempts: 3" in msg.sent[-1]
    assert "Next action: STUCK" in msg.sent[-1]


def test_state_command_shows_running_state_quickly(monkeypatch, tmp_path: Path) -> None:
    project_dir = tmp_path / "running_state_proj"
    project_dir.mkdir(parents=True, exist_ok=True)
    _mark_archmind_project(project_dir)
    monkeypatch.setattr("archmind.telegram_bot.load_last_project_path", lambda: project_dir)
    monkeypatch.setattr("archmind.telegram_bot.set_agent_state", lambda *a, **k: {})

    class DummyProc:
        pid = 808

        def poll(self) -> None:
            return None

    monkeypatch.setattr("archmind.telegram_bot.start_background_process", lambda *a, **k: DummyProc())
    monkeypatch.setattr("archmind.telegram_bot.run_state_command", lambda *_: (True, "should not be used"))
    msg = DummyMessage()
    update = DummyUpdate(message=msg, effective_chat=DummyChat())
    ctx = DummyContext(application=None)

    asyncio.run(command_continue(update, ctx))
    asyncio.run(command_state(update, ctx))

    assert "Current state: RUNNING" in msg.sent[-1]
    assert "Current command: /continue" in msg.sent[-1]
    assert "Progress: Running checks" in msg.sent[-1]
    assert str(project_dir) in msg.sent[-1]


def test_status_command_returns_summary(monkeypatch, tmp_path: Path) -> None:
    project_dir = tmp_path / "status_proj"
    archmind = project_dir / ".archmind"
    archmind.mkdir(parents=True, exist_ok=True)
    _mark_archmind_project(project_dir)
    monkeypatch.setattr("archmind.telegram_bot.load_last_project_path", lambda: project_dir)
    (archmind / "state.json").write_text(
        json.dumps(
            {
                "agent_state": "IDLE",
                "iterations": 3,
                "fix_attempts": 1,
                "project_type": "frontend-web",
                "effective_template": "nextjs",
                "next_action": "run /fix",
            }
        ),
        encoding="utf-8",
    )
    run_logs = archmind / "run_logs"
    run_logs.mkdir(parents=True, exist_ok=True)
    (run_logs / "run_20260312_120000.summary.json").write_text(
        json.dumps({"backend": {"status": "SKIPPED"}, "frontend": {"status": "WARNING"}}),
        encoding="utf-8",
    )
    msg = DummyMessage()
    update = DummyUpdate(message=msg, effective_chat=DummyChat())
    ctx = DummyContext()
    asyncio.run(command_status(update, ctx))

    out = msg.sent[-1]
    assert "ArchMind status" in out
    assert "Project:\nstatus_proj" in out
    assert "Status:\nIDLE" in out
    assert "Iterations: 3" in out
    assert "Fix attempts: 1" in out
    assert "Project type: frontend-web" in out
    assert "Template: nextjs" in out
    assert "Backend:\nSKIP" in out
    assert "Frontend:\nWARNING" in out
    assert "Next:\n/fix" in out


def test_status_command_works_when_running(monkeypatch, tmp_path: Path) -> None:
    project_dir = tmp_path / "status_running"
    archmind = project_dir / ".archmind"
    archmind.mkdir(parents=True, exist_ok=True)
    _mark_archmind_project(project_dir)
    monkeypatch.setattr("archmind.telegram_bot.load_last_project_path", lambda: project_dir)
    (archmind / "state.json").write_text(
        json.dumps({"agent_state": "IDLE", "iterations": 4, "fix_attempts": 2, "project_type": "backend-api", "effective_template": "fastapi"}),
        encoding="utf-8",
    )
    (archmind / "evaluation.json").write_text(json.dumps({"next_actions": ["run /continue"]}), encoding="utf-8")
    run_logs = archmind / "run_logs"
    run_logs.mkdir(parents=True, exist_ok=True)
    (run_logs / "run_20260312_120000.summary.json").write_text(
        json.dumps({"backend": {"status": "FAIL"}, "frontend": {"status": "ABSENT"}}),
        encoding="utf-8",
    )

    class DummyProc:
        pid = 1001

        def poll(self) -> None:
            return None

    telegram_bot._register_running_job("/continue", "RUNNING", project_dir, proc=DummyProc())
    msg = DummyMessage()
    update = DummyUpdate(message=msg, effective_chat=DummyChat())
    ctx = DummyContext()
    asyncio.run(command_status(update, ctx))

    out = msg.sent[-1]
    assert "Status:\nRUNNING" in out
    assert "Progress: Running checks" in out
    assert "Backend:\nFAIL" in out
    assert "Frontend:\nABSENT" in out
    assert "Next:\n/continue" in out


def test_format_status_text_defaults_when_idle_without_artifacts(tmp_path: Path) -> None:
    project_dir = tmp_path / "status_idle_default"
    project_dir.mkdir(parents=True, exist_ok=True)
    out = format_status_text(project_dir)
    assert "ArchMind status" in out
    assert "Project:\nstatus_idle_default" in out
    assert "Status:\nIDLE" in out
    assert "Backend:\nUNKNOWN" in out
    assert "Frontend:\nUNKNOWN" in out


def test_format_status_text_includes_architecture_reasoning(tmp_path: Path) -> None:
    project_dir = tmp_path / "status_reasoning"
    archmind = project_dir / ".archmind"
    archmind.mkdir(parents=True, exist_ok=True)
    (archmind / "state.json").write_text(
        json.dumps(
            {
                "agent_state": "IDLE",
                "architecture_app_shape": "fullstack",
                "architecture_reason_summary": "task tracking web app with separate backend and frontend",
            }
        ),
        encoding="utf-8",
    )

    out = format_status_text(project_dir)
    assert "Reasoning: fullstack / task tracking web app with separate backend and frontend" in out


def test_projects_command_works_when_no_projects_exist(monkeypatch, tmp_path: Path) -> None:
    empty_root = tmp_path / "projects"
    empty_root.mkdir(parents=True, exist_ok=True)
    monkeypatch.setenv("ARCHMIND_PROJECTS_DIR", str(empty_root))

    msg = DummyMessage()
    update = DummyUpdate(message=msg, effective_chat=DummyChat())
    ctx = DummyContext()
    asyncio.run(command_projects(update, ctx))
    assert msg.sent
    assert "Recent ArchMind projects" in msg.sent[-1]
    assert "(no projects found)" in msg.sent[-1]


def test_projects_command_returns_list(monkeypatch, tmp_path: Path) -> None:
    root = tmp_path / "projects"
    root.mkdir(parents=True, exist_ok=True)
    monkeypatch.setenv("ARCHMIND_PROJECTS_DIR", str(root))

    p1 = root / "20260312_210244_simple_nextjs_todo_dashboard_req"
    p2 = root / "20260312_140408_simple_fastapi_notes_api_require"
    p1_arch = p1 / ".archmind"
    p2_arch = p2 / ".archmind"
    p1_arch.mkdir(parents=True, exist_ok=True)
    p2_arch.mkdir(parents=True, exist_ok=True)
    (p1_arch / "state.json").write_text(
        json.dumps({"last_status": "DONE", "project_type": "frontend-web", "effective_template": "nextjs"}),
        encoding="utf-8",
    )
    (p2_arch / "state.json").write_text(
        json.dumps({"last_status": "DONE", "project_type": "backend-api", "effective_template": "fastapi"}),
        encoding="utf-8",
    )

    msg = DummyMessage()
    update = DummyUpdate(message=msg, effective_chat=DummyChat())
    ctx = DummyContext()
    asyncio.run(command_projects(update, ctx))
    out = msg.sent[-1]
    assert "Recent ArchMind projects" in out
    assert "1. 20260312_210244_simple_nextjs_todo_dashboard_req" in out or "1. 20260312_140408_simple_fastapi_notes_api_require" in out
    assert "Status: STOPPED" in out
    assert "Type: frontend-web" in out
    assert "Template: nextjs" in out
    assert "Type: backend-api" in out
    assert "Template: fastapi" in out


def test_use_by_index_works(monkeypatch, tmp_path: Path) -> None:
    root = tmp_path / "projects"
    root.mkdir(parents=True, exist_ok=True)
    monkeypatch.setenv("ARCHMIND_PROJECTS_DIR", str(root))
    for name in ("20260312_p1", "20260312_p2"):
        project = root / name
        arch = project / ".archmind"
        arch.mkdir(parents=True, exist_ok=True)
        (arch / "project_spec.json").write_text(
            json.dumps({"shape": "backend", "template": "fastapi", "domains": ["notes"], "modules": ["db"]}),
            encoding="utf-8",
        )
        (project / ".archmind" / "state.json").write_text(
            json.dumps({"last_status": "NOT_DONE", "project_type": "backend-api", "effective_template": "fastapi"}),
            encoding="utf-8",
        )

    monkeypatch.setattr(
        "archmind.deploy.get_local_runtime_status",
        lambda _p: {
            "backend": {"status": "NOT RUNNING", "pid": None, "url": ""},
            "frontend": {"status": "NOT RUNNING", "pid": None, "url": ""},
        },
    )

    msg = DummyMessage()
    update = DummyUpdate(message=msg, effective_chat=DummyChat())
    ctx = DummyContext(args=["1"])
    asyncio.run(command_use(update, ctx))

    assert msg.sent
    assert "Selected project:" in msg.sent[-1]
    assert "Shape:" in msg.sent[-1]
    assert "Template:" in msg.sent[-1]
    assert get_current_project() is not None


def test_use_by_project_name_works(monkeypatch, tmp_path: Path) -> None:
    root = tmp_path / "projects"
    root.mkdir(parents=True, exist_ok=True)
    monkeypatch.setenv("ARCHMIND_PROJECTS_DIR", str(root))
    project = root / "20260312_named_proj"
    arch = project / ".archmind"
    arch.mkdir(parents=True, exist_ok=True)
    (arch / "project_spec.json").write_text(
        json.dumps(
            {
                "shape": "fullstack",
                "template": "fullstack-ddd",
                "domains": ["tasks", "teams"],
                "modules": ["auth", "db", "dashboard"],
            }
        ),
        encoding="utf-8",
    )
    (project / ".archmind" / "state.json").write_text(
        json.dumps(
            {
                "last_status": "DONE",
                "project_type": "frontend-web",
                "effective_template": "nextjs",
                "backend_deploy_url": "http://127.0.0.1:8011",
                "frontend_deploy_url": "http://127.0.0.1:3011",
                "deploy_target": "local",
                "last_deploy_status": "SUCCESS",
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(
        "archmind.deploy.get_local_runtime_status",
        lambda _p: {
            "backend": {"status": "RUNNING", "pid": 12001, "url": "http://127.0.0.1:8011"},
            "frontend": {"status": "RUNNING", "pid": 13001, "url": "http://127.0.0.1:3011"},
        },
    )

    msg = DummyMessage()
    update = DummyUpdate(message=msg, effective_chat=DummyChat())
    ctx = DummyContext(args=["20260312_named_proj"])
    asyncio.run(command_use(update, ctx))

    assert msg.sent
    out = msg.sent[-1]
    assert "Selected project: 20260312_named_proj" in out
    assert "Shape:" in out
    assert "Template:" in out
    assert "Domains:" in out
    assert "tasks, teams" in out
    assert "Modules:" in out
    assert "auth, db, dashboard" in out
    assert "Runtime:" in out
    assert "Backend: RUNNING" in out
    assert "Frontend: RUNNING" in out
    assert "Backend URL:" in out
    assert "Frontend URL:" in out
    assert "Deploy:" in out
    assert "Target: local" in out
    assert "Status: SUCCESS" in out
    assert "Try next:" in out
    assert "- /next" in out
    assert get_current_project() == project.resolve()


def test_use_summary_shows_backend_running_frontend_stopped(monkeypatch, tmp_path: Path) -> None:
    root = tmp_path / "projects"
    root.mkdir(parents=True, exist_ok=True)
    monkeypatch.setenv("ARCHMIND_PROJECTS_DIR", str(root))
    project = root / "worker_api_proj"
    arch = project / ".archmind"
    arch.mkdir(parents=True, exist_ok=True)
    (arch / "project_spec.json").write_text(
        json.dumps({"shape": "backend", "template": "worker-api", "modules": ["worker"]}),
        encoding="utf-8",
    )
    (arch / "state.json").write_text(json.dumps({"last_status": "DONE"}), encoding="utf-8")
    monkeypatch.setattr(
        "archmind.deploy.get_local_runtime_status",
        lambda _p: {
            "backend": {"status": "RUNNING", "pid": 22001, "url": "http://127.0.0.1:8050"},
            "frontend": {"status": "NOT RUNNING", "pid": None, "url": ""},
        },
    )

    msg = DummyMessage()
    update = DummyUpdate(message=msg, effective_chat=DummyChat())
    asyncio.run(command_use(update, DummyContext(args=["worker_api_proj"])))
    out = msg.sent[-1]
    assert "Runtime:" in out
    assert "Backend: RUNNING" in out
    assert "Frontend: STOPPED" in out


def test_invalid_use_returns_error(monkeypatch, tmp_path: Path) -> None:
    root = tmp_path / "projects"
    root.mkdir(parents=True, exist_ok=True)
    monkeypatch.setenv("ARCHMIND_PROJECTS_DIR", str(root))
    msg = DummyMessage()
    update = DummyUpdate(message=msg, effective_chat=DummyChat())

    asyncio.run(command_use(update, DummyContext(args=["3"])))
    assert "invalid index" in msg.sent[-1]

    asyncio.run(command_use(update, DummyContext(args=["missing_project"])))
    assert "project not found" in msg.sent[-1]


def test_current_shows_selected_project(monkeypatch, tmp_path: Path) -> None:
    project = tmp_path / "current_proj"
    archmind = project / ".archmind"
    archmind.mkdir(parents=True, exist_ok=True)
    (archmind / "state.json").write_text(
        json.dumps({"last_status": "DONE", "project_type": "frontend-web", "effective_template": "nextjs"}),
        encoding="utf-8",
    )
    monkeypatch.setattr(
        "archmind.deploy.get_local_runtime_status",
        lambda _p: {
            "backend": {"status": "RUNNING", "pid": 22001, "url": "http://127.0.0.1:8050"},
            "frontend": {"status": "NOT RUNNING", "pid": None, "url": ""},
        },
    )
    set_current_project(project)

    msg = DummyMessage()
    update = DummyUpdate(message=msg, effective_chat=DummyChat())
    asyncio.run(command_current(update, DummyContext()))
    out = msg.sent[-1]
    assert "Current project" in out
    assert "Project: current_proj" in out
    assert "Status: RUNNING" in out
    assert "Type: frontend-web" in out
    assert "Template: nextjs" in out
    assert "Runtime" in out
    assert "Backend: RUNNING" in out
    assert "Backend URL: http://127.0.0.1:8050" in out
    assert "Frontend: NOT RUNNING" in out
    assert "Frontend URL:" not in out
    assert "/inspect" in out
    assert "/next" in out


def test_current_uses_persisted_selection_when_in_memory_current_is_missing(monkeypatch, tmp_path: Path) -> None:
    project = tmp_path / "persisted_current_proj"
    archmind = project / ".archmind"
    archmind.mkdir(parents=True, exist_ok=True)
    (archmind / "state.json").write_text(
        json.dumps({"last_status": "DONE", "project_type": "frontend-web", "effective_template": "nextjs"}),
        encoding="utf-8",
    )
    clear_current_project()
    monkeypatch.setattr("archmind.telegram_bot.get_validated_current_project", lambda: project)
    monkeypatch.setattr(
        "archmind.deploy.get_local_runtime_status",
        lambda _p: {
            "backend": {"status": "STOPPED", "pid": None, "url": ""},
            "frontend": {"status": "NOT RUNNING", "pid": None, "url": ""},
        },
    )

    msg = DummyMessage()
    update = DummyUpdate(message=msg, effective_chat=DummyChat())
    asyncio.run(command_current(update, DummyContext()))
    out = msg.sent[-1]
    assert "Current project" in out
    assert "Project: persisted_current_proj" in out


def test_get_current_project_reads_persisted_selection_over_stale_in_memory_cache(tmp_path: Path) -> None:
    alpha = tmp_path / "alpha"
    beta = tmp_path / "beta"
    _mark_archmind_project(alpha)
    _mark_archmind_project(beta)
    current_project_state._CURRENT_PROJECT = alpha.resolve()
    current_project_state.save_last_project_path(beta)
    try:
        assert get_current_project() == beta.resolve()
    finally:
        clear_current_project()


def test_current_returns_no_selection_when_persisted_project_is_stale(monkeypatch, tmp_path: Path) -> None:
    stale_project = tmp_path / "beta"
    stale_project.mkdir(parents=True, exist_ok=True)
    clear_current_project()
    monkeypatch.setattr("archmind.telegram_bot.get_validated_current_project", lambda: None)

    msg = DummyMessage()
    update = DummyUpdate(message=msg, effective_chat=DummyChat())
    asyncio.run(command_current(update, DummyContext()))
    out = msg.sent[-1]
    assert "No current project selected" in out


def test_history_without_current_project_returns_safe_guidance() -> None:
    clear_current_project()
    msg = DummyMessage()
    update = DummyUpdate(message=msg, effective_chat=DummyChat())
    asyncio.run(command_history(update, DummyContext()))
    out = msg.sent[-1]
    assert "No active project." in out


def test_history_no_history_file_returns_empty_message(tmp_path: Path) -> None:
    project = tmp_path / "history_empty_proj"
    _mark_archmind_project(project)
    set_current_project(project)
    msg = DummyMessage()
    update = DummyUpdate(message=msg, effective_chat=DummyChat())
    asyncio.run(command_history(update, DummyContext()))
    out = msg.sent[-1]
    assert "Execution history" in out
    assert "Target Project: history_empty_proj" in out
    assert "No execution history yet." in out


def test_history_shows_recent_events_newest_first_and_reason(tmp_path: Path) -> None:
    project = tmp_path / "history_proj"
    _mark_archmind_project(project)
    set_current_project(project)
    assert append_execution_event(
        project,
        project_name=project.name,
        source="telegram-next",
        command="/add_field Task title:string",
        status="ok",
        message="Field added",
        timestamp="2026-03-22T00:00:01Z",
    )
    assert append_execution_event(
        project,
        project_name=project.name,
        source="telegram-auto",
        command="/auto",
        status="stop",
        message="Stopped",
        stop_reason="low-priority next action",
        timestamp="2026-03-22T00:00:02Z",
    )
    assert append_execution_event(
        project,
        project_name=project.name,
        source="ui-next-run",
        command="/implement_page songs/favorite",
        status="fail",
        message="Page not found",
        timestamp="2026-03-22T00:00:03Z",
    )
    msg = DummyMessage()
    update = DummyUpdate(message=msg, effective_chat=DummyChat())
    asyncio.run(command_history(update, DummyContext()))
    out = msg.sent[-1]
    assert "Execution history" in out
    assert "Target Project: history_proj" in out
    assert "1. [fail] /implement_page songs/favorite" in out
    assert "Source: ui-next-run" in out
    assert "Message: Page not found" in out
    assert "2. [stop] /auto" in out
    assert "Reason: low-priority next action" in out
    assert "3. [ok] /add_field Task title:string" in out


def test_history_limit_clamps_to_one_to_twenty(tmp_path: Path) -> None:
    project = tmp_path / "history_limit_proj"
    _mark_archmind_project(project)
    set_current_project(project)
    for idx in range(25):
        assert append_execution_event(
            project,
            project_name=project.name,
            source="manual-command",
            command=f"/add_page tasks/{idx}",
            status="ok",
            message="ok",
            timestamp=f"2026-03-22T00:00:{idx:02d}Z",
        )

    msg_one = DummyMessage()
    update_one = DummyUpdate(message=msg_one, effective_chat=DummyChat())
    asyncio.run(command_history(update_one, DummyContext(args=["0"])))
    out_one = msg_one.sent[-1]
    assert out_one.count(". [ok]") == 1
    assert "/add_page tasks/24" in out_one

    msg_twenty = DummyMessage()
    update_twenty = DummyUpdate(message=msg_twenty, effective_chat=DummyChat())
    asyncio.run(command_history(update_twenty, DummyContext(args=["999"])))
    out_twenty = msg_twenty.sent[-1]
    assert out_twenty.count(". [ok]") == 20
    assert "/add_page tasks/24" in out_twenty
    assert "/add_page tasks/5" in out_twenty
    assert "/add_page tasks/4" not in out_twenty


def test_current_shows_frontend_url_when_frontend_running(monkeypatch, tmp_path: Path) -> None:
    project = tmp_path / "current_frontend_proj"
    archmind = project / ".archmind"
    archmind.mkdir(parents=True, exist_ok=True)
    (archmind / "state.json").write_text(
        json.dumps({"last_status": "DONE", "project_type": "fullstack-web", "effective_template": "fullstack-ddd"}),
        encoding="utf-8",
    )
    monkeypatch.setattr(
        "archmind.deploy.get_local_runtime_status",
        lambda _p: {
            "backend": {"status": "RUNNING", "pid": 22001, "url": "http://127.0.0.1:8050"},
            "frontend": {"status": "RUNNING", "pid": 22002, "url": "http://127.0.0.1:3000"},
        },
    )
    set_current_project(project)

    msg = DummyMessage()
    update = DummyUpdate(message=msg, effective_chat=DummyChat())
    asyncio.run(command_current(update, DummyContext()))
    out = msg.sent[-1]
    assert "Frontend: RUNNING" in out
    assert "Frontend URL: http://127.0.0.1:3000" in out
    assert "/inspect" in out
    assert "/next" in out


def test_current_shows_external_urls_when_runtime_running(monkeypatch, tmp_path: Path) -> None:
    project = tmp_path / "current_external_proj"
    archmind = project / ".archmind"
    archmind.mkdir(parents=True, exist_ok=True)
    (archmind / "state.json").write_text(
        json.dumps({"last_status": "DONE", "project_type": "fullstack-web", "effective_template": "fullstack-ddd"}),
        encoding="utf-8",
    )
    monkeypatch.setattr(
        "archmind.deploy.get_local_runtime_status",
        lambda _p: {
            "backend": {"status": "RUNNING", "pid": 22001, "url": "http://127.0.0.1:8050"},
            "frontend": {"status": "RUNNING", "pid": 22002, "url": "http://127.0.0.1:3000"},
        },
    )
    monkeypatch.setattr("archmind.telegram_bot._detect_external_ip", lambda: "100.64.0.10")
    set_current_project(project)

    msg = DummyMessage()
    update = DummyUpdate(message=msg, effective_chat=DummyChat())
    asyncio.run(command_current(update, DummyContext()))
    out = msg.sent[-1]
    assert "Backend URL: http://127.0.0.1:8050" in out
    assert "Frontend URL: http://127.0.0.1:3000" in out
    assert "External URL: http://100.64.0.10:8050" in out
    assert "External URL: http://100.64.0.10:3000" in out


def test_projects_marks_current_project(monkeypatch, tmp_path: Path) -> None:
    root = tmp_path / "projects"
    root.mkdir(parents=True, exist_ok=True)
    monkeypatch.setenv("ARCHMIND_PROJECTS_DIR", str(root))
    p1 = root / "p1"
    p2 = root / "p2"
    (p1 / ".archmind").mkdir(parents=True, exist_ok=True)
    (p2 / ".archmind").mkdir(parents=True, exist_ok=True)
    set_current_project(p2)
    out = format_projects_list()
    assert "p2 [current]" in out


def test_projects_shows_runtime_status_and_urls(monkeypatch, tmp_path: Path) -> None:
    root = tmp_path / "projects"
    root.mkdir(parents=True, exist_ok=True)
    monkeypatch.setenv("ARCHMIND_PROJECTS_DIR", str(root))

    p1 = root / "task-tracker"
    p2 = root / "notes-api"
    p3 = root / "worker-api-demo"
    for name, ptype, tmpl in (
        ("task-tracker", "fullstack-web", "fullstack-ddd"),
        ("notes-api", "backend-api", "fastapi"),
        ("worker-api-demo", "backend-api", "worker-api"),
    ):
        project = root / name
        arch = project / ".archmind"
        arch.mkdir(parents=True, exist_ok=True)
        (arch / "state.json").write_text(
            json.dumps(
                {
                    "last_status": "DONE",
                    "project_type": ptype,
                    "effective_template": tmpl,
                }
            ),
            encoding="utf-8",
        )

    runtime_map = {
        str(p1.resolve()): {
            "backend": {"status": "RUNNING", "pid": 12001, "url": "http://127.0.0.1:8011"},
            "frontend": {"status": "RUNNING", "pid": 13001, "url": "http://127.0.0.1:3011"},
        },
        str(p2.resolve()): {
            "backend": {"status": "NOT RUNNING", "pid": None, "url": ""},
            "frontend": {"status": "NOT RUNNING", "pid": None, "url": ""},
        },
        str(p3.resolve()): {
            "backend": {"status": "RUNNING", "pid": 15001, "url": "http://127.0.0.1:8050"},
            "frontend": {"status": "NOT RUNNING", "pid": None, "url": ""},
        },
    }

    monkeypatch.setattr(
        "archmind.deploy.get_local_runtime_status",
        lambda project_dir: runtime_map.get(
            str(Path(project_dir).resolve()),
            {"backend": {"status": "NOT RUNNING", "pid": None, "url": ""}, "frontend": {"status": "NOT RUNNING", "pid": None, "url": ""}},
        ),
    )

    set_current_project(p1)
    out = format_projects_list()
    assert "task-tracker [current]" in out
    assert "Status: RUNNING" in out
    assert "Type: fullstack-web" in out
    assert "Template: fullstack-ddd" in out
    assert "Runtime: RUNNING (backend+frontend)" in out
    assert "Backend: http://127.0.0.1:8011" in out
    assert "Frontend: http://127.0.0.1:3011" in out
    assert "notes-api" in out
    assert "Status: STOPPED" in out
    assert "Runtime: STOPPED" in out
    assert "worker-api-demo" in out
    assert "Status: RUNNING" in out
    assert "Runtime: RUNNING (backend)" in out
    assert "Backend: http://127.0.0.1:8050" in out


def test_current_status_is_stopped_after_stop_state(monkeypatch, tmp_path: Path) -> None:
    project = tmp_path / "current_stopped_proj"
    archmind = project / ".archmind"
    archmind.mkdir(parents=True, exist_ok=True)
    (archmind / "state.json").write_text(
        json.dumps(
            {
                "last_status": "FAIL",
                "runtime": {
                    "backend_status": "STOPPED",
                    "frontend_status": "STOPPED",
                    "failure_class": "",
                    "services": {
                        "backend": {"status": "STOPPED", "pid": None, "url": ""},
                        "frontend": {"status": "STOPPED", "pid": None, "url": ""},
                    },
                },
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(
        "archmind.deploy.get_local_runtime_status",
        lambda _p: {
            "backend": {"status": "NOT RUNNING", "pid": None, "url": ""},
            "frontend": {"status": "NOT RUNNING", "pid": None, "url": ""},
        },
    )
    set_current_project(project)
    msg = DummyMessage()
    update = DummyUpdate(message=msg, effective_chat=DummyChat())
    asyncio.run(command_current(update, DummyContext()))
    out = msg.sent[-1]
    assert "Status: STOPPED" in out


def test_current_status_is_running_after_successful_run_all(monkeypatch, tmp_path: Path) -> None:
    project = tmp_path / "current_running_proj"
    archmind = project / ".archmind"
    archmind.mkdir(parents=True, exist_ok=True)
    (archmind / "state.json").write_text(
        json.dumps(
            {
                "last_status": "FAIL",
                "runtime": {
                    "backend_status": "RUNNING",
                    "frontend_status": "RUNNING",
                    "failure_class": "",
                },
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(
        "archmind.deploy.get_local_runtime_status",
        lambda _p: {
            "backend": {"status": "RUNNING", "pid": 22001, "url": "http://127.0.0.1:8050"},
            "frontend": {"status": "RUNNING", "pid": 22002, "url": "http://127.0.0.1:3000"},
        },
    )
    set_current_project(project)
    msg = DummyMessage()
    update = DummyUpdate(message=msg, effective_chat=DummyChat())
    asyncio.run(command_current(update, DummyContext()))
    out = msg.sent[-1]
    assert "Status: RUNNING" in out


def test_current_status_is_fail_after_runtime_run_failure(monkeypatch, tmp_path: Path) -> None:
    project = tmp_path / "current_failed_proj"
    archmind = project / ".archmind"
    archmind.mkdir(parents=True, exist_ok=True)
    (archmind / "state.json").write_text(
        json.dumps(
            {
                "last_status": "DONE",
                "runtime": {
                    "backend_status": "FAIL",
                    "frontend_status": "STOPPED",
                    "failure_class": "runtime-execution-error",
                    "preflight": {"status": "FAILED"},
                },
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(
        "archmind.deploy.get_local_runtime_status",
        lambda _p: {
            "backend": {"status": "NOT RUNNING", "pid": None, "url": ""},
            "frontend": {"status": "NOT RUNNING", "pid": None, "url": ""},
        },
    )
    set_current_project(project)
    msg = DummyMessage()
    update = DummyUpdate(message=msg, effective_chat=DummyChat())
    asyncio.run(command_current(update, DummyContext()))
    out = msg.sent[-1]
    assert "Status: FAIL" in out


def test_projects_type_fallback_from_template_and_shape(monkeypatch, tmp_path: Path) -> None:
    root = tmp_path / "projects"
    root.mkdir(parents=True, exist_ok=True)
    monkeypatch.setenv("ARCHMIND_PROJECTS_DIR", str(root))

    cases = [
        ("fastapi_proj", "", "fastapi", "", "backend-api"),
        ("worker_proj", "", "worker-api", "", "worker-api"),
        ("fullstack_proj", "", "fullstack-ddd", "", "fullstack-web"),
        ("explicit_proj", "frontend-web", "fastapi", "backend", "frontend-web"),
    ]
    for name, ptype, template, shape, _expected in cases:
        project = root / name
        arch = project / ".archmind"
        arch.mkdir(parents=True, exist_ok=True)
        payload = {
            "last_status": "DONE",
            "project_type": ptype,
            "effective_template": template,
        }
        if shape:
            payload["architecture_app_shape"] = shape
        (arch / "state.json").write_text(json.dumps(payload), encoding="utf-8")
        if name == "fullstack_proj":
            (project / "frontend").mkdir(parents=True, exist_ok=True)
            (project / "app").mkdir(parents=True, exist_ok=True)

    monkeypatch.setattr(
        "archmind.deploy.get_local_runtime_status",
        lambda _p: {
            "backend": {"status": "NOT RUNNING", "pid": None, "url": ""},
            "frontend": {"status": "NOT RUNNING", "pid": None, "url": ""},
        },
    )

    out = format_projects_list()
    assert "Type: backend-api" in out
    assert "Type: worker-api" in out
    assert "Type: fullstack-web" in out
    assert "1. explicit_proj" in out or "explicit_proj" in out
    assert "Type: frontend-web" in out


def test_current_type_fallback_uses_template_when_project_type_unknown(monkeypatch, tmp_path: Path) -> None:
    project = tmp_path / "current_fallback_proj"
    archmind = project / ".archmind"
    archmind.mkdir(parents=True, exist_ok=True)
    (archmind / "state.json").write_text(
        json.dumps(
            {
                "last_status": "DONE",
                "project_type": "unknown",
                "effective_template": "fastapi",
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(
        "archmind.deploy.get_local_runtime_status",
        lambda _p: {
            "backend": {"status": "NOT RUNNING", "pid": None, "url": ""},
            "frontend": {"status": "NOT RUNNING", "pid": None, "url": ""},
        },
    )
    set_current_project(project)

    msg = DummyMessage()
    update = DummyUpdate(message=msg, effective_chat=DummyChat())
    asyncio.run(command_current(update, DummyContext()))
    out = msg.sent[-1]
    assert "Type: backend-api" in out
    assert "Template: fastapi" in out


def test_status_uses_current_project_when_set(monkeypatch, tmp_path: Path) -> None:
    current = tmp_path / "current_status_proj"
    other = tmp_path / "other_status_proj"
    for project, typ in ((current, "frontend-web"), (other, "backend-api")):
        archmind = project / ".archmind"
        archmind.mkdir(parents=True, exist_ok=True)
        (archmind / "state.json").write_text(
            json.dumps({"agent_state": "IDLE", "iterations": 1, "fix_attempts": 0, "project_type": typ, "effective_template": "nextjs"}),
            encoding="utf-8",
        )
    set_current_project(current)
    monkeypatch.setattr("archmind.telegram_bot.load_last_project_path", lambda: other)
    msg = DummyMessage()
    update = DummyUpdate(message=msg, effective_chat=DummyChat())
    asyncio.run(command_status(update, DummyContext()))
    assert "Project:\ncurrent_status_proj" in msg.sent[-1]


def test_fix_continue_retry_use_current_project_when_set(monkeypatch, tmp_path: Path) -> None:
    current = tmp_path / "current_ops_proj"
    other = tmp_path / "other_ops_proj"
    current.mkdir(parents=True, exist_ok=True)
    other.mkdir(parents=True, exist_ok=True)
    set_current_project(current)
    monkeypatch.setattr("archmind.telegram_bot.load_last_project_path", lambda: other)
    monkeypatch.setattr("archmind.telegram_bot._status_from_sources", lambda _p: "NOT_DONE")

    used: list[Path] = []

    def fake_set_agent_state(project_dir_arg, state, **kwargs):  # type: ignore[no-untyped-def]
        del state, kwargs
        used.append(project_dir_arg)
        return {}

    class DummyProc:
        pid = 999

        def poll(self) -> None:
            return None

    monkeypatch.setattr("archmind.telegram_bot.set_agent_state", fake_set_agent_state)
    monkeypatch.setattr("archmind.telegram_bot.start_background_process", lambda *a, **k: DummyProc())
    msg = DummyMessage()
    update = DummyUpdate(message=msg, effective_chat=DummyChat())
    asyncio.run(command_continue(update, DummyContext(application=None)))
    telegram_bot._clear_running_job()
    asyncio.run(command_fix(update, DummyContext(application=None)))
    telegram_bot._clear_running_job()
    asyncio.run(command_retry(update, DummyContext(application=None)))

    assert used
    assert all(path == current for path in used)


def test_tree_works_with_current_project(tmp_path: Path) -> None:
    project = tmp_path / "tree_current_proj"
    (project / "app").mkdir(parents=True, exist_ok=True)
    (project / "app" / "page.tsx").write_text("export default function Page(){}", encoding="utf-8")
    set_current_project(project)
    msg = DummyMessage()
    update = DummyUpdate(message=msg, effective_chat=DummyChat())
    asyncio.run(command_tree(update, DummyContext()))
    out = msg.sent[-1]
    assert "Project tree" in out
    assert "Project: tree_current_proj" in out
    assert "app" in out
    assert "page.tsx" in out


def test_tree_falls_back_to_last_project(monkeypatch, tmp_path: Path) -> None:
    project = tmp_path / "tree_last_proj"
    (project / "app").mkdir(parents=True, exist_ok=True)
    (project / "app" / "layout.tsx").write_text("export default function Layout(){}", encoding="utf-8")
    _mark_archmind_project(project)
    monkeypatch.setattr("archmind.telegram_bot.load_last_project_path", lambda: project)
    msg = DummyMessage()
    update = DummyUpdate(message=msg, effective_chat=DummyChat())
    asyncio.run(command_tree(update, DummyContext()))
    assert "Project: tree_last_proj" in msg.sent[-1]
    assert "layout.tsx" in msg.sent[-1]


def test_tree_with_explicit_depth_works(tmp_path: Path) -> None:
    project = tmp_path / "tree_depth_proj"
    deep = project / "a" / "b" / "c"
    deep.mkdir(parents=True, exist_ok=True)
    (deep / "file.txt").write_text("x", encoding="utf-8")
    set_current_project(project)
    msg = DummyMessage()
    update = DummyUpdate(message=msg, effective_chat=DummyChat())
    asyncio.run(command_tree(update, DummyContext(args=["3"])))
    out = msg.sent[-1]
    assert "a" in out
    assert "b" in out
    assert "c" in out


def test_tree_invalid_depth_returns_error(tmp_path: Path) -> None:
    project = tmp_path / "tree_invalid_proj"
    project.mkdir(parents=True, exist_ok=True)
    set_current_project(project)
    msg = DummyMessage()
    update = DummyUpdate(message=msg, effective_chat=DummyChat())
    asyncio.run(command_tree(update, DummyContext(args=["abc"])))
    assert "Invalid depth. Use /tree or /tree <n>." in msg.sent[-1]


def test_tree_excluded_dirs_are_hidden(tmp_path: Path) -> None:
    project = tmp_path / "tree_exclude_proj"
    (project / "node_modules").mkdir(parents=True, exist_ok=True)
    (project / ".git").mkdir(parents=True, exist_ok=True)
    (project / ".archmind").mkdir(parents=True, exist_ok=True)
    (project / ".archmind" / "state.json").write_text("{}", encoding="utf-8")
    out = format_project_tree(project, depth=2)
    assert "node_modules" not in out
    assert ".git" not in out
    assert ".archmind" in out


def test_tree_output_truncates_when_too_long(tmp_path: Path) -> None:
    project = tmp_path / "tree_truncate_proj"
    project.mkdir(parents=True, exist_ok=True)
    for i in range(120):
        (project / f"file_{i}.txt").write_text("x", encoding="utf-8")
    out = format_project_tree(project, depth=2, max_lines=30)
    assert "... (truncated)" in out


def test_open_works_for_valid_file(tmp_path: Path) -> None:
    project = tmp_path / "open_valid_proj"
    file_path = project / "app" / "page.tsx"
    file_path.parent.mkdir(parents=True, exist_ok=True)
    file_path.write_text("export default function Page() {\n  return <main>Hello</main>\n}\n", encoding="utf-8")
    set_current_project(project)
    msg = DummyMessage()
    update = DummyUpdate(message=msg, effective_chat=DummyChat())
    asyncio.run(command_open(update, DummyContext(args=["app/page.tsx"])))
    out = msg.sent[-1]
    assert "File: app/page.tsx" in out
    assert "1 | export default function Page() {" in out


def test_open_rejects_missing_file(tmp_path: Path) -> None:
    project = tmp_path / "open_missing_proj"
    project.mkdir(parents=True, exist_ok=True)
    set_current_project(project)
    msg = DummyMessage()
    update = DummyUpdate(message=msg, effective_chat=DummyChat())
    asyncio.run(command_open(update, DummyContext(args=["app/missing.tsx"])))
    assert "File not found: app/missing.tsx" in msg.sent[-1]


def test_open_rejects_directory(tmp_path: Path) -> None:
    project = tmp_path / "open_dir_proj"
    (project / "app").mkdir(parents=True, exist_ok=True)
    set_current_project(project)
    msg = DummyMessage()
    update = DummyUpdate(message=msg, effective_chat=DummyChat())
    asyncio.run(command_open(update, DummyContext(args=["app"])))
    assert "Path is a directory: app" in msg.sent[-1]


def test_open_rejects_path_escape(tmp_path: Path) -> None:
    project = tmp_path / "open_escape_proj"
    project.mkdir(parents=True, exist_ok=True)
    set_current_project(project)
    msg = DummyMessage()
    update = DummyUpdate(message=msg, effective_chat=DummyChat())
    asyncio.run(command_open(update, DummyContext(args=["../secret.txt"])))
    assert "Invalid path. Use a project-relative file path." in msg.sent[-1]


def test_open_truncates_long_file(tmp_path: Path) -> None:
    project = tmp_path / "open_truncate_proj"
    file_path = project / "notes.txt"
    file_path.parent.mkdir(parents=True, exist_ok=True)
    file_path.write_text("\n".join([f"line {i}" for i in range(180)]), encoding="utf-8")
    out = format_file_preview(project, "notes.txt", max_lines=40)
    assert "... (truncated)" in out


def test_diff_returns_latest_fix_patch_when_present(tmp_path: Path) -> None:
    project = tmp_path / "diff_patch_proj"
    run_logs = project / ".archmind" / "run_logs"
    run_logs.mkdir(parents=True, exist_ok=True)
    (run_logs / "fix_20260312.patch.diff").write_text(
        "--- a/app/page.tsx\n+++ b/app/page.tsx\n@@\n-old line\n+new line\n",
        encoding="utf-8",
    )
    set_current_project(project)
    msg = DummyMessage()
    update = DummyUpdate(message=msg, effective_chat=DummyChat())
    asyncio.run(command_diff(update, DummyContext()))
    out = msg.sent[-1]
    assert "Recent diff" in out
    assert "--- a/app/page.tsx" in out
    assert "+new line" in out


def test_diff_falls_back_to_git_diff_when_no_patch_exists(monkeypatch, tmp_path: Path) -> None:
    project = tmp_path / "diff_git_proj"
    (project / ".git").mkdir(parents=True, exist_ok=True)
    set_current_project(project)

    class DummyCompleted:
        def __init__(self) -> None:
            self.stdout = "--- a/file.txt\n+++ b/file.txt\n@@\n-old\n+new\n"
            self.returncode = 0

    monkeypatch.setattr("archmind.telegram_bot.subprocess.run", lambda *a, **k: DummyCompleted())
    out = format_recent_diff(project)
    assert "Recent diff" in out
    assert "--- a/file.txt" in out
    assert "+new" in out


def test_diff_returns_no_diff_message_when_nothing_available(tmp_path: Path) -> None:
    project = tmp_path / "diff_none_proj"
    project.mkdir(parents=True, exist_ok=True)
    out = format_recent_diff(project)
    assert out == "No recent diff available."


def test_open_and_diff_use_current_project_when_set(monkeypatch, tmp_path: Path) -> None:
    current = tmp_path / "current_open_diff"
    other = tmp_path / "other_open_diff"
    (current / "app").mkdir(parents=True, exist_ok=True)
    (other / "app").mkdir(parents=True, exist_ok=True)
    (current / "app" / "page.tsx").write_text("current", encoding="utf-8")
    (other / "app" / "page.tsx").write_text("other", encoding="utf-8")
    run_logs = current / ".archmind" / "run_logs"
    run_logs.mkdir(parents=True, exist_ok=True)
    (run_logs / "fix_current.patch.diff").write_text("--- a/x\n+++ b/x\n+current\n", encoding="utf-8")
    set_current_project(current)
    monkeypatch.setattr("archmind.telegram_bot.load_last_project_path", lambda: other)

    msg = DummyMessage()
    update = DummyUpdate(message=msg, effective_chat=DummyChat())
    asyncio.run(command_open(update, DummyContext(args=["app/page.tsx"])))
    assert "current" in msg.sent[-1]

    asyncio.run(command_diff(update, DummyContext()))
    assert "+current" in msg.sent[-1]


def test_format_projects_list_limits_to_ten_projects(monkeypatch, tmp_path: Path) -> None:
    root = tmp_path / "projects"
    root.mkdir(parents=True, exist_ok=True)
    monkeypatch.setenv("ARCHMIND_PROJECTS_DIR", str(root))
    for i in range(12):
        project = root / f"20260312_000{i:02d}_proj_{i}"
        arch = project / ".archmind"
        arch.mkdir(parents=True, exist_ok=True)
        (arch / "state.json").write_text(
            json.dumps({"last_status": "NOT_DONE", "project_type": "unknown", "effective_template": "unknown"}),
            encoding="utf-8",
        )

    out = format_projects_list()
    assert "Recent ArchMind projects" in out
    assert out.count("Status: ") == 10


def test_help_mentions_command_groups() -> None:
    msg = DummyMessage()
    update = DummyUpdate(message=msg, effective_chat=DummyChat())
    ctx = DummyContext()
    asyncio.run(command_help(update, ctx))
    assert msg.sent
    out = msg.sent[-1]
    assert "ArchMind quick actions" in out
    assert "Create" in out
    assert "Current project" in out
    assert "Runtime" in out
    assert "More help" in out
    assert "/idea_local <idea>" in out
    assert "/design <idea>" in out
    assert "/plan <idea>" in out
    assert "/inspect" in out
    assert "/next" in out
    assert "/improve" in out
    assert "/run backend" in out
    assert "/running" in out
    assert "/restart" in out
    assert "/stop" in out
    assert "/stop all" in out
    assert "/help runtime" in out
    assert "/help all" in out
    assert "Example workflow" in out
    assert "/design defect tracker" in out
    assert "/idea_local defect tracker" in out
    assert msg.sent_kwargs
    reply_markup = msg.sent_kwargs[-1].get("reply_markup")
    assert reply_markup is not None
    buttons = [btn for row in getattr(reply_markup, "inline_keyboard", []) for btn in row]
    callback_values = [str(getattr(btn, "callback_data", "")) for btn in buttons]
    assert any(value == "help|create" for value in callback_values)
    assert any(value == "help|runtime" for value in callback_values)
    assert any(value == "help|project" for value in callback_values)
    assert any(value == "help|deploy" for value in callback_values)
    assert any(value == "help|all" for value in callback_values)


def test_help_runtime_section_text_and_buttons() -> None:
    msg = DummyMessage()
    update = DummyUpdate(message=msg, effective_chat=DummyChat())
    asyncio.run(command_help(update, DummyContext(args=["runtime"])))
    out = msg.sent[-1]
    assert "Help: runtime" in out
    assert "/run backend" in out
    assert "/running" in out
    assert "/restart" in out
    assert "/stop" in out
    assert "/stop all" in out
    assert "stop all local services" in out
    assert "/logs backend" in out
    assert "/logs frontend" in out
    reply_markup = msg.sent_kwargs[-1].get("reply_markup")
    assert reply_markup is not None
    buttons = [btn for row in getattr(reply_markup, "inline_keyboard", []) for btn in row]
    callback_values = [str(getattr(btn, "callback_data", "")) for btn in buttons]
    assert any(value == "cmd|/stop all" for value in callback_values)
    assert any(value == "cmd|/logs backend" for value in callback_values)
    assert any(value == "cmd|/logs frontend" for value in callback_values)
    assert any(value == "help|quick" for value in callback_values)


def test_help_callback_renders_runtime_section(monkeypatch) -> None:
    msg = DummyMessage()
    query = DummyCallbackQuery(data="help|runtime", message=msg)
    update = DummyUpdate(message=msg, effective_chat=DummyChat())
    update.callback_query = query  # type: ignore[attr-defined]
    asyncio.run(command_suggestion_callback(update, DummyContext()))
    assert query.answered is True
    assert msg.sent
    out = msg.sent[-1]
    assert "Help: runtime" in out
    assert "/stop all" in out


def test_help_create_section_uses_navigation_buttons_only() -> None:
    msg = DummyMessage()
    update = DummyUpdate(message=msg, effective_chat=DummyChat())
    asyncio.run(command_help(update, DummyContext(args=["create"])))
    reply_markup = msg.sent_kwargs[-1].get("reply_markup")
    assert reply_markup is not None
    buttons = [btn for row in getattr(reply_markup, "inline_keyboard", []) for btn in row]
    callback_values = [str(getattr(btn, "callback_data", "")) for btn in buttons]
    assert any(value == "help|project" for value in callback_values)
    assert any(value == "help|runtime" for value in callback_values)
    assert not any("sample idea" in value for value in callback_values)


def test_command_callback_dispatches_running_and_restart(monkeypatch) -> None:
    captured: dict[str, list[str]] = {"running": [], "restart": []}

    async def fake_running(update_arg, context_arg):  # type: ignore[no-untyped-def]
        captured["running"] = list(getattr(context_arg, "args", []))
        await update_arg.message.reply_text("running called")

    async def fake_restart(update_arg, context_arg):  # type: ignore[no-untyped-def]
        captured["restart"] = list(getattr(context_arg, "args", []))
        await update_arg.message.reply_text("restart called")

    monkeypatch.setattr("archmind.telegram_bot.command_running", fake_running)
    monkeypatch.setattr("archmind.telegram_bot.command_restart", fake_restart)

    msg_running = DummyMessage()
    q_running = DummyCallbackQuery(data="cmd|/running", message=msg_running)
    u_running = DummyUpdate(message=msg_running, effective_chat=DummyChat())
    u_running.callback_query = q_running  # type: ignore[attr-defined]
    asyncio.run(command_suggestion_callback(u_running, DummyContext()))
    assert q_running.answered is True
    assert captured["running"] == []
    assert "Unsupported command action" not in (msg_running.sent[-1] if msg_running.sent else "")

    msg_restart = DummyMessage()
    q_restart = DummyCallbackQuery(data="cmd|/restart", message=msg_restart)
    u_restart = DummyUpdate(message=msg_restart, effective_chat=DummyChat())
    u_restart.callback_query = q_restart  # type: ignore[attr-defined]
    asyncio.run(command_suggestion_callback(u_restart, DummyContext()))
    assert q_restart.answered is True
    assert captured["restart"] == []
    assert "Unsupported command action" not in (msg_restart.sent[-1] if msg_restart.sent else "")

    msg_running_colon = DummyMessage()
    q_running_colon = DummyCallbackQuery(data="cmd:/running", message=msg_running_colon)
    u_running_colon = DummyUpdate(message=msg_running_colon, effective_chat=DummyChat())
    u_running_colon.callback_query = q_running_colon  # type: ignore[attr-defined]
    asyncio.run(command_suggestion_callback(u_running_colon, DummyContext()))
    assert q_running_colon.answered is True
    assert "Unsupported command action" not in (msg_running_colon.sent[-1] if msg_running_colon.sent else "")


def test_command_callback_dispatches_stop_all(monkeypatch) -> None:
    captured: dict[str, list[str]] = {"stop": []}

    async def fake_stop(update_arg, context_arg):  # type: ignore[no-untyped-def]
        captured["stop"] = list(getattr(context_arg, "args", []))
        await update_arg.message.reply_text("stop called")

    monkeypatch.setattr("archmind.telegram_bot.command_stop", fake_stop)

    msg = DummyMessage()
    query = DummyCallbackQuery(data="cmd|/stop all", message=msg)
    update = DummyUpdate(message=msg, effective_chat=DummyChat())
    update.callback_query = query  # type: ignore[attr-defined]
    asyncio.run(command_suggestion_callback(update, DummyContext()))
    assert query.answered is True
    assert captured["stop"] == ["all"]
    assert "Unsupported command action" not in (msg.sent[-1] if msg.sent else "")


def test_help_all_keeps_full_command_list() -> None:
    msg = DummyMessage()
    update = DummyUpdate(message=msg, effective_chat=DummyChat())
    asyncio.run(command_help(update, DummyContext(args=["all"])))
    out = msg.sent[-1]
    assert "ArchMind commands" in out
    assert "PROJECT CREATION" in out
    assert "LOCAL RUNTIME" in out
    assert "/stop all" in out


def test_preview_command_outputs_brain_reasoning_fields() -> None:
    msg = DummyMessage()
    update = DummyUpdate(message=msg, effective_chat=DummyChat())
    asyncio.run(command_preview(update, DummyContext(args=["team", "task", "tracker", "with", "login", "dashboard"])))
    out = msg.sent[-1]
    assert "Idea analysis" in out
    assert "Shape:" in out
    assert "Template:" in out
    assert "Modules:" in out
    assert "Reason:" in out
    assert "Language:" in out
    assert "auth" in out
    assert "db" in out
    assert "dashboard" in out


def test_suggest_command_outputs_suggestion_list(tmp_path: Path, monkeypatch) -> None:
    project_dir = tmp_path / "task_tracker"
    project_dir.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr("archmind.telegram_bot._resolve_target_project", lambda: project_dir)
    monkeypatch.setattr(
        "archmind.telegram_bot._build_project_analysis",
        lambda _project: {
            "suggestions": [
                {"kind": "api", "message": "Add update endpoint for Task.", "command": "/add_api PUT /tasks/{id}"},
                {"kind": "page", "message": "Add detail page for Task.", "command": "/add_page tasks/detail"},
                {"kind": "field", "message": "Add priority field to Task.", "command": ""},
            ]
        },
    )

    msg = DummyMessage()
    update = DummyUpdate(message=msg, effective_chat=DummyChat())
    asyncio.run(command_suggest(update, DummyContext()))
    out = msg.sent[-1]
    assert out.startswith("Suggestions")
    assert f"Target Project: {project_dir.name}" in out
    assert "1. Add update endpoint for Task." in out
    assert "Command: /add_api PUT /tasks/{id}" in out
    assert "2. Add detail page for Task." in out
    assert "Command: /add_page tasks/detail" in out
    assert "3. Add priority field to Task." in out
    assert out.count("   Command:") == 2


def test_suggest_command_canonicalizes_and_filters_malformed_commands(tmp_path: Path, monkeypatch) -> None:
    project_dir = tmp_path / "task_tracker"
    project_dir.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr("archmind.telegram_bot._resolve_target_project", lambda: project_dir)
    monkeypatch.setattr(
        "archmind.telegram_bot._build_project_analysis",
        lambda _project: {
            "suggestions": [
                {
                    "kind": "placeholder_page",
                    "message": "Page task/lists is still placeholder-level. Implement a usable UI flow.",
                    "command": "/add_page task/lists",
                },
                {
                    "kind": "missing_crud_api",
                    "message": "Task is missing list API coverage.",
                    "command": "/add_api GET task",
                },
                {
                    "kind": "bad",
                    "message": "broken suggestion",
                    "command": "/add_api INVALID /tasks",
                },
            ]
        },
    )
    msg = DummyMessage()
    update = DummyUpdate(message=msg, effective_chat=DummyChat())
    asyncio.run(command_suggest(update, DummyContext()))
    out = msg.sent[-1]
    assert "/implement_page tasks/list" in out
    assert "/add_page task/lists" not in out
    assert "/add_api GET /tasks" in out
    assert "INVALID" not in out


def test_next_command_outputs_implement_page_for_existing_placeholder_page(tmp_path: Path, monkeypatch) -> None:
    project_dir = tmp_path / "task_tracker"
    project_dir.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr("archmind.telegram_bot._resolve_target_project", lambda: project_dir)
    monkeypatch.setattr(
        "archmind.telegram_bot._build_project_analysis",
        lambda _project: {
            "next_action": {
                "kind": "placeholder_page",
                "message": "Page tasks/list is still placeholder-level. Implement a usable UI flow.",
                "command": "/implement_page tasks/list",
            }
        },
    )

    msg = DummyMessage()
    update = DummyUpdate(message=msg, effective_chat=DummyChat())
    asyncio.run(command_next(update, DummyContext()))
    out = msg.sent[-1]
    assert "Page tasks/list is still placeholder-level." in out
    assert "Command: /implement_page tasks/list" in out


def test_design_command_outputs_design_sections() -> None:
    msg = DummyMessage()
    update = DummyUpdate(message=msg, effective_chat=DummyChat())
    asyncio.run(
        command_design(
            update,
            DummyContext(
                args=[
                    "tv",
                    "hardware",
                    "qa",
                    "defect",
                    "tracker",
                    "with",
                    "dashboard,",
                    "device",
                    "management,",
                    "test",
                    "run",
                    "history,",
                    "and",
                    "team",
                    "collaboration",
                ]
            ),
        )
    )
    out = msg.sent[-1]
    assert "Architecture design" in out
    assert "Overview:" in out
    assert "Architecture:" in out
    assert "Domains:" in out
    assert "Entities:" in out
    assert "APIs:" in out
    assert "Frontend:" in out
    assert "Reasoning:" in out
    assert "- Device(" in out
    assert "- TestRun(" in out
    assert "- Defect(" in out
    assert "Relationships:" in out
    assert "Device has many TestRuns" in out
    assert "Next step" in out
    assert "1. generate development plan" in out
    assert "2. generate project" in out


def test_design_command_requires_idea() -> None:
    msg = DummyMessage()
    update = DummyUpdate(message=msg, effective_chat=DummyChat())
    asyncio.run(command_design(update, DummyContext()))
    assert msg.sent[-1] == "Usage: /design <idea>"


def test_design_command_simple_todo_app_is_fullstack_and_has_frontend() -> None:
    msg = DummyMessage()
    update = DummyUpdate(message=msg, effective_chat=DummyChat())
    asyncio.run(command_design(update, DummyContext(args=["simple", "todo", "app"])))
    out = msg.sent[-1]
    assert "Shape: fullstack" in out
    assert "Template: fullstack-ddd" in out
    assert "Frontend:" in out
    assert "Frontend:\n- (none)" not in out


def test_get_template_suggestions_ambiguous_case() -> None:
    reasoning = {
        "app_shape": "unknown",
        "recommended_template": "fastapi",
        "domains": ["documents"],
        "dashboard_needed": True,
        "internal_tool": True,
        "worker_needed": False,
        "backend_needed": True,
        "frontend_needed": True,
        "db_needed": False,
        "file_upload_needed": True,
    }
    suggestions = get_template_suggestions("document upload admin tool", reasoning)
    assert "internal-tool" in suggestions
    assert len(suggestions) >= 2


def test_inspect_command_summarizes_project_spec_reasoning_and_state(tmp_path: Path, monkeypatch) -> None:
    project_dir = tmp_path / "task_tracker"
    archmind = project_dir / ".archmind"
    archmind.mkdir(parents=True, exist_ok=True)
    (project_dir / "app").mkdir(parents=True, exist_ok=True)
    (project_dir / "frontend").mkdir(parents=True, exist_ok=True)
    (project_dir / "README.md").write_text("# demo\n", encoding="utf-8")
    (project_dir / "requirements.txt").write_text("fastapi\n", encoding="utf-8")
    (archmind / "project_spec.json").write_text(
        json.dumps(
            {
                "shape": "fullstack",
                "domains": ["tasks", "teams"],
                "template": "fullstack-ddd",
                "modules": ["auth", "db", "dashboard"],
                "entities": [{"name": "Task", "fields": [{"name": "title", "type": "string"}]}],
                "reason_summary": "fullstack app for tasks, teams with auth, db, dashboard",
                "evolution": {"version": 1, "added_modules": ["auth"], "history": [{"action": "add_module", "module": "auth"}]},
            }
        ),
        encoding="utf-8",
    )
    (archmind / "architecture_reasoning.json").write_text(
        json.dumps(
            {
                "app_shape": "fullstack",
                "domains": ["tasks", "teams"],
                "recommended_template": "fullstack-ddd",
                "reason_summary": "fullstack app for tasks, teams with auth, db, dashboard",
            }
        ),
        encoding="utf-8",
    )
    (archmind / "state.json").write_text(
        json.dumps(
            {
                "backend_deploy_url": "http://127.0.0.1:8011",
                "frontend_deploy_url": "http://127.0.0.1:3011",
                "backend_pid": 12001,
                "frontend_pid": 13001,
                "backend_smoke_status": "RUNNING",
                "frontend_smoke_status": "RUNNING",
                "deploy_target": "local",
                "last_deploy_status": "SUCCESS",
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr("archmind.telegram_bot._resolve_target_project", lambda: project_dir)
    monkeypatch.setattr(
        "archmind.deploy.get_local_runtime_status",
        lambda _p: {
            "backend": {"status": "RUNNING", "pid": 12001, "url": "http://127.0.0.1:8011"},
            "frontend": {"status": "RUNNING", "pid": 13001, "url": "http://127.0.0.1:3011"},
        },
    )

    msg = DummyMessage()
    update = DummyUpdate(message=msg, effective_chat=DummyChat())
    asyncio.run(command_inspect(update, DummyContext()))
    out = msg.sent[-1]
    assert "Project:" in out
    assert "task_tracker" in out
    assert "Architecture:" in out
    assert "Shape: fullstack" in out
    assert "Template: fullstack-ddd" in out
    assert "Domains: tasks, teams" in out
    assert "Modules: auth, db, dashboard" in out
    assert "Entities:" in out
    assert "- Task(title:string)" in out
    assert "Entity Fields:" in out
    assert "- Task" in out
    assert "  - title:string" in out
    assert "APIs:" in out
    assert "- GET /tasks" in out
    assert "Pages:" in out
    assert "- tasks/list" in out
    assert "- tasks/detail" in out
    assert "Reasoning:" in out
    assert "Evolution:" in out
    assert "Version: 1" in out
    assert "Added modules: auth" in out
    assert "History count: 1" in out
    assert "Structure:" in out
    assert "backend + frontend" in out
    assert "Files:" in out
    assert "app/" in out
    assert "frontend/" in out
    assert "Runtime:" in out
    assert "Backend: RUNNING" in out
    assert "Frontend: RUNNING" in out
    assert "Backend URL:" in out
    assert "Frontend URL:" in out
    assert "Deploy:" in out
    assert "Target: local" in out
    assert "Status: SUCCESS" in out


def test_inspect_command_truncates_entity_api_and_page_lists(tmp_path: Path, monkeypatch) -> None:
    project_dir = tmp_path / "big_proj"
    archmind = project_dir / ".archmind"
    archmind.mkdir(parents=True, exist_ok=True)
    (project_dir / "app").mkdir(parents=True, exist_ok=True)
    (project_dir / "frontend").mkdir(parents=True, exist_ok=True)
    entities = [{"name": "Task", "fields": [{"name": f"f{i}", "type": "string"} for i in range(7)]}]
    entities += [{"name": f"Entity{i}", "fields": []} for i in range(1, 7)]
    (archmind / "project_spec.json").write_text(
        json.dumps(
            {
                "shape": "fullstack",
                "domains": ["tasks"],
                "template": "fullstack-ddd",
                "modules": ["db"],
                "entities": entities,
                "reason_summary": "demo",
                "evolution": {
                    "version": 1,
                    "added_modules": ["db"],
                    "history": [{"action": "add_module", "module": "db"} for _ in range(3)],
                },
            }
        ),
        encoding="utf-8",
    )
    (archmind / "state.json").write_text("{}", encoding="utf-8")
    monkeypatch.setattr("archmind.telegram_bot._resolve_target_project", lambda: project_dir)

    msg = DummyMessage()
    update = DummyUpdate(message=msg, effective_chat=DummyChat())
    asyncio.run(command_inspect(update, DummyContext()))
    out = msg.sent[-1]

    assert "Task(f0:string, f1:string, f2:string, f3:string, f4:string, ... +2 more)" in out
    assert "more endpoints" in out
    assert "more pages" in out
    assert "History count: 3" in out


def test_inspect_command_shows_recent_evolution_entries(tmp_path: Path, monkeypatch) -> None:
    project_dir = tmp_path / "inspect_recent_evolution"
    archmind = project_dir / ".archmind"
    archmind.mkdir(parents=True, exist_ok=True)
    (project_dir / "app").mkdir(parents=True, exist_ok=True)
    (project_dir / "app" / "main.py").write_text("from fastapi import FastAPI\napp = FastAPI()\n", encoding="utf-8")
    (project_dir / "requirements.txt").write_text("fastapi\n", encoding="utf-8")
    (archmind / "project_spec.json").write_text(
        json.dumps(
            {
                "shape": "fullstack",
                "template": "fullstack-ddd",
                "entities": [{"name": "Note", "fields": [{"name": "title", "type": "string"}]}],
                "api_endpoints": ["GET /notes"],
                "frontend_pages": ["notes/list"],
                "evolution": {
                    "version": 1,
                    "added_modules": [],
                    "history": [
                        {"action": "add_entity", "entity": "Note"},
                        {"action": "add_field", "entity": "Note", "field": "title", "type": "string"},
                        {"action": "add_api", "method": "GET", "path": "/notes"},
                        {"action": "add_page", "page": "notes/list"},
                    ],
                },
            }
        ),
        encoding="utf-8",
    )
    (archmind / "state.json").write_text("{}", encoding="utf-8")
    monkeypatch.setattr("archmind.telegram_bot._resolve_target_project", lambda: project_dir)

    msg = DummyMessage()
    asyncio.run(command_inspect(DummyUpdate(message=msg, effective_chat=DummyChat()), DummyContext()))
    out = msg.sent[-1]
    assert "Evolution:" in out
    assert "History count: 4" in out
    assert "Recent evolution:" in out
    assert "- add_entity Note" in out
    assert "- add_field Note title:string" in out
    assert "- add_api GET /notes" in out
    assert "- add_page notes/list" in out


def test_inspect_command_shows_recent_evolution_none_when_history_empty(tmp_path: Path, monkeypatch) -> None:
    project_dir = tmp_path / "inspect_recent_evolution_none"
    archmind = project_dir / ".archmind"
    archmind.mkdir(parents=True, exist_ok=True)
    (project_dir / "app").mkdir(parents=True, exist_ok=True)
    (project_dir / "app" / "main.py").write_text("from fastapi import FastAPI\napp = FastAPI()\n", encoding="utf-8")
    (project_dir / "requirements.txt").write_text("fastapi\n", encoding="utf-8")
    (archmind / "project_spec.json").write_text(
        json.dumps(
            {
                "shape": "backend",
                "template": "fastapi",
                "entities": [],
                "api_endpoints": [],
                "frontend_pages": [],
                "evolution": {"version": 1, "added_modules": [], "history": []},
            }
        ),
        encoding="utf-8",
    )
    (archmind / "state.json").write_text("{}", encoding="utf-8")
    monkeypatch.setattr("archmind.telegram_bot._resolve_target_project", lambda: project_dir)

    msg = DummyMessage()
    asyncio.run(command_inspect(DummyUpdate(message=msg, effective_chat=DummyChat()), DummyContext()))
    out = msg.sent[-1]
    assert "Recent evolution:" in out
    assert "(none)" in out


def test_inspect_recent_evolution_reflects_primitive_execution_and_limit(tmp_path: Path, monkeypatch) -> None:
    project_dir = tmp_path / "inspect_evolution_from_primitives"
    archmind = project_dir / ".archmind"
    archmind.mkdir(parents=True, exist_ok=True)
    (project_dir / "app").mkdir(parents=True, exist_ok=True)
    (project_dir / "app" / "main.py").write_text("from fastapi import FastAPI\napp = FastAPI()\n", encoding="utf-8")
    (project_dir / "requirements.txt").write_text("fastapi\n", encoding="utf-8")
    (project_dir / "frontend").mkdir(parents=True, exist_ok=True)
    (project_dir / "frontend" / "pages").mkdir(parents=True, exist_ok=True)
    (project_dir / "frontend" / "package.json").write_text(json.dumps({"name": "demo", "scripts": {"dev": "next dev"}}), encoding="utf-8")
    (archmind / "project_spec.json").write_text(
        json.dumps(
            {
                "shape": "fullstack",
                "template": "fullstack-ddd",
                "entities": [],
                "api_endpoints": [],
                "frontend_pages": [],
                "evolution": {"version": 1, "added_modules": [], "history": []},
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr("archmind.telegram_bot._resolve_target_project", lambda: project_dir)

    msg1 = DummyMessage()
    asyncio.run(command_add_entity(DummyUpdate(message=msg1, effective_chat=DummyChat()), DummyContext(args=["Note"])))
    msg2 = DummyMessage()
    asyncio.run(command_add_field(DummyUpdate(message=msg2, effective_chat=DummyChat()), DummyContext(args=["Note", "title:string"])))
    msg3 = DummyMessage()
    asyncio.run(command_add_field(DummyUpdate(message=msg3, effective_chat=DummyChat()), DummyContext(args=["Note", "content:string"])))
    msg4 = DummyMessage()
    asyncio.run(command_add_api(DummyUpdate(message=msg4, effective_chat=DummyChat()), DummyContext(args=["GET", "/reports"])))
    msg5 = DummyMessage()
    asyncio.run(command_add_page(DummyUpdate(message=msg5, effective_chat=DummyChat()), DummyContext(args=["reports/list"])))
    msg6 = DummyMessage()
    asyncio.run(command_add_page(DummyUpdate(message=msg6, effective_chat=DummyChat()), DummyContext(args=["reports/detail"])))

    inspect_msg = DummyMessage()
    asyncio.run(command_inspect(DummyUpdate(message=inspect_msg, effective_chat=DummyChat()), DummyContext()))
    out = inspect_msg.sent[-1]
    assert "History count: 10" in out
    assert "Recent evolution:" in out
    # recent list is capped to latest 5 entries in inspect
    assert "- auto_add_page notes/detail" not in out
    assert "- add_field Note title:string" in out
    assert "- add_field Note content:string" in out
    assert "- add_api GET /reports" in out
    assert "- add_page reports/list" in out
    assert "- add_page reports/detail" in out


def test_inspect_command_shows_api_base_url_from_frontend_env(tmp_path: Path, monkeypatch) -> None:
    project_dir = tmp_path / "inspect_api_base"
    archmind = project_dir / ".archmind"
    archmind.mkdir(parents=True, exist_ok=True)
    (project_dir / "app").mkdir(parents=True, exist_ok=True)
    (project_dir / "app" / "main.py").write_text("from fastapi import FastAPI\napp = FastAPI()\n", encoding="utf-8")
    (project_dir / "frontend").mkdir(parents=True, exist_ok=True)
    (project_dir / "frontend" / ".env.local").write_text(
        "NEXT_PUBLIC_API_BASE_URL=http://127.0.0.1:8011\n",
        encoding="utf-8",
    )
    (archmind / "project_spec.json").write_text(
        json.dumps(
            {
                "shape": "fullstack",
                "domains": ["tasks"],
                "template": "fullstack-ddd",
                "modules": ["db"],
                "entities": [],
                "api_endpoints": [],
                "frontend_pages": [],
            }
        ),
        encoding="utf-8",
    )
    (archmind / "state.json").write_text("{}", encoding="utf-8")
    monkeypatch.setattr("archmind.telegram_bot._resolve_target_project", lambda: project_dir)

    msg = DummyMessage()
    update = DummyUpdate(message=msg, effective_chat=DummyChat())
    asyncio.run(command_inspect(update, DummyContext()))
    out = msg.sent[-1]
    assert "API Base URL:" in out
    assert "http://127.0.0.1:8011" in out


def test_inspect_command_shows_repository_status_section(tmp_path: Path, monkeypatch) -> None:
    project_dir = tmp_path / "inspect_repository_status"
    archmind = project_dir / ".archmind"
    archmind.mkdir(parents=True, exist_ok=True)
    (project_dir / "app").mkdir(parents=True, exist_ok=True)
    (project_dir / "app" / "main.py").write_text("from fastapi import FastAPI\napp = FastAPI()\n", encoding="utf-8")
    (project_dir / "requirements.txt").write_text("fastapi\nuvicorn\n", encoding="utf-8")
    (archmind / "project_spec.json").write_text(
        json.dumps(
            {
                "shape": "backend",
                "template": "fastapi",
                "modules": [],
                "entities": [],
                "api_endpoints": [],
                "frontend_pages": [],
            }
        ),
        encoding="utf-8",
    )
    (archmind / "state.json").write_text(
        json.dumps(
            {
                "repository": {
                    "status": "FAILED",
                    "url": "",
                    "name": "inspect_repository_status",
                    "reason": "gh auth missing",
                    "attempted": True,
                }
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr("archmind.telegram_bot._resolve_target_project", lambda: project_dir)
    msg = DummyMessage()
    update = DummyUpdate(message=msg, effective_chat=DummyChat())
    asyncio.run(command_inspect(update, DummyContext()))
    out = msg.sent[-1]
    assert "Repository:" in out
    assert "Status: FAILED" in out
    assert "Reason: gh auth missing" in out


def test_inspect_command_hides_stale_runtime_failure_when_detection_ok(tmp_path: Path, monkeypatch) -> None:
    project_dir = tmp_path / "inspect_stale_runtime_class"
    archmind = project_dir / ".archmind"
    archmind.mkdir(parents=True, exist_ok=True)
    (project_dir / "app").mkdir(parents=True, exist_ok=True)
    (project_dir / "app" / "main.py").write_text("from fastapi import FastAPI\napp = FastAPI()\n", encoding="utf-8")
    (project_dir / "requirements.txt").write_text("fastapi\nuvicorn\n", encoding="utf-8")
    (archmind / "project_spec.json").write_text(
        json.dumps(
            {
                "shape": "backend",
                "template": "fastapi",
                "modules": [],
                "entities": [],
                "api_endpoints": [],
                "frontend_pages": [],
            }
        ),
        encoding="utf-8",
    )
    (archmind / "state.json").write_text(
        json.dumps(
            {
                "runtime": {"backend_status": "RUNNING", "failure_class": ""},
                "runtime_failure_class": "environment-python",
                "last_failure_class": "environment-python",
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(
        "archmind.telegram_bot.detect_backend_runtime_entry",
        lambda _p, port=8000: {"ok": True, "backend_entry": "app.main:app", "backend_run_mode": "asgi-direct"},
    )
    monkeypatch.setattr("archmind.telegram_bot._resolve_target_project", lambda: project_dir)
    msg = DummyMessage()
    update = DummyUpdate(message=msg, effective_chat=DummyChat())
    asyncio.run(command_inspect(update, DummyContext()))
    out = msg.sent[-1]
    assert "Failure Class: (none)" in out
    assert "environment-python" not in out


def test_inspect_command_keeps_runtime_and_repository_status_separate(tmp_path: Path, monkeypatch) -> None:
    project_dir = tmp_path / "inspect_runtime_repo_separate"
    archmind = project_dir / ".archmind"
    archmind.mkdir(parents=True, exist_ok=True)
    (project_dir / "app").mkdir(parents=True, exist_ok=True)
    (project_dir / "app" / "main.py").write_text("from fastapi import FastAPI\napp = FastAPI()\n", encoding="utf-8")
    (project_dir / "requirements.txt").write_text("fastapi\nuvicorn\n", encoding="utf-8")
    (archmind / "project_spec.json").write_text(
        json.dumps(
            {
                "shape": "backend",
                "template": "fastapi",
                "modules": [],
                "entities": [],
                "api_endpoints": [],
                "frontend_pages": [],
            }
        ),
        encoding="utf-8",
    )
    (archmind / "state.json").write_text(
        json.dumps(
            {
                "runtime": {"backend_status": "FAIL", "failure_class": "runtime-execution-error"},
                "repository": {
                    "status": "CREATED",
                    "url": "https://github.com/siriusnen-commits/inspect_runtime_repo_separate",
                    "name": "inspect_runtime_repo_separate",
                    "reason": "",
                    "attempted": True,
                },
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(
        "archmind.telegram_bot.detect_backend_runtime_entry",
        lambda _p, port=8000: {"ok": False, "failure_class": "runtime-execution-error", "failure_reason": "runtime failed"},
    )
    monkeypatch.setattr("archmind.telegram_bot._resolve_target_project", lambda: project_dir)
    msg = DummyMessage()
    asyncio.run(command_inspect(DummyUpdate(message=msg, effective_chat=DummyChat()), DummyContext()))
    out = msg.sent[-1]
    assert "Failure Class: runtime-execution-error" in out
    assert "Repository:" in out
    assert "Status: CREATED" in out
    assert "https://github.com/siriusnen-commits/inspect_runtime_repo_separate" in out


def test_inspect_command_prefers_live_runtime_over_stale_fail_state(tmp_path: Path, monkeypatch) -> None:
    project_dir = tmp_path / "inspect_live_runtime_override"
    archmind = project_dir / ".archmind"
    archmind.mkdir(parents=True, exist_ok=True)
    (project_dir / "app").mkdir(parents=True, exist_ok=True)
    (project_dir / "app" / "main.py").write_text("from fastapi import FastAPI\napp = FastAPI()\n", encoding="utf-8")
    (project_dir / "requirements.txt").write_text("fastapi\nuvicorn\n", encoding="utf-8")
    (archmind / "project_spec.json").write_text(
        json.dumps({"shape": "backend", "template": "fastapi", "modules": [], "entities": [], "api_endpoints": [], "frontend_pages": []}),
        encoding="utf-8",
    )
    (archmind / "state.json").write_text(
        json.dumps({"runtime": {"backend_status": "FAIL", "failure_class": "runtime-execution-error"}}),
        encoding="utf-8",
    )
    monkeypatch.setattr(
        "archmind.telegram_bot.detect_backend_runtime_entry",
        lambda _p, port=8000: {"ok": False, "failure_class": "runtime-execution-error", "failure_reason": "recent failure"},
    )
    monkeypatch.setattr(
        "archmind.deploy.get_local_runtime_status",
        lambda _p: {
            "backend": {"status": "RUNNING", "pid": 45127, "url": "http://127.0.0.1:8000"},
            "frontend": {"status": "NOT RUNNING", "pid": None, "url": ""},
        },
    )
    monkeypatch.setattr("archmind.telegram_bot._resolve_target_project", lambda: project_dir)
    msg = DummyMessage()
    asyncio.run(command_inspect(DummyUpdate(message=msg, effective_chat=DummyChat()), DummyContext()))
    out = msg.sent[-1]
    assert "Runtime:" in out
    assert "Backend: RUNNING" in out
    assert "Backend PID: 45127" in out
    assert "Backend URL:" in out
    assert "http://127.0.0.1:8000" in out
    assert "Failure Class: runtime-execution-error" not in out


def test_inspect_and_running_show_consistent_runtime_for_current_project(tmp_path: Path, monkeypatch) -> None:
    project_dir = tmp_path / "inspect_running_consistent"
    project_dir.mkdir(parents=True, exist_ok=True)
    archmind = project_dir / ".archmind"
    archmind.mkdir(parents=True, exist_ok=True)
    (project_dir / "app").mkdir(parents=True, exist_ok=True)
    (project_dir / "app" / "main.py").write_text("from fastapi import FastAPI\napp = FastAPI()\n", encoding="utf-8")
    (project_dir / "requirements.txt").write_text("fastapi\nuvicorn\n", encoding="utf-8")
    (archmind / "project_spec.json").write_text(
        json.dumps({"shape": "backend", "template": "fastapi", "modules": [], "entities": [], "api_endpoints": [], "frontend_pages": []}),
        encoding="utf-8",
    )
    (archmind / "state.json").write_text(json.dumps({}), encoding="utf-8")
    set_current_project(project_dir)
    monkeypatch.setattr("archmind.telegram_bot._resolve_target_project", lambda: project_dir)
    monkeypatch.setattr(
        "archmind.deploy.get_local_runtime_status",
        lambda _p: {
            "project_dir": project_dir,
            "project_name": project_dir.name,
            "backend": {"status": "RUNNING", "pid": 55123, "url": "http://127.0.0.1:8000"},
            "frontend": {"status": "NOT RUNNING", "pid": None, "url": ""},
        },
    )
    monkeypatch.setattr(
        "archmind.deploy.list_running_local_projects",
        lambda _root: [
            {
                "project_dir": project_dir,
                "project_name": project_dir.name,
                "backend": {"status": "RUNNING", "pid": 55123, "url": "http://127.0.0.1:8000"},
                "frontend": {"status": "NOT RUNNING", "pid": None, "url": ""},
            }
        ],
    )

    inspect_msg = DummyMessage()
    asyncio.run(command_inspect(DummyUpdate(message=inspect_msg, effective_chat=DummyChat()), DummyContext()))
    inspect_out = inspect_msg.sent[-1]
    running_msg = DummyMessage()
    asyncio.run(command_running(DummyUpdate(message=running_msg, effective_chat=DummyChat()), DummyContext()))
    running_out = running_msg.sent[-1]
    assert "Backend: RUNNING" in inspect_out
    assert "Backend: RUNNING (pid 55123)" in running_out
    assert "http://127.0.0.1:8000" in inspect_out
    assert "http://127.0.0.1:8000" in running_out


def test_inspect_command_shows_fail_only_when_not_running_with_unresolved_failure(tmp_path: Path, monkeypatch) -> None:
    project_dir = tmp_path / "inspect_real_fail"
    archmind = project_dir / ".archmind"
    archmind.mkdir(parents=True, exist_ok=True)
    (project_dir / "app").mkdir(parents=True, exist_ok=True)
    (project_dir / "app" / "main.py").write_text("from fastapi import FastAPI\napp = FastAPI()\n", encoding="utf-8")
    (project_dir / "requirements.txt").write_text("fastapi\nuvicorn\n", encoding="utf-8")
    (archmind / "project_spec.json").write_text(
        json.dumps({"shape": "backend", "template": "fastapi", "modules": [], "entities": [], "api_endpoints": [], "frontend_pages": []}),
        encoding="utf-8",
    )
    (archmind / "state.json").write_text(
        json.dumps({"runtime": {"backend_status": "FAIL", "failure_class": "runtime-execution-error"}}),
        encoding="utf-8",
    )
    monkeypatch.setattr(
        "archmind.telegram_bot.detect_backend_runtime_entry",
        lambda _p, port=8000: {"ok": False, "failure_class": "runtime-execution-error", "failure_reason": "startup failed"},
    )
    monkeypatch.setattr(
        "archmind.deploy.get_local_runtime_status",
        lambda _p: {
            "backend": {"status": "NOT RUNNING", "pid": None, "url": ""},
            "frontend": {"status": "NOT RUNNING", "pid": None, "url": ""},
        },
    )
    monkeypatch.setattr("archmind.telegram_bot._resolve_target_project", lambda: project_dir)
    msg = DummyMessage()
    asyncio.run(command_inspect(DummyUpdate(message=msg, effective_chat=DummyChat()), DummyContext()))
    out = msg.sent[-1]
    assert "Runtime:" in out
    assert "Backend: FAIL" in out
    assert "Failure Class: runtime-execution-error" in out


def test_inspect_command_shows_runtime_status_and_backend_runtime_info_together(tmp_path: Path, monkeypatch) -> None:
    project_dir = tmp_path / "inspect_runtime_and_detect"
    archmind = project_dir / ".archmind"
    archmind.mkdir(parents=True, exist_ok=True)
    (project_dir / "app").mkdir(parents=True, exist_ok=True)
    (project_dir / "app" / "main.py").write_text("from fastapi import FastAPI\napp = FastAPI()\n", encoding="utf-8")
    (project_dir / "requirements.txt").write_text("fastapi\nuvicorn\n", encoding="utf-8")
    (archmind / "project_spec.json").write_text(
        json.dumps({"shape": "backend", "template": "fastapi", "modules": [], "entities": [], "api_endpoints": [], "frontend_pages": []}),
        encoding="utf-8",
    )
    (archmind / "state.json").write_text(json.dumps({}), encoding="utf-8")
    monkeypatch.setattr(
        "archmind.telegram_bot.detect_backend_runtime_entry",
        lambda _p, port=8000: {"ok": True, "backend_entry": "app.main:app", "backend_run_mode": "asgi-direct"},
    )
    monkeypatch.setattr(
        "archmind.deploy.get_local_runtime_status",
        lambda _p: {
            "backend": {"status": "RUNNING", "pid": 42001, "url": "http://127.0.0.1:8010"},
            "frontend": {"status": "NOT RUNNING", "pid": None, "url": ""},
        },
    )
    monkeypatch.setattr("archmind.telegram_bot._resolve_target_project", lambda: project_dir)
    msg = DummyMessage()
    asyncio.run(command_inspect(DummyUpdate(message=msg, effective_chat=DummyChat()), DummyContext()))
    out = msg.sent[-1]
    assert "Runtime:" in out
    assert "Backend: RUNNING" in out
    assert "Backend Runtime:" in out
    assert "Backend Entry: app.main:app" in out
    assert "Backend Run Mode: asgi-direct" in out


def test_inspect_command_separates_runtime_url_from_deploy_state(tmp_path: Path, monkeypatch) -> None:
    project_dir = tmp_path / "inspect_runtime_deploy_separate"
    archmind = project_dir / ".archmind"
    archmind.mkdir(parents=True, exist_ok=True)
    (project_dir / "app").mkdir(parents=True, exist_ok=True)
    (project_dir / "app" / "main.py").write_text("from fastapi import FastAPI\napp = FastAPI()\n", encoding="utf-8")
    (project_dir / "requirements.txt").write_text("fastapi\nuvicorn\n", encoding="utf-8")
    (archmind / "project_spec.json").write_text(
        json.dumps({"shape": "backend", "template": "fastapi", "modules": [], "entities": [], "api_endpoints": [], "frontend_pages": []}),
        encoding="utf-8",
    )
    (archmind / "state.json").write_text(
        json.dumps(
            {
                "deploy": {"target": "railway", "status": "SUCCESS", "backend_url": "https://prod.example.com"},
                "runtime": {"backend_status": "FAIL"},
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(
        "archmind.deploy.get_local_runtime_status",
        lambda _p: {
            "backend": {"status": "RUNNING", "pid": 77123, "url": "http://127.0.0.1:8000"},
            "frontend": {"status": "NOT RUNNING", "pid": None, "url": ""},
        },
    )
    monkeypatch.setattr("archmind.telegram_bot._resolve_target_project", lambda: project_dir)
    msg = DummyMessage()
    asyncio.run(command_inspect(DummyUpdate(message=msg, effective_chat=DummyChat()), DummyContext()))
    out = msg.sent[-1]
    assert "Runtime:" in out
    assert "Backend: RUNNING" in out
    assert "Backend URL:" in out
    assert "http://127.0.0.1:8000" in out
    assert "Deploy:" in out
    assert "Target: railway" in out


def test_improve_command_without_project_shows_guidance(monkeypatch) -> None:
    monkeypatch.setattr("archmind.telegram_bot._resolve_target_project", lambda: None)
    msg = DummyMessage()
    asyncio.run(command_improve(DummyUpdate(message=msg, effective_chat=DummyChat()), DummyContext()))
    out = msg.sent[-1]
    assert "No active project." in out
    assert "/design <idea>" in out
    assert "/idea_local <idea>" in out


def test_improve_command_prioritizes_spec_progression_over_webapp_and_env_noise(tmp_path: Path, monkeypatch) -> None:
    project_dir = tmp_path / "blog_backend_only"
    archmind = project_dir / ".archmind"
    archmind.mkdir(parents=True, exist_ok=True)
    (project_dir / "app").mkdir(parents=True, exist_ok=True)
    (project_dir / "requirements.txt").write_text("fastapi==0.115.0\n", encoding="utf-8")
    (archmind / "architecture_reasoning.json").write_text(
        json.dumps(
            {
                "idea_original": "개인용 블로그형식의 다이어리 webapp",
                "app_shape": "backend",
                "recommended_template": "fastapi",
                "reason_summary": "backend app for notes",
            }
        ),
        encoding="utf-8",
    )
    (archmind / "project_spec.json").write_text(
        json.dumps(
            {
                "shape": "backend",
                "template": "fastapi",
                "modules": ["db"],
                "entities": [],
                "api_endpoints": [],
                "frontend_pages": [],
            }
        ),
        encoding="utf-8",
    )
    (archmind / "state.json").write_text(
        json.dumps(
            {
                "effective_template": "fastapi",
                "architecture_app_shape": "backend",
                "architecture_reason_summary": "backend app",
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr("archmind.telegram_bot._resolve_target_project", lambda: project_dir)

    msg = DummyMessage()
    asyncio.run(command_improve(DummyUpdate(message=msg, effective_chat=DummyChat()), DummyContext()))
    out = msg.sent[-1]
    assert "Project:" in out
    assert "Improve suggestions" in out
    assert "1. " in out
    assert "reason:" in out
    assert "command:" in out
    assert "Define your first entity" in out
    assert "/add_entity Note" in out
    assert "Align intent with fullstack template" not in out
    assert "Repair runtime env injection" not in out
    assert "Next:" in out
    assert "- /inspect" in out
    assert "- /next" in out


def test_improve_command_includes_runtime_failure_class_suggestion(tmp_path: Path, monkeypatch) -> None:
    project_dir = tmp_path / "runtime_fail_proj"
    archmind = project_dir / ".archmind"
    archmind.mkdir(parents=True, exist_ok=True)
    (project_dir / "app").mkdir(parents=True, exist_ok=True)
    (project_dir / "app" / "main.py").write_text("from fastapi import FastAPI\napp = FastAPI()\n", encoding="utf-8")
    (project_dir / "requirements.txt").write_text("fastapi==0.115.0\n", encoding="utf-8")
    (archmind / "project_spec.json").write_text(
        json.dumps(
            {
                "shape": "backend",
                "template": "fastapi",
                "modules": [],
                "entities": [],
                "api_endpoints": [],
                "frontend_pages": [],
            }
        ),
        encoding="utf-8",
    )
    (archmind / "state.json").write_text(
        json.dumps(
            {
                "runtime": {"backend_status": "FAIL", "failure_class": "runtime-entrypoint-error"},
                "runtime_failure_class": "runtime-entrypoint-error",
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(
        "archmind.telegram_bot.detect_backend_runtime_entry",
        lambda _p, port=8000: {"ok": False, "failure_class": "runtime-entrypoint-error", "failure_reason": "entrypoint invalid"},
    )
    monkeypatch.setattr("archmind.telegram_bot._resolve_target_project", lambda: project_dir)
    msg = DummyMessage()
    asyncio.run(command_improve(DummyUpdate(message=msg, effective_chat=DummyChat()), DummyContext()))
    out = msg.sent[-1]
    assert "Resolve runtime failure classification" in out
    assert "runtime-entrypoint-error" in out
    assert "/logs backend" in out


def test_improve_command_suppresses_stale_legacy_runtime_failure_when_detect_ok(tmp_path: Path, monkeypatch) -> None:
    project_dir = tmp_path / "runtime_stale_legacy"
    archmind = project_dir / ".archmind"
    archmind.mkdir(parents=True, exist_ok=True)
    (project_dir / "app").mkdir(parents=True, exist_ok=True)
    (project_dir / "app" / "main.py").write_text("from fastapi import FastAPI\napp = FastAPI()\n", encoding="utf-8")
    (project_dir / "requirements.txt").write_text("fastapi==0.115.0\n", encoding="utf-8")
    (archmind / "project_spec.json").write_text(
        json.dumps(
            {
                "shape": "backend",
                "template": "fastapi",
                "modules": [],
                "entities": [],
                "api_endpoints": [],
                "frontend_pages": [],
            }
        ),
        encoding="utf-8",
    )
    (archmind / "state.json").write_text(
        json.dumps(
            {
                "runtime": {"backend_status": "RUNNING", "failure_class": ""},
                "runtime_failure_class": "environment-python",
                "last_failure_class": "environment-python",
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(
        "archmind.telegram_bot.detect_backend_runtime_entry",
        lambda _p, port=8000: {"ok": True, "backend_entry": "app.main:app", "backend_run_mode": "asgi-direct"},
    )
    monkeypatch.setattr("archmind.telegram_bot._resolve_target_project", lambda: project_dir)
    msg = DummyMessage()
    asyncio.run(command_improve(DummyUpdate(message=msg, effective_chat=DummyChat()), DummyContext()))
    out = msg.sent[-1]
    assert "Resolve runtime failure classification" not in out
    assert "environment-python" not in out


def test_improve_command_does_not_mix_deploy_success_with_runtime_health(tmp_path: Path, monkeypatch) -> None:
    project_dir = tmp_path / "deploy_success_runtime_ok"
    archmind = project_dir / ".archmind"
    archmind.mkdir(parents=True, exist_ok=True)
    (project_dir / "app").mkdir(parents=True, exist_ok=True)
    (project_dir / "app" / "main.py").write_text("from fastapi import FastAPI\napp = FastAPI()\n", encoding="utf-8")
    (project_dir / "requirements.txt").write_text("fastapi==0.115.0\n", encoding="utf-8")
    (archmind / "project_spec.json").write_text(
        json.dumps(
            {
                "shape": "backend",
                "template": "fastapi",
                "modules": [],
                "entities": [],
                "api_endpoints": [],
                "frontend_pages": [],
            }
        ),
        encoding="utf-8",
    )
    (archmind / "state.json").write_text(
        json.dumps(
            {
                "deploy": {"target": "railway", "status": "SUCCESS", "failure_class": ""},
                "runtime": {"mode": "local", "backend_status": "RUNNING", "failure_class": ""},
                "runtime_failure_class": "environment-python",
                "last_failure_class": "environment-python",
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(
        "archmind.telegram_bot.detect_backend_runtime_entry",
        lambda _p, port=8000: {"ok": True, "backend_entry": "app.main:app", "backend_run_mode": "asgi-direct"},
    )
    monkeypatch.setattr("archmind.telegram_bot._resolve_target_project", lambda: project_dir)
    msg = DummyMessage()
    asyncio.run(command_improve(DummyUpdate(message=msg, effective_chat=DummyChat()), DummyContext()))
    out = msg.sent[-1]
    assert "Resolve runtime failure classification" not in out
    assert "Investigate deploy failure classification" not in out


def test_improve_command_prioritizes_progression_gaps_over_generic_expansion(tmp_path: Path, monkeypatch) -> None:
    project_dir = tmp_path / "runtime_ok_expand"
    archmind = project_dir / ".archmind"
    archmind.mkdir(parents=True, exist_ok=True)
    (project_dir / "app").mkdir(parents=True, exist_ok=True)
    (project_dir / "app" / "main.py").write_text("from fastapi import FastAPI\napp = FastAPI()\n", encoding="utf-8")
    (project_dir / "requirements.txt").write_text("fastapi==0.115.0\n", encoding="utf-8")
    (archmind / "project_spec.json").write_text(
        json.dumps(
            {
                "shape": "backend",
                "template": "fastapi",
                "modules": [],
                "entities": [],
                "api_endpoints": [],
                "frontend_pages": [],
            }
        ),
        encoding="utf-8",
    )
    (archmind / "state.json").write_text(
        json.dumps(
            {
                "runtime": {"backend_status": "RUNNING", "failure_class": ""},
                "runtime_failure_class": "environment-python",
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(
        "archmind.telegram_bot.detect_backend_runtime_entry",
        lambda _p, port=8000: {"ok": True, "backend_entry": "app.main:app", "backend_run_mode": "asgi-direct"},
    )
    monkeypatch.setattr("archmind.telegram_bot._resolve_target_project", lambda: project_dir)
    msg = DummyMessage()
    asyncio.run(command_improve(DummyUpdate(message=msg, effective_chat=DummyChat()), DummyContext()))
    out = msg.sent[-1]
    assert "Resolve runtime failure classification" not in out
    assert "Define your first entity" in out
    assert "Expand features incrementally" not in out
    assert "Expand domain model" not in out


def test_improve_command_suppresses_env_repair_when_runtime_env_keys_present(tmp_path: Path, monkeypatch) -> None:
    project_dir = tmp_path / "improve_env_ok"
    archmind = project_dir / ".archmind"
    archmind.mkdir(parents=True, exist_ok=True)
    (project_dir / "backend" / "app").mkdir(parents=True, exist_ok=True)
    (project_dir / "backend" / "app" / "main.py").write_text("from fastapi import FastAPI\napp = FastAPI()\n", encoding="utf-8")
    (project_dir / "backend" / "requirements.txt").write_text("fastapi\nuvicorn\n", encoding="utf-8")
    (project_dir / "frontend").mkdir(parents=True, exist_ok=True)
    (project_dir / "frontend" / ".env.local").write_text(
        "NEXT_PUBLIC_API_BASE_URL=http://127.0.0.1:8011\n",
        encoding="utf-8",
    )
    (project_dir / "backend" / ".env").write_text(
        "APP_PORT=8011\nBACKEND_BASE_URL=http://127.0.0.1:8011\nCORS_ALLOW_ORIGINS=http://localhost:3011,http://127.0.0.1:3011\n",
        encoding="utf-8",
    )
    (archmind / "project_spec.json").write_text(
        json.dumps(
            {
                "shape": "fullstack",
                "template": "fullstack-ddd",
                "modules": [],
                "entities": [],
                "api_endpoints": [],
                "frontend_pages": [],
            }
        ),
        encoding="utf-8",
    )
    (archmind / "state.json").write_text(
        json.dumps({"runtime": {"backend_status": "RUNNING", "failure_class": ""}}),
        encoding="utf-8",
    )
    monkeypatch.setattr(
        "archmind.telegram_bot.detect_backend_runtime_entry",
        lambda _p, port=8000: {"ok": True, "backend_entry": "app.main:app", "backend_run_mode": "asgi-direct"},
    )
    monkeypatch.setattr("archmind.telegram_bot._resolve_target_project", lambda: project_dir)
    msg = DummyMessage()
    asyncio.run(command_improve(DummyUpdate(message=msg, effective_chat=DummyChat()), DummyContext()))
    out = msg.sent[-1]
    assert "Repair runtime env injection" not in out


def test_improve_command_suppresses_env_repair_for_detected_flat_backend(tmp_path: Path, monkeypatch) -> None:
    project_dir = tmp_path / "improve_flat_backend_env_ok"
    archmind = project_dir / ".archmind"
    archmind.mkdir(parents=True, exist_ok=True)
    (project_dir / "app").mkdir(parents=True, exist_ok=True)
    (project_dir / "app" / "main.py").write_text("from fastapi import FastAPI\napp = FastAPI()\n", encoding="utf-8")
    (project_dir / "requirements.txt").write_text("fastapi\nuvicorn\n", encoding="utf-8")
    (project_dir / ".env").write_text(
        "APP_PORT=8000\nBACKEND_BASE_URL=http://127.0.0.1:8000\nCORS_ALLOW_ORIGINS=http://localhost:3000,http://127.0.0.1:3000\n",
        encoding="utf-8",
    )
    (archmind / "project_spec.json").write_text(
        json.dumps(
            {
                "shape": "fullstack",
                "template": "fullstack-ddd",
                "modules": [],
                "entities": [],
                "api_endpoints": [],
                "frontend_pages": [],
            }
        ),
        encoding="utf-8",
    )
    (archmind / "state.json").write_text(
        json.dumps({"runtime": {"backend_status": "RUNNING", "failure_class": ""}}),
        encoding="utf-8",
    )
    monkeypatch.setattr(
        "archmind.telegram_bot.detect_backend_runtime_entry",
        lambda _p, port=8000: {"ok": True, "backend_entry": "app.main:app", "backend_run_mode": "asgi-direct"},
    )
    monkeypatch.setattr("archmind.telegram_bot._resolve_target_project", lambda: project_dir)
    msg = DummyMessage()
    asyncio.run(command_improve(DummyUpdate(message=msg, effective_chat=DummyChat()), DummyContext()))
    out = msg.sent[-1]
    assert "Repair runtime env injection" not in out


def test_improve_command_suppresses_cors_only_env_hint_when_runtime_healthy(tmp_path: Path, monkeypatch) -> None:
    project_dir = tmp_path / "improve_cors_only_missing"
    archmind = project_dir / ".archmind"
    archmind.mkdir(parents=True, exist_ok=True)
    (project_dir / "app").mkdir(parents=True, exist_ok=True)
    (project_dir / "app" / "main.py").write_text("from fastapi import FastAPI\napp = FastAPI()\n", encoding="utf-8")
    (project_dir / "requirements.txt").write_text("fastapi\nuvicorn\n", encoding="utf-8")
    (project_dir / ".env").write_text(
        "APP_PORT=8000\nBACKEND_BASE_URL=http://127.0.0.1:8000\n",
        encoding="utf-8",
    )
    (archmind / "project_spec.json").write_text(
        json.dumps(
            {
                "shape": "backend",
                "template": "fastapi",
                "modules": [],
                "entities": [],
                "api_endpoints": [],
                "frontend_pages": [],
            }
        ),
        encoding="utf-8",
    )
    (archmind / "state.json").write_text(
        json.dumps(
            {
                "runtime": {"backend_status": "RUNNING", "failure_class": "", "healthcheck_status": "SUCCESS"},
                "backend_smoke_status": "SUCCESS",
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(
        "archmind.telegram_bot.detect_backend_runtime_entry",
        lambda _p, port=8000: {"ok": True, "backend_entry": "app.main:app", "backend_run_mode": "asgi-direct"},
    )
    monkeypatch.setattr(
        "archmind.deploy.get_local_runtime_status",
        lambda _p: {
            "backend": {"status": "RUNNING", "pid": 22001, "url": "http://127.0.0.1:8000"},
            "frontend": {"status": "NOT RUNNING", "pid": None, "url": ""},
        },
    )
    monkeypatch.setattr("archmind.telegram_bot._resolve_target_project", lambda: project_dir)
    msg = DummyMessage()
    asyncio.run(command_improve(DummyUpdate(message=msg, effective_chat=DummyChat()), DummyContext()))
    out = msg.sent[-1]
    assert "Repair runtime env injection" not in out


def test_improve_command_suppresses_env_repair_when_runtime_services_are_healthy(tmp_path: Path, monkeypatch) -> None:
    project_dir = tmp_path / "improve_runtime_services_healthy"
    archmind = project_dir / ".archmind"
    archmind.mkdir(parents=True, exist_ok=True)
    (project_dir / "backend" / "app").mkdir(parents=True, exist_ok=True)
    (project_dir / "backend" / "app" / "main.py").write_text("from fastapi import FastAPI\napp = FastAPI()\n", encoding="utf-8")
    (project_dir / "backend" / "requirements.txt").write_text("fastapi\nuvicorn\n", encoding="utf-8")
    (project_dir / "frontend").mkdir(parents=True, exist_ok=True)
    # Intentionally keep backend/.env incomplete to verify runtime-usability suppression.
    (project_dir / "backend" / ".env").write_text(
        "APP_PORT=8017\nBACKEND_BASE_URL=http://127.0.0.1:8017\n",
        encoding="utf-8",
    )
    (project_dir / "frontend" / ".env.local").write_text(
        "NEXT_PUBLIC_API_BASE_URL=http://127.0.0.1:8017\n",
        encoding="utf-8",
    )
    (archmind / "project_spec.json").write_text(
        json.dumps(
            {
                "shape": "fullstack",
                "template": "fullstack-ddd",
                "modules": [],
                "entities": [],
                "api_endpoints": [],
                "frontend_pages": [],
            }
        ),
        encoding="utf-8",
    )
    (archmind / "state.json").write_text(
        json.dumps(
            {
                "runtime": {
                    "backend_status": "RUNNING",
                    "frontend_status": "RUNNING",
                    "failure_class": "",
                    "healthcheck_status": "SUCCESS",
                    "services": {
                        "backend": {"status": "RUNNING", "health": "SUCCESS", "url": "http://127.0.0.1:8017"},
                        "frontend": {"status": "RUNNING", "health": "SUCCESS", "url": "http://127.0.0.1:3017"},
                    },
                }
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(
        "archmind.telegram_bot.detect_backend_runtime_entry",
        lambda _p, port=8000: {"ok": True, "backend_entry": "app.main:app", "backend_run_mode": "asgi-direct"},
    )
    monkeypatch.setattr(
        "archmind.telegram_bot.detect_frontend_runtime_entry",
        lambda _p, port=None, backend_base_url=None: {"ok": True, "frontend_port": 3017},
    )
    monkeypatch.setattr(
        "archmind.deploy.get_local_runtime_status",
        lambda _p: {
            "backend": {"status": "RUNNING", "pid": 32001, "url": "http://127.0.0.1:8017"},
            "frontend": {"status": "RUNNING", "pid": 32002, "url": "http://127.0.0.1:3017"},
        },
    )
    monkeypatch.setattr("archmind.telegram_bot._resolve_target_project", lambda: project_dir)
    msg = DummyMessage()
    asyncio.run(command_improve(DummyUpdate(message=msg, effective_chat=DummyChat()), DummyContext()))
    out = msg.sent[-1]
    assert "Repair runtime env injection" not in out


def test_improve_command_formats_command_hints_as_single_line(tmp_path: Path, monkeypatch) -> None:
    project_dir = tmp_path / "improve_command_format"
    archmind = project_dir / ".archmind"
    archmind.mkdir(parents=True, exist_ok=True)
    (project_dir / "app").mkdir(parents=True, exist_ok=True)
    (project_dir / "requirements.txt").write_text("fastapi==0.115.0\n", encoding="utf-8")
    (archmind / "architecture_reasoning.json").write_text(
        json.dumps(
            {
                "idea_original": "개인용 블로그형식의 다이어리 webapp",
                "app_shape": "backend",
                "recommended_template": "fastapi",
            }
        ),
        encoding="utf-8",
    )
    (archmind / "project_spec.json").write_text(
        json.dumps(
            {
                "shape": "backend",
                "template": "fastapi",
                "modules": [],
                "entities": [],
                "api_endpoints": [],
                "frontend_pages": [],
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr("archmind.telegram_bot._resolve_target_project", lambda: project_dir)
    msg = DummyMessage()
    asyncio.run(command_improve(DummyUpdate(message=msg, effective_chat=DummyChat()), DummyContext()))
    out = msg.sent[-1]
    lines = out.splitlines()
    for idx, line in enumerate(lines):
        if "command:" not in line:
            continue
        assert re.search(r"command:\s*/\S", line)
        if idx + 1 < len(lines):
            assert not lines[idx + 1].startswith("/")


def test_improve_command_includes_action_keyboard_with_cmd_callbacks(tmp_path: Path, monkeypatch) -> None:
    project_dir = tmp_path / "improve_buttons"
    archmind = project_dir / ".archmind"
    archmind.mkdir(parents=True, exist_ok=True)
    (project_dir / "app").mkdir(parents=True, exist_ok=True)
    (project_dir / "requirements.txt").write_text("fastapi==0.115.0\n", encoding="utf-8")
    (archmind / "project_spec.json").write_text(
        json.dumps(
            {
                "shape": "backend",
                "template": "fastapi",
                "modules": [],
                "entities": [],
                "api_endpoints": [],
                "frontend_pages": [],
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr("archmind.telegram_bot._resolve_target_project", lambda: project_dir)
    msg = DummyMessage()
    asyncio.run(command_improve(DummyUpdate(message=msg, effective_chat=DummyChat()), DummyContext()))
    assert msg.sent_kwargs
    reply_markup = msg.sent_kwargs[-1].get("reply_markup")
    assert reply_markup is not None
    buttons = [btn for row in getattr(reply_markup, "inline_keyboard", []) for btn in row]
    callback_values = [str(getattr(btn, "callback_data", "")) for btn in buttons]
    assert any(value.startswith("cmd|/") for value in callback_values)
    assert any("cmd|/inspect" in value for value in callback_values)


def test_command_callback_dispatches_complete_command_payload(monkeypatch) -> None:
    msg = DummyMessage()
    query = DummyCallbackQuery(data="cmd|/logs backend", message=msg)
    update = DummyUpdate(message=msg, effective_chat=DummyChat())
    update.callback_query = query  # type: ignore[attr-defined]
    captured: dict[str, Any] = {}

    async def fake_logs(update_arg, context_arg):  # type: ignore[no-untyped-def]
        captured["called"] = True
        captured["args"] = list(getattr(context_arg, "args", []))
        await update_arg.message.reply_text("logs called")

    monkeypatch.setattr("archmind.telegram_bot.command_logs", fake_logs)
    asyncio.run(command_suggestion_callback(update, DummyContext()))
    assert query.answered is True
    assert captured.get("called") is True
    assert captured.get("args") == ["backend"]


def test_add_module_updates_spec_and_reuses_apply_hook(tmp_path: Path, monkeypatch) -> None:
    project_dir = tmp_path / "task_tracker"
    archmind = project_dir / ".archmind"
    archmind.mkdir(parents=True, exist_ok=True)
    (archmind / "project_spec.json").write_text(
        json.dumps(
            {
                "shape": "fullstack",
                "domains": ["tasks", "teams"],
                "template": "fullstack-ddd",
                "modules": ["db", "dashboard"],
                "reason_summary": "task tracker",
                "evolution": {"version": 1, "added_modules": [], "history": []},
            }
        ),
        encoding="utf-8",
    )

    captured: dict[str, object] = {}

    def fake_apply_modules(project_path: Path, template_name: str, modules: list[str]) -> None:
        captured["project_path"] = project_path
        captured["template_name"] = template_name
        captured["modules"] = list(modules)

    monkeypatch.setattr("archmind.telegram_bot._resolve_target_project", lambda: project_dir)
    monkeypatch.setattr("archmind.telegram_bot.apply_modules_to_project", fake_apply_modules)

    msg = DummyMessage()
    update = DummyUpdate(message=msg, effective_chat=DummyChat())
    asyncio.run(command_add_module(update, DummyContext(args=["auth"])))

    assert "Module added" in msg.sent[-1]
    assert "Added module:\nauth" in msg.sent[-1]
    assert captured["project_path"] == project_dir
    assert captured["template_name"] == "fullstack-ddd"
    assert captured["modules"] == ["auth", "db", "dashboard"]

    payload = json.loads((archmind / "project_spec.json").read_text(encoding="utf-8"))
    assert payload.get("modules") == ["auth", "db", "dashboard"]
    assert payload.get("evolution", {}).get("added_modules") == ["auth"]
    assert payload.get("evolution", {}).get("history", [])[-1] == {"action": "add_module", "module": "auth"}


def test_add_module_avoids_duplicate_and_does_not_reapply(tmp_path: Path, monkeypatch) -> None:
    project_dir = tmp_path / "task_tracker"
    archmind = project_dir / ".archmind"
    archmind.mkdir(parents=True, exist_ok=True)
    (archmind / "project_spec.json").write_text(
        json.dumps(
            {
                "shape": "fullstack",
                "domains": ["tasks"],
                "template": "fullstack-ddd",
                "modules": ["auth", "db"],
                "reason_summary": "task tracker",
                "evolution": {"version": 1, "added_modules": ["auth"], "history": [{"action": "add_module", "module": "auth"}]},
            }
        ),
        encoding="utf-8",
    )
    called = {"count": 0}

    def fake_apply_modules(*_args, **_kwargs) -> None:  # type: ignore[no-untyped-def]
        called["count"] += 1

    monkeypatch.setattr("archmind.telegram_bot._resolve_target_project", lambda: project_dir)
    monkeypatch.setattr("archmind.telegram_bot.apply_modules_to_project", fake_apply_modules)

    msg = DummyMessage()
    update = DummyUpdate(message=msg, effective_chat=DummyChat())
    asyncio.run(command_add_module(update, DummyContext(args=["auth"])))

    assert "Module already present" in msg.sent[-1]
    assert called["count"] == 0
    payload = json.loads((archmind / "project_spec.json").read_text(encoding="utf-8"))
    assert payload.get("modules") == ["auth", "db"]


def test_add_module_unknown_module_shows_available_list(tmp_path: Path, monkeypatch) -> None:
    project_dir = tmp_path / "task_tracker"
    (project_dir / ".archmind").mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr("archmind.telegram_bot._resolve_target_project", lambda: project_dir)

    msg = DummyMessage()
    update = DummyUpdate(message=msg, effective_chat=DummyChat())
    asyncio.run(command_add_module(update, DummyContext(args=["cache"])))

    out = msg.sent[-1]
    assert "Unknown module: cache" in out
    assert "Available modules:" in out
    assert "auth, db, dashboard, worker, file-upload" in out


def test_add_entity_updates_spec_and_evolution_history(tmp_path: Path, monkeypatch) -> None:
    project_dir = tmp_path / "task_tracker"
    archmind = project_dir / ".archmind"
    archmind.mkdir(parents=True, exist_ok=True)
    (archmind / "project_spec.json").write_text(
        json.dumps(
            {
                "shape": "fullstack",
                "domains": ["tasks"],
                "template": "fullstack-ddd",
                "modules": ["db"],
                "entities": [],
                "reason_summary": "task tracker",
                "evolution": {"version": 1, "added_modules": [], "history": []},
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr("archmind.telegram_bot._resolve_target_project", lambda: project_dir)

    msg = DummyMessage()
    update = DummyUpdate(message=msg, effective_chat=DummyChat())
    asyncio.run(command_add_entity(update, DummyContext(args=["task"])))

    out = msg.sent[-1]
    assert "Entity added" in out
    assert "Entity:\nTask" in out
    assert "Code scaffold:" in out
    assert "SKIPPED (no backend structure)" in out

    payload = json.loads((archmind / "project_spec.json").read_text(encoding="utf-8"))
    assert payload.get("entities") == [{"name": "Task", "fields": []}]
    history = payload.get("evolution", {}).get("history", [])
    assert history[0] == {"action": "add_entity", "entity": "Task"}
    assert {"action": "auto_add_api", "method": "GET", "path": "/tasks"} in history
    assert {"action": "auto_add_api", "method": "POST", "path": "/tasks"} in history
    assert {"action": "auto_add_page", "page": "tasks/list"} in history
    assert {"action": "auto_add_page", "page": "tasks/detail"} in history


def test_add_entity_prevents_duplicate_case_insensitive(tmp_path: Path, monkeypatch) -> None:
    project_dir = tmp_path / "task_tracker"
    archmind = project_dir / ".archmind"
    archmind.mkdir(parents=True, exist_ok=True)
    (archmind / "project_spec.json").write_text(
        json.dumps(
            {
                "shape": "fullstack",
                "domains": ["tasks"],
                "template": "fullstack-ddd",
                "modules": [],
                "entities": [{"name": "Task", "fields": []}],
                "reason_summary": "task tracker",
                "evolution": {"version": 1, "added_modules": [], "history": []},
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr("archmind.telegram_bot._resolve_target_project", lambda: project_dir)

    msg = DummyMessage()
    update = DummyUpdate(message=msg, effective_chat=DummyChat())
    asyncio.run(command_add_entity(update, DummyContext(args=["task"])))

    out = msg.sent[-1]
    assert "Entity already exists" in out
    assert "Entity:\nTask" in out

    payload = json.loads((archmind / "project_spec.json").read_text(encoding="utf-8"))
    assert payload.get("entities") == [{"name": "Task", "fields": []}]
    assert payload.get("evolution", {}).get("history", []) == []


def test_add_entity_auto_generated_evolution_visible_in_inspect(tmp_path: Path, monkeypatch) -> None:
    project_dir = tmp_path / "note_fullstack"
    archmind = project_dir / ".archmind"
    archmind.mkdir(parents=True, exist_ok=True)
    (project_dir / "app").mkdir(parents=True, exist_ok=True)
    (project_dir / "app" / "main.py").write_text("from fastapi import FastAPI\napp = FastAPI()\n", encoding="utf-8")
    (project_dir / "requirements.txt").write_text("fastapi\n", encoding="utf-8")
    (project_dir / "frontend").mkdir(parents=True, exist_ok=True)
    (project_dir / "frontend" / "pages").mkdir(parents=True, exist_ok=True)
    (project_dir / "frontend" / "package.json").write_text(json.dumps({"name": "demo", "scripts": {"dev": "next dev"}}), encoding="utf-8")
    (archmind / "project_spec.json").write_text(
        json.dumps(
            {
                "shape": "fullstack",
                "template": "fullstack-ddd",
                "modules": [],
                "entities": [],
                "api_endpoints": [],
                "frontend_pages": [],
                "evolution": {"version": 1, "added_modules": [], "history": []},
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr("archmind.telegram_bot._resolve_target_project", lambda: project_dir)

    add_msg = DummyMessage()
    asyncio.run(command_add_entity(DummyUpdate(message=add_msg, effective_chat=DummyChat()), DummyContext(args=["Note"])))

    inspect_msg = DummyMessage()
    asyncio.run(command_inspect(DummyUpdate(message=inspect_msg, effective_chat=DummyChat()), DummyContext()))
    out = inspect_msg.sent[-1]
    assert "Recent evolution:" in out
    assert "- add_entity Note" in out
    assert "- auto_add_api GET /notes" in out
    assert "- auto_add_api POST /notes" in out
    assert "- auto_add_page notes/list" in out
    assert "- auto_add_page notes/detail" in out


def test_add_entity_already_exists_preserves_existing_fields(tmp_path: Path, monkeypatch) -> None:
    project_dir = tmp_path / "task_tracker"
    archmind = project_dir / ".archmind"
    archmind.mkdir(parents=True, exist_ok=True)
    (archmind / "project_spec.json").write_text(
        json.dumps(
            {
                "shape": "backend",
                "domains": ["tasks"],
                "template": "fastapi",
                "modules": [],
                "entities": [{"name": "Task", "fields": [{"name": "title", "type": "string"}]}],
                "reason_summary": "task api",
                "evolution": {"version": 1, "added_modules": [], "history": []},
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr("archmind.telegram_bot._resolve_target_project", lambda: project_dir)

    msg = DummyMessage()
    update = DummyUpdate(message=msg, effective_chat=DummyChat())
    asyncio.run(command_add_entity(update, DummyContext(args=["Task"])))
    out = msg.sent[-1]
    assert "Entity already exists" in out

    payload = json.loads((archmind / "project_spec.json").read_text(encoding="utf-8"))
    assert payload.get("entities") == [{"name": "Task", "fields": [{"name": "title", "type": "string"}]}]


def test_add_entity_detects_existing_entity_from_generated_files(tmp_path: Path, monkeypatch) -> None:
    project_dir = tmp_path / "task_tracker"
    archmind = project_dir / ".archmind"
    archmind.mkdir(parents=True, exist_ok=True)
    (project_dir / "app" / "models").mkdir(parents=True, exist_ok=True)
    (project_dir / "app" / "models" / "task.py").write_text("class Task:\n    pass\n", encoding="utf-8")
    (archmind / "project_spec.json").write_text(
        json.dumps(
            {
                "shape": "backend",
                "domains": ["tasks"],
                "template": "fastapi",
                "modules": [],
                "entities": [],
                "reason_summary": "task api",
                "evolution": {"version": 1, "added_modules": [], "history": []},
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr("archmind.telegram_bot._resolve_target_project", lambda: project_dir)

    msg = DummyMessage()
    update = DummyUpdate(message=msg, effective_chat=DummyChat())
    asyncio.run(command_add_entity(update, DummyContext(args=["Task"])))
    out = msg.sent[-1]
    assert "Entity already exists" in out

    payload = json.loads((archmind / "project_spec.json").read_text(encoding="utf-8"))
    assert payload.get("entities") == [{"name": "Task", "fields": []}]


def test_add_entity_generates_backend_scaffold_and_main_router_registration(tmp_path: Path, monkeypatch) -> None:
    project_dir = tmp_path / "task_tracker"
    archmind = project_dir / ".archmind"
    archmind.mkdir(parents=True, exist_ok=True)
    (project_dir / "app").mkdir(parents=True, exist_ok=True)
    (project_dir / "requirements.txt").write_text("fastapi\n", encoding="utf-8")
    (project_dir / "app" / "main.py").write_text(
        "from fastapi import FastAPI\n\napp = FastAPI()\n",
        encoding="utf-8",
    )
    (archmind / "project_spec.json").write_text(
        json.dumps(
            {
                "shape": "backend",
                "domains": ["tasks"],
                "template": "fastapi",
                "modules": [],
                "entities": [],
                "reason_summary": "task api",
                "evolution": {"version": 1, "added_modules": [], "history": []},
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr("archmind.telegram_bot._resolve_target_project", lambda: project_dir)

    msg = DummyMessage()
    update = DummyUpdate(message=msg, effective_chat=DummyChat())
    asyncio.run(command_add_entity(update, DummyContext(args=["Task"])))

    out = msg.sent[-1]
    assert "Entity added" in out
    assert "Generated:" in out
    assert "- app/models/task.py" in out
    assert "- app/schemas/task.py" in out
    assert "- app/routers/task.py" in out
    assert "- app/main.py" in out
    assert "Frontend scaffold:" in out
    assert "SKIPPED (no frontend structure)" in out

    assert (project_dir / "app" / "models" / "task.py").exists()
    assert (project_dir / "app" / "schemas" / "task.py").exists()
    assert (project_dir / "app" / "routers" / "task.py").exists()
    router_text = (project_dir / "app" / "routers" / "task.py").read_text(encoding="utf-8")
    assert "def list_tasks()" in router_text
    assert "def create_task(payload: dict[str, Any] = Body(default_factory=dict))" in router_text
    assert "def get_task(id: int)" in router_text
    assert "def update_task(id: int, payload: dict[str, Any] = Body(default_factory=dict))" in router_text
    assert "def delete_task(id: int)" in router_text
    assert "sqlite3.connect" in router_text

    main_text = (project_dir / "app" / "main.py").read_text(encoding="utf-8")
    assert "from app.routers.task import router as task_router" in main_text
    assert "app.include_router(task_router)" in main_text
    payload = json.loads((archmind / "project_spec.json").read_text(encoding="utf-8"))
    assert payload.get("api_endpoints") == [
        "GET /tasks",
        "POST /tasks",
        "GET /tasks/{id}",
        "PATCH /tasks/{id}",
        "DELETE /tasks/{id}",
    ]
    assert payload.get("frontend_pages") == ["tasks/list", "tasks/detail"]


def test_add_entity_generates_frontend_pages_when_frontend_structure_exists(tmp_path: Path, monkeypatch) -> None:
    project_dir = tmp_path / "task_tracker"
    archmind = project_dir / ".archmind"
    archmind.mkdir(parents=True, exist_ok=True)
    (project_dir / "app").mkdir(parents=True, exist_ok=True)
    (project_dir / "requirements.txt").write_text("fastapi\n", encoding="utf-8")
    (project_dir / "app" / "main.py").write_text("from fastapi import FastAPI\n\napp = FastAPI()\n", encoding="utf-8")
    (project_dir / "frontend" / "app").mkdir(parents=True, exist_ok=True)
    (project_dir / "frontend" / "package.json").write_text('{"name":"frontend"}\n', encoding="utf-8")
    (archmind / "project_spec.json").write_text(
        json.dumps(
            {
                "shape": "fullstack",
                "domains": ["tasks"],
                "template": "fullstack-ddd",
                "modules": [],
                "entities": [],
                "reason_summary": "task app",
                "evolution": {"version": 1, "added_modules": [], "history": []},
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr("archmind.telegram_bot._resolve_target_project", lambda: project_dir)

    msg = DummyMessage()
    update = DummyUpdate(message=msg, effective_chat=DummyChat())
    asyncio.run(command_add_entity(update, DummyContext(args=["Task"])))
    out = msg.sent[-1]
    assert "- frontend/app/tasks/page.tsx" in out
    assert "- frontend/app/tasks/[id]/page.tsx" in out
    assert "- /restart" in out
    assert (project_dir / "frontend" / "app" / "tasks" / "page.tsx").exists()
    assert (project_dir / "frontend" / "app" / "tasks" / "[id]" / "page.tsx").exists()


def test_add_field_updates_spec_and_scaffold_files(tmp_path: Path, monkeypatch) -> None:
    project_dir = tmp_path / "task_tracker"
    archmind = project_dir / ".archmind"
    archmind.mkdir(parents=True, exist_ok=True)
    (project_dir / "app").mkdir(parents=True, exist_ok=True)
    (project_dir / "requirements.txt").write_text("fastapi\n", encoding="utf-8")
    (project_dir / "app" / "main.py").write_text("from fastapi import FastAPI\n\napp = FastAPI()\n", encoding="utf-8")
    (archmind / "project_spec.json").write_text(
        json.dumps(
            {
                "shape": "backend",
                "domains": ["tasks"],
                "template": "fastapi",
                "modules": [],
                "entities": [{"name": "Task", "fields": []}],
                "reason_summary": "task api",
                "evolution": {"version": 1, "added_modules": [], "history": []},
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr("archmind.telegram_bot._resolve_target_project", lambda: project_dir)

    msg = DummyMessage()
    update = DummyUpdate(message=msg, effective_chat=DummyChat())
    asyncio.run(command_add_field(update, DummyContext(args=["Task", "title:string"])))

    out = msg.sent[-1]
    assert "Field added" in out
    assert "Field:\ntitle:string" in out
    assert "Fields:\ntitle:string" in out

    payload = json.loads((archmind / "project_spec.json").read_text(encoding="utf-8"))
    entities = payload.get("entities") or []
    assert entities[0]["fields"] == [{"name": "title", "type": "string"}]
    assert payload.get("api_endpoints") == [
        "GET /tasks",
        "POST /tasks",
        "GET /tasks/{id}",
        "PATCH /tasks/{id}",
        "DELETE /tasks/{id}",
    ]
    assert payload.get("frontend_pages") == ["tasks/list", "tasks/detail"]
    assert payload.get("evolution", {}).get("history", [])[-1] == {
        "action": "add_field",
        "entity": "Task",
        "field": "title",
        "type": "string",
    }

    model_text = (project_dir / "app" / "models" / "task.py").read_text(encoding="utf-8")
    schema_text = (project_dir / "app" / "schemas" / "task.py").read_text(encoding="utf-8")
    assert "title: str" in model_text
    assert "title: str" in schema_text


def test_add_field_prevents_duplicate(tmp_path: Path, monkeypatch) -> None:
    project_dir = tmp_path / "task_tracker"
    archmind = project_dir / ".archmind"
    archmind.mkdir(parents=True, exist_ok=True)
    (archmind / "project_spec.json").write_text(
        json.dumps(
            {
                "shape": "backend",
                "domains": ["tasks"],
                "template": "fastapi",
                "modules": [],
                "entities": [{"name": "Task", "fields": [{"name": "title", "type": "string"}]}],
                "reason_summary": "task api",
                "evolution": {"version": 1, "added_modules": [], "history": []},
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr("archmind.telegram_bot._resolve_target_project", lambda: project_dir)

    msg = DummyMessage()
    update = DummyUpdate(message=msg, effective_chat=DummyChat())
    asyncio.run(command_add_field(update, DummyContext(args=["Task", "title:string"])))
    out = msg.sent[-1]
    assert "Field already exists" in out

    payload = json.loads((archmind / "project_spec.json").read_text(encoding="utf-8"))
    fields = payload.get("entities", [{}])[0].get("fields", [])
    assert fields == [{"name": "title", "type": "string"}]
    endpoints = payload.get("api_endpoints") or []
    assert endpoints == [
        "GET /tasks",
        "POST /tasks",
        "GET /tasks/{id}",
        "PATCH /tasks/{id}",
        "DELETE /tasks/{id}",
    ]
    assert len(endpoints) == len(set(endpoints))
    assert payload.get("frontend_pages") == ["tasks/list", "tasks/detail"]


def test_add_field_entity_not_found_shows_hint(tmp_path: Path, monkeypatch) -> None:
    project_dir = tmp_path / "task_tracker"
    archmind = project_dir / ".archmind"
    archmind.mkdir(parents=True, exist_ok=True)
    (archmind / "project_spec.json").write_text(
        json.dumps(
            {
                "shape": "backend",
                "domains": ["tasks"],
                "template": "fastapi",
                "modules": [],
                "entities": [],
                "reason_summary": "task api",
                "evolution": {"version": 1, "added_modules": [], "history": []},
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr("archmind.telegram_bot._resolve_target_project", lambda: project_dir)

    msg = DummyMessage()
    update = DummyUpdate(message=msg, effective_chat=DummyChat())
    asyncio.run(command_add_field(update, DummyContext(args=["Task", "title:string"])))
    out = msg.sent[-1]
    assert "Entity not found: Task" in out
    assert "/add_entity Task" in out


def test_add_field_preserves_existing_fields_and_appends_new_field(tmp_path: Path, monkeypatch) -> None:
    project_dir = tmp_path / "task_tracker"
    archmind = project_dir / ".archmind"
    archmind.mkdir(parents=True, exist_ok=True)
    (project_dir / "app").mkdir(parents=True, exist_ok=True)
    (project_dir / "requirements.txt").write_text("fastapi\n", encoding="utf-8")
    (project_dir / "app" / "main.py").write_text("from fastapi import FastAPI\n\napp = FastAPI()\n", encoding="utf-8")
    (archmind / "project_spec.json").write_text(
        json.dumps(
            {
                "shape": "backend",
                "domains": ["tasks"],
                "template": "fastapi",
                "modules": [],
                "entities": [{"name": "Task", "fields": [{"name": "title", "type": "string"}]}],
                "reason_summary": "task api",
                "evolution": {"version": 1, "added_modules": [], "history": []},
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr("archmind.telegram_bot._resolve_target_project", lambda: project_dir)

    msg = DummyMessage()
    update = DummyUpdate(message=msg, effective_chat=DummyChat())
    asyncio.run(command_add_field(update, DummyContext(args=["Task", "status:string"])))
    out = msg.sent[-1]
    assert "Field added" in out
    assert "Entity not found: Task" not in out

    payload = json.loads((archmind / "project_spec.json").read_text(encoding="utf-8"))
    assert payload.get("entities") == [
        {
            "name": "Task",
            "fields": [{"name": "title", "type": "string"}, {"name": "status", "type": "string"}],
        }
    ]


def test_add_field_uses_generated_files_as_entity_existence_signal(tmp_path: Path, monkeypatch) -> None:
    project_dir = tmp_path / "task_tracker"
    archmind = project_dir / ".archmind"
    archmind.mkdir(parents=True, exist_ok=True)
    (project_dir / "app").mkdir(parents=True, exist_ok=True)
    (project_dir / "requirements.txt").write_text("fastapi\n", encoding="utf-8")
    (project_dir / "app" / "main.py").write_text("from fastapi import FastAPI\n\napp = FastAPI()\n", encoding="utf-8")
    (project_dir / "app" / "models").mkdir(parents=True, exist_ok=True)
    (project_dir / "app" / "models" / "task.py").write_text("class Task:\n    pass\n", encoding="utf-8")
    (archmind / "project_spec.json").write_text(
        json.dumps(
            {
                "shape": "backend",
                "domains": ["tasks"],
                "template": "fastapi",
                "modules": [],
                "entities": [],
                "reason_summary": "task api",
                "evolution": {"version": 1, "added_modules": [], "history": []},
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr("archmind.telegram_bot._resolve_target_project", lambda: project_dir)

    msg = DummyMessage()
    update = DummyUpdate(message=msg, effective_chat=DummyChat())
    asyncio.run(command_add_field(update, DummyContext(args=["Task", "title:string"])))
    out = msg.sent[-1]
    assert "Field added" in out
    assert "Entity not found: Task" not in out

    payload = json.loads((archmind / "project_spec.json").read_text(encoding="utf-8"))
    assert payload.get("entities") == [{"name": "Task", "fields": [{"name": "title", "type": "string"}]}]


def test_add_field_auto_restart_when_backend_running(tmp_path: Path, monkeypatch) -> None:
    project_dir = tmp_path / "task_tracker"
    archmind = project_dir / ".archmind"
    archmind.mkdir(parents=True, exist_ok=True)
    (project_dir / "app").mkdir(parents=True, exist_ok=True)
    (project_dir / "requirements.txt").write_text("fastapi\n", encoding="utf-8")
    (project_dir / "app" / "main.py").write_text("from fastapi import FastAPI\n\napp = FastAPI()\n", encoding="utf-8")
    (archmind / "project_spec.json").write_text(
        json.dumps(
            {
                "shape": "backend",
                "domains": ["tasks"],
                "template": "fastapi",
                "modules": [],
                "entities": [{"name": "Task", "fields": []}],
                "reason_summary": "task api",
                "evolution": {"version": 1, "added_modules": [], "history": []},
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr("archmind.telegram_bot._resolve_target_project", lambda: project_dir)
    calls = {"status": 0, "restart": 0}

    def fake_runtime(_p):  # type: ignore[no-untyped-def]
        calls["status"] += 1
        return {"backend": {"status": "RUNNING", "url": "http://127.0.0.1:8011"}, "frontend": {"status": "NOT RUNNING", "url": ""}}

    def fake_restart(_p):  # type: ignore[no-untyped-def]
        calls["restart"] += 1
        return {
            "backend": {"status": "RESTARTED", "detail": ""},
            "frontend": {"status": "NOT RUNNING", "detail": ""},
        }

    monkeypatch.setattr("archmind.deploy.get_local_runtime_status", fake_runtime)
    monkeypatch.setattr("archmind.deploy.restart_local_services", fake_restart)

    msg = DummyMessage()
    update = DummyUpdate(message=msg, effective_chat=DummyChat())
    asyncio.run(command_add_field(update, DummyContext(args=["Task", "priority:int"])))
    out = msg.sent[-1]
    assert calls["restart"] == 1
    assert "Auto-restart:" in out
    assert "Backend: RESTARTED" in out


def test_add_field_auto_restart_skipped_when_backend_not_running(tmp_path: Path, monkeypatch) -> None:
    project_dir = tmp_path / "task_tracker"
    archmind = project_dir / ".archmind"
    archmind.mkdir(parents=True, exist_ok=True)
    (project_dir / "app").mkdir(parents=True, exist_ok=True)
    (project_dir / "requirements.txt").write_text("fastapi\n", encoding="utf-8")
    (project_dir / "app" / "main.py").write_text("from fastapi import FastAPI\n\napp = FastAPI()\n", encoding="utf-8")
    (archmind / "project_spec.json").write_text(
        json.dumps(
            {
                "shape": "backend",
                "domains": ["tasks"],
                "template": "fastapi",
                "modules": [],
                "entities": [{"name": "Task", "fields": []}],
                "reason_summary": "task api",
                "evolution": {"version": 1, "added_modules": [], "history": []},
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr("archmind.telegram_bot._resolve_target_project", lambda: project_dir)
    calls = {"restart": 0}

    monkeypatch.setattr(
        "archmind.deploy.get_local_runtime_status",
        lambda _p: {"backend": {"status": "NOT RUNNING", "url": ""}, "frontend": {"status": "NOT RUNNING", "url": ""}},
    )

    def fake_restart(_p):  # type: ignore[no-untyped-def]
        calls["restart"] += 1
        return {"backend": {"status": "RESTARTED", "detail": ""}, "frontend": {"status": "NOT RUNNING", "detail": ""}}

    monkeypatch.setattr("archmind.deploy.restart_local_services", fake_restart)

    msg = DummyMessage()
    update = DummyUpdate(message=msg, effective_chat=DummyChat())
    asyncio.run(command_add_field(update, DummyContext(args=["Task", "priority:int"])))
    out = msg.sent[-1]
    assert calls["restart"] == 0
    assert "Auto-restart:" in out
    assert "Skipped (backend not running)" in out


def test_add_field_unknown_type_shows_available_types(tmp_path: Path, monkeypatch) -> None:
    project_dir = tmp_path / "task_tracker"
    (project_dir / ".archmind").mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr("archmind.telegram_bot._resolve_target_project", lambda: project_dir)

    msg = DummyMessage()
    update = DummyUpdate(message=msg, effective_chat=DummyChat())
    asyncio.run(command_add_field(update, DummyContext(args=["Task", "title:text"])))
    out = msg.sent[-1]
    assert "Unknown field type: text" in out
    assert "Available types:" in out
    assert "string, int, float, bool, datetime" in out


def test_add_api_updates_spec_and_generates_custom_router(tmp_path: Path, monkeypatch) -> None:
    project_dir = tmp_path / "task_tracker"
    archmind = project_dir / ".archmind"
    archmind.mkdir(parents=True, exist_ok=True)
    (project_dir / "app").mkdir(parents=True, exist_ok=True)
    (project_dir / "requirements.txt").write_text("fastapi\n", encoding="utf-8")
    (project_dir / "app" / "main.py").write_text("from fastapi import FastAPI\n\napp = FastAPI()\n", encoding="utf-8")
    (archmind / "project_spec.json").write_text(
        json.dumps(
            {
                "shape": "backend",
                "domains": ["tasks"],
                "template": "fastapi",
                "modules": [],
                "entities": [],
                "api_endpoints": [],
                "frontend_pages": [],
                "reason_summary": "task api",
                "evolution": {"version": 1, "added_modules": [], "history": []},
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr("archmind.telegram_bot._resolve_target_project", lambda: project_dir)

    msg = DummyMessage()
    update = DummyUpdate(message=msg, effective_chat=DummyChat())
    asyncio.run(command_add_api(update, DummyContext(args=["GET", "/reports"])))
    out = msg.sent[-1]
    assert "API added" in out
    assert "Endpoint:\nGET /reports" in out

    payload = json.loads((archmind / "project_spec.json").read_text(encoding="utf-8"))
    assert "GET /reports" in (payload.get("api_endpoints") or [])
    assert payload.get("evolution", {}).get("history", [])[-1] == {"action": "add_api", "method": "GET", "path": "/reports"}

    custom_text = (project_dir / "app" / "routers" / "custom.py").read_text(encoding="utf-8")
    assert '@router.get("/reports")' in custom_text
    main_text = (project_dir / "app" / "main.py").read_text(encoding="utf-8")
    assert "from app.routers.custom import router as custom_router" in main_text
    assert "app.include_router(custom_router)" in main_text


def test_add_api_prevents_duplicate_and_invalid_method(tmp_path: Path, monkeypatch) -> None:
    project_dir = tmp_path / "task_tracker"
    archmind = project_dir / ".archmind"
    archmind.mkdir(parents=True, exist_ok=True)
    (archmind / "project_spec.json").write_text(
        json.dumps(
            {
                "shape": "backend",
                "domains": ["tasks"],
                "template": "fastapi",
                "modules": [],
                "entities": [],
                "api_endpoints": ["GET /reports"],
                "frontend_pages": [],
                "reason_summary": "task api",
                "evolution": {"version": 1, "added_modules": [], "history": []},
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr("archmind.telegram_bot._resolve_target_project", lambda: project_dir)

    msg = DummyMessage()
    update = DummyUpdate(message=msg, effective_chat=DummyChat())
    asyncio.run(command_add_api(update, DummyContext(args=["GET", "/reports"])))
    assert "API already exists" in msg.sent[-1]

    msg2 = DummyMessage()
    update2 = DummyUpdate(message=msg2, effective_chat=DummyChat())
    asyncio.run(command_add_api(update2, DummyContext(args=["PUT", "/reports"])))
    assert "Unknown method: PUT" in msg2.sent[-1]
    assert "GET, POST, PATCH, DELETE" in msg2.sent[-1]


def test_add_api_normalizes_method_and_path(tmp_path: Path, monkeypatch) -> None:
    project_dir = tmp_path / "api_normalize_proj"
    archmind = project_dir / ".archmind"
    archmind.mkdir(parents=True, exist_ok=True)
    (archmind / "project_spec.json").write_text(
        json.dumps(
            {
                "shape": "backend",
                "template": "fastapi",
                "modules": [],
                "entities": [],
                "api_endpoints": [],
                "frontend_pages": [],
                "evolution": {"version": 1, "added_modules": [], "history": []},
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr("archmind.telegram_bot._resolve_target_project", lambda: project_dir)

    msg = DummyMessage()
    asyncio.run(command_add_api(DummyUpdate(message=msg, effective_chat=DummyChat()), DummyContext(args=["get", "reports"])))
    out = msg.sent[-1]
    assert "API added" in out
    assert "Endpoint:\nGET /reports" in out

    payload = json.loads((archmind / "project_spec.json").read_text(encoding="utf-8"))
    assert "GET /reports" in (payload.get("api_endpoints") or [])

    msg2 = DummyMessage()
    asyncio.run(command_add_api(DummyUpdate(message=msg2, effective_chat=DummyChat()), DummyContext(args=["GET", "/reports"])))
    assert "API already exists" in msg2.sent[-1]


def test_add_api_normalizes_singular_resource_path_to_plural(tmp_path: Path, monkeypatch) -> None:
    project_dir = tmp_path / "api_plural_proj"
    archmind = project_dir / ".archmind"
    archmind.mkdir(parents=True, exist_ok=True)
    (archmind / "project_spec.json").write_text(
        json.dumps(
            {
                "shape": "backend",
                "template": "fastapi",
                "modules": [],
                "entities": [],
                "api_endpoints": [],
                "frontend_pages": [],
                "evolution": {"version": 1, "added_modules": [], "history": []},
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr("archmind.telegram_bot._resolve_target_project", lambda: project_dir)

    msg = DummyMessage()
    asyncio.run(command_add_api(DummyUpdate(message=msg, effective_chat=DummyChat()), DummyContext(args=["GET", "/task"])))
    out = msg.sent[-1]
    assert "API added" in out
    assert "Endpoint:\nGET /tasks" in out

    payload = json.loads((archmind / "project_spec.json").read_text(encoding="utf-8"))
    assert "GET /tasks" in (payload.get("api_endpoints") or [])


def test_add_page_updates_spec_and_generates_frontend_page(tmp_path: Path, monkeypatch) -> None:
    project_dir = tmp_path / "task_tracker"
    archmind = project_dir / ".archmind"
    archmind.mkdir(parents=True, exist_ok=True)
    (project_dir / "frontend" / "app").mkdir(parents=True, exist_ok=True)
    (project_dir / "frontend" / "package.json").write_text('{"name":"frontend"}\n', encoding="utf-8")
    (archmind / "project_spec.json").write_text(
        json.dumps(
            {
                "shape": "fullstack",
                "domains": ["tasks"],
                "template": "fullstack-ddd",
                "modules": [],
                "entities": [],
                "api_endpoints": [],
                "frontend_pages": [],
                "reason_summary": "task app",
                "evolution": {"version": 1, "added_modules": [], "history": []},
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr("archmind.telegram_bot._resolve_target_project", lambda: project_dir)

    msg = DummyMessage()
    update = DummyUpdate(message=msg, effective_chat=DummyChat())
    asyncio.run(command_add_page(update, DummyContext(args=["reports/list"])))
    out = msg.sent[-1]
    assert "Page added" in out
    assert "Page:\nreports/list" in out
    assert "- frontend/app/reports/page.tsx" in out

    payload = json.loads((archmind / "project_spec.json").read_text(encoding="utf-8"))
    assert "reports/list" in (payload.get("frontend_pages") or [])
    assert payload.get("evolution", {}).get("history", [])[-1] == {"action": "add_page", "page": "reports/list"}
    assert (project_dir / "frontend" / "app" / "reports" / "page.tsx").exists()


def test_add_page_skips_frontend_scaffold_for_backend_only_and_prevents_duplicate(tmp_path: Path, monkeypatch) -> None:
    project_dir = tmp_path / "worker_api_demo"
    archmind = project_dir / ".archmind"
    archmind.mkdir(parents=True, exist_ok=True)
    (archmind / "project_spec.json").write_text(
        json.dumps(
            {
                "shape": "backend",
                "domains": ["tasks"],
                "template": "worker-api",
                "modules": [],
                "entities": [],
                "api_endpoints": [],
                "frontend_pages": ["reports/list"],
                "reason_summary": "worker api",
                "evolution": {"version": 1, "added_modules": [], "history": []},
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr("archmind.telegram_bot._resolve_target_project", lambda: project_dir)

    msg = DummyMessage()
    update = DummyUpdate(message=msg, effective_chat=DummyChat())
    asyncio.run(command_add_page(update, DummyContext(args=["reports/list"])))
    assert "Page already exists" in msg.sent[-1]

    msg2 = DummyMessage()
    update2 = DummyUpdate(message=msg2, effective_chat=DummyChat())
    asyncio.run(command_add_page(update2, DummyContext(args=["admin/overview"])))
    out = msg2.sent[-1]
    assert "Frontend scaffold:" in out
    assert "SKIPPED (no frontend structure)" in out


def test_add_page_normalizes_path_and_prevents_duplicate_case_insensitive(tmp_path: Path, monkeypatch) -> None:
    project_dir = tmp_path / "page_normalize_proj"
    archmind = project_dir / ".archmind"
    archmind.mkdir(parents=True, exist_ok=True)
    (archmind / "project_spec.json").write_text(
        json.dumps(
            {
                "shape": "fullstack",
                "template": "fullstack-ddd",
                "modules": [],
                "entities": [],
                "api_endpoints": [],
                "frontend_pages": [],
                "evolution": {"version": 1, "added_modules": [], "history": []},
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr("archmind.telegram_bot._resolve_target_project", lambda: project_dir)

    msg = DummyMessage()
    asyncio.run(command_add_page(DummyUpdate(message=msg, effective_chat=DummyChat()), DummyContext(args=["/Reports//List/"])))
    out = msg.sent[-1]
    assert "Page added" in out
    assert "Page:\nreports/list" in out

    payload = json.loads((archmind / "project_spec.json").read_text(encoding="utf-8"))
    assert "reports/list" in (payload.get("frontend_pages") or [])

    msg2 = DummyMessage()
    asyncio.run(command_add_page(DummyUpdate(message=msg2, effective_chat=DummyChat()), DummyContext(args=["reports/list"])))
    assert "Page already exists" in msg2.sent[-1]


def test_add_page_normalizes_single_token_to_plural_list_route(tmp_path: Path, monkeypatch) -> None:
    project_dir = tmp_path / "page_single_token_proj"
    archmind = project_dir / ".archmind"
    archmind.mkdir(parents=True, exist_ok=True)
    (archmind / "project_spec.json").write_text(
        json.dumps(
            {
                "shape": "fullstack",
                "template": "fullstack-ddd",
                "modules": [],
                "entities": [],
                "api_endpoints": [],
                "frontend_pages": [],
                "evolution": {"version": 1, "added_modules": [], "history": []},
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr("archmind.telegram_bot._resolve_target_project", lambda: project_dir)

    msg = DummyMessage()
    asyncio.run(command_add_page(DummyUpdate(message=msg, effective_chat=DummyChat()), DummyContext(args=["Tests"])))
    out = msg.sent[-1]
    assert "Page added" in out
    assert "Page:\ntests/list" in out

    payload = json.loads((archmind / "project_spec.json").read_text(encoding="utf-8"))
    assert "tests/list" in (payload.get("frontend_pages") or [])


def test_implement_page_upgrades_placeholder_page(tmp_path: Path, monkeypatch) -> None:
    project_dir = tmp_path / "implement_page_proj"
    archmind = project_dir / ".archmind"
    archmind.mkdir(parents=True, exist_ok=True)
    (project_dir / "frontend" / "app").mkdir(parents=True, exist_ok=True)
    (project_dir / "frontend" / "package.json").write_text('{"name":"frontend"}\n', encoding="utf-8")
    (project_dir / "frontend" / "app" / "tasks" / "list").mkdir(parents=True, exist_ok=True)
    (project_dir / "frontend" / "app" / "tasks" / "list" / "page.tsx").write_text(
        '"use client";\n'
        "export default function TasksListPage(){\n"
        "  return <p>Page placeholder for tasks/list</p>;\n"
        "}\n",
        encoding="utf-8",
    )
    (archmind / "project_spec.json").write_text(
        json.dumps(
            {
                "shape": "fullstack",
                "template": "fullstack-ddd",
                "modules": [],
                "entities": [],
                "api_endpoints": [],
                "frontend_pages": ["tasks/list"],
                "evolution": {"version": 1, "added_modules": [], "history": []},
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr("archmind.telegram_bot._resolve_target_project", lambda: project_dir)

    msg = DummyMessage()
    asyncio.run(command_implement_page(DummyUpdate(message=msg, effective_chat=DummyChat()), DummyContext(args=["tasks/list"])))
    out = msg.sent[-1]
    assert "Implemented page: tasks/list" in out

    page_text = (project_dir / "frontend" / "app" / "tasks" / "list" / "page.tsx").read_text(encoding="utf-8")
    assert "Page placeholder for tasks/list" not in page_text
    assert "fetch(`${apiBaseUrl}/tasks`" in page_text


def test_implement_page_reports_already_implemented(tmp_path: Path, monkeypatch) -> None:
    project_dir = tmp_path / "implement_page_ready_proj"
    archmind = project_dir / ".archmind"
    archmind.mkdir(parents=True, exist_ok=True)
    (project_dir / "frontend" / "app").mkdir(parents=True, exist_ok=True)
    (project_dir / "frontend" / "package.json").write_text('{"name":"frontend"}\n', encoding="utf-8")
    (project_dir / "frontend" / "app" / "tasks" / "list").mkdir(parents=True, exist_ok=True)
    (project_dir / "frontend" / "app" / "tasks" / "list" / "page.tsx").write_text(
        '"use client";\n'
        'import { useApiBaseUrl } from "../../_lib/apiBase";\n'
        "export default function TasksListPage(){\n"
        "  const { apiBaseUrl } = useApiBaseUrl();\n"
        "  return <div>{apiBaseUrl}</div>;\n"
        "}\n",
        encoding="utf-8",
    )
    (archmind / "project_spec.json").write_text(
        json.dumps(
            {
                "shape": "fullstack",
                "template": "fullstack-ddd",
                "modules": [],
                "entities": [],
                "api_endpoints": [],
                "frontend_pages": ["tasks/list"],
                "evolution": {"version": 1, "added_modules": [], "history": []},
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr("archmind.telegram_bot._resolve_target_project", lambda: project_dir)

    msg = DummyMessage()
    asyncio.run(command_implement_page(DummyUpdate(message=msg, effective_chat=DummyChat()), DummyContext(args=["tasks/list"])))
    out = msg.sent[-1]
    assert "Page already implemented: tasks/list" in out


def test_inspect_reflects_explicitly_added_api_and_page(tmp_path: Path, monkeypatch) -> None:
    project_dir = tmp_path / "task_tracker"
    archmind = project_dir / ".archmind"
    archmind.mkdir(parents=True, exist_ok=True)
    (project_dir / "app").mkdir(parents=True, exist_ok=True)
    (project_dir / "requirements.txt").write_text("fastapi\n", encoding="utf-8")
    (project_dir / "app" / "main.py").write_text("from fastapi import FastAPI\n\napp = FastAPI()\n", encoding="utf-8")
    (project_dir / "frontend" / "app").mkdir(parents=True, exist_ok=True)
    (project_dir / "frontend" / "package.json").write_text('{"name":"frontend"}\n', encoding="utf-8")
    (archmind / "project_spec.json").write_text(
        json.dumps(
            {
                "shape": "fullstack",
                "domains": ["tasks"],
                "template": "fullstack-ddd",
                "modules": [],
                "entities": [],
                "api_endpoints": [],
                "frontend_pages": [],
                "reason_summary": "demo",
                "evolution": {"version": 1, "added_modules": [], "history": []},
            }
        ),
        encoding="utf-8",
    )
    (archmind / "state.json").write_text("{}", encoding="utf-8")
    monkeypatch.setattr("archmind.telegram_bot._resolve_target_project", lambda: project_dir)

    update1 = DummyUpdate(message=DummyMessage(), effective_chat=DummyChat())
    asyncio.run(command_add_api(update1, DummyContext(args=["GET", "/healthz/custom"])))
    update2 = DummyUpdate(message=DummyMessage(), effective_chat=DummyChat())
    asyncio.run(command_add_page(update2, DummyContext(args=["reports/list"])))

    msg = DummyMessage()
    update = DummyUpdate(message=msg, effective_chat=DummyChat())
    asyncio.run(command_inspect(update, DummyContext()))
    out = msg.sent[-1]
    assert "- GET /healthz/custom" in out
    assert "- reports/list" in out


def test_suggest_command_no_suggestions_shows_guidance(tmp_path: Path, monkeypatch) -> None:
    project_dir = tmp_path / "task_tracker"
    project_dir.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr("archmind.telegram_bot._resolve_target_project", lambda: project_dir)
    monkeypatch.setattr("archmind.telegram_bot._build_project_analysis", lambda _project: {"suggestions": []})

    msg = DummyMessage()
    update = DummyUpdate(message=msg, effective_chat=DummyChat())
    asyncio.run(command_suggest(update, DummyContext()))
    out = msg.sent[-1]
    assert "Suggestions" in out
    assert f"Target Project: {project_dir.name}" in out
    assert "No immediate suggestions." in out


def test_suggest_command_without_current_project_returns_safe_guidance(monkeypatch) -> None:
    monkeypatch.setattr("archmind.telegram_bot._resolve_target_project", lambda: None)
    msg = DummyMessage()
    update = DummyUpdate(message=msg, effective_chat=DummyChat())
    asyncio.run(command_suggest(update, DummyContext()))
    assert "No active project." in msg.sent[-1]


def test_apply_suggestion_entities_api_pages_modes_and_history(tmp_path: Path, monkeypatch) -> None:
    project_dir = tmp_path / "task_tracker"
    archmind = project_dir / ".archmind"
    archmind.mkdir(parents=True, exist_ok=True)
    (archmind / "project_spec.json").write_text(
        json.dumps(
            {
                "shape": "fullstack",
                "domains": ["tasks"],
                "template": "fullstack-ddd",
                "modules": [],
                "entities": [{"name": "Task", "fields": [{"name": "title", "type": "string"}]}],
                "api_endpoints": ["GET /tasks"],
                "frontend_pages": ["tasks/list"],
                "reason_summary": "demo",
                "evolution": {"version": 1, "added_modules": [], "history": []},
            }
        ),
        encoding="utf-8",
    )
    (archmind / "suggestion.json").write_text(
        json.dumps(
            {
                "entities": [
                    {"name": "Task", "fields": [{"name": "title", "type": "string"}]},
                    {"name": "Defect", "fields": [{"name": "title", "type": "string"}]},
                ],
                "api_endpoints": ["GET /tasks", "POST /defects"],
                "frontend_pages": ["tasks/list", "defects/list"],
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr("archmind.telegram_bot._resolve_target_project", lambda: project_dir)

    m1 = DummyMessage()
    asyncio.run(command_apply_suggestion(DummyUpdate(message=m1, effective_chat=DummyChat()), DummyContext(args=["entities"])))
    m2 = DummyMessage()
    asyncio.run(command_apply_suggestion(DummyUpdate(message=m2, effective_chat=DummyChat()), DummyContext(args=["api"])))
    m3 = DummyMessage()
    asyncio.run(command_apply_suggestion(DummyUpdate(message=m3, effective_chat=DummyChat()), DummyContext(args=["pages"])))

    payload = json.loads((archmind / "project_spec.json").read_text(encoding="utf-8"))
    names = [entity["name"] for entity in (payload.get("entities") or [])]
    assert names.count("Task") == 1
    assert "Defect" in names
    assert "POST /defects" in (payload.get("api_endpoints") or [])
    assert "defects/list" in (payload.get("frontend_pages") or [])
    history = payload.get("evolution", {}).get("history", [])
    assert any(item.get("action") == "apply_suggestion" and item.get("type") == "entities" for item in history if isinstance(item, dict))
    assert any(item.get("action") == "apply_suggestion" and item.get("type") == "api" for item in history if isinstance(item, dict))
    assert any(item.get("action") == "apply_suggestion" and item.get("type") == "pages" for item in history if isinstance(item, dict))


def test_apply_suggestion_missing_file_shows_message(tmp_path: Path, monkeypatch) -> None:
    project_dir = tmp_path / "task_tracker"
    (project_dir / ".archmind").mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr("archmind.telegram_bot._resolve_target_project", lambda: project_dir)
    msg = DummyMessage()
    asyncio.run(command_apply_suggestion(DummyUpdate(message=msg, effective_chat=DummyChat()), DummyContext()))
    assert "No suggestion available" in msg.sent[-1]


def test_apply_suggestion_without_project_shows_guided_message(monkeypatch) -> None:
    monkeypatch.setattr("archmind.telegram_bot._resolve_target_project", lambda: None)
    msg = DummyMessage()
    asyncio.run(command_apply_suggestion(DummyUpdate(message=msg, effective_chat=DummyChat()), DummyContext()))
    out = msg.sent[-1]
    assert "No active project." in out
    assert "/idea_local <your idea>" in out
    assert "/projects" in out
    assert "/use <n>" in out
    assert "/apply_suggestion" in out


def test_inspect_reflects_apply_suggestion_results(tmp_path: Path, monkeypatch) -> None:
    project_dir = tmp_path / "task_tracker"
    archmind = project_dir / ".archmind"
    archmind.mkdir(parents=True, exist_ok=True)
    (project_dir / "app").mkdir(parents=True, exist_ok=True)
    (project_dir / "frontend").mkdir(parents=True, exist_ok=True)
    (archmind / "project_spec.json").write_text(
        json.dumps(
            {
                "shape": "fullstack",
                "domains": ["tasks"],
                "template": "fullstack-ddd",
                "modules": [],
                "entities": [],
                "api_endpoints": [],
                "frontend_pages": [],
                "reason_summary": "demo",
                "evolution": {"version": 1, "added_modules": [], "history": []},
            }
        ),
        encoding="utf-8",
    )
    (archmind / "suggestion.json").write_text(
        json.dumps(
            {
                "entities": [{"name": "Defect", "fields": [{"name": "title", "type": "string"}]}],
                "api_endpoints": ["GET /defects"],
                "frontend_pages": ["defects/list"],
            }
        ),
        encoding="utf-8",
    )
    (archmind / "state.json").write_text("{}", encoding="utf-8")
    monkeypatch.setattr("archmind.telegram_bot._resolve_target_project", lambda: project_dir)
    asyncio.run(command_apply_suggestion(DummyUpdate(message=DummyMessage(), effective_chat=DummyChat()), DummyContext(args=["all"])))
    msg = DummyMessage()
    asyncio.run(command_inspect(DummyUpdate(message=msg, effective_chat=DummyChat()), DummyContext()))
    out = msg.sent[-1]
    assert "- Defect(title:string)" in out
    assert "- GET /defects" in out
    assert "- defects/list" in out


def test_next_command_recommends_user_entity_for_auth_module(tmp_path: Path, monkeypatch) -> None:
    project_dir = tmp_path / "task_tracker"
    archmind = project_dir / ".archmind"
    archmind.mkdir(parents=True, exist_ok=True)
    (archmind / "project_spec.json").write_text(
        json.dumps(
            {
                "shape": "fullstack",
                "domains": ["tasks"],
                "template": "fullstack-ddd",
                "modules": ["auth"],
                "entities": [{"name": "Task", "fields": [{"name": "title", "type": "string"}]}],
                "api_endpoints": ["GET /tasks"],
                "frontend_pages": ["tasks/list"],
                "reason_summary": "demo",
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr("archmind.telegram_bot._resolve_target_project", lambda: project_dir)
    analysis = telegram_bot._build_project_analysis(project_dir)
    next_action = analysis.get("next_action") if isinstance(analysis.get("next_action"), dict) else {}
    msg = DummyMessage()
    asyncio.run(command_next(DummyUpdate(message=msg, effective_chat=DummyChat()), DummyContext()))
    out = msg.sent[-1]
    assert "Next development suggestion" in out
    assert "Target Project: task_tracker" in out
    expected_message = str(next_action.get("message") or "").strip()
    expected_command = str(next_action.get("command") or "").strip()
    assert expected_message in out
    if expected_command:
        assert f"Command: {expected_command}" in out


def test_next_command_recommends_add_entity_when_entities_missing(tmp_path: Path, monkeypatch) -> None:
    project_dir = tmp_path / "entity_seed_proj"
    archmind = project_dir / ".archmind"
    archmind.mkdir(parents=True, exist_ok=True)
    (archmind / "project_spec.json").write_text(
        json.dumps(
            {
                "shape": "backend",
                "domains": ["notes"],
                "template": "fastapi",
                "modules": [],
                "entities": [],
                "api_endpoints": [],
                "frontend_pages": [],
                "reason_summary": "demo",
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr("archmind.telegram_bot._resolve_target_project", lambda: project_dir)
    analysis = telegram_bot._build_project_analysis(project_dir)
    next_action = analysis.get("next_action") if isinstance(analysis.get("next_action"), dict) else {}
    msg = DummyMessage()
    asyncio.run(command_next(DummyUpdate(message=msg, effective_chat=DummyChat()), DummyContext()))
    out = msg.sent[-1]
    expected_message = str(next_action.get("message") or "").strip()
    expected_command = str(next_action.get("command") or "").strip()
    if expected_message.lower() == "no immediate suggestions.":
        assert "No immediate next action." in out
    else:
        assert expected_message in out
    if expected_command:
        assert f"Command: {expected_command}" in out


def test_next_command_recommends_add_field_for_entity_without_fields(tmp_path: Path, monkeypatch) -> None:
    project_dir = tmp_path / "entity_field_seed_proj"
    archmind = project_dir / ".archmind"
    archmind.mkdir(parents=True, exist_ok=True)
    (archmind / "project_spec.json").write_text(
        json.dumps(
            {
                "shape": "backend",
                "domains": ["notes"],
                "template": "fastapi",
                "modules": [],
                "entities": [{"name": "Note", "fields": []}],
                "api_endpoints": [],
                "frontend_pages": [],
                "reason_summary": "demo",
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr("archmind.telegram_bot._resolve_target_project", lambda: project_dir)
    analysis = telegram_bot._build_project_analysis(project_dir)
    next_action = analysis.get("next_action") if isinstance(analysis.get("next_action"), dict) else {}
    msg = DummyMessage()
    asyncio.run(command_next(DummyUpdate(message=msg, effective_chat=DummyChat()), DummyContext()))
    out = msg.sent[-1]
    expected_message = str(next_action.get("message") or "").strip()
    expected_command = str(next_action.get("command") or "").strip()
    assert expected_message in out
    if expected_command:
        assert f"Command: {expected_command}" in out


def test_next_command_prioritizes_missing_api_before_pages_for_entity(tmp_path: Path, monkeypatch) -> None:
    project_dir = tmp_path / "task_tracker"
    archmind = project_dir / ".archmind"
    archmind.mkdir(parents=True, exist_ok=True)
    (archmind / "project_spec.json").write_text(
        json.dumps(
            {
                "shape": "fullstack",
                "domains": ["tasks"],
                "template": "fullstack-ddd",
                "modules": [],
                "entities": [{"name": "Task", "fields": [{"name": "title", "type": "string"}]}],
                "api_endpoints": ["GET /tasks"],
                "frontend_pages": [],
                "reason_summary": "demo",
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr("archmind.telegram_bot._resolve_target_project", lambda: project_dir)
    msg = DummyMessage()
    asyncio.run(command_next(DummyUpdate(message=msg, effective_chat=DummyChat()), DummyContext()))
    out = msg.sent[-1]
    assert "/add_api GET /tasks/{id}" in out
    assert "/add_page tasks/list" not in out
    assert "Command: /add_api GET /tasks/{id}" in out


def test_next_command_recommends_add_api_when_entity_exists_without_apis(tmp_path: Path, monkeypatch) -> None:
    project_dir = tmp_path / "next_missing_api"
    archmind = project_dir / ".archmind"
    archmind.mkdir(parents=True, exist_ok=True)
    (archmind / "project_spec.json").write_text(
        json.dumps(
            {
                "shape": "backend",
                "domains": ["notes"],
                "template": "fastapi",
                "modules": [],
                "entities": [{"name": "Note", "fields": [{"name": "title", "type": "string"}, {"name": "content", "type": "string"}]}],
                "api_endpoints": [],
                "frontend_pages": [],
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr("archmind.telegram_bot._resolve_target_project", lambda: project_dir)
    msg = DummyMessage()
    asyncio.run(command_next(DummyUpdate(message=msg, effective_chat=DummyChat()), DummyContext()))
    out = msg.sent[-1]
    assert "/add_api GET /notes/{id}" in out


def test_next_command_diary_crud_gap_is_actionable_not_diagnosis_only(tmp_path: Path, monkeypatch) -> None:
    project_dir = tmp_path / "next_diary_crud_gap"
    archmind = project_dir / ".archmind"
    archmind.mkdir(parents=True, exist_ok=True)
    (archmind / "project_spec.json").write_text(
        json.dumps(
            {
                "shape": "fullstack",
                "domains": ["diary"],
                "template": "fullstack-ddd",
                "modules": [],
                "entities": [{"name": "Entry", "fields": [{"name": "title", "type": "string"}]}],
                "api_endpoints": ["GET /entries", "POST /entries"],
                "frontend_pages": ["entries/list", "entries/new", "entries/detail"],
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr("archmind.telegram_bot._resolve_target_project", lambda: project_dir)
    msg = DummyMessage()
    asyncio.run(command_next(DummyUpdate(message=msg, effective_chat=DummyChat()), DummyContext()))
    out = msg.sent[-1]
    assert "incomplete CRUD API coverage" not in out
    assert "Command: /add_api GET /entries/{id}" in out


def test_next_command_recommends_add_page_when_api_exists_without_pages(tmp_path: Path, monkeypatch) -> None:
    project_dir = tmp_path / "next_missing_pages"
    archmind = project_dir / ".archmind"
    archmind.mkdir(parents=True, exist_ok=True)
    (archmind / "project_spec.json").write_text(
        json.dumps(
            {
                "shape": "fullstack",
                "domains": ["notes"],
                "template": "fullstack-ddd",
                "modules": [],
                "entities": [{"name": "Note", "fields": [{"name": "title", "type": "string"}]}],
                "api_endpoints": ["GET /notes", "POST /notes"],
                "frontend_pages": [],
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr("archmind.telegram_bot._resolve_target_project", lambda: project_dir)
    analysis = telegram_bot._build_project_analysis(project_dir)
    next_action = analysis.get("next_action") if isinstance(analysis.get("next_action"), dict) else {}
    msg = DummyMessage()
    asyncio.run(command_next(DummyUpdate(message=msg, effective_chat=DummyChat()), DummyContext()))
    out = msg.sent[-1]
    expected_message = str(next_action.get("message") or "").strip()
    expected_command = str(next_action.get("command") or "").strip()
    assert expected_message in out
    if expected_command:
        assert f"Command: {expected_command}" in out


def test_next_callback_executes_full_add_api_command(tmp_path: Path, monkeypatch) -> None:
    project_dir = tmp_path / "task_tracker"
    archmind = project_dir / ".archmind"
    archmind.mkdir(parents=True, exist_ok=True)
    (archmind / "project_spec.json").write_text(
        json.dumps(
            {
                "shape": "backend",
                "domains": ["tasks"],
                "template": "fastapi",
                "modules": [],
                "entities": [],
                "api_endpoints": [],
                "frontend_pages": [],
                "reason_summary": "demo",
                "evolution": {"version": 1, "added_modules": [], "history": []},
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr("archmind.telegram_bot._resolve_target_project", lambda: project_dir)

    msg = DummyMessage()
    query = DummyCallbackQuery(data="/add_api GET /tasks/{id}", message=msg)
    update = DummyUpdate(message=msg, effective_chat=DummyChat())
    update.callback_query = query  # type: ignore[attr-defined]
    asyncio.run(command_suggestion_callback(update, DummyContext()))

    assert query.answered is True
    out = msg.sent[-1]
    assert "API added" in out
    assert "Endpoint:\nGET /tasks/{id}" in out
    payload = json.loads((archmind / "project_spec.json").read_text(encoding="utf-8"))
    assert "GET /tasks/{id}" in (payload.get("api_endpoints") or [])
    events = load_recent_execution_events(project_dir, limit=5)
    assert len(events) >= 1
    assert events[-1].get("source") == "telegram-next"
    assert events[-1].get("status") == "ok"


def test_next_callback_with_project_id_runs_next_for_target_project(tmp_path: Path, monkeypatch) -> None:
    project_dir = tmp_path / "target_proj"
    archmind = project_dir / ".archmind"
    archmind.mkdir(parents=True, exist_ok=True)
    (archmind / "project_spec.json").write_text(
        json.dumps(
            {
                "shape": "backend",
                "domains": ["tasks"],
                "template": "fastapi",
                "modules": [],
                "entities": [],
                "api_endpoints": [],
                "frontend_pages": [],
                "reason_summary": "demo",
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr("archmind.telegram_bot.DEFAULT_PROJECTS_DIR", tmp_path)
    msg = DummyMessage()
    query = DummyCallbackQuery(data="next|target_proj", message=msg)
    update = DummyUpdate(message=msg, effective_chat=DummyChat())
    update.callback_query = query  # type: ignore[attr-defined]

    asyncio.run(command_suggestion_callback(update, DummyContext()))

    assert query.answered is True
    out = msg.sent[-1]
    assert "Next development suggestion" in out
    assert "Target Project: target_proj" in out


def test_next_command_uses_single_analysis_next_action_only(tmp_path: Path, monkeypatch) -> None:
    project_dir = tmp_path / "big_proj"
    archmind = project_dir / ".archmind"
    archmind.mkdir(parents=True, exist_ok=True)
    (archmind / "project_spec.json").write_text(
        json.dumps(
            {
                "shape": "fullstack",
                "domains": ["tasks", "teams"],
                "template": "fullstack-ddd",
                "modules": ["auth", "dashboard"],
                "entities": [{"name": "Task", "fields": [{"name": "title", "type": "string"}]}],
                "api_endpoints": [],
                "frontend_pages": [],
                "reason_summary": "demo",
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr("archmind.telegram_bot._resolve_target_project", lambda: project_dir)
    monkeypatch.setattr(
        "archmind.telegram_bot._build_project_analysis",
        lambda _p: {
            "suggestions": [
                {"kind": "missing_crud_api", "message": "s1", "command": "/add_api GET /tasks"},
                {"kind": "missing_page", "message": "s2", "command": "/add_page tasks/list"},
            ],
            "next_action": {"kind": "missing_field", "message": "Task is missing an important field: title", "command": "/add_field Task title:string"},
        },
    )
    msg = DummyMessage()
    asyncio.run(command_next(DummyUpdate(message=msg, effective_chat=DummyChat()), DummyContext()))
    out = msg.sent[-1]
    assert "Task is missing an important field: title" in out
    assert "Command: /add_field Task title:string" in out
    assert "/add_api GET /tasks" not in out
    assert "/add_page tasks/list" not in out


def test_next_command_no_suggestions_shows_guidance(tmp_path: Path, monkeypatch) -> None:
    project_dir = tmp_path / "next_done_proj"
    archmind = project_dir / ".archmind"
    archmind.mkdir(parents=True, exist_ok=True)
    (archmind / "project_spec.json").write_text(
        json.dumps(
            {
                "shape": "fullstack",
                "domains": ["notes"],
                "template": "fullstack-ddd",
                "modules": [],
                "entities": [
                    {
                        "name": "Note",
                        "fields": [
                            {"name": "title", "type": "string"},
                            {"name": "description", "type": "string"},
                            {"name": "created_at", "type": "datetime"},
                            {"name": "updated_at", "type": "datetime"},
                        ],
                    }
                ],
                "api_endpoints": [
                    "GET /notes",
                    "POST /notes",
                    "GET /notes/{id}",
                    "DELETE /notes/{id}",
                    "PUT /notes/{id}",
                ],
                "frontend_pages": ["notes/list", "notes/detail"],
                "reason_summary": "demo",
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr("archmind.telegram_bot._resolve_target_project", lambda: project_dir)
    msg = DummyMessage()
    asyncio.run(command_next(DummyUpdate(message=msg, effective_chat=DummyChat()), DummyContext()))
    out = msg.sent[-1]
    assert "No immediate next action." in out


def test_spec_progression_stage0_inspect_next_improve(tmp_path: Path, monkeypatch) -> None:
    project_dir = tmp_path / "progress_stage0"
    archmind = project_dir / ".archmind"
    archmind.mkdir(parents=True, exist_ok=True)
    (project_dir / "app").mkdir(parents=True, exist_ok=True)
    (project_dir / "app" / "main.py").write_text("from fastapi import FastAPI\napp = FastAPI()\n", encoding="utf-8")
    (project_dir / "requirements.txt").write_text("fastapi\n", encoding="utf-8")
    (archmind / "project_spec.json").write_text(
        json.dumps({"shape": "backend", "template": "fastapi", "entities": [], "api_endpoints": [], "frontend_pages": []}),
        encoding="utf-8",
    )
    (archmind / "state.json").write_text(json.dumps({"runtime": {"backend_status": "RUNNING", "failure_class": ""}}), encoding="utf-8")
    monkeypatch.setattr("archmind.telegram_bot._resolve_target_project", lambda: project_dir)
    monkeypatch.setattr(
        "archmind.telegram_bot.detect_backend_runtime_entry",
        lambda _p, port=8000: {"ok": True, "backend_entry": "app.main:app", "backend_run_mode": "asgi-direct"},
    )

    inspect_msg = DummyMessage()
    asyncio.run(command_inspect(DummyUpdate(message=inspect_msg, effective_chat=DummyChat()), DummyContext()))
    inspect_out = inspect_msg.sent[-1]
    assert "Spec Summary:" in inspect_out
    assert "- Stage: Stage 0" in inspect_out

    next_msg = DummyMessage()
    asyncio.run(command_next(DummyUpdate(message=next_msg, effective_chat=DummyChat()), DummyContext()))
    next_out = next_msg.sent[-1]
    analysis = telegram_bot._build_project_analysis(project_dir)
    next_action = analysis.get("next_action") if isinstance(analysis.get("next_action"), dict) else {}
    expected_message = str(next_action.get("message") or "").strip()
    expected_command = str(next_action.get("command") or "").strip()
    if expected_message.lower() == "no immediate suggestions.":
        assert "No immediate next action." in next_out
    else:
        assert expected_message in next_out
    if expected_command:
        assert f"Command: {expected_command}" in next_out

    improve_msg = DummyMessage()
    asyncio.run(command_improve(DummyUpdate(message=improve_msg, effective_chat=DummyChat()), DummyContext()))
    improve_out = improve_msg.sent[-1]
    assert "Define your first entity" in improve_out
    assert "/add_entity Note" in improve_out


def test_spec_progression_stage1_next_and_improve(tmp_path: Path, monkeypatch) -> None:
    project_dir = tmp_path / "progress_stage1"
    archmind = project_dir / ".archmind"
    archmind.mkdir(parents=True, exist_ok=True)
    (archmind / "project_spec.json").write_text(
        json.dumps(
            {"shape": "backend", "template": "fastapi", "entities": [{"name": "Note", "fields": []}], "api_endpoints": [], "frontend_pages": []}
        ),
        encoding="utf-8",
    )
    (project_dir / "app").mkdir(parents=True, exist_ok=True)
    (project_dir / "app" / "main.py").write_text("from fastapi import FastAPI\napp = FastAPI()\n", encoding="utf-8")
    (project_dir / "requirements.txt").write_text("fastapi\n", encoding="utf-8")
    (archmind / "state.json").write_text(json.dumps({"runtime": {"backend_status": "RUNNING", "failure_class": ""}}), encoding="utf-8")
    monkeypatch.setattr("archmind.telegram_bot._resolve_target_project", lambda: project_dir)
    monkeypatch.setattr(
        "archmind.telegram_bot.detect_backend_runtime_entry",
        lambda _p, port=8000: {"ok": True, "backend_entry": "app.main:app", "backend_run_mode": "asgi-direct"},
    )

    next_msg = DummyMessage()
    asyncio.run(command_next(DummyUpdate(message=next_msg, effective_chat=DummyChat()), DummyContext()))
    next_out = next_msg.sent[-1]
    analysis = telegram_bot._build_project_analysis(project_dir)
    next_action = analysis.get("next_action") if isinstance(analysis.get("next_action"), dict) else {}
    expected_message = str(next_action.get("message") or "").strip()
    expected_command = str(next_action.get("command") or "").strip()
    assert expected_message in next_out
    if expected_command:
        assert f"Command: {expected_command}" in next_out

    improve_msg = DummyMessage()
    asyncio.run(command_improve(DummyUpdate(message=improve_msg, effective_chat=DummyChat()), DummyContext()))
    assert "Add fields to Note" in improve_msg.sent[-1]


def test_next_command_omits_command_line_when_next_action_command_is_empty(tmp_path: Path, monkeypatch) -> None:
    project_dir = tmp_path / "next_omit_empty_command"
    archmind = project_dir / ".archmind"
    archmind.mkdir(parents=True, exist_ok=True)
    (archmind / "project_spec.json").write_text(
        json.dumps(
            {"shape": "backend", "template": "fastapi", "entities": [], "api_endpoints": [], "frontend_pages": []}
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr("archmind.telegram_bot._resolve_target_project", lambda: project_dir)
    monkeypatch.setattr(
        "archmind.telegram_bot._build_project_analysis",
        lambda _p: {
            "next_action": {"kind": "none", "message": "No immediate suggestions.", "command": ""},
            "suggestions": [],
        },
    )

    next_msg = DummyMessage()
    asyncio.run(command_next(DummyUpdate(message=next_msg, effective_chat=DummyChat()), DummyContext()))
    out = next_msg.sent[-1]
    assert "Next development suggestion" in out
    assert "No immediate next action." in out
    assert "Command:" not in out


def test_auto_command_without_current_project_returns_safe_guidance(monkeypatch) -> None:
    monkeypatch.setattr("archmind.telegram_bot._resolve_target_project", lambda: None)
    msg = DummyMessage()
    asyncio.run(command_auto(DummyUpdate(message=msg, effective_chat=DummyChat()), DummyContext()))
    assert "No active project." in msg.sent[-1]


def test_auto_command_stops_when_no_immediate_next_action(tmp_path: Path, monkeypatch) -> None:
    project_dir = tmp_path / "auto_none"
    project_dir.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr("archmind.telegram_bot._resolve_target_project", lambda: project_dir)
    monkeypatch.setattr(
        "archmind.telegram_bot._build_project_analysis",
        lambda _p: {"next_action": {"kind": "none", "message": "No immediate suggestions.", "command": ""}},
    )
    msg = DummyMessage()
    asyncio.run(command_auto(DummyUpdate(message=msg, effective_chat=DummyChat()), DummyContext()))
    out = msg.sent[-1]
    assert "Auto evolution run" in out
    assert "Step 1" in out
    assert "- No immediate next action." in out
    assert "- Executed: 0" in out
    assert "- Stopped: no immediate next action" in out
    events = load_recent_execution_events(project_dir, limit=5)
    assert len(events) >= 1
    last = events[-1]
    assert last.get("source") == "telegram-auto"
    assert last.get("status") == "stop"
    assert last.get("stop_reason") == "no immediate next action"


def test_auto_command_executes_valid_next_actions(tmp_path: Path, monkeypatch) -> None:
    project_dir = tmp_path / "auto_ok"
    project_dir.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr("archmind.telegram_bot._resolve_target_project", lambda: project_dir)
    sequence = iter(
        [
            {"next_action": {"kind": "missing_api", "message": "add list api", "command": "/add_api GET /tasks"}},
            {"next_action": {"kind": "missing_page", "message": "add list page", "command": "/add_page tasks/list"}},
            {"next_action": {"kind": "none", "message": "No immediate suggestions.", "command": ""}},
        ]
    )
    monkeypatch.setattr("archmind.telegram_bot._build_project_analysis", lambda _p: next(sequence))
    executed_commands: list[str] = []

    def _fake_execute(command: str, _project_name: str, **_kwargs: Any) -> dict[str, object]:
        executed_commands.append(command)
        return {"ok": True, "message": "ok"}

    monkeypatch.setattr("archmind.telegram_bot.execute_command", _fake_execute)
    msg = DummyMessage()
    asyncio.run(command_auto(DummyUpdate(message=msg, effective_chat=DummyChat()), DummyContext()))
    out = msg.sent[-1]
    assert executed_commands == ["/add_api GET /tasks", "/add_page tasks/list"]
    assert "- Result: OK" in out
    assert "- Executed: 2" in out
    assert "- Stopped: no immediate next action" in out


def test_auto_command_stops_on_repeated_command(tmp_path: Path, monkeypatch) -> None:
    project_dir = tmp_path / "auto_repeat"
    project_dir.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr("archmind.telegram_bot._resolve_target_project", lambda: project_dir)
    sequence = iter(
        [
            {"next_action": {"kind": "missing_page", "message": "implement", "command": "/implement_page tasks/list"}},
            {"next_action": {"kind": "missing_page", "message": "implement again", "command": "/implement_page tasks/list"}},
        ]
    )
    monkeypatch.setattr("archmind.telegram_bot._build_project_analysis", lambda _p: next(sequence))
    calls = {"count": 0}

    def _fake_execute(command: str, _project_name: str, **_kwargs: Any) -> dict[str, Any]:
        calls["count"] += 1
        return {"ok": True, "message": command}

    monkeypatch.setattr("archmind.telegram_bot.execute_command", _fake_execute)
    msg = DummyMessage()
    asyncio.run(command_auto(DummyUpdate(message=msg, effective_chat=DummyChat()), DummyContext(args=["3"])))
    out = msg.sent[-1]
    assert calls["count"] == 1
    assert "repeated-command protection" in out
    assert "- Stopped: repeated command detected" in out


def test_auto_command_stops_on_command_failure(tmp_path: Path, monkeypatch) -> None:
    project_dir = tmp_path / "auto_fail"
    project_dir.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr("archmind.telegram_bot._resolve_target_project", lambda: project_dir)
    monkeypatch.setattr(
        "archmind.telegram_bot._build_project_analysis",
        lambda _p: {"next_action": {"kind": "missing_field", "message": "add field", "command": "/add_field Task title:string"}},
    )
    monkeypatch.setattr(
        "archmind.telegram_bot.execute_command",
        lambda _c, _p, **_kwargs: {"ok": False, "error": "duplicate field"},
    )
    msg = DummyMessage()
    asyncio.run(command_auto(DummyUpdate(message=msg, effective_chat=DummyChat()), DummyContext()))
    out = msg.sent[-1]
    assert "- Result: FAIL (duplicate field)" in out
    assert "- Executed: 0" in out
    assert "- Stopped: command failed: duplicate field" in out


def test_auto_command_respects_max_step_cap_and_allowed_commands(tmp_path: Path, monkeypatch) -> None:
    project_dir = tmp_path / "auto_cap"
    project_dir.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr("archmind.telegram_bot._resolve_target_project", lambda: project_dir)
    sequence = iter(
        [
            {"next_action": {"kind": "k1", "message": "m1", "command": "/add_api GET /tasks"}},
            {"next_action": {"kind": "k2", "message": "m2", "command": "/add_page tasks/list"}},
            {"next_action": {"kind": "k3", "message": "m3", "command": "/run all"}},
        ]
    )
    monkeypatch.setattr("archmind.telegram_bot._build_project_analysis", lambda _p: next(sequence))
    executed: list[str] = []
    monkeypatch.setattr(
        "archmind.telegram_bot.execute_command",
        lambda cmd, _p, **_kwargs: (executed.append(cmd) or {"ok": True, "message": "ok"}),
    )
    msg = DummyMessage()
    # value 9 must be clamped to 3
    asyncio.run(command_auto(DummyUpdate(message=msg, effective_chat=DummyChat()), DummyContext(args=["9"])))
    out = msg.sent[-1]
    assert executed == ["/add_api GET /tasks", "/add_page tasks/list"]
    assert "- Result: STOP (unsupported command)" in out
    assert "- Stopped: unsupported command: /run" in out


def test_auto_command_stops_on_low_priority_next_action(tmp_path: Path, monkeypatch) -> None:
    project_dir = tmp_path / "auto_low_priority"
    project_dir.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr("archmind.telegram_bot._resolve_target_project", lambda: project_dir)
    monkeypatch.setattr(
        "archmind.telegram_bot._build_project_analysis",
        lambda _p: {
            "next_action": {
                "kind": "missing_field",
                "message": "Task is missing an important field: created_at",
                "command": "/add_field Task created_at:datetime",
            }
        },
    )
    executed: list[str] = []
    monkeypatch.setattr(
        "archmind.telegram_bot.execute_command",
        lambda cmd, _p, **_kwargs: (executed.append(cmd) or {"ok": True, "message": "ok"}),
    )
    msg = DummyMessage()
    asyncio.run(command_auto(DummyUpdate(message=msg, effective_chat=DummyChat()), DummyContext()))
    out = msg.sent[-1]
    assert executed == []
    assert "- Result: STOP (low-priority next action)" in out
    assert "- Stopped: low-priority next action" in out


def test_auto_command_stops_on_repeated_low_value_pattern(tmp_path: Path, monkeypatch) -> None:
    project_dir = tmp_path / "auto_repeated_weak_pattern"
    project_dir.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr("archmind.telegram_bot._resolve_target_project", lambda: project_dir)
    sequence = iter(
        [
            {"next_action": {"kind": "missing_field", "message": "Task is missing an important field: title", "command": "/add_field Task title:string"}},
            {"next_action": {"kind": "missing_field", "message": "Reminder is missing an important field: title", "command": "/add_field Reminder title:string"}},
            {"next_action": {"kind": "missing_page", "message": "Reminder is missing list page coverage.", "command": "/add_page reminders/list"}},
        ]
    )
    monkeypatch.setattr("archmind.telegram_bot._build_project_analysis", lambda _p: next(sequence))
    executed: list[str] = []
    monkeypatch.setattr(
        "archmind.telegram_bot.execute_command",
        lambda cmd, _p, **_kwargs: (executed.append(cmd) or {"ok": True, "message": "ok"}),
    )
    msg = DummyMessage()
    asyncio.run(command_auto(DummyUpdate(message=msg, effective_chat=DummyChat()), DummyContext(args=["3"])))
    out = msg.sent[-1]
    assert executed == ["/add_field Task title:string"]
    assert "- Result: STOP (repeated low-value pattern)" in out
    assert "- Stopped: repeated low-value pattern" in out


def test_auto_command_prioritizes_missing_page_before_placeholder_implementation(tmp_path: Path, monkeypatch) -> None:
    project_dir = tmp_path / "auto_existing_placeholder_page"
    archmind = project_dir / ".archmind"
    archmind.mkdir(parents=True, exist_ok=True)
    (archmind / "project_spec.json").write_text(
        json.dumps(
            {
                "shape": "fullstack",
                "domains": ["songs"],
                "template": "fullstack-ddd",
                "modules": [],
                "entities": [{"name": "Song", "fields": [{"name": "title", "type": "string"}]}],
                "api_endpoints": [
                    "GET /songs",
                    "POST /songs",
                    "GET /songs/{song_id}",
                    "PUT /songs/{song_id}",
                    "DELETE /songs/{song_id}",
                ],
                # stale/missing page metadata
                "frontend_pages": [],
            }
        ),
        encoding="utf-8",
    )
    (project_dir / "frontend" / "app" / "songs" / "favorite").mkdir(parents=True, exist_ok=True)
    (project_dir / "frontend" / "app" / "songs" / "favorite" / "page.tsx").write_text(
        "export default function Page() { return <p>Page placeholder for songs/favorite</p>; }",
        encoding="utf-8",
    )
    monkeypatch.setattr("archmind.telegram_bot._resolve_target_project", lambda: project_dir)
    executed: list[str] = []
    monkeypatch.setattr(
        "archmind.telegram_bot.execute_command",
        lambda cmd, _p, **_kwargs: (executed.append(cmd) or {"ok": True, "message": "ok"}),
    )
    msg = DummyMessage()
    asyncio.run(command_auto(DummyUpdate(message=msg, effective_chat=DummyChat()), DummyContext(args=["1"])))
    out = msg.sent[-1]
    assert executed == ["/add_page songs/list"]
    assert "- Next: /add_page songs/list" in out
    assert "/implement_page songs/favorite" not in out
def test_improve_suggestion_button_dispatches_add_field_command(tmp_path: Path, monkeypatch) -> None:
    project_dir = tmp_path / "improve_button_dispatch_add_field"
    archmind = project_dir / ".archmind"
    archmind.mkdir(parents=True, exist_ok=True)
    (archmind / "project_spec.json").write_text(
        json.dumps(
            {
                "shape": "backend",
                "template": "fastapi",
                "entities": [{"name": "Note", "fields": []}],
                "api_endpoints": [],
                "frontend_pages": [],
            }
        ),
        encoding="utf-8",
    )
    (project_dir / "app").mkdir(parents=True, exist_ok=True)
    (project_dir / "app" / "main.py").write_text("from fastapi import FastAPI\napp = FastAPI()\n", encoding="utf-8")
    (project_dir / "requirements.txt").write_text("fastapi\n", encoding="utf-8")
    (archmind / "state.json").write_text(json.dumps({"runtime": {"backend_status": "RUNNING", "failure_class": ""}}), encoding="utf-8")
    monkeypatch.setattr("archmind.telegram_bot._resolve_target_project", lambda: project_dir)
    monkeypatch.setattr(
        "archmind.telegram_bot.detect_backend_runtime_entry",
        lambda _p, port=8000: {"ok": True, "backend_entry": "app.main:app", "backend_run_mode": "asgi-direct"},
    )

    improve_msg = DummyMessage()
    asyncio.run(command_improve(DummyUpdate(message=improve_msg, effective_chat=DummyChat()), DummyContext()))
    reply_markup = improve_msg.sent_kwargs[-1].get("reply_markup")
    assert reply_markup is not None
    buttons = [btn for row in getattr(reply_markup, "inline_keyboard", []) for btn in row]
    callback_data = next(
        str(getattr(btn, "callback_data", ""))
        for btn in buttons
        if "/add_field Note title:string" in str(getattr(btn, "callback_data", ""))
    )
    assert callback_data.startswith("cmd|")

    callback_msg = DummyMessage()
    callback_query = DummyCallbackQuery(data=callback_data, message=callback_msg)
    callback_update = DummyUpdate(message=callback_msg, effective_chat=DummyChat())
    callback_update.callback_query = callback_query  # type: ignore[attr-defined]
    asyncio.run(command_suggestion_callback(callback_update, DummyContext()))

    updated = json.loads((archmind / "project_spec.json").read_text(encoding="utf-8"))
    note = next((item for item in (updated.get("entities") or []) if isinstance(item, dict) and str(item.get("name")) == "Note"), None)
    fields = note.get("fields") if isinstance(note, dict) and isinstance(note.get("fields"), list) else []
    assert any(isinstance(field, dict) and field.get("name") == "title" and field.get("type") == "string" for field in fields)
    assert "Unsupported command action" not in "\n".join(callback_msg.sent)


def test_spec_progression_keeps_stage0_priority_even_when_api_and_pages_exist(tmp_path: Path, monkeypatch) -> None:
    project_dir = tmp_path / "progress_stage0_api_pages"
    archmind = project_dir / ".archmind"
    archmind.mkdir(parents=True, exist_ok=True)
    (archmind / "project_spec.json").write_text(
        json.dumps(
            {
                "shape": "fullstack",
                "template": "fullstack-ddd",
                "entities": [],
                "api_endpoints": ["GET /notes", "POST /notes"],
                "frontend_pages": ["notes/list", "notes/detail"],
            }
        ),
        encoding="utf-8",
    )
    (project_dir / "app").mkdir(parents=True, exist_ok=True)
    (project_dir / "app" / "main.py").write_text("from fastapi import FastAPI\napp = FastAPI()\n", encoding="utf-8")
    (project_dir / "requirements.txt").write_text("fastapi\n", encoding="utf-8")
    (archmind / "state.json").write_text(json.dumps({"runtime": {"backend_status": "RUNNING", "failure_class": ""}}), encoding="utf-8")
    monkeypatch.setattr("archmind.telegram_bot._resolve_target_project", lambda: project_dir)
    monkeypatch.setattr(
        "archmind.telegram_bot.detect_backend_runtime_entry",
        lambda _p, port=8000: {"ok": True, "backend_entry": "app.main:app", "backend_run_mode": "asgi-direct"},
    )

    inspect_msg = DummyMessage()
    asyncio.run(command_inspect(DummyUpdate(message=inspect_msg, effective_chat=DummyChat()), DummyContext()))
    assert "- Stage: Stage 0" in inspect_msg.sent[-1]

    next_msg = DummyMessage()
    asyncio.run(command_next(DummyUpdate(message=next_msg, effective_chat=DummyChat()), DummyContext()))
    next_out = next_msg.sent[-1]
    analysis = telegram_bot._build_project_analysis(project_dir)
    next_action = analysis.get("next_action") if isinstance(analysis.get("next_action"), dict) else {}
    expected_message = str(next_action.get("message") or "").strip()
    expected_command = str(next_action.get("command") or "").strip()
    if expected_message.lower() == "no immediate suggestions.":
        assert "No immediate next action." in next_out
    else:
        assert expected_message in next_out
    if expected_command:
        assert f"Command: {expected_command}" in next_out

    improve_msg = DummyMessage()
    asyncio.run(command_improve(DummyUpdate(message=improve_msg, effective_chat=DummyChat()), DummyContext()))
    improve_out = improve_msg.sent[-1]
    assert "Define your first entity" in improve_out
    assert "/add_entity Note" in improve_out


def test_spec_progression_keeps_stage1_priority_even_when_api_and_pages_exist(tmp_path: Path, monkeypatch) -> None:
    project_dir = tmp_path / "progress_stage1_api_pages"
    archmind = project_dir / ".archmind"
    archmind.mkdir(parents=True, exist_ok=True)
    (archmind / "project_spec.json").write_text(
        json.dumps(
            {
                "shape": "fullstack",
                "template": "fullstack-ddd",
                "entities": [{"name": "Note", "fields": []}],
                "api_endpoints": ["GET /notes", "POST /notes"],
                "frontend_pages": ["notes/list", "notes/detail"],
            }
        ),
        encoding="utf-8",
    )
    (project_dir / "app").mkdir(parents=True, exist_ok=True)
    (project_dir / "app" / "main.py").write_text("from fastapi import FastAPI\napp = FastAPI()\n", encoding="utf-8")
    (project_dir / "requirements.txt").write_text("fastapi\n", encoding="utf-8")
    (archmind / "state.json").write_text(json.dumps({"runtime": {"backend_status": "RUNNING", "failure_class": ""}}), encoding="utf-8")
    monkeypatch.setattr("archmind.telegram_bot._resolve_target_project", lambda: project_dir)
    monkeypatch.setattr(
        "archmind.telegram_bot.detect_backend_runtime_entry",
        lambda _p, port=8000: {"ok": True, "backend_entry": "app.main:app", "backend_run_mode": "asgi-direct"},
    )

    inspect_msg = DummyMessage()
    asyncio.run(command_inspect(DummyUpdate(message=inspect_msg, effective_chat=DummyChat()), DummyContext()))
    assert "- Stage: Stage 1" in inspect_msg.sent[-1]

    next_msg = DummyMessage()
    asyncio.run(command_next(DummyUpdate(message=next_msg, effective_chat=DummyChat()), DummyContext()))
    next_out = next_msg.sent[-1]
    analysis = telegram_bot._build_project_analysis(project_dir)
    next_action = analysis.get("next_action") if isinstance(analysis.get("next_action"), dict) else {}
    expected_message = str(next_action.get("message") or "").strip()
    expected_command = str(next_action.get("command") or "").strip()
    assert expected_message in next_out
    if expected_command:
        assert f"Command: {expected_command}" in next_out

    improve_msg = DummyMessage()
    asyncio.run(command_improve(DummyUpdate(message=improve_msg, effective_chat=DummyChat()), DummyContext()))
    improve_out = improve_msg.sent[-1]
    assert "Add fields to Note" in improve_out
    assert "/add_field Note title:string" in improve_out


def test_spec_progression_stage2_next_and_improve(tmp_path: Path, monkeypatch) -> None:
    project_dir = tmp_path / "progress_stage2"
    archmind = project_dir / ".archmind"
    archmind.mkdir(parents=True, exist_ok=True)
    (archmind / "project_spec.json").write_text(
        json.dumps(
            {
                "shape": "backend",
                "template": "fastapi",
                "entities": [{"name": "Note", "fields": [{"name": "title", "type": "string"}]}],
                "api_endpoints": [],
                "frontend_pages": [],
            }
        ),
        encoding="utf-8",
    )
    (project_dir / "app").mkdir(parents=True, exist_ok=True)
    (project_dir / "app" / "main.py").write_text("from fastapi import FastAPI\napp = FastAPI()\n", encoding="utf-8")
    (project_dir / "requirements.txt").write_text("fastapi\n", encoding="utf-8")
    (archmind / "state.json").write_text(json.dumps({"runtime": {"backend_status": "RUNNING", "failure_class": ""}}), encoding="utf-8")
    monkeypatch.setattr("archmind.telegram_bot._resolve_target_project", lambda: project_dir)
    monkeypatch.setattr(
        "archmind.telegram_bot.detect_backend_runtime_entry",
        lambda _p, port=8000: {"ok": True, "backend_entry": "app.main:app", "backend_run_mode": "asgi-direct"},
    )

    next_msg = DummyMessage()
    asyncio.run(command_next(DummyUpdate(message=next_msg, effective_chat=DummyChat()), DummyContext()))
    next_out = next_msg.sent[-1]
    analysis = telegram_bot._build_project_analysis(project_dir)
    next_action = analysis.get("next_action") if isinstance(analysis.get("next_action"), dict) else {}
    expected_message = str(next_action.get("message") or "").strip()
    expected_command = str(next_action.get("command") or "").strip()
    assert expected_message in next_out
    if expected_command:
        assert f"Command: {expected_command}" in next_out

    improve_msg = DummyMessage()
    asyncio.run(command_improve(DummyUpdate(message=improve_msg, effective_chat=DummyChat()), DummyContext()))
    improve_out = improve_msg.sent[-1]
    assert "Add an API for Note" in improve_out
    assert "/add_api GET /notes" in improve_out


def test_spec_progression_stage3_next_and_improve(tmp_path: Path, monkeypatch) -> None:
    project_dir = tmp_path / "progress_stage3"
    archmind = project_dir / ".archmind"
    archmind.mkdir(parents=True, exist_ok=True)
    (archmind / "project_spec.json").write_text(
        json.dumps(
            {
                "shape": "fullstack",
                "template": "fullstack-ddd",
                "entities": [{"name": "Note", "fields": [{"name": "title", "type": "string"}]}],
                "api_endpoints": ["GET /notes", "POST /notes"],
                "frontend_pages": [],
            }
        ),
        encoding="utf-8",
    )
    (project_dir / "app").mkdir(parents=True, exist_ok=True)
    (project_dir / "app" / "main.py").write_text("from fastapi import FastAPI\napp = FastAPI()\n", encoding="utf-8")
    (project_dir / "requirements.txt").write_text("fastapi\n", encoding="utf-8")
    (project_dir / "frontend").mkdir(parents=True, exist_ok=True)
    (project_dir / "frontend" / ".env.local").write_text("NEXT_PUBLIC_API_BASE_URL=http://127.0.0.1:8000\n", encoding="utf-8")
    (project_dir / ".env").write_text(
        "APP_PORT=8000\nBACKEND_BASE_URL=http://127.0.0.1:8000\nCORS_ALLOW_ORIGINS=http://localhost:3000\n",
        encoding="utf-8",
    )
    (archmind / "state.json").write_text(json.dumps({"runtime": {"backend_status": "RUNNING", "failure_class": ""}}), encoding="utf-8")
    monkeypatch.setattr("archmind.telegram_bot._resolve_target_project", lambda: project_dir)
    monkeypatch.setattr(
        "archmind.telegram_bot.detect_backend_runtime_entry",
        lambda _p, port=8000: {"ok": True, "backend_entry": "app.main:app", "backend_run_mode": "asgi-direct"},
    )

    next_msg = DummyMessage()
    asyncio.run(command_next(DummyUpdate(message=next_msg, effective_chat=DummyChat()), DummyContext()))
    next_out = next_msg.sent[-1]
    analysis = telegram_bot._build_project_analysis(project_dir)
    next_action = analysis.get("next_action") if isinstance(analysis.get("next_action"), dict) else {}
    expected_message = str(next_action.get("message") or "").strip()
    expected_command = str(next_action.get("command") or "").strip()
    assert expected_message in next_out
    if expected_command:
        assert f"Command: {expected_command}" in next_out

    improve_msg = DummyMessage()
    asyncio.run(command_improve(DummyUpdate(message=improve_msg, effective_chat=DummyChat()), DummyContext()))
    improve_out = improve_msg.sent[-1]
    assert "Add a page for Note" in improve_out
    assert "/add_page notes/list" in improve_out


def test_spec_progression_stage4_next_and_improve_not_overly_noisy(tmp_path: Path, monkeypatch) -> None:
    project_dir = tmp_path / "progress_stage4"
    archmind = project_dir / ".archmind"
    archmind.mkdir(parents=True, exist_ok=True)
    (archmind / "project_spec.json").write_text(
        json.dumps(
            {
                "shape": "fullstack",
                "template": "fullstack-ddd",
                "entities": [
                    {
                        "name": "Note",
                        "fields": [
                            {"name": "title", "type": "string"},
                            {"name": "description", "type": "string"},
                            {"name": "created_at", "type": "datetime"},
                            {"name": "updated_at", "type": "datetime"},
                        ],
                    }
                ],
                "api_endpoints": ["GET /notes", "POST /notes", "GET /notes/{id}", "DELETE /notes/{id}", "PUT /notes/{id}"],
                "frontend_pages": ["notes/list", "notes/detail"],
            }
        ),
        encoding="utf-8",
    )
    (project_dir / "app").mkdir(parents=True, exist_ok=True)
    (project_dir / "app" / "main.py").write_text("from fastapi import FastAPI\napp = FastAPI()\n", encoding="utf-8")
    (project_dir / "requirements.txt").write_text("fastapi\n", encoding="utf-8")
    (project_dir / "frontend").mkdir(parents=True, exist_ok=True)
    (project_dir / "frontend" / ".env.local").write_text("NEXT_PUBLIC_API_BASE_URL=http://127.0.0.1:8000\n", encoding="utf-8")
    (project_dir / ".env").write_text(
        "APP_PORT=8000\nBACKEND_BASE_URL=http://127.0.0.1:8000\nCORS_ALLOW_ORIGINS=http://localhost:3000\n",
        encoding="utf-8",
    )
    (archmind / "state.json").write_text(json.dumps({"runtime": {"backend_status": "RUNNING", "failure_class": ""}}), encoding="utf-8")
    monkeypatch.setattr("archmind.telegram_bot._resolve_target_project", lambda: project_dir)
    monkeypatch.setattr(
        "archmind.telegram_bot.detect_backend_runtime_entry",
        lambda _p, port=8000: {"ok": True, "backend_entry": "app.main:app", "backend_run_mode": "asgi-direct"},
    )

    next_msg = DummyMessage()
    asyncio.run(command_next(DummyUpdate(message=next_msg, effective_chat=DummyChat()), DummyContext()))
    assert "No immediate next action." in next_msg.sent[-1]

    improve_msg = DummyMessage()
    asyncio.run(command_improve(DummyUpdate(message=improve_msg, effective_chat=DummyChat()), DummyContext()))
    improve_out = improve_msg.sent[-1]
    assert "Define your first entity" not in improve_out
    assert "Add fields to" not in improve_out
    assert "Add an API for" not in improve_out
    assert "Add a page for" not in improve_out


def test_next_command_without_selected_project_shows_error(monkeypatch) -> None:
    monkeypatch.setattr("archmind.telegram_bot._resolve_target_project", lambda: None)
    msg = DummyMessage()
    asyncio.run(command_next(DummyUpdate(message=msg, effective_chat=DummyChat()), DummyContext()))
    out = msg.sent[-1]
    assert "No active project." in out
    assert "1. /design <idea>" in out
    assert "2. /plan <idea>" in out
    assert "3. /idea_local <idea>" in out


def test_improve_command_reports_missing_entities_as_actionable_gap(tmp_path: Path, monkeypatch) -> None:
    project_dir = tmp_path / "improve_missing_entities"
    archmind = project_dir / ".archmind"
    archmind.mkdir(parents=True, exist_ok=True)
    (project_dir / "app").mkdir(parents=True, exist_ok=True)
    (project_dir / "app" / "main.py").write_text("from fastapi import FastAPI\napp = FastAPI()\n", encoding="utf-8")
    (project_dir / "requirements.txt").write_text("fastapi\n", encoding="utf-8")
    (archmind / "project_spec.json").write_text(
        json.dumps(
            {
                "shape": "backend",
                "template": "fastapi",
                "modules": [],
                "entities": [],
                "api_endpoints": [],
                "frontend_pages": [],
            }
        ),
        encoding="utf-8",
    )
    (archmind / "state.json").write_text(json.dumps({"runtime": {"backend_status": "RUNNING", "failure_class": ""}}), encoding="utf-8")
    monkeypatch.setattr(
        "archmind.telegram_bot.detect_backend_runtime_entry",
        lambda _p, port=8000: {"ok": True, "backend_entry": "app.main:app", "backend_run_mode": "asgi-direct"},
    )
    monkeypatch.setattr("archmind.telegram_bot._resolve_target_project", lambda: project_dir)

    msg = DummyMessage()
    asyncio.run(command_improve(DummyUpdate(message=msg, effective_chat=DummyChat()), DummyContext()))
    out = msg.sent[-1]
    assert "Define your first entity" in out
    assert "/add_entity Note" in out


def test_improve_command_reports_entity_without_fields(tmp_path: Path, monkeypatch) -> None:
    project_dir = tmp_path / "improve_missing_fields"
    archmind = project_dir / ".archmind"
    archmind.mkdir(parents=True, exist_ok=True)
    (project_dir / "app").mkdir(parents=True, exist_ok=True)
    (project_dir / "app" / "main.py").write_text("from fastapi import FastAPI\napp = FastAPI()\n", encoding="utf-8")
    (project_dir / "requirements.txt").write_text("fastapi\n", encoding="utf-8")
    (archmind / "project_spec.json").write_text(
        json.dumps(
            {
                "shape": "backend",
                "template": "fastapi",
                "modules": [],
                "entities": [{"name": "Note", "fields": []}],
                "api_endpoints": [],
                "frontend_pages": [],
            }
        ),
        encoding="utf-8",
    )
    (archmind / "state.json").write_text(json.dumps({"runtime": {"backend_status": "RUNNING", "failure_class": ""}}), encoding="utf-8")
    monkeypatch.setattr(
        "archmind.telegram_bot.detect_backend_runtime_entry",
        lambda _p, port=8000: {"ok": True, "backend_entry": "app.main:app", "backend_run_mode": "asgi-direct"},
    )
    monkeypatch.setattr("archmind.telegram_bot._resolve_target_project", lambda: project_dir)

    msg = DummyMessage()
    asyncio.run(command_improve(DummyUpdate(message=msg, effective_chat=DummyChat()), DummyContext()))
    out = msg.sent[-1]
    assert "Add fields to Note" in out
    assert "/add_field Note title:string" in out


def test_improve_command_reports_missing_api_and_pages(tmp_path: Path, monkeypatch) -> None:
    project_dir = tmp_path / "improve_missing_api_pages"
    archmind = project_dir / ".archmind"
    archmind.mkdir(parents=True, exist_ok=True)
    (project_dir / "app").mkdir(parents=True, exist_ok=True)
    (project_dir / "app" / "main.py").write_text("from fastapi import FastAPI\napp = FastAPI()\n", encoding="utf-8")
    (project_dir / "requirements.txt").write_text("fastapi\n", encoding="utf-8")
    (project_dir / "frontend").mkdir(parents=True, exist_ok=True)
    (archmind / "project_spec.json").write_text(
        json.dumps(
            {
                "shape": "fullstack",
                "template": "fullstack-ddd",
                "modules": [],
                "entities": [{"name": "Note", "fields": [{"name": "title", "type": "string"}]}],
                "api_endpoints": [],
                "frontend_pages": [],
            }
        ),
        encoding="utf-8",
    )
    (archmind / "state.json").write_text(json.dumps({"runtime": {"backend_status": "RUNNING", "failure_class": ""}}), encoding="utf-8")
    monkeypatch.setattr(
        "archmind.telegram_bot.detect_backend_runtime_entry",
        lambda _p, port=8000: {"ok": True, "backend_entry": "app.main:app", "backend_run_mode": "asgi-direct"},
    )
    monkeypatch.setattr("archmind.telegram_bot._resolve_target_project", lambda: project_dir)

    msg = DummyMessage()
    asyncio.run(command_improve(DummyUpdate(message=msg, effective_chat=DummyChat()), DummyContext()))
    out = msg.sent[-1]
    assert "Add an API for Note" in out
    assert "/add_api GET /notes" in out


def test_plan_command_from_idea_includes_phases() -> None:
    msg = DummyMessage()
    update = DummyUpdate(message=msg, effective_chat=DummyChat())
    asyncio.run(command_plan(update, DummyContext(args=["defect", "tracker", "dashboard"])))
    out = msg.sent[-1]
    assert "Development plan" in out
    assert "Phase 1 - Core entities" in out
    assert "Phase 2 - Core fields" in out
    assert "Phase 3 - APIs" in out
    assert "Phase 4 - Frontend" in out
    reply_markup = msg.sent_kwargs[-1].get("reply_markup")
    assert reply_markup is not None
    buttons = [btn for row in getattr(reply_markup, "inline_keyboard", []) for btn in row]
    assert any(str(getattr(btn, "callback_data", "")).startswith("generate|") for btn in buttons)


def test_design_command_includes_plan_and_generate_buttons() -> None:
    msg = DummyMessage()
    update = DummyUpdate(message=msg, effective_chat=DummyChat())
    asyncio.run(command_design(update, DummyContext(args=["defect", "tracker"])))
    reply_markup = msg.sent_kwargs[-1].get("reply_markup")
    assert reply_markup is not None
    buttons = [btn for row in getattr(reply_markup, "inline_keyboard", []) for btn in row]
    callback_values = [str(getattr(btn, "callback_data", "")) for btn in buttons]
    assert any(val.startswith("plan|") for val in callback_values)
    assert any(val.startswith("generate|") for val in callback_values)


def test_plan_command_from_current_project_works_and_limits_steps(tmp_path: Path, monkeypatch) -> None:
    project_dir = tmp_path / "task_tracker"
    archmind = project_dir / ".archmind"
    archmind.mkdir(parents=True, exist_ok=True)
    entities = [{"name": f"Entity{i}", "fields": [{"name": "name", "type": "string"}]} for i in range(20)]
    (archmind / "project_spec.json").write_text(
        json.dumps(
            {
                "shape": "fullstack",
                "domains": ["tasks"],
                "template": "fullstack-ddd",
                "modules": ["auth", "dashboard"],
                "entities": entities,
                "api_endpoints": [],
                "frontend_pages": [],
                "reason_summary": "demo",
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr("archmind.telegram_bot._resolve_target_project", lambda: project_dir)
    msg = DummyMessage()
    asyncio.run(command_plan(DummyUpdate(message=msg, effective_chat=DummyChat()), DummyContext()))
    out = msg.sent[-1]
    assert "Development plan" in out
    numbered = [line for line in out.splitlines() if line.startswith(tuple(str(i) + "." for i in range(1, 20)))]
    assert len(numbered) <= 15


def test_plan_command_saves_plan_execution_json_for_current_project(tmp_path: Path, monkeypatch) -> None:
    project_dir = tmp_path / "plan_save_proj"
    archmind = project_dir / ".archmind"
    archmind.mkdir(parents=True, exist_ok=True)
    (archmind / "project_spec.json").write_text(
        json.dumps(
            {
                "shape": "fullstack",
                "domains": ["tasks"],
                "template": "fullstack-ddd",
                "modules": ["auth", "db", "dashboard"],
                "entities": [{"name": "Task", "fields": []}],
                "api_endpoints": [],
                "frontend_pages": [],
                "reason_summary": "demo",
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr("archmind.telegram_bot._resolve_target_project", lambda: project_dir)

    msg = DummyMessage()
    asyncio.run(command_plan(DummyUpdate(message=msg, effective_chat=DummyChat()), DummyContext()))

    plan_path = archmind / "plan_execution.json"
    assert plan_path.exists()
    payload = json.loads(plan_path.read_text(encoding="utf-8"))
    assert isinstance(payload.get("phases"), list)
    assert payload["phases"]


def test_apply_plan_executes_supported_steps(tmp_path: Path, monkeypatch) -> None:
    project_dir = tmp_path / "apply_plan_proj"
    archmind = project_dir / ".archmind"
    (project_dir / "app").mkdir(parents=True, exist_ok=True)
    (project_dir / "frontend" / "app").mkdir(parents=True, exist_ok=True)
    (project_dir / "app" / "main.py").write_text(
        "from fastapi import FastAPI\n\napp = FastAPI()\n",
        encoding="utf-8",
    )
    archmind.mkdir(parents=True, exist_ok=True)
    (archmind / "project_spec.json").write_text(
        json.dumps(
            {
                "shape": "fullstack",
                "domains": ["defects"],
                "template": "fullstack-ddd",
                "modules": ["db", "dashboard"],
                "entities": [],
                "api_endpoints": [],
                "frontend_pages": [],
                "reason_summary": "demo",
                "evolution": {"version": 1, "added_modules": [], "history": []},
            }
        ),
        encoding="utf-8",
    )
    (archmind / "plan_execution.json").write_text(
        json.dumps(
            {
                "phases": [
                    {"title": "Core entities", "steps": ["/add_entity Defect"]},
                    {"title": "Core fields", "steps": ["/add_field Defect title:string"]},
                    {"title": "APIs", "steps": ["/add_api GET /reports"]},
                    {"title": "Frontend", "steps": ["/add_page reports/list"]},
                ]
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr("archmind.telegram_bot._resolve_target_project", lambda: project_dir)

    msg = DummyMessage()
    asyncio.run(command_apply_plan(DummyUpdate(message=msg, effective_chat=DummyChat()), DummyContext()))
    out = msg.sent[-1]
    assert "Applying development plan..." in out
    assert "Plan execution complete." in out
    assert "Success: 4" in out
    assert "Failed: 0" in out

    spec = json.loads((archmind / "project_spec.json").read_text(encoding="utf-8"))
    assert any(str(e.get("name")) == "Defect" for e in (spec.get("entities") or []))
    defect = [e for e in (spec.get("entities") or []) if str(e.get("name")) == "Defect"][0]
    assert any(str(f.get("name")) == "title" and str(f.get("type")) == "string" for f in (defect.get("fields") or []))
    assert "GET /reports" in (spec.get("api_endpoints") or [])
    assert "reports/list" in (spec.get("frontend_pages") or [])


def test_apply_plan_continues_after_failed_step_and_tracks_skip(tmp_path: Path, monkeypatch) -> None:
    project_dir = tmp_path / "apply_plan_fail_continue"
    archmind = project_dir / ".archmind"
    (project_dir / "app").mkdir(parents=True, exist_ok=True)
    (project_dir / "app" / "main.py").write_text(
        "from fastapi import FastAPI\n\napp = FastAPI()\n",
        encoding="utf-8",
    )
    archmind.mkdir(parents=True, exist_ok=True)
    (archmind / "project_spec.json").write_text(
        json.dumps(
            {
                "shape": "backend",
                "domains": ["tasks"],
                "template": "fastapi",
                "modules": [],
                "entities": [],
                "api_endpoints": [],
                "frontend_pages": [],
                "reason_summary": "demo",
            }
        ),
        encoding="utf-8",
    )
    (archmind / "plan_execution.json").write_text(
        json.dumps(
            {
                "phases": [
                    {"title": "Bad", "steps": ["/add_field UnknownEntity title:string"]},
                    {"title": "Skip", "steps": ["/unknown_command something"]},
                    {"title": "Good", "steps": ["/add_entity Task"]},
                ]
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr("archmind.telegram_bot._resolve_target_project", lambda: project_dir)

    msg = DummyMessage()
    asyncio.run(command_apply_plan(DummyUpdate(message=msg, effective_chat=DummyChat()), DummyContext()))
    out = msg.sent[-1]
    assert "✗ FAILED" in out
    assert "~ SKIPPED" in out
    assert "Success: 1" in out
    assert "Skipped: 1" in out
    assert "Failed: 1" in out

    spec = json.loads((archmind / "project_spec.json").read_text(encoding="utf-8"))
    assert any(str(e.get("name")) == "Task" for e in (spec.get("entities") or []))


def test_apply_plan_without_project_shows_error(monkeypatch) -> None:
    monkeypatch.setattr("archmind.telegram_bot._resolve_target_project", lambda: None)
    msg = DummyMessage()
    asyncio.run(command_apply_plan(DummyUpdate(message=msg, effective_chat=DummyChat()), DummyContext()))
    out = msg.sent[-1]
    assert "No active project." in out
    assert "To execute a development plan" in out
    assert "/design <idea>" in out
    assert "/plan <idea>" in out
    assert "/idea_local <idea>" in out
    assert "/projects" in out
    assert "2. /use <n>" in out
    assert "/apply_plan" in out


def test_apply_plan_without_saved_plan_shows_error(tmp_path: Path, monkeypatch) -> None:
    project_dir = tmp_path / "apply_plan_no_file"
    (project_dir / ".archmind").mkdir(parents=True, exist_ok=True)
    (project_dir / ".archmind" / "project_spec.json").write_text(
        json.dumps({"shape": "backend", "domains": [], "template": "fastapi", "modules": []}),
        encoding="utf-8",
    )
    monkeypatch.setattr("archmind.telegram_bot._resolve_target_project", lambda: project_dir)
    msg = DummyMessage()
    asyncio.run(command_apply_plan(DummyUpdate(message=msg, effective_chat=DummyChat()), DummyContext()))
    assert msg.sent[-1] == "No saved plan available.\n\nRun:\n- /plan <idea>\nor\n- /plan"

def test_plan_command_without_project_shows_error(monkeypatch) -> None:
    monkeypatch.setattr("archmind.telegram_bot._resolve_target_project", lambda: None)
    msg = DummyMessage()
    asyncio.run(command_plan(DummyUpdate(message=msg, effective_chat=DummyChat()), DummyContext()))
    out = msg.sent[-1]
    assert "No active project." in out
    assert "1. /design <idea>" in out
    assert "1. /projects" in out


def test_help_topic_idea() -> None:
    msg = DummyMessage()
    update = DummyUpdate(message=msg, effective_chat=DummyChat())
    asyncio.run(command_help(update, DummyContext(args=["idea"])))
    out = msg.sent[-1]
    assert "/idea <idea>" in out
    assert "Generate a new project from an idea." in out
    assert "/idea simple notes api with fastapi" in out


def test_help_topic_deploy() -> None:
    msg = DummyMessage()
    update = DummyUpdate(message=msg, effective_chat=DummyChat())
    asyncio.run(command_help(update, DummyContext(args=["deploy"])))
    out = msg.sent[-1]
    assert "/deploy local" in out
    assert "/deploy railway" in out


def test_help_text_includes_run_backend_command() -> None:
    msg = DummyMessage()
    update = DummyUpdate(message=msg, effective_chat=DummyChat())
    asyncio.run(command_help(update, DummyContext()))
    out = msg.sent[-1]
    assert "/run backend" in out


def test_idea_local_starts_pipeline_with_auto_deploy_local(monkeypatch, tmp_path: Path) -> None:
    project_dir = tmp_path / "20260315_auto_local"
    log_path = tmp_path / "20260315_auto_local.telegram.log"
    captured: dict[str, object] = {}

    class DummyProc:
        pid = 31337

    def fake_start_pipeline_process(cmd, base_dir, project_name):  # type: ignore[no-untyped-def]
        captured["cmd"] = cmd
        captured["base_dir"] = base_dir
        captured["project_name"] = project_name
        return DummyProc(), log_path

    monkeypatch.setattr("archmind.telegram_bot.resolve_base_dir", lambda: tmp_path)
    monkeypatch.setattr("archmind.telegram_bot.planned_project_dir", lambda *_a, **_k: project_dir)
    monkeypatch.setattr("archmind.telegram_bot.start_pipeline_process", fake_start_pipeline_process)

    msg = DummyMessage()
    update = DummyUpdate(message=msg, effective_chat=DummyChat())
    ctx = DummyContext(args=["build", "notes", "app"], application=None)
    asyncio.run(command_idea_local(update, ctx))

    cmd = captured["cmd"]
    assert isinstance(cmd, list)
    assert "--auto-deploy" in cmd
    assert "--deploy-target" in cmd
    assert cmd[cmd.index("--deploy-target") + 1] == "local"
    assert "command=/idea_local" in msg.sent[-1]
    assert "auto_deploy=local" in msg.sent[-1]
    reply_markup = msg.sent_kwargs[-1].get("reply_markup")
    assert reply_markup is not None
    buttons = [btn for row in getattr(reply_markup, "inline_keyboard", []) for btn in row]
    assert any(str(getattr(btn, "text", "")).startswith("NEXT (for 20260315_auto_local)") for btn in buttons)
    assert any(str(getattr(btn, "callback_data", "")) == "next|20260315_auto_local" for btn in buttons)


def test_unknown_command_returns_guidance_message() -> None:
    msg = DummyMessage()
    update = DummyUpdate(message=msg, effective_chat=DummyChat())
    asyncio.run(command_unknown(update, DummyContext(args=["oops"])))
    out = msg.sent[-1]
    assert "알 수 없는 명령어입니다." in out
    assert "/help" in out
    assert "/design {아이디어}" in out
    assert "/plan {아이디어}" in out
    assert "/idea_local {아이디어}" in out
    assert "/inspect" in out
    assert "/next" in out


def test_deploy_without_selected_project_shows_message(monkeypatch) -> None:
    monkeypatch.setattr("archmind.telegram_bot.load_last_project_path", lambda: None)
    msg = DummyMessage()
    update = DummyUpdate(message=msg, effective_chat=DummyChat())
    asyncio.run(command_deploy(update, DummyContext()))
    assert msg.sent
    assert msg.sent[-1] == "No project selected. Use /projects then /use <n>."


def test_deploy_uses_current_project_selection(monkeypatch, tmp_path: Path) -> None:
    current = tmp_path / "current_for_deploy"
    other = tmp_path / "other_for_deploy"
    current.mkdir(parents=True, exist_ok=True)
    other.mkdir(parents=True, exist_ok=True)
    set_current_project(current)
    monkeypatch.setattr("archmind.telegram_bot.load_last_project_path", lambda: other)

    used_paths: list[Path] = []

    def fake_deploy(project_dir, target="railway", allow_real_deploy=False):  # type: ignore[no-untyped-def]
        used_paths.append(project_dir)
        assert target == "railway"
        assert allow_real_deploy is False
        return {
            "ok": True,
            "target": "railway",
            "mode": "mock",
            "status": "SUCCESS",
            "url": "https://example.up.railway.app",
            "detail": "mock deploy success",
        }

    monkeypatch.setattr("archmind.telegram_bot.update_after_deploy", lambda *a, **k: {})
    monkeypatch.setattr("archmind.deploy.deploy_project", fake_deploy)

    msg = DummyMessage()
    update = DummyUpdate(message=msg, effective_chat=DummyChat())
    asyncio.run(command_deploy(update, DummyContext()))
    assert used_paths == [current]
    assert "Project:\ncurrent_for_deploy" in msg.sent[-1]


def test_deploy_output_includes_target_status_url(monkeypatch, tmp_path: Path) -> None:
    project = tmp_path / "deploy_msg_proj"
    project.mkdir(parents=True, exist_ok=True)
    set_current_project(project)

    monkeypatch.setattr(
        "archmind.deploy.deploy_project",
        lambda *a, **k: {
            "ok": True,
            "target": "railway",
            "mode": "mock",
            "status": "SUCCESS",
            "url": "https://example.up.railway.app",
            "detail": "mock deploy success",
        },
    )
    monkeypatch.setattr("archmind.telegram_bot.update_after_deploy", lambda *a, **k: {})

    msg = DummyMessage()
    update = DummyUpdate(message=msg, effective_chat=DummyChat())
    asyncio.run(command_deploy(update, DummyContext(args=["railway"])))
    out = msg.sent[-1]
    assert "Target:\nrailway" in out
    assert "Mode: mock" in out
    assert "Status:\nSUCCESS" in out
    assert "Deploy URL:\nhttps://example.up.railway.app" in out


def test_deploy_parses_real_flag(monkeypatch, tmp_path: Path) -> None:
    project = tmp_path / "deploy_real_proj"
    project.mkdir(parents=True, exist_ok=True)
    set_current_project(project)

    captured: dict[str, object] = {}

    def fake_deploy(project_dir, target="railway", allow_real_deploy=False):  # type: ignore[no-untyped-def]
        captured["project_dir"] = project_dir
        captured["target"] = target
        captured["allow_real_deploy"] = allow_real_deploy
        return {
            "ok": True,
            "target": "railway",
            "mode": "real",
            "status": "SUCCESS",
            "url": "https://real-demo.up.railway.app",
            "detail": "railway deploy success",
            "healthcheck_url": "https://real-demo.up.railway.app/health",
            "healthcheck_status": "SUCCESS",
            "healthcheck_detail": "health endpoint returned status ok",
            "backend_smoke_url": "https://real-demo.up.railway.app/health",
            "backend_smoke_status": "SUCCESS",
            "backend_smoke_detail": "health endpoint returned status ok",
            "frontend_smoke_url": "",
            "frontend_smoke_status": "SKIPPED",
            "frontend_smoke_detail": "frontend not deployed",
        }

    monkeypatch.setattr("archmind.deploy.deploy_project", fake_deploy)
    monkeypatch.setattr("archmind.telegram_bot.update_after_deploy", lambda *a, **k: {})

    msg = DummyMessage()
    update = DummyUpdate(message=msg, effective_chat=DummyChat())
    asyncio.run(command_deploy(update, DummyContext(args=["railway", "real"])))
    out = msg.sent[-1]

    assert captured["allow_real_deploy"] is True
    assert "Mode: real" in out
    assert "Deploy URL:\nhttps://real-demo.up.railway.app" in out
    assert "Health check:\nSUCCESS" in out
    assert "Health URL:\nhttps://real-demo.up.railway.app/health" in out
    assert "Backend smoke:\nSUCCESS" in out


def test_telegram_deploy_fullstack_output_sections(monkeypatch, tmp_path: Path) -> None:
    project = tmp_path / "deploy_fullstack_proj"
    project.mkdir(parents=True, exist_ok=True)
    set_current_project(project)

    monkeypatch.setattr(
        "archmind.deploy.deploy_project",
        lambda *a, **k: {
            "ok": True,
            "target": "railway",
            "mode": "mock",
            "kind": "fullstack",
            "status": "SUCCESS",
            "url": "https://web-example.up.railway.app",
            "detail": "mock fullstack deploy success",
            "backend": {
                "status": "SUCCESS",
                "url": "https://api-example.up.railway.app",
                "detail": "mock backend deploy success",
            },
            "frontend": {
                "status": "SUCCESS",
                "url": "https://web-example.up.railway.app",
                "detail": "mock frontend deploy success",
            },
            "backend_smoke_url": "",
            "backend_smoke_status": "SKIPPED",
            "backend_smoke_detail": "mock deploy mode",
            "frontend_smoke_url": "",
            "frontend_smoke_status": "SKIPPED",
            "frontend_smoke_detail": "mock deploy mode",
        },
    )
    monkeypatch.setattr("archmind.telegram_bot.update_after_deploy", lambda *a, **k: {})

    msg = DummyMessage()
    update = DummyUpdate(message=msg, effective_chat=DummyChat())
    asyncio.run(command_deploy(update, DummyContext(args=["railway"])))
    out = msg.sent[-1]
    assert "Kind:\nfullstack" in out
    assert "Backend:\nSUCCESS" in out
    assert "https://api-example.up.railway.app" in out
    assert "Backend smoke:\nSKIPPED" in out
    assert "Frontend:\nSUCCESS" in out
    assert "https://web-example.up.railway.app" in out
    assert "Frontend smoke:\nSKIPPED" in out


def test_telegram_real_fullstack_shows_real_frontend_deploy_result(monkeypatch, tmp_path: Path) -> None:
    project = tmp_path / "deploy_fullstack_real_proj"
    project.mkdir(parents=True, exist_ok=True)
    set_current_project(project)

    monkeypatch.setattr(
        "archmind.deploy.deploy_project",
        lambda *a, **k: {
            "ok": True,
            "target": "railway",
            "mode": "real",
            "kind": "fullstack",
            "status": "SUCCESS",
            "url": "https://web-real.up.railway.app",
            "detail": "fullstack deploy completed",
            "backend": {
                "status": "SUCCESS",
                "url": "https://api-real.up.railway.app",
                "detail": "railway deploy success",
            },
            "frontend": {
                "status": "SUCCESS",
                "url": "https://web-real.up.railway.app",
                "detail": "real frontend deploy success",
            },
            "healthcheck_url": "https://api-real.up.railway.app/health",
            "healthcheck_status": "SUCCESS",
            "healthcheck_detail": "health endpoint returned status ok",
            "backend_smoke_url": "https://api-real.up.railway.app/health",
            "backend_smoke_status": "SUCCESS",
            "backend_smoke_detail": "health endpoint returned status ok",
            "frontend_smoke_url": "https://web-real.up.railway.app",
            "frontend_smoke_status": "SUCCESS",
            "frontend_smoke_detail": "frontend URL returned HTTP 200",
        },
    )
    monkeypatch.setattr("archmind.telegram_bot.update_after_deploy", lambda *a, **k: {})

    msg = DummyMessage()
    update = DummyUpdate(message=msg, effective_chat=DummyChat())
    asyncio.run(command_deploy(update, DummyContext(args=["railway", "real"])))
    out = msg.sent[-1]
    assert "Mode: real" in out
    assert "Kind:\nfullstack" in out
    assert "Frontend:\nSUCCESS" in out
    assert "https://web-real.up.railway.app" in out
    assert "Backend smoke:\nSUCCESS" in out
    assert "Frontend smoke:\nSUCCESS" in out


def test_deploy_local_target_parses_and_displays(monkeypatch, tmp_path: Path) -> None:
    project = tmp_path / "deploy_local_proj"
    project.mkdir(parents=True, exist_ok=True)
    set_current_project(project)

    captured: dict[str, object] = {}

    def fake_deploy(project_dir, target="railway", allow_real_deploy=False):  # type: ignore[no-untyped-def]
        captured["project_dir"] = project_dir
        captured["target"] = target
        captured["allow_real_deploy"] = allow_real_deploy
        return {
            "ok": True,
            "target": "local",
            "mode": "real",
            "kind": "fullstack",
            "status": "SUCCESS",
            "url": "http://127.0.0.1:3011",
            "detail": "local fullstack deploy completed",
            "backend": {"status": "SUCCESS", "url": "http://127.0.0.1:8011", "detail": "local backend started"},
            "frontend": {"status": "SUCCESS", "url": "http://127.0.0.1:3011", "detail": "local frontend started"},
            "backend_smoke_url": "http://127.0.0.1:8011/health",
            "backend_smoke_status": "SUCCESS",
            "backend_smoke_detail": "health endpoint returned status ok",
            "frontend_smoke_url": "http://127.0.0.1:3011",
            "frontend_smoke_status": "SUCCESS",
            "frontend_smoke_detail": "frontend URL returned HTTP 200",
        }

    monkeypatch.setattr("archmind.deploy.deploy_project", fake_deploy)
    monkeypatch.setattr("archmind.telegram_bot.update_after_deploy", lambda *a, **k: {})

    msg = DummyMessage()
    update = DummyUpdate(message=msg, effective_chat=DummyChat())
    asyncio.run(command_deploy(update, DummyContext(args=["local"])))
    out = msg.sent[-1]

    assert captured["target"] == "local"
    assert "Target:\nlocal" in out
    assert "Backend:\nSUCCESS" in out
    assert "http://127.0.0.1:8011" in out
    assert "Frontend:\nSUCCESS" in out
    assert "http://127.0.0.1:3011" in out


def test_run_backend_without_selected_project_shows_message(monkeypatch) -> None:
    monkeypatch.setattr("archmind.telegram_bot.load_last_project_path", lambda: None)
    msg = DummyMessage()
    update = DummyUpdate(message=msg, effective_chat=DummyChat())
    asyncio.run(command_run(update, DummyContext(args=["backend"])))
    assert msg.sent
    assert msg.sent[-1] == "No project selected. Use /projects then /use <n>."


def test_run_backend_usage_validation(monkeypatch, tmp_path: Path) -> None:
    project = tmp_path / "run_usage_proj"
    project.mkdir(parents=True, exist_ok=True)
    set_current_project(project)
    msg = DummyMessage()
    update = DummyUpdate(message=msg, effective_chat=DummyChat())
    asyncio.run(command_run(update, DummyContext(args=[])))
    assert msg.sent[-1] == "Usage: /run backend|all"
    asyncio.run(command_run(update, DummyContext(args=["frontend"])))
    assert msg.sent[-1] == "Usage: /run backend|all"


def test_run_all_fullstack_runs_backend_and_frontend(monkeypatch, tmp_path: Path) -> None:
    project = tmp_path / "run_all_fullstack_proj"
    project.mkdir(parents=True, exist_ok=True)
    set_current_project(project)

    monkeypatch.setattr(
        "archmind.runtime_orchestrator.run_all_local_services",
        lambda _p: {
            "ok": True,
            "target": "local",
            "mode": "real",
            "kind": "fullstack",
            "status": "SUCCESS",
            "services": {
                "backend": {
                    "status": "RUNNING",
                    "pid": 20001,
                    "port": 8126,
                    "url": "http://127.0.0.1:8126",
                    "log_path": str(project / ".archmind" / "backend.log"),
                },
                "frontend": {
                    "status": "RUNNING",
                    "pid": 20002,
                    "port": 3011,
                    "url": "http://127.0.0.1:3011",
                    "log_path": str(project / ".archmind" / "frontend.log"),
                },
            },
            "backend_status": "RUNNING",
            "backend_pid": 20001,
            "backend_port": 8126,
            "backend_log_path": str(project / ".archmind" / "backend.log"),
            "frontend_status": "RUNNING",
            "frontend_pid": 20002,
            "frontend_port": 3011,
            "frontend_log_path": str(project / ".archmind" / "frontend.log"),
            "url": "http://127.0.0.1:8126",
            "detail": "services started",
            "failure_class": "",
        },
    )

    msg = DummyMessage()
    update = DummyUpdate(message=msg, effective_chat=DummyChat())
    asyncio.run(command_run(update, DummyContext(args=["all"])))
    out = msg.sent[-1]
    assert "Run all finished" in out
    assert "Backend:\nRUNNING" in out
    assert "Frontend:\nRUNNING" in out
    assert "Backend URL:\nhttp://127.0.0.1:8126" in out
    assert "Frontend URL:\nhttp://127.0.0.1:3011" in out

    state = telegram_bot.load_state(project) or {}
    runtime = state.get("runtime") if isinstance(state.get("runtime"), dict) else {}
    services = runtime.get("services") if isinstance(runtime.get("services"), dict) else {}
    frontend = services.get("frontend") if isinstance(services.get("frontend"), dict) else {}
    assert str(frontend.get("status") or "").upper() == "RUNNING"
    assert int(frontend.get("pid") or 0) == 20002


def test_run_all_backend_only_skips_frontend(monkeypatch, tmp_path: Path) -> None:
    project = tmp_path / "run_all_backend_only_proj"
    project.mkdir(parents=True, exist_ok=True)
    set_current_project(project)
    monkeypatch.setattr(
        "archmind.runtime_orchestrator.run_all_local_services",
        lambda _p: {
            "ok": True,
            "target": "local",
            "mode": "real",
            "kind": "backend",
            "status": "SUCCESS",
            "services": {
                "backend": {"status": "RUNNING", "pid": 21001, "port": 8130, "url": "http://127.0.0.1:8130", "log_path": ""},
                "frontend": {"status": "ABSENT", "pid": None, "port": None, "url": "", "log_path": ""},
            },
            "backend_status": "RUNNING",
            "backend_pid": 21001,
            "frontend_status": "ABSENT",
            "frontend_pid": None,
            "url": "http://127.0.0.1:8130",
            "detail": "services started",
            "failure_class": "",
        },
    )
    msg = DummyMessage()
    update = DummyUpdate(message=msg, effective_chat=DummyChat())
    asyncio.run(command_run(update, DummyContext(args=["all"])))
    out = msg.sent[-1]
    assert "Run all finished" in out
    assert "Backend:\nRUNNING" in out
    assert "Frontend:\nABSENT" in out


def test_run_backend_success_message_and_running_integration(monkeypatch, tmp_path: Path) -> None:
    project = tmp_path / "run_backend_ok_proj"
    project.mkdir(parents=True, exist_ok=True)
    set_current_project(project)

    monkeypatch.setattr(
        "archmind.deploy.get_local_runtime_status",
        lambda _p: {
            "backend": {"status": "NOT RUNNING", "pid": None, "url": ""},
            "frontend": {"status": "NOT RUNNING", "pid": None, "url": ""},
        },
    )
    monkeypatch.setattr(
        "archmind.deploy.run_backend_local_with_health",
        lambda _p: {
            "ok": True,
            "target": "local",
            "mode": "real",
            "kind": "backend",
            "status": "SUCCESS",
            "url": "http://127.0.0.1:8126",
            "detail": "local backend started",
            "backend_entry": "app.main:app",
            "backend_run_mode": "asgi-direct",
            "run_cwd": str(project / "backend"),
            "run_command": "uvicorn app.main:app --host 0.0.0.0 --port 8126",
            "backend_smoke_url": "http://127.0.0.1:8126/health",
            "backend_smoke_status": "SUCCESS",
            "backend_smoke_detail": "health endpoint returned status ok",
        },
    )
    monkeypatch.setattr("archmind.telegram_bot.update_after_deploy", lambda *a, **k: {})

    msg = DummyMessage()
    update = DummyUpdate(message=msg, effective_chat=DummyChat())
    asyncio.run(command_run(update, DummyContext(args=["backend"])))
    out = msg.sent[-1]
    assert "Run finished" in out
    assert "Backend:\nRUNNING" in out
    assert "Backend URL:\nhttp://127.0.0.1:8126" in out
    assert "Backend smoke:\nSUCCESS" in out
    assert "http://127.0.0.1:8126/health" in out
    assert "Detected backend target:\napp.main:app" in out
    assert "Run mode:\nasgi-direct" in out
    assert "Next:\n- /logs backend\n- /running\n- /restart" in out


def test_run_backend_failure_message(monkeypatch, tmp_path: Path) -> None:
    project = tmp_path / "run_backend_fail_proj"
    project.mkdir(parents=True, exist_ok=True)
    set_current_project(project)

    monkeypatch.setattr(
        "archmind.deploy.get_local_runtime_status",
        lambda _p: {
            "backend": {"status": "NOT RUNNING", "pid": None, "url": ""},
            "frontend": {"status": "NOT RUNNING", "pid": None, "url": ""},
        },
    )
    monkeypatch.setattr(
        "archmind.deploy.run_backend_local_with_health",
        lambda _p: {
            "ok": False,
            "target": "local",
            "mode": "real",
            "kind": "backend",
            "status": "FAIL",
            "url": "",
            "detail": "runtime-execution-error: health request failed",
            "failure_class": "runtime-execution-error",
            "backend_entry": "app.main:app",
            "run_cwd": str(project / "backend"),
            "run_command": "uvicorn app.main:app --host 0.0.0.0 --port 8127",
        },
    )
    monkeypatch.setattr("archmind.telegram_bot.update_after_deploy", lambda *a, **k: {})

    msg = DummyMessage()
    update = DummyUpdate(message=msg, effective_chat=DummyChat())
    asyncio.run(command_run(update, DummyContext(args=["backend"])))
    out = msg.sent[-1]
    assert "Run failed" in out
    assert "Backend:\nFAIL" in out
    assert "Failure class:\nruntime-execution-error" in out
    assert "Detected backend target:\napp.main:app" in out
    assert "Run command:\nuvicorn app.main:app --host 0.0.0.0 --port 8127" in out
    assert "Next:\n- /logs backend\n- /inspect" in out


def test_run_backend_success_message_after_auto_fix(monkeypatch, tmp_path: Path) -> None:
    project = tmp_path / "run_backend_autofix_ok_proj"
    project.mkdir(parents=True, exist_ok=True)
    set_current_project(project)

    monkeypatch.setattr(
        "archmind.deploy.get_local_runtime_status",
        lambda _p: {
            "backend": {"status": "NOT RUNNING", "pid": None, "url": ""},
            "frontend": {"status": "NOT RUNNING", "pid": None, "url": ""},
        },
    )
    monkeypatch.setattr(
        "archmind.deploy.run_backend_local_with_health",
        lambda _p: {
            "ok": True,
            "target": "local",
            "mode": "real",
            "kind": "backend",
            "status": "SUCCESS",
            "url": "http://127.0.0.1:8130",
            "detail": "local backend started",
            "backend_entry": "app.main:app",
            "backend_run_mode": "asgi-direct",
            "run_cwd": str(project / "backend"),
            "run_command": "uvicorn app.main:app --host 0.0.0.0 --port 8130",
            "backend_smoke_url": "http://127.0.0.1:8130/health",
            "backend_smoke_status": "SUCCESS",
            "backend_smoke_detail": "health endpoint returned status ok",
            "auto_fix": {
                "attempts": 1,
                "last_fix": "missing_dependency",
                "last_detail": "missing_dependency -> sqlmodel installed",
                "status": "SUCCESS",
            },
        },
    )

    msg = DummyMessage()
    update = DummyUpdate(message=msg, effective_chat=DummyChat())
    asyncio.run(command_run(update, DummyContext(args=["backend"])))
    out = msg.sent[-1]
    assert "Backend:\nRUNNING (after auto-fix)" in out
    assert "Fix applied:\nmissing_dependency -> sqlmodel installed" in out


def test_run_backend_failure_message_includes_auto_fix_attempts(monkeypatch, tmp_path: Path) -> None:
    project = tmp_path / "run_backend_autofix_fail_proj"
    project.mkdir(parents=True, exist_ok=True)
    set_current_project(project)

    monkeypatch.setattr(
        "archmind.deploy.get_local_runtime_status",
        lambda _p: {
            "backend": {"status": "NOT RUNNING", "pid": None, "url": ""},
            "frontend": {"status": "NOT RUNNING", "pid": None, "url": ""},
        },
    )
    monkeypatch.setattr(
        "archmind.deploy.run_backend_local_with_health",
        lambda _p: {
            "ok": False,
            "target": "local",
            "mode": "real",
            "kind": "backend",
            "status": "FAIL",
            "url": "",
            "detail": "runtime-execution-error: health request failed",
            "failure_class": "runtime-execution-error",
            "backend_entry": "app.main:app",
            "run_cwd": str(project / "backend"),
            "run_command": "uvicorn app.main:app --host 0.0.0.0 --port 8131",
            "auto_fix": {
                "attempts": 2,
                "last_fix": "env_missing",
                "last_detail": "runtime env defaults applied",
                "status": "FAILED",
            },
        },
    )

    msg = DummyMessage()
    update = DummyUpdate(message=msg, effective_chat=DummyChat())
    asyncio.run(command_run(update, DummyContext(args=["backend"])))
    out = msg.sent[-1]
    assert "Auto-fix attempts:\n2" in out
    assert "Last auto-fix:\nenv_missing" in out
    assert "Last error:\nruntime env defaults applied" in out


def test_run_backend_message_includes_preflight_status(monkeypatch, tmp_path: Path) -> None:
    project = tmp_path / "run_backend_preflight_proj"
    project.mkdir(parents=True, exist_ok=True)
    set_current_project(project)

    monkeypatch.setattr(
        "archmind.deploy.get_local_runtime_status",
        lambda _p: {
            "backend": {"status": "NOT RUNNING", "pid": None, "url": ""},
            "frontend": {"status": "NOT RUNNING", "pid": None, "url": ""},
        },
    )
    monkeypatch.setattr(
        "archmind.deploy.run_backend_local_with_health",
        lambda _p: {
            "ok": True,
            "target": "local",
            "mode": "real",
            "kind": "backend",
            "status": "SUCCESS",
            "url": "http://127.0.0.1:8135",
            "detail": "local backend started",
            "backend_entry": "app.main:app",
            "backend_run_mode": "asgi-direct",
            "run_cwd": str(project / "backend"),
            "run_command": "uvicorn app.main:app --host 0.0.0.0 --port 8135",
            "backend_smoke_url": "http://127.0.0.1:8135/health",
            "backend_smoke_status": "SUCCESS",
            "backend_smoke_detail": "health endpoint returned status ok",
            "preflight": {
                "status": "FIXED",
                "fixes_applied": ["installed requirements", "created .env defaults"],
                "issues_found": [],
            },
        },
    )

    msg = DummyMessage()
    update = DummyUpdate(message=msg, effective_chat=DummyChat())
    asyncio.run(command_run(update, DummyContext(args=["backend"])))
    out = msg.sent[-1]
    assert "Preflight:\nFIXED" in out
    assert "- installed requirements" in out
    assert "- created .env defaults" in out


def test_run_backend_skips_when_already_running(monkeypatch, tmp_path: Path) -> None:
    project = tmp_path / "run_backend_already_proj"
    project.mkdir(parents=True, exist_ok=True)
    set_current_project(project)
    monkeypatch.setattr(
        "archmind.deploy.get_local_runtime_status",
        lambda _p: {
            "backend": {"status": "RUNNING", "pid": 9999, "url": "http://127.0.0.1:8128"},
            "frontend": {"status": "NOT RUNNING", "pid": None, "url": ""},
        },
    )
    msg = DummyMessage()
    update = DummyUpdate(message=msg, effective_chat=DummyChat())
    asyncio.run(command_run(update, DummyContext(args=["backend"])))
    out = msg.sent[-1]
    assert "Run skipped" in out
    assert "Backend:\nRUNNING" in out
    assert "Backend URL:\nhttp://127.0.0.1:8128" in out


def test_stop_without_selected_project_shows_message(monkeypatch) -> None:
    monkeypatch.setattr("archmind.telegram_bot.load_last_project_path", lambda: None)
    msg = DummyMessage()
    update = DummyUpdate(message=msg, effective_chat=DummyChat())
    asyncio.run(command_stop(update, DummyContext()))
    assert msg.sent
    assert msg.sent[-1] == "No project selected. Use /projects then /use <n>."


def test_stop_all_does_not_require_selected_project(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr("archmind.telegram_bot.load_last_project_path", lambda: None)
    monkeypatch.setenv("ARCHMIND_PROJECTS_DIR", str(tmp_path))
    monkeypatch.setattr(
        "archmind.deploy.stop_all_local_services",
        lambda _root: {
            "ok": True,
            "counts": {"projects": 2, "stopped": 2, "already_stopped": 0, "failed": 0},
            "stopped": [
                {"project_name": "project_a", "backend_status": "STOPPED", "backend_pid": 1234, "frontend_status": "NOT RUNNING", "frontend_pid": None},
                {"project_name": "project_b", "backend_status": "STOPPED", "backend_pid": 5678, "frontend_status": "STOPPED", "frontend_pid": 5679},
            ],
            "already_stopped": [],
            "failed": [],
        },
    )
    msg = DummyMessage()
    update = DummyUpdate(message=msg, effective_chat=DummyChat())
    asyncio.run(command_stop(update, DummyContext(args=["all"])))
    out = msg.sent[-1]
    assert "All services stop finished" in out
    assert "- stopped: 2" in out
    assert "- already stopped: 0" in out
    assert "- failed: 0" in out
    assert "Failed:" not in out


def test_stop_local_stops_services_and_prints_status(monkeypatch, tmp_path: Path) -> None:
    project = tmp_path / "stop_local_proj"
    project.mkdir(parents=True, exist_ok=True)
    set_current_project(project)

    monkeypatch.setattr(
        "archmind.deploy.stop_local_services",
        lambda _p: {
            "ok": True,
            "target": "local",
            "backend": {"status": "STOPPED", "pid": 12001, "detail": ""},
            "frontend": {"status": "STOPPED", "pid": 13001, "detail": ""},
        },
    )

    msg = DummyMessage()
    update = DummyUpdate(message=msg, effective_chat=DummyChat())
    asyncio.run(command_stop(update, DummyContext()))
    out = msg.sent[-1]
    assert "Local services stopped" in out
    assert "Project:\nstop_local_proj" in out
    assert "Backend:\nSTOPPED" in out
    assert "Frontend:\nSTOPPED" in out
    assert "Backend detail:" not in out
    assert "Frontend detail:" not in out


def test_stop_local_when_not_running(monkeypatch, tmp_path: Path) -> None:
    project = tmp_path / "stop_none_proj"
    project.mkdir(parents=True, exist_ok=True)
    set_current_project(project)

    monkeypatch.setattr(
        "archmind.deploy.stop_local_services",
        lambda _p: {
            "ok": True,
            "target": "local",
            "backend": {"status": "NOT RUNNING", "pid": None, "detail": ""},
            "frontend": {"status": "NOT RUNNING", "pid": None, "detail": ""},
        },
    )

    msg = DummyMessage()
    update = DummyUpdate(message=msg, effective_chat=DummyChat())
    asyncio.run(command_stop(update, DummyContext(args=["local"])))
    out = msg.sent[-1]
    assert "Backend:\nNOT RUNNING" in out
    assert "Frontend:\nNOT RUNNING" in out


def test_stop_all_includes_already_stopped_and_failed(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setenv("ARCHMIND_PROJECTS_DIR", str(tmp_path))
    monkeypatch.setattr("archmind.telegram_bot.load_last_project_path", lambda: None)
    monkeypatch.setattr(
        "archmind.deploy.stop_all_local_services",
        lambda _root: {
            "ok": False,
            "counts": {"projects": 3, "stopped": 1, "already_stopped": 1, "failed": 1},
            "stopped": [{"project_name": "project_a", "backend_status": "STOPPED", "backend_pid": 1001, "frontend_status": "NOT RUNNING", "frontend_pid": None}],
            "already_stopped": [{"project_name": "project_b"}],
            "failed": [{"project_name": "project_c", "backend_detail": "permission denied", "frontend_detail": ""}],
        },
    )
    msg = DummyMessage()
    update = DummyUpdate(message=msg, effective_chat=DummyChat())
    asyncio.run(command_stop(update, DummyContext(args=["all"])))
    out = msg.sent[-1]
    assert "- stopped: 1" in out
    assert "- already stopped: 1" in out
    assert "- failed: 1" in out
    assert "Failed:" in out
    assert "- project_c: permission denied" in out


def test_stop_local_includes_warning_section_when_present(monkeypatch, tmp_path: Path) -> None:
    project = tmp_path / "stop_warning_proj"
    project.mkdir(parents=True, exist_ok=True)
    set_current_project(project)

    monkeypatch.setattr(
        "archmind.deploy.stop_local_services",
        lambda _p: {
            "ok": True,
            "target": "local",
            "warnings": ["backend process lingered briefly but service is down"],
            "backend": {"status": "STOPPED", "pid": 12001, "detail": ""},
            "frontend": {"status": "STOPPED", "pid": 13001, "detail": ""},
        },
    )

    msg = DummyMessage()
    update = DummyUpdate(message=msg, effective_chat=DummyChat())
    asyncio.run(command_stop(update, DummyContext()))
    out = msg.sent[-1]
    assert "Warnings:" in out
    assert "- backend process lingered briefly but service is down" in out


def test_restart_without_selected_project_shows_message(monkeypatch) -> None:
    monkeypatch.setattr("archmind.telegram_bot.load_last_project_path", lambda: None)
    msg = DummyMessage()
    update = DummyUpdate(message=msg, effective_chat=DummyChat())
    asyncio.run(command_restart(update, DummyContext()))
    assert msg.sent
    assert msg.sent[-1] == "No project selected. Use /projects then /use <n>."


def test_restart_local_restarts_services_and_displays_urls(monkeypatch, tmp_path: Path) -> None:
    project = tmp_path / "restart_local_proj"
    project.mkdir(parents=True, exist_ok=True)
    set_current_project(project)
    monkeypatch.setattr(
        "archmind.deploy.restart_local_services",
        lambda _p: {
            "ok": True,
            "target": "local",
            "backend": {"status": "RESTARTED", "url": "http://127.0.0.1:8011", "detail": ""},
            "frontend": {"status": "RESTARTED", "url": "http://127.0.0.1:3011", "detail": ""},
        },
    )
    monkeypatch.setattr(
        "archmind.deploy.get_local_runtime_status",
        lambda _p: {
            "backend": {"status": "RUNNING", "url": "http://127.0.0.1:8011"},
            "frontend": {"status": "RUNNING", "url": "http://127.0.0.1:3011"},
        },
    )
    msg = DummyMessage()
    update = DummyUpdate(message=msg, effective_chat=DummyChat())
    asyncio.run(command_restart(update, DummyContext(args=["local"])))
    out = msg.sent[-1]
    assert "Restart result" in out
    assert "Project:\nrestart_local_proj" in out
    assert "Backend:\nRUNNING" in out
    assert "Backend URL:\nhttp://127.0.0.1:8011" in out
    assert "http://127.0.0.1:8011" in out
    assert "Frontend:\nRUNNING" in out
    assert "Frontend URL:\nhttp://127.0.0.1:3011" in out
    assert "Frontend URL:\nhttp://127.0.0.1:8011" not in out
    assert "http://127.0.0.1:3011" in out
    assert "Next:\n- /running\n- /logs" in out


def test_restart_local_when_not_running(monkeypatch, tmp_path: Path) -> None:
    project = tmp_path / "restart_none_proj"
    project.mkdir(parents=True, exist_ok=True)
    set_current_project(project)
    monkeypatch.setattr(
        "archmind.deploy.restart_local_services",
        lambda _p: {
            "ok": True,
            "target": "local",
            "backend": {"status": "NOT RUNNING", "url": "", "detail": ""},
            "frontend": {"status": "NOT RUNNING", "url": "", "detail": ""},
        },
    )
    monkeypatch.setattr(
        "archmind.deploy.get_local_runtime_status",
        lambda _p: {
            "backend": {"status": "NOT RUNNING", "url": ""},
            "frontend": {"status": "NOT RUNNING", "url": ""},
        },
    )
    msg = DummyMessage()
    update = DummyUpdate(message=msg, effective_chat=DummyChat())
    asyncio.run(command_restart(update, DummyContext()))
    out = msg.sent[-1]
    assert "Restart result" in out
    assert "Backend:\nNOT RUNNING" in out
    assert "Frontend:\nNOT RUNNING" in out
    assert "Next:\n- /running\n- /logs" in out


def test_restart_local_shows_preflight_db_init_skip_without_failure(monkeypatch, tmp_path: Path) -> None:
    project = tmp_path / "restart_preflight_skip_proj"
    project.mkdir(parents=True, exist_ok=True)
    set_current_project(project)
    monkeypatch.setattr(
        "archmind.deploy.restart_local_services",
        lambda _p: {
            "ok": True,
            "target": "local",
            "backend": {"status": "RESTARTED", "url": "http://127.0.0.1:8012", "detail": "local backend started"},
            "frontend": {"status": "NOT RUNNING", "url": "", "detail": ""},
            "deploy": {
                "preflight": {
                    "status": "FIXED",
                    "fixes_applied": ["db init skipped (no explicit init command)"],
                    "issues_found": [],
                }
            },
        },
    )
    monkeypatch.setattr(
        "archmind.deploy.get_local_runtime_status",
        lambda _p: {
            "backend": {"status": "RUNNING", "url": "http://127.0.0.1:8012"},
            "frontend": {"status": "NOT RUNNING", "url": ""},
        },
    )
    msg = DummyMessage()
    update = DummyUpdate(message=msg, effective_chat=DummyChat())
    asyncio.run(command_restart(update, DummyContext(args=["local"])))
    out = msg.sent[-1]
    assert "Backend:\nRUNNING" in out
    assert "Preflight:\nFIXED" in out
    assert "- db init skipped (no explicit init command)" in out


def test_delete_project_local_executes_and_reports(monkeypatch, tmp_path: Path) -> None:
    project = tmp_path / "delete_local_proj"
    project.mkdir(parents=True, exist_ok=True)
    set_current_project(project)
    monkeypatch.setattr(
        "archmind.deploy.delete_project",
        lambda _p, mode="local": {
            "ok": True,
            "mode": mode,
            "local_status": "DELETED",
            "local_detail": "",
            "repo_status": "UNCHANGED",
            "repo_detail": "",
        },
    )
    msg = DummyMessage()
    update = DummyUpdate(message=msg, effective_chat=DummyChat())
    asyncio.run(command_delete_project(update, DummyContext()))
    out = msg.sent[-1]
    assert "Project deleted" in out
    assert "Mode:\nlocal" in out
    assert "Local directory:\nDELETED" in out
    assert "GitHub repository:\nUNCHANGED" in out


def test_delete_project_local_clears_current_selection(monkeypatch, tmp_path: Path) -> None:
    project = tmp_path / "delete_local_clear_proj"
    project.mkdir(parents=True, exist_ok=True)
    set_current_project(project)
    monkeypatch.setattr(
        "archmind.deploy.delete_project",
        lambda _p, mode="local": {
            "ok": True,
            "mode": mode,
            "local_status": "DELETED",
            "local_detail": "",
            "repo_status": "UNCHANGED",
            "repo_detail": "",
        },
    )
    _mark_archmind_project(project)
    monkeypatch.setattr("archmind.telegram_bot.load_last_project_path", lambda: project)
    monkeypatch.setattr("archmind.telegram_bot.LAST_PROJECT_PATH_FILE", tmp_path / "last_proj")
    (tmp_path / "last_proj").write_text(str(project), encoding="utf-8")

    msg = DummyMessage()
    update = DummyUpdate(message=msg, effective_chat=DummyChat())
    asyncio.run(command_delete_project(update, DummyContext(args=["local"])))
    assert get_current_project() is None


def test_delete_project_repo_requires_confirmation(tmp_path: Path) -> None:
    project = tmp_path / "delete_repo_proj"
    project.mkdir(parents=True, exist_ok=True)
    set_current_project(project)
    msg = DummyMessage()
    update = DummyUpdate(message=msg, effective_chat=DummyChat(id=77))
    asyncio.run(command_delete_project(update, DummyContext(args=["repo"])))
    out = msg.sent[-1]
    assert "Delete confirmation required" in out
    assert "Reply exactly with:\nDELETE YES" in out


def test_delete_project_all_requires_confirmation(tmp_path: Path) -> None:
    project = tmp_path / "delete_all_proj"
    project.mkdir(parents=True, exist_ok=True)
    set_current_project(project)
    msg = DummyMessage()
    update = DummyUpdate(message=msg, effective_chat=DummyChat(id=88))
    asyncio.run(command_delete_project(update, DummyContext(args=["all"])))
    out = msg.sent[-1]
    assert "Delete confirmation required" in out
    assert "- local project directory" in out
    assert "- GitHub repository" in out


def test_delete_project_confirmation_executes_delete(monkeypatch, tmp_path: Path) -> None:
    project = tmp_path / "delete_confirm_proj"
    project.mkdir(parents=True, exist_ok=True)
    set_current_project(project)
    calls: list[str] = []
    monkeypatch.setattr(
        "archmind.deploy.delete_project",
        lambda _p, mode="local": calls.append(mode)
        or {
            "ok": True,
            "mode": mode,
            "local_status": "DELETED",
            "local_detail": "",
            "repo_status": "DELETED",
            "repo_detail": "",
        },
    )

    msg = DummyMessage()
    update = DummyUpdate(message=msg, effective_chat=DummyChat(id=99))
    asyncio.run(command_delete_project(update, DummyContext(args=["all"])))

    confirm_msg = DummyMessage()
    confirm_update = DummyUpdate(message=confirm_msg, effective_chat=DummyChat(id=99))
    confirm_update.message.text = "DELETE YES"  # type: ignore[attr-defined]
    asyncio.run(telegram_bot.command_text(confirm_update, DummyContext()))
    assert calls == ["all"]
    assert "Project deleted" in confirm_msg.sent[-1]
    assert "Mode:\nall" in confirm_msg.sent[-1]


def test_delete_project_all_treats_repo_404_as_already_deleted(monkeypatch, tmp_path: Path) -> None:
    project = tmp_path / "delete_all_idempotent_repo"
    project.mkdir(parents=True, exist_ok=True)
    set_current_project(project)
    monkeypatch.setattr(
        "archmind.deploy.delete_project",
        lambda _p, mode="all": {
            "ok": True,
            "mode": mode,
            "local_status": "DELETED",
            "local_detail": "local project directory deleted",
            "repo_status": "ALREADY_DELETED",
            "repo_detail": "github repository already deleted",
        },
    )

    msg = DummyMessage()
    update = DummyUpdate(message=msg, effective_chat=DummyChat(id=109))
    asyncio.run(command_delete_project(update, DummyContext(args=["all"])))

    confirm_msg = DummyMessage()
    confirm_update = DummyUpdate(message=confirm_msg, effective_chat=DummyChat(id=109))
    confirm_update.message.text = "DELETE YES"  # type: ignore[attr-defined]
    asyncio.run(telegram_bot.command_text(confirm_update, DummyContext()))
    out = confirm_msg.sent[-1]
    assert "GitHub repository:\nALREADY_DELETED" in out
    assert "Repo detail:\ngithub repository already deleted" in out
    assert get_current_project() is None


def test_delete_project_repo_only_keeps_current_and_persists_state(monkeypatch, tmp_path: Path) -> None:
    project = tmp_path / "delete_repo_state_proj"
    archmind = project / ".archmind"
    archmind.mkdir(parents=True, exist_ok=True)
    (archmind / "state.json").write_text(json.dumps({"last_status": "DONE"}), encoding="utf-8")
    set_current_project(project)
    monkeypatch.setattr(
        "archmind.deploy.delete_project",
        lambda _p, mode="repo": {
            "ok": True,
            "mode": mode,
            "local_status": "UNCHANGED",
            "local_detail": "",
            "repo_status": "ALREADY_DELETED",
            "repo_detail": "github repository already deleted",
        },
    )

    msg = DummyMessage()
    update = DummyUpdate(message=msg, effective_chat=DummyChat(id=111))
    asyncio.run(command_delete_project(update, DummyContext(args=["repo"])))

    confirm_msg = DummyMessage()
    confirm_update = DummyUpdate(message=confirm_msg, effective_chat=DummyChat(id=111))
    confirm_update.message.text = "DELETE YES"  # type: ignore[attr-defined]
    asyncio.run(telegram_bot.command_text(confirm_update, DummyContext()))

    assert get_current_project() == project.resolve()
    payload = telegram_bot.load_state(project) or {}
    deletion = payload.get("deletion") if isinstance(payload.get("deletion"), dict) else {}
    assert deletion.get("mode") == "repo"
    assert deletion.get("repo_status") == "ALREADY_DELETED"
    assert deletion.get("local_status") == "UNCHANGED"


def test_delete_yes_without_pending_is_ignored() -> None:
    msg = DummyMessage()
    update = DummyUpdate(message=msg, effective_chat=DummyChat(id=66))
    update.message.text = "DELETE YES"  # type: ignore[attr-defined]
    asyncio.run(telegram_bot.command_text(update, DummyContext()))
    assert msg.sent == []


def test_running_shows_no_local_services(monkeypatch) -> None:
    monkeypatch.setattr("archmind.deploy.list_running_local_projects", lambda _root: [])
    msg = DummyMessage()
    update = DummyUpdate(message=msg, effective_chat=DummyChat())
    asyncio.run(command_running(update, DummyContext()))
    assert msg.sent[-1] == "No local services running."


def test_running_lists_projects_with_current_marker(monkeypatch, tmp_path: Path) -> None:
    current = tmp_path / "proj_current"
    other = tmp_path / "proj_other"
    current.mkdir(parents=True, exist_ok=True)
    other.mkdir(parents=True, exist_ok=True)
    set_current_project(current)

    monkeypatch.setattr(
        "archmind.deploy.list_running_local_projects",
        lambda _root: [
            {
                "project_dir": current,
                "project_name": "proj_current",
                "backend": {"status": "RUNNING", "pid": 12345, "url": "http://127.0.0.1:8011"},
                "frontend": {"status": "RUNNING", "pid": 12346, "url": "http://127.0.0.1:3011"},
            },
            {
                "project_dir": other,
                "project_name": "proj_other",
                "backend": {"status": "RUNNING", "pid": 11111, "url": "http://127.0.0.1:8050"},
                "frontend": {"status": "NOT RUNNING", "pid": None, "url": ""},
            },
        ],
    )

    msg = DummyMessage()
    update = DummyUpdate(message=msg, effective_chat=DummyChat())
    asyncio.run(command_running(update, DummyContext()))
    out = msg.sent[-1]
    assert "Running local services" in out
    assert "1. proj_current [current]" in out
    assert "Backend: RUNNING (pid 12345)" in out
    assert "URL: http://127.0.0.1:8011" in out
    assert "Frontend: RUNNING (pid 12346)" in out
    assert "2. proj_other" in out
    assert "Frontend: NOT RUNNING" in out


def test_running_shows_external_urls_when_ip_detected(monkeypatch, tmp_path: Path) -> None:
    current = tmp_path / "proj_current_external"
    current.mkdir(parents=True, exist_ok=True)
    set_current_project(current)
    monkeypatch.setattr(
        "archmind.deploy.list_running_local_projects",
        lambda _root: [
            {
                "project_dir": current,
                "project_name": "proj_current_external",
                "backend": {"status": "RUNNING", "pid": 12345, "url": "http://127.0.0.1:8011"},
                "frontend": {"status": "RUNNING", "pid": 12346, "url": "http://127.0.0.1:3011"},
            }
        ],
    )
    monkeypatch.setattr("archmind.telegram_bot._detect_external_ip", lambda: "100.64.0.10")

    msg = DummyMessage()
    update = DummyUpdate(message=msg, effective_chat=DummyChat())
    asyncio.run(command_running(update, DummyContext()))
    out = msg.sent[-1]
    assert "External URL: http://100.64.0.10:8011" in out
    assert "External URL: http://100.64.0.10:3011" in out


def test_watch_retry_accumulates_existing_fix_attempts(monkeypatch, tmp_path: Path) -> None:
    project_dir = tmp_path / "retry_project_existing_fix"
    archmind = project_dir / ".archmind"
    archmind.mkdir(parents=True, exist_ok=True)
    temp_log = tmp_path / "retry_existing.log"

    (archmind / "state.json").write_text(
        json.dumps({"last_status": "NOT_DONE", "iterations": 4, "fix_attempts": 2}),
        encoding="utf-8",
    )
    (archmind / "evaluation.json").write_text(json.dumps({"status": "NOT_DONE"}), encoding="utf-8")

    def fake_run_command(cmd, _temp_log):  # type: ignore[no-untyped-def]
        state_payload = json.loads((archmind / "state.json").read_text(encoding="utf-8"))
        if cmd[:2] == ["archmind", "fix"]:
            state_payload["fix_attempts"] = int(state_payload.get("fix_attempts") or 0) + 1
        if cmd[:2] == ["archmind", "pipeline"]:
            state_payload["iterations"] = int(state_payload.get("iterations") or 0) + 1
        (archmind / "state.json").write_text(json.dumps(state_payload), encoding="utf-8")
        return 0

    monkeypatch.setattr("archmind.telegram_bot._run_command_to_log", fake_run_command)

    class DummyBot:
        def __init__(self) -> None:
            self.sent: list[str] = []

        async def send_message(self, chat_id: int, text: str) -> None:  # noqa: ARG002
            self.sent.append(text)

    class DummyApp:
        def __init__(self) -> None:
            self.bot = DummyBot()

    app = DummyApp()
    asyncio.run(watch_retry_and_notify(project_dir=project_dir, temp_log=temp_log, chat_id=1, application=app))
    final_msg = app.bot.sent[-1]
    assert "Iterations: 5" in final_msg
    assert "Fix attempts: 3" in final_msg


def test_watch_retry_records_fixing_and_running_states(monkeypatch, tmp_path: Path) -> None:
    project_dir = tmp_path / "retry_states"
    archmind = project_dir / ".archmind"
    archmind.mkdir(parents=True, exist_ok=True)
    temp_log = tmp_path / "retry_states.log"
    (archmind / "state.json").write_text(json.dumps({"iterations": 0, "fix_attempts": 0}), encoding="utf-8")
    states: list[str] = []

    def fake_set_agent_state(_project_dir, state, **kwargs):  # type: ignore[no-untyped-def]
        states.append(state)
        return {}

    monkeypatch.setattr("archmind.telegram_bot.set_agent_state", fake_set_agent_state)
    monkeypatch.setattr("archmind.telegram_bot._run_command_to_log", lambda cmd, _log: 0)

    class DummyBot:
        async def send_message(self, chat_id: int, text: str) -> None:  # noqa: ARG002
            return None

    class DummyApp:
        def __init__(self) -> None:
            self.bot = DummyBot()

    asyncio.run(watch_retry_and_notify(project_dir=project_dir, temp_log=temp_log, chat_id=1, application=DummyApp()))
    assert "FIXING" in states
    assert "RUNNING" in states


def test_build_completion_message_recovers_fix_attempts_from_history(tmp_path: Path) -> None:
    project_dir = tmp_path / "history_recovery"
    archmind = project_dir / ".archmind"
    archmind.mkdir(parents=True, exist_ok=True)
    (archmind / "state.json").write_text(
        json.dumps(
            {
                "last_status": "NOT_DONE",
                "iterations": 3,
                "history": [
                    {"action": "archmind fix --path p --apply", "status": "FAIL"},
                    {"action": "pipeline fix iteration 1", "status": "FAIL"},
                ],
            }
        ),
        encoding="utf-8",
    )
    msg = build_completion_message(project_dir, tmp_path / "unused.log")
    assert "Fix attempts: 2" in msg


def test_build_completion_message_corrects_stale_fix_attempts_from_history(tmp_path: Path) -> None:
    project_dir = tmp_path / "history_recovery_stale"
    archmind = project_dir / ".archmind"
    archmind.mkdir(parents=True, exist_ok=True)
    (archmind / "state.json").write_text(
        json.dumps(
            {
                "last_status": "NOT_DONE",
                "iterations": 7,
                "fix_attempts": 1,
                "history": [
                    {"action": "archmind fix --path p --apply", "status": "FAIL"},
                    {"action": "pipeline fix iteration 1", "status": "FAIL"},
                    {"action": "archmind fix --path p --apply", "status": "FAIL"},
                ],
            }
        ),
        encoding="utf-8",
    )
    msg = build_completion_message(project_dir, tmp_path / "unused.log")
    assert "Fix attempts: 3" in msg


def test_watch_pipeline_and_notify_appends_auto_run_result(monkeypatch, tmp_path: Path) -> None:
    project_dir = tmp_path / "idea_local_watch_proj"
    project_dir.mkdir(parents=True, exist_ok=True)
    temp_log = tmp_path / "idea_local_watch.log"

    class DummyProc:
        def wait(self) -> int:
            return 0

    class DummyBot:
        def __init__(self) -> None:
            self.sent: list[str] = []

        async def send_message(self, chat_id: int, text: str) -> None:  # noqa: ARG002
            self.sent.append(text)

    class DummyApp:
        def __init__(self) -> None:
            self.bot = DummyBot()

    app = DummyApp()
    monkeypatch.setattr("archmind.telegram_bot._wait_for_latest_artifacts", lambda *_a, **_k: None)
    monkeypatch.setattr("archmind.telegram_bot.build_completion_message", lambda *_a, **_k: "Project created")
    monkeypatch.setattr("archmind.telegram_bot._auto_run_backend_after_idea_local", lambda _p: "Backend:\nRUNNING")

    asyncio.run(
        watch_pipeline_and_notify(
            proc=DummyProc(),
            project_dir=project_dir,
            temp_log=temp_log,
            chat_id=1,
            application=app,
            auto_run_backend=True,
        )
    )
    assert app.bot.sent
    assert "Project created" in app.bot.sent[-1]
    assert "Backend:\nRUNNING" in app.bot.sent[-1]


def test_idea_local_sets_auto_run_backend_flag_for_watcher(monkeypatch, tmp_path: Path) -> None:
    project_dir = tmp_path / "idea_local_autorun_flag"
    log_path = tmp_path / "idea_local_autorun_flag.telegram.log"
    captured: dict[str, object] = {}

    class DummyProc:
        pid = 10101

    async def fake_watch(**kwargs):  # type: ignore[no-untyped-def]
        captured["watch_kwargs"] = kwargs

    monkeypatch.setattr("archmind.telegram_bot.resolve_base_dir", lambda: tmp_path)
    monkeypatch.setattr("archmind.telegram_bot.planned_project_dir", lambda *_a, **_k: project_dir)
    monkeypatch.setattr("archmind.telegram_bot.start_pipeline_process", lambda *_a, **_k: (DummyProc(), log_path))
    monkeypatch.setattr("archmind.telegram_bot.watch_pipeline_and_notify", fake_watch)

    class DummyBot:
        async def send_message(self, chat_id: int, text: str) -> None:  # noqa: ARG002
            return None

    class DummyApp:
        bot = DummyBot()

    msg = DummyMessage()
    update = DummyUpdate(message=msg, effective_chat=DummyChat())
    ctx = DummyContext(args=["fastapi", "app"], application=DummyApp())
    asyncio.run(command_idea_local(update, ctx))
    assert isinstance(captured.get("watch_kwargs"), dict)
    assert bool(captured["watch_kwargs"].get("auto_run_backend")) is True


def test_auto_run_backend_after_idea_local_detect_ok_runs_backend(monkeypatch, tmp_path: Path) -> None:
    project_dir = tmp_path / "idea_local_autorun_ok"
    project_dir.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr("archmind.telegram_bot.load_state", lambda _p: {"effective_template": "fastapi"})
    monkeypatch.setattr(
        "archmind.deploy.get_local_runtime_status",
        lambda _p: {
            "backend": {"status": "NOT RUNNING", "pid": None, "url": ""},
            "frontend": {"status": "NOT RUNNING", "pid": None, "url": ""},
        },
    )
    monkeypatch.setattr(
        "archmind.telegram_bot.detect_backend_runtime_entry",
        lambda _p, port=8000: {"ok": True, "backend_entry": "app.main:app"},
    )
    monkeypatch.setattr(
        "archmind.deploy.run_backend_local_with_health",
        lambda _p: {
            "ok": True,
            "status": "SUCCESS",
            "url": "http://127.0.0.1:8131",
            "backend_smoke_status": "SUCCESS",
            "backend_smoke_url": "http://127.0.0.1:8131/health",
        },
    )
    monkeypatch.setattr("archmind.telegram_bot.update_after_deploy", lambda *a, **k: {})
    out = telegram_bot._auto_run_backend_after_idea_local(project_dir)
    assert "Backend:\nRUNNING" in out
    assert "Backend smoke:\nSUCCESS" in out
    assert "http://127.0.0.1:8131" in out


def test_auto_run_backend_after_idea_local_detect_fail_skips(monkeypatch, tmp_path: Path) -> None:
    project_dir = tmp_path / "idea_local_autorun_skip"
    project_dir.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr("archmind.telegram_bot.load_state", lambda _p: {"effective_template": "fastapi"})
    monkeypatch.setattr(
        "archmind.deploy.get_local_runtime_status",
        lambda _p: {
            "backend": {"status": "NOT RUNNING", "pid": None, "url": ""},
            "frontend": {"status": "NOT RUNNING", "pid": None, "url": ""},
        },
    )
    monkeypatch.setattr(
        "archmind.telegram_bot.detect_backend_runtime_entry",
        lambda _p, port=8000: {"ok": False, "failure_reason": "missing backend entrypoint"},
    )
    called = {"run": 0}
    monkeypatch.setattr(
        "archmind.deploy.run_backend_local_with_health",
        lambda _p: called.__setitem__("run", called["run"] + 1) or {"status": "SUCCESS"},
    )
    out = telegram_bot._auto_run_backend_after_idea_local(project_dir)
    assert called["run"] == 0
    assert "Backend:\nSKIPPED" in out
    assert "missing backend entrypoint" in out


def test_auto_run_backend_after_idea_local_fail_response(monkeypatch, tmp_path: Path) -> None:
    project_dir = tmp_path / "idea_local_autorun_fail"
    project_dir.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr("archmind.telegram_bot.load_state", lambda _p: {"effective_template": "fastapi"})
    monkeypatch.setattr(
        "archmind.deploy.get_local_runtime_status",
        lambda _p: {
            "backend": {"status": "NOT RUNNING", "pid": None, "url": ""},
            "frontend": {"status": "NOT RUNNING", "pid": None, "url": ""},
        },
    )
    monkeypatch.setattr(
        "archmind.telegram_bot.detect_backend_runtime_entry",
        lambda _p, port=8000: {"ok": True, "backend_entry": "app.main:app"},
    )
    monkeypatch.setattr(
        "archmind.deploy.run_backend_local_with_health",
        lambda _p: {
            "ok": False,
            "status": "FAIL",
            "url": "",
            "failure_class": "runtime-execution-error",
            "backend_smoke_status": "FAIL",
            "backend_smoke_url": "http://127.0.0.1:8132/health",
        },
    )
    monkeypatch.setattr("archmind.telegram_bot.update_after_deploy", lambda *a, **k: {})
    out = telegram_bot._auto_run_backend_after_idea_local(project_dir)
    assert "Backend:\nFAIL" in out
    assert "Failure class:\nruntime-execution-error" in out
    assert "Next:\n- /logs backend\n- /fix" in out


def test_auto_run_backend_after_idea_local_injects_runtime_env_defaults(monkeypatch, tmp_path: Path) -> None:
    project_dir = tmp_path / "idea_local_env_injection"
    (project_dir / "backend" / "app").mkdir(parents=True, exist_ok=True)
    (project_dir / "backend" / "app" / "main.py").write_text("from fastapi import FastAPI\napp = FastAPI()\n", encoding="utf-8")
    (project_dir / "backend" / "requirements.txt").write_text("fastapi\nuvicorn\n", encoding="utf-8")
    (project_dir / "frontend").mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr("archmind.telegram_bot.load_state", lambda _p: {"effective_template": "fullstack-ddd"})
    monkeypatch.setattr(
        "archmind.deploy.get_local_runtime_status",
        lambda _p: {
            "backend": {"status": "NOT RUNNING", "pid": None, "url": ""},
            "frontend": {"status": "NOT RUNNING", "pid": None, "url": ""},
        },
    )
    monkeypatch.setattr("archmind.deploy._detect_lan_ip", lambda: "")
    monkeypatch.setattr(
        "archmind.telegram_bot.detect_backend_runtime_entry",
        lambda _p, port=8000: {"ok": True, "backend_entry": "app.main:app"},
    )
    monkeypatch.setattr(
        "archmind.deploy.run_backend_local_with_health",
        lambda _p: {
            "ok": True,
            "status": "SUCCESS",
            "url": "http://127.0.0.1:8131",
            "backend_smoke_status": "SUCCESS",
            "backend_smoke_url": "http://127.0.0.1:8131/health",
        },
    )
    monkeypatch.setattr("archmind.telegram_bot.update_runtime_state", lambda *a, **k: {})
    telegram_bot._auto_run_backend_after_idea_local(project_dir)
    backend_env = (project_dir / "backend" / ".env").read_text(encoding="utf-8")
    frontend_env = (project_dir / "frontend" / ".env.local").read_text(encoding="utf-8")
    assert "APP_PORT=8000" in backend_env
    assert "BACKEND_BASE_URL=http://127.0.0.1:8000" in backend_env
    assert "CORS_ALLOW_ORIGINS=http://localhost:3000,http://127.0.0.1:3000" in backend_env
    assert "NEXT_PUBLIC_API_BASE_URL=" not in frontend_env
    assert "NEXT_PUBLIC_FRONTEND_PORT=3000" in frontend_env
    assert "NEXT_PUBLIC_RUNTIME_BACKEND_URL=http://127.0.0.1:8000" in frontend_env
