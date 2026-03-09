from __future__ import annotations

import asyncio
import json
import os
import re
import subprocess
from datetime import datetime
from pathlib import Path
from typing import Any, Optional

LAST_PROJECT_PATH_FILE = Path.home() / ".archmind_telegram_last_project"
DEFAULT_BASE_DIR = Path.home() / "archmind-telegram-projects"
DEFAULT_TEMPLATE = "fullstack-ddd"


def extract_idea(args: list[str]) -> str:
    return " ".join(args).strip()


def _slugify(value: str, max_len: int = 32) -> str:
    cleaned = re.sub(r"[^a-zA-Z0-9가-힣]+", "_", value.strip().lower())
    cleaned = re.sub(r"_+", "_", cleaned).strip("_")
    if not cleaned:
        cleaned = "project"
    return cleaned[:max_len]


def make_project_name(idea: str, ts: Optional[str] = None) -> str:
    timestamp = ts or datetime.now().strftime("%Y%m%d_%H%M%S")
    return f"{timestamp}_{_slugify(idea)}"


def resolve_base_dir() -> Path:
    raw = os.getenv("ARCHMIND_BASE_DIR", "").strip()
    if raw:
        return Path(raw).expanduser().resolve()
    return DEFAULT_BASE_DIR.expanduser().resolve()


def resolve_default_template() -> str:
    return os.getenv("ARCHMIND_DEFAULT_TEMPLATE", DEFAULT_TEMPLATE).strip() or DEFAULT_TEMPLATE


def save_last_project_path(project_dir: Path, file_path: Path = LAST_PROJECT_PATH_FILE) -> None:
    file_path.expanduser().write_text(str(project_dir.expanduser().resolve()), encoding="utf-8")


def load_last_project_path(file_path: Path = LAST_PROJECT_PATH_FILE) -> Optional[Path]:
    target = file_path.expanduser()
    if not target.exists():
        return None
    value = target.read_text(encoding="utf-8", errors="replace").strip()
    if not value:
        return None
    return Path(value).expanduser().resolve()


def planned_project_dir(base_dir: Path, idea: str, ts: Optional[str] = None) -> Path:
    return base_dir.expanduser().resolve() / make_project_name(idea, ts=ts)


def build_pipeline_command(idea: str, template: str, base_dir: Path, project_name: str) -> list[str]:
    return [
        "archmind",
        "pipeline",
        "--idea",
        idea,
        "--template",
        template,
        "--out",
        str(base_dir),
        "--name",
        project_name,
        "--apply",
    ]


def build_continue_command(project_dir: Path) -> list[str]:
    return ["archmind", "pipeline", "--path", str(project_dir.expanduser().resolve())]


def build_fix_command(project_dir: Path) -> list[str]:
    return ["archmind", "fix", "--path", str(project_dir.expanduser().resolve()), "--apply"]


def start_pipeline_process(cmd: list[str], base_dir: Path, project_name: str) -> tuple[subprocess.Popen[str], Path]:
    base = base_dir.expanduser().resolve()
    base.mkdir(parents=True, exist_ok=True)
    _project_dir = base / project_name  # compute only: pipeline must create this directory
    log_path = base / f"{project_name}.telegram.log"
    log_handle = open(log_path, "a", encoding="utf-8")
    try:
        proc = subprocess.Popen(  # noqa: S603
            cmd,
            stdout=log_handle,
            stderr=log_handle,
            text=True,
            shell=False,
            start_new_session=True,
        )
    finally:
        log_handle.close()
    return proc, log_path


def start_background_process(cmd: list[str], temp_log: Path) -> subprocess.Popen[str]:
    temp_log.parent.mkdir(parents=True, exist_ok=True)
    log_handle = open(temp_log, "a", encoding="utf-8")
    try:
        proc = subprocess.Popen(  # noqa: S603
            cmd,
            stdout=log_handle,
            stderr=log_handle,
            text=True,
            shell=False,
            start_new_session=True,
        )
    finally:
        log_handle.close()
    return proc


def run_state_command(project_dir: Path, timeout_s: int = 30) -> tuple[bool, str]:
    cmd = ["archmind", "state", "--path", str(project_dir)]
    try:
        completed = subprocess.run(  # noqa: S603
            cmd,
            capture_output=True,
            text=True,
            timeout=timeout_s,
            shell=False,
            check=False,
        )
    except Exception as exc:
        return False, f"state command failed: {exc}"
    if completed.returncode != 0:
        detail = completed.stderr.strip() or completed.stdout.strip() or "unknown error"
        return False, f"state command failed: {detail}"
    return True, completed.stdout.strip() or "(empty)"


def _help_text() -> str:
    return (
        "Commands:\n"
        "/idea <text> - run archmind pipeline from an idea\n"
        "/pipeline <text> - alias of /idea\n"
        "/continue - continue the last project with pipeline\n"
        "/fix - run fix on the last project\n"
        "/state - show latest project state\n"
        "/help - show this message"
    )


def _truncate_message(text: str, limit: int = 3900) -> str:
    if len(text) <= limit:
        return text
    return text[: limit - 3] + "..."


