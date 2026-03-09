from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass, field
from pathlib import Path

from archmind.telegram_bot import (
    build_completion_message,
    build_continue_command,
    build_fix_command,
    build_pipeline_command,
    command_continue,
    command_fix,
    extract_idea,
    load_last_project_path,
    make_project_name,
    planned_project_dir,
    run_state_command,
    save_last_project_path,
    start_pipeline_process,
)


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
        template="fullstack-ddd",
        base_dir=base_dir,
        project_name=project_name,
    )
    assert cmd[:2] == ["archmind", "pipeline"]
    assert "--apply" in cmd
    assert cmd[cmd.index("--out") + 1] == str(base_dir)
    assert cmd[cmd.index("--name") + 1] == project_name
    assert cmd[cmd.index("--template") + 1] == "fullstack-ddd"


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
        json.dumps({"last_status": "NOT_DONE", "iterations": 2, "current_task_id": 2}),
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
    assert "Status: NOT_DONE" in message
    assert "Iterations: 2" in message
    assert "Current task: add API endpoints" in message
    assert "- - Backend: FAIL" in message
    assert "Next:" in message
    assert "- run /fix" in message
    assert "- then /continue" in message


def test_build_completion_message_fallbacks_to_temp_log(tmp_path: Path) -> None:
    project_dir = tmp_path / "p2"
    project_dir.mkdir(parents=True, exist_ok=True)
    temp_log = tmp_path / "p2.telegram.log"
    temp_log.write_text("\n".join([f"log line {i}" for i in range(30)]), encoding="utf-8")
    message = build_completion_message(project_dir, temp_log)
    assert "Status: UNKNOWN" in message
    assert "Summary:" in message
    assert "log line 29" in message


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
                "reasons": ["same backend pytest failure repeated 3 times"],
                "next_actions": ["inspect backend failure details"],
            }
        ),
        encoding="utf-8",
    )
    (archmind / "state.json").write_text(
        json.dumps({"last_status": "STUCK", "iterations": 4, "current_task_id": 3}),
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
    assert "Reason: same backend pytest failure repeated 3 times" in msg
    assert "Next:" in msg
    assert "inspect backend failure details" in msg


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
