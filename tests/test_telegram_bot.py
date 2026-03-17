from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass, field
from pathlib import Path

import pytest
import archmind.telegram_bot as telegram_bot
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
    command_diff,
    command_open,
    command_tree,
    command_use,
    command_projects,
    command_status,
    command_deploy,
    command_delete_project,
    command_restart,
    command_stop,
    command_help,
    command_inspect,
    command_add_module,
    command_add_entity,
    command_add_field,
    command_add_api,
    command_add_page,
    command_apply_suggestion,
    command_apply_plan,
    command_next,
    command_plan,
    command_retry,
    command_preview,
    command_suggest,
    command_design,
    command_state,
    extract_idea,
    load_last_project_path,
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
    get_template_suggestions,
    get_current_project,
    start_pipeline_process,
    format_projects_list,
    format_project_tree,
    format_file_preview,
    format_recent_diff,
    format_status_text,
    list_recent_projects,
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


def test_last_project_path_save_and_load(tmp_path: Path) -> None:
    path_file = tmp_path / "last_project"
    project_path = tmp_path / "demo_project"
    save_last_project_path(project_path, file_path=path_file)
    loaded = load_last_project_path(file_path=path_file)
    assert loaded == project_path.resolve()


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
    assert "- run /fix" in message
    assert "- run /logs backend" in message


def test_build_completion_message_includes_github_repo_url_when_present(tmp_path: Path) -> None:
    project_dir = tmp_path / "repo_msg"
    archmind = project_dir / ".archmind"
    archmind.mkdir(parents=True, exist_ok=True)
    (archmind / "result.json").write_text(
        json.dumps({"status": "SUCCESS", "github_repo_url": "https://github.com/siriusnen-commits/repo_msg"}),
        encoding="utf-8",
    )
    (archmind / "state.json").write_text(
        json.dumps({"last_status": "DONE", "iterations": 1, "fix_attempts": 0, "github_repo_url": "https://github.com/siriusnen-commits/repo_msg"}),
        encoding="utf-8",
    )
    msg = build_completion_message(project_dir, tmp_path / "unused.log")
    assert "GitHub repo:" in msg
    assert "https://github.com/siriusnen-commits/repo_msg" in msg


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
    assert "- run /continue" in msg


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

    async def reply_text(self, text: str) -> None:
        self.sent.append(text)


@dataclass
class DummyUpdate:
    message: DummyMessage
    effective_chat: object


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
    assert "No backend logs found." in msg_back
    assert "No frontend logs found." in msg_front
    assert "Focus:" in msg_last


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
    set_current_project(project_dir)

    msg = DummyMessage()
    update = DummyUpdate(message=msg, effective_chat=DummyChat())
    asyncio.run(command_logs(update, DummyContext(args=["local"])))
    assert msg.sent[-1] == "No logs available."


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
    monkeypatch.setattr("archmind.telegram_bot.load_last_project_path", lambda: project_dir)
    monkeypatch.setattr("archmind.telegram_bot._status_from_sources", lambda _p: "DONE")
    msg = DummyMessage()
    update = DummyUpdate(message=msg, effective_chat=DummyChat())
    ctx = DummyContext(application=None)
    asyncio.run(command_retry(update, ctx))
    assert msg.sent
    assert "Project already complete." in msg.sent[-1]


def test_retry_sets_retrying_state_on_start(monkeypatch, tmp_path: Path) -> None:
    project_dir = tmp_path / "retry_proj"
    project_dir.mkdir(parents=True, exist_ok=True)
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
    assert "Next:\nrun /fix" in out