def _load_json(path: Path) -> Optional[dict[str, Any]]:
    if not path.exists():
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None
    return payload if isinstance(payload, dict) else None


def _status_from_sources(project_dir: Path) -> str:
    archmind_dir = project_dir / ".archmind"
    evaluation = _load_json(archmind_dir / "evaluation.json")
    if evaluation and evaluation.get("status"):
        return str(evaluation.get("status"))
    state = _load_json(archmind_dir / "state.json")
    if state and state.get("last_status"):
        return str(state.get("last_status"))
    result = _load_json(archmind_dir / "result.json")
    if result and result.get("status"):
        return str(result.get("status"))
    return "UNKNOWN"


def _current_task_label(project_dir: Path) -> Optional[str]:
    archmind_dir = project_dir / ".archmind"
    state = _load_json(archmind_dir / "state.json") or {}
    task_id = state.get("current_task_id")
    if task_id is None:
        return None
    tasks = _load_json(archmind_dir / "tasks.json") or {}
    raw = tasks.get("tasks")
    if isinstance(raw, list):
        for item in raw:
            if isinstance(item, dict) and int(item.get("id") or -1) == int(task_id):
                title = str(item.get("title") or "").strip()
                if title:
                    return title
    return f"task {task_id}"


def _result_summary_lines(project_dir: Path, temp_log: Path) -> list[str]:
    archmind_dir = project_dir / ".archmind"
    result_txt = archmind_dir / "result.txt"
    if result_txt.exists():
        lines = [line.strip() for line in result_txt.read_text(encoding="utf-8", errors="replace").splitlines()]
        lines = [line for line in lines if line and not line.startswith("ArchMind Pipeline Result")]
        return lines[:8]

    result_json = _load_json(archmind_dir / "result.json")
    if result_json:
        lines: list[str] = []
        if result_json.get("status"):
            lines.append(f"status: {result_json.get('status')}")
        evaluation = result_json.get("evaluation")
        if isinstance(evaluation, dict) and evaluation.get("status"):
            lines.append(f"evaluation: {evaluation.get('status')}")
        steps = result_json.get("steps")
        if isinstance(steps, dict):
            run_before = steps.get("run_before_fix")
            if isinstance(run_before, dict):
                step_status = run_before.get("status")
                if step_status:
                    lines.append(f"run_before_fix: {step_status}")
        return lines[:8]

    state = _load_json(archmind_dir / "state.json")
    if state:
        failures = state.get("recent_failures")
        if isinstance(failures, list):
            picked = [str(item).strip() for item in failures if str(item).strip()]
            if picked:
                return picked[:8]
    evaluation = _load_json(archmind_dir / "evaluation.json")
    if evaluation:
        reasons = evaluation.get("reasons")
        actions = evaluation.get("next_actions")
        lines: list[str] = []
        if isinstance(reasons, list):
            lines.extend(str(item).strip() for item in reasons if str(item).strip())
        if isinstance(actions, list):
            lines.extend(f"next: {str(item).strip()}" for item in actions if str(item).strip())
        if lines:
            return lines[:8]

    if temp_log.exists():
        lines = temp_log.read_text(encoding="utf-8", errors="replace").splitlines()
        tail = [line.strip() for line in lines[-20:] if line.strip()]
        return tail[-8:]

    return ["no summary available"]


def build_completion_message(
    project_dir: Path,
    temp_log: Path,
    *,
    max_len: int = 1200,
    exit_code: Optional[int] = None,
) -> str:
    project_dir = project_dir.expanduser().resolve()
    archmind_dir = project_dir / ".archmind"
    state = _load_json(archmind_dir / "state.json") or {}
    status = _status_from_sources(project_dir)
    iterations = state.get("iterations")
    current_task = _current_task_label(project_dir)
    summary_lines = _result_summary_lines(project_dir, temp_log)

    lines = [
        "ArchMind finished",
        "",
        "Project:",
        str(project_dir),
        "",
        f"Status: {status}",
    ]
    if iterations is not None:
        lines.append(f"Iterations: {iterations}")
    if current_task:
        lines.append(f"Current task: {current_task}")
    if exit_code is not None:
        lines.append(f"Exit code: {exit_code}")
    lines += [
        "",
        "Summary:",
    ]
    lines.extend(f"- {line}" for line in summary_lines[:10])
    return _truncate_message("\n".join(lines), limit=max_len)


async def watch_pipeline_and_notify(
    proc: subprocess.Popen[str],
    project_dir: Path,
    temp_log: Path,
    chat_id: int,
    application: Any,
) -> None:
    try:
        exit_code = await asyncio.to_thread(proc.wait)
        message = build_completion_message(project_dir, temp_log, max_len=1200, exit_code=exit_code)
    except Exception as exc:
        message = f"ArchMind finished with notification error: {exc}"

    try:
        await application.bot.send_message(chat_id=chat_id, text=message)
    except Exception:
        # Notification errors should never crash the bot loop.
        pass


