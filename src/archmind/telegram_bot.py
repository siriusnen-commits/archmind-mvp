from __future__ import annotations

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
        "--force",
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


def start_pipeline_process(cmd: list[str], base_dir: Path, project_name: str) -> tuple[subprocess.Popen[str], Path]:
    base = base_dir.expanduser().resolve()
    base.mkdir(parents=True, exist_ok=True)
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
        "/state - show latest project state\n"
        "/help - show this message"
    )


def _truncate_message(text: str, limit: int = 3900) -> str:
    if len(text) <= limit:
        return text
    return text[: limit - 3] + "..."


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

    await update.message.reply_text(
        f"started: pid={proc.pid}\nproject={project_dir}\nlog={log_path}"
    )


async def command_idea(update: Any, context: Any) -> None:
    await _handle_idea_like(update, context, "idea")


async def command_pipeline(update: Any, context: Any) -> None:
    await _handle_idea_like(update, context, "pipeline")


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
    app.add_handler(CommandHandler("state", command_state))
    app.add_handler(CommandHandler("help", command_help))
    app.run_polling()