def test_status_command_works_when_running(monkeypatch, tmp_path: Path) -> None:
    project_dir = tmp_path / "status_running"
    archmind = project_dir / ".archmind"
    archmind.mkdir(parents=True, exist_ok=True)
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
    assert "Next:\nrun /continue" in out


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
    assert "Status: DONE" in out
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
    assert "Status: DONE" in out
    assert "Type: frontend-web" in out
    assert "Template: nextjs" in out
    assert "Runtime" in out
    assert "Backend: RUNNING" in out
    assert "Backend URL: http://127.0.0.1:8050" in out
    assert "Frontend: NOT RUNNING" in out
    assert "Frontend URL:" not in out
    assert "/inspect" in out
    assert "/next" in out


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
    assert "Status: DONE" in out
    assert "Type: fullstack-web" in out
    assert "Template: fullstack-ddd" in out
    assert "RUNNING" in out
    assert "Backend: http://127.0.0.1:8011" in out
    assert "Frontend: http://127.0.0.1:3011" in out
    assert "notes-api" in out
    assert "STOPPED" in out
    assert "worker-api-demo" in out
    assert "RUNNING (backend)" in out
    assert "Backend: http://127.0.0.1:8050" in out


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
    assert "ArchMind commands" in out
    assert "PROJECT CREATION" in out
    assert "PROJECT EVOLUTION" in out
    assert "PROJECT MANAGEMENT" in out
    assert "PIPELINE CONTROL" in out
    assert "LOCAL RUNTIME" in out
    assert "DEPLOY" in out
    assert "CODE" in out
    assert "INSPECTION" in out
    assert "CLEANUP" in out
    assert "/idea <idea>" in out
    assert "/idea_local <idea>" in out
    assert "/pipeline <idea>" in out
    assert "/preview <idea>" in out
    assert "/suggest <idea>" in out
    assert "/design <idea>" in out
    assert "/plan <idea>" in out
    assert "/add_entity <name>" in out
    assert "/add_field <E> <f:t>" in out
    assert "/add_api <M> <path>" in out
    assert "/add_page <path>" in out
    assert "/apply_suggestion" in out
    assert "/next" in out
    assert "/projects" in out
    assert "/help" in out
    assert "/use <n>" in out
    assert "/current" in out
    assert "/status" in out
    assert "/state" in out
    assert "/continue" in out
    assert "/fix" in out
    assert "/retry" in out
    assert "/running" in out
    assert "/logs" in out
    assert "/restart" in out
    assert "/stop" in out
    assert "/deploy local" in out
    assert "/tree" in out
    assert "/open <file>" in out
    assert "/diff" in out
    assert "/inspect" in out
    assert "/apply_plan" in out
    assert "/delete_project" in out
    assert "Example workflow" in out
    assert "/design defect tracker" in out
    assert "/idea_local defect tracker" in out
    assert "/inspect" in out
    assert "/next" in out


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


def test_suggest_command_outputs_suggestion_list() -> None:
    msg = DummyMessage()
    update = DummyUpdate(message=msg, effective_chat=DummyChat())
    asyncio.run(command_suggest(update, DummyContext(args=["document", "upload", "admin", "tool"])))
    out = msg.sent[-1]
    assert "Architecture suggestion" in out
    assert "Template candidates:" in out
    assert "Suggested entities:" in out
    assert "Suggested APIs:" in out
    assert "Suggested pages:" in out
    assert "Reasoning:" in out


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
    assert "API:" in out
    assert "- GET /tasks" in out
    assert "Frontend:" in out
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
    assert payload.get("evolution", {}).get("history", [])[-1] == {"action": "add_entity", "entity": "Task"}


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
    assert "def create_task()" in router_text
    assert "def get_task(id: int)" in router_text
    assert "def update_task(id: int)" in router_text
    assert "def delete_task(id: int)" in router_text

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
    assert "- frontend/app/reports/list/page.tsx" in out

    payload = json.loads((archmind / "project_spec.json").read_text(encoding="utf-8"))
    assert "reports/list" in (payload.get("frontend_pages") or [])
    assert payload.get("evolution", {}).get("history", [])[-1] == {"action": "add_page", "page": "reports/list"}
    assert (project_dir / "frontend" / "app" / "reports" / "list" / "page.tsx").exists()


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


