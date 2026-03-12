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
    command_logs,
    command_continue,
    command_fix,
    command_current,
    command_use,
    command_projects,
    command_status,
    command_help,
    command_retry,
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
    get_current_project,
    start_pipeline_process,
    format_projects_list,
    format_status_text,
    list_recent_projects,
    watch_retry_and_notify,
)


@pytest.fixture(autouse=True)
def _reset_running_job() -> None:
    telegram_bot._clear_running_job()
    telegram_bot.clear_current_project()
    yield
    telegram_bot._clear_running_job()
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
    assert "Use /state to inspect current progress." in msg.sent[-1]


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
    assert "Project: status_proj" in out
    assert "State: IDLE" in out
    assert "Iterations: 3" in out
    assert "Fix attempts: 1" in out
    assert "Project type: frontend-web" in out
    assert "Template: nextjs" in out
    assert "Backend: SKIP" in out
    assert "Frontend: WARNING" in out
    assert "Next action:\nrun /fix" in out


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
    assert "State: RUNNING" in out
    assert "Backend: FAIL" in out
    assert "Frontend: ABSENT" in out
    assert "Next action:\nrun /continue" in out


def test_format_status_text_defaults_when_idle_without_artifacts(tmp_path: Path) -> None:
    project_dir = tmp_path / "status_idle_default"
    project_dir.mkdir(parents=True, exist_ok=True)
    out = format_status_text(project_dir)
    assert "ArchMind status" in out
    assert "Project: status_idle_default" in out
    assert "State: IDLE" in out
    assert "Backend: UNKNOWN" in out
    assert "Frontend: UNKNOWN" in out


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
        (project / ".archmind").mkdir(parents=True, exist_ok=True)
        (project / ".archmind" / "state.json").write_text(
            json.dumps({"last_status": "NOT_DONE", "project_type": "backend-api", "effective_template": "fastapi"}),
            encoding="utf-8",
        )

    msg = DummyMessage()
    update = DummyUpdate(message=msg, effective_chat=DummyChat())
    ctx = DummyContext(args=["1"])
    asyncio.run(command_use(update, ctx))

    assert msg.sent
    assert "selected current project:" in msg.sent[-1]
    assert get_current_project() is not None


def test_use_by_project_name_works(monkeypatch, tmp_path: Path) -> None:
    root = tmp_path / "projects"
    root.mkdir(parents=True, exist_ok=True)
    monkeypatch.setenv("ARCHMIND_PROJECTS_DIR", str(root))
    project = root / "20260312_named_proj"
    (project / ".archmind").mkdir(parents=True, exist_ok=True)
    (project / ".archmind" / "state.json").write_text(
        json.dumps({"last_status": "DONE", "project_type": "frontend-web", "effective_template": "nextjs"}),
        encoding="utf-8",
    )

    msg = DummyMessage()
    update = DummyUpdate(message=msg, effective_chat=DummyChat())
    ctx = DummyContext(args=["20260312_named_proj"])
    asyncio.run(command_use(update, ctx))

    assert msg.sent
    assert "selected current project: 20260312_named_proj" in msg.sent[-1]
    assert get_current_project() == project.resolve()


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
    assert "Project: current_status_proj" in msg.sent[-1]


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


def test_help_mentions_state_for_long_running_commands() -> None:
    msg = DummyMessage()
    update = DummyUpdate(message=msg, effective_chat=DummyChat())
    ctx = DummyContext()
    asyncio.run(command_help(update, ctx))
    assert msg.sent
    assert "Long-running commands may take time; use /state for progress." in msg.sent[-1]
    assert "/projects - list recent ArchMind projects" in msg.sent[-1]
    assert "/use <n|name> - select a project to work on" in msg.sent[-1]
    assert "/current - show currently selected project" in msg.sent[-1]


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