def _missing_project_message() -> str:
    return "No previous project found. Use /idea first."


def _temp_log_for_project(project_dir: Path) -> Path:
    root = project_dir.expanduser().resolve().parent
    return root / f"{project_dir.name}.telegram.log"


async def _handle_idea_like(update: Any, context: Any, cmd_name: str) -> None:
    idea = extract_idea(getattr(context, "args", []))
    if not idea:
        await update.message.reply_text(f"Usage: /{cmd_name} <idea text>")
        return

    base_dir = resolve_base_dir()
    template = resolve_default_template()
    base_dir.mkdir(parents=True, exist_ok=True)
    project_dir = planned_project_dir(base_dir, idea)
    save_last_project_path(project_dir)

    command = build_pipeline_command(
        idea=idea,
        template=template,
        base_dir=base_dir,
        project_name=project_dir.name,
    )
    try:
        proc, log_path = start_pipeline_process(command, base_dir=base_dir, project_name=project_dir.name)
    except Exception as exc:
        await update.message.reply_text(f"Failed to start pipeline: {exc}")
        return

    application = getattr(context, "application", None)
    chat = getattr(update, "effective_chat", None)
    chat_id = getattr(chat, "id", None)
    if application is not None and chat_id is not None:
        asyncio.create_task(
            watch_pipeline_and_notify(
                proc=proc,
                project_dir=project_dir,
                temp_log=log_path,
                chat_id=int(chat_id),
                application=application,
            )
        )

    await update.message.reply_text(
        f"started: pid={proc.pid}\nproject={project_dir}\nlog={log_path}"
    )


async def _handle_continue(update: Any, context: Any) -> None:
    project_dir = load_last_project_path()
    if project_dir is None:
        await update.message.reply_text(_missing_project_message())
        return

    command = build_continue_command(project_dir)
    temp_log = _temp_log_for_project(project_dir)
    try:
        proc = start_background_process(command, temp_log=temp_log)
    except Exception as exc:
        await update.message.reply_text(f"Failed to continue pipeline: {exc}")
        return

    application = getattr(context, "application", None)
    chat = getattr(update, "effective_chat", None)
    chat_id = getattr(chat, "id", None)
    if application is not None and chat_id is not None:
        asyncio.create_task(
            watch_pipeline_and_notify(
                proc=proc,
                project_dir=project_dir,
                temp_log=temp_log,
                chat_id=int(chat_id),
                application=application,
            )
        )
    await update.message.reply_text(f"continuing: pid={proc.pid}\nproject={project_dir}")


async def _handle_fix(update: Any, context: Any) -> None:
    project_dir = load_last_project_path()
    if project_dir is None:
        await update.message.reply_text(_missing_project_message())
        return

    command = build_fix_command(project_dir)
    temp_log = _temp_log_for_project(project_dir)
    try:
        proc = start_background_process(command, temp_log=temp_log)
    except Exception as exc:
        await update.message.reply_text(f"Failed to start fix: {exc}")
        return

    application = getattr(context, "application", None)
    chat = getattr(update, "effective_chat", None)
    chat_id = getattr(chat, "id", None)
    if application is not None and chat_id is not None:
        asyncio.create_task(
            watch_pipeline_and_notify(
                proc=proc,
                project_dir=project_dir,
                temp_log=temp_log,
                chat_id=int(chat_id),
                application=application,
            )
        )
    await update.message.reply_text(f"fix started: pid={proc.pid}\nproject={project_dir}")


async def command_idea(update: Any, context: Any) -> None:
    await _handle_idea_like(update, context, "idea")


async def command_pipeline(update: Any, context: Any) -> None:
    await _handle_idea_like(update, context, "pipeline")


async def command_continue(update: Any, context: Any) -> None:
    await _handle_continue(update, context)


async def command_fix(update: Any, context: Any) -> None:
    await _handle_fix(update, context)


async def command_state(update: Any, context: Any) -> None:
    del context
    project_path = load_last_project_path()
    if project_path is None:
        await update.message.reply_text("No project yet. Start with /idea <text> first.")
        return
    ok, output = run_state_command(project_path)
    if not ok:
        await update.message.reply_text(_truncate_message(output))
        return
    await update.message.reply_text(_truncate_message(output))


async def command_help(update: Any, context: Any) -> None:
    del context
    await update.message.reply_text(_help_text())


def run_bot() -> None:
    token = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
    if not token:
        raise SystemExit("TELEGRAM_BOT_TOKEN is required")

    try:
        from telegram.ext import ApplicationBuilder, CommandHandler
    except Exception as exc:
        raise SystemExit(f"python-telegram-bot is required: {exc}") from exc

    app = ApplicationBuilder().token(token).build()
    app.add_handler(CommandHandler("idea", command_idea))
    app.add_handler(CommandHandler("pipeline", command_pipeline))
    app.add_handler(CommandHandler("continue", command_continue))
    app.add_handler(CommandHandler("fix", command_fix))
    app.add_handler(CommandHandler("state", command_state))
    app.add_handler(CommandHandler("help", command_help))
    app.run_polling()