def test_suggest_writes_suggestion_json_for_current_project(tmp_path: Path, monkeypatch) -> None:
    project_dir = tmp_path / "task_tracker"
    (project_dir / ".archmind").mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr("archmind.telegram_bot._resolve_target_project", lambda: project_dir)

    msg = DummyMessage()
    update = DummyUpdate(message=msg, effective_chat=DummyChat())
    asyncio.run(command_suggest(update, DummyContext(args=["team", "defect", "tracker"])))

    suggestion_path = project_dir / ".archmind" / "suggestion.json"
    assert suggestion_path.exists()
    payload = json.loads(suggestion_path.read_text(encoding="utf-8"))
    assert isinstance(payload.get("entities"), list)
    assert isinstance(payload.get("api_endpoints"), list)
    assert isinstance(payload.get("frontend_pages"), list)


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
    msg = DummyMessage()
    asyncio.run(command_next(DummyUpdate(message=msg, effective_chat=DummyChat()), DummyContext()))
    out = msg.sent[-1]
    assert "Next development suggestions" in out
    assert "/add_entity User" in out


def test_next_command_recommends_api_and_pages_for_entity(tmp_path: Path, monkeypatch) -> None:
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
    expected_candidates = [
        "/add_api GET /tasks/{id}",
        "/add_api PUT /tasks/{id}",
        "/add_api PATCH /tasks/{id}",
        "/add_field Task created_at:datetime",
        "/add_field Task updated_at:datetime",
        "/add_page tasks/list",
        "/add_page tasks/detail",
    ]
    assert any("/add_api " in cmd for cmd in out.splitlines())
    assert any("/add_field " in cmd for cmd in out.splitlines())
    assert any(candidate in out for candidate in expected_candidates)


def test_next_command_limits_suggestions_to_five(tmp_path: Path, monkeypatch) -> None:
    project_dir = tmp_path / "big_proj"
    archmind = project_dir / ".archmind"
    archmind.mkdir(parents=True, exist_ok=True)
    entities = [
        {"name": "Task", "fields": [{"name": "title", "type": "string"}]},
        {"name": "Project", "fields": [{"name": "name", "type": "string"}]},
        {"name": "Defect", "fields": [{"name": "title", "type": "string"}]},
    ]
    (archmind / "project_spec.json").write_text(
        json.dumps(
            {
                "shape": "fullstack",
                "domains": ["tasks", "teams"],
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
    asyncio.run(command_next(DummyUpdate(message=msg, effective_chat=DummyChat()), DummyContext()))
    out = msg.sent[-1]
    numbered = [line for line in out.splitlines() if line.startswith(tuple(str(i) + "." for i in range(1, 10)))]
    assert len(numbered) <= 5


def test_next_command_no_suggestions_shows_guidance(tmp_path: Path, monkeypatch) -> None:
    project_dir = tmp_path / "next_done_proj"
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
    msg = DummyMessage()
    asyncio.run(command_next(DummyUpdate(message=msg, effective_chat=DummyChat()), DummyContext()))
    out = msg.sent[-1]
    assert "No immediate suggestions." in out
    assert "Next:" in out
    assert "- /inspect" in out
    assert "- continue evolving the project" in out


def test_next_command_without_selected_project_shows_error(monkeypatch) -> None:
    monkeypatch.setattr("archmind.telegram_bot._resolve_target_project", lambda: None)
    msg = DummyMessage()
    asyncio.run(command_next(DummyUpdate(message=msg, effective_chat=DummyChat()), DummyContext()))
    out = msg.sent[-1]
    assert "No active project." in out
    assert "1. /design <idea>" in out
    assert "2. /plan <idea>" in out
    assert "3. /idea_local <idea>" in out


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


def test_stop_without_selected_project_shows_message(monkeypatch) -> None:
    monkeypatch.setattr("archmind.telegram_bot.load_last_project_path", lambda: None)
    msg = DummyMessage()
    update = DummyUpdate(message=msg, effective_chat=DummyChat())
    asyncio.run(command_stop(update, DummyContext()))
    assert msg.sent
    assert msg.sent[-1] == "No project selected. Use /projects then /use <n>."


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
