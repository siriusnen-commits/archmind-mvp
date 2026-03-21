from __future__ import annotations

import asyncio
import hashlib
import json
import os
import re
import subprocess
import time
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Optional

from archmind.brain import reason_architecture_from_idea
from archmind.backend_runtime import detect_backend_runtime_entry
from archmind.decision import decide_next_action, next_action_suggestions
from archmind.failure import classify_failure
from archmind.frontend_runtime import detect_frontend_runtime_entry
from archmind.generator import (
    SUPPORTED_MODULES,
    apply_api_scaffold,
    apply_entity_fields_to_scaffold,
    apply_entity_scaffold,
    apply_frontend_page_scaffold,
    apply_modules_to_project,
    apply_page_scaffold,
    has_frontend_structure,
)
from archmind.idea_normalizer import normalize_idea
from archmind.next_suggester import analyze_spec_progression, suggest_next_commands, suggest_spec_improvements
from archmind.plan_suggester import build_plan_from_project_spec, build_plan_from_suggestion
from archmind.project_type import detect_project_type, normalize_project_type
from archmind.design_suggester import build_architecture_design
from archmind.spec_suggester import suggest_project_spec
from archmind.state import (
    derive_task_label_from_failure_signature,
    load_state,
    set_agent_state,
    update_after_deploy,
    update_runtime_state,
    write_state,
)
from archmind.template_selector import is_supported_template, select_template_for_project_type

LAST_PROJECT_PATH_FILE = Path.home() / ".archmind_telegram_last_project"
DEFAULT_BASE_DIR = Path.home() / "archmind-telegram-projects"
DEFAULT_PROJECTS_DIR = Path.home() / "archmind-telegram-projects"
DEFAULT_TEMPLATE = "fullstack-ddd"
SUPPORTED_FIELD_TYPES = ("string", "int", "float", "bool", "datetime")
SUPPORTED_API_METHODS = ("GET", "POST", "PATCH", "DELETE")
HELP_TEXT = """ArchMind commands

PROJECT CREATION
/idea <idea>           generate project
/idea_local <idea>     generate + run locally
/pipeline <idea>       alias of /idea
/preview <idea>        preview Brain reasoning
/suggest <idea>        show architecture suggestions
/design <idea>         generate architecture design document
/plan <idea>           build development plan from an idea
/plan                  build next development plan for current project
/apply_plan            execute saved development plan

PROJECT EVOLUTION
/add_module <name>     add module to current project
/add_entity <name>     add entity metadata
/add_field <E> <f:t>   add entity field metadata
/add_api <M> <path>    add API endpoint metadata
/add_page <path>       add frontend page metadata
/apply_suggestion      apply last suggestion to spec
/next                  suggest next development steps

PROJECT MANAGEMENT
/help                  show command guide
/projects              list projects
/use <n>               select project
/current               show selected project
/status                show current status
/state                 show raw pipeline state

PIPELINE CONTROL
/continue              continue last project
/fix                   run fix step
/retry                 fix + continue

LOCAL RUNTIME
/run backend           start backend locally
/run all               start backend + frontend locally
/running               show running services
/logs                  show logs
/restart               restart services
/stop                  stop current project services
/stop all              stop all local services

DEPLOY
/deploy local
/deploy railway

CODE
/tree                  show file tree
/open <file>           open file
/diff                  show changes

INSPECTION
/inspect               show project summary
/improve               analyze project mismatches and suggest corrections

CLEANUP
/delete_project
/delete_project repo
/delete_project all

Example workflow

/design defect tracker
/plan defect tracker
/idea_local defect tracker
/inspect
/next"""


@dataclass
class _RunningJob:
    job_id: int
    command: str
    state: str
    project_dir: Path
    started_at: float
    proc: Optional[subprocess.Popen[str]] = None
    task: Optional[asyncio.Task[Any]] = None


@dataclass
class _PendingDelete:
    chat_id: int
    project_dir: Path
    mode: str
    created_at: float


_RUNNING_JOB: Optional[_RunningJob] = None
_RUNNING_JOB_SEQ = 0
_CURRENT_PROJECT: Optional[Path] = None
_PENDING_DELETE: Optional[_PendingDelete] = None
_CALLBACK_PAYLOADS: dict[str, str] = {}


def _is_job_active(job: _RunningJob) -> bool:
    if job.task is not None and job.task.done():
        return False
    if job.proc is not None and job.proc.poll() is not None:
        return False
    return job.task is not None or job.proc is not None


def _get_running_job() -> Optional[_RunningJob]:
    global _RUNNING_JOB
    if _RUNNING_JOB is None:
        return None
    if _is_job_active(_RUNNING_JOB):
        return _RUNNING_JOB
    _RUNNING_JOB = None
    return None


def _clear_running_job(job_id: Optional[int] = None) -> None:
    global _RUNNING_JOB
    if _RUNNING_JOB is None:
        return
    if job_id is None or _RUNNING_JOB.job_id == job_id:
        _RUNNING_JOB = None


def _set_pending_delete(chat_id: int, project_dir: Path, mode: str) -> None:
    global _PENDING_DELETE
    _PENDING_DELETE = _PendingDelete(
        chat_id=int(chat_id),
        project_dir=project_dir.expanduser().resolve(),
        mode=str(mode or "local").strip().lower() or "local",
        created_at=time.time(),
    )


def _get_pending_delete(chat_id: int) -> Optional[_PendingDelete]:
    if _PENDING_DELETE is None:
        return None
    if int(_PENDING_DELETE.chat_id) != int(chat_id):
        return None
    return _PENDING_DELETE


def _clear_pending_delete() -> None:
    global _PENDING_DELETE
    _PENDING_DELETE = None


def set_current_project(project_dir: Path) -> None:
    global _CURRENT_PROJECT
    _CURRENT_PROJECT = project_dir.expanduser().resolve()


def clear_current_project() -> None:
    global _CURRENT_PROJECT
    _CURRENT_PROJECT = None


def get_current_project() -> Optional[Path]:
    if _CURRENT_PROJECT is None:
        return None
    project_dir = _CURRENT_PROJECT.expanduser().resolve()
    if project_dir.exists() and project_dir.is_dir():
        return project_dir
    return None


def _clear_project_selection_if_deleted(project_dir: Path) -> None:
    target = project_dir.expanduser().resolve()
    current = get_current_project()
    if current is not None and current.resolve() == target:
        clear_current_project()
    last = load_last_project_path()
    if last is not None and last.resolve() == target and LAST_PROJECT_PATH_FILE.expanduser().exists():
        try:
            LAST_PROJECT_PATH_FILE.expanduser().unlink()
        except Exception:
            pass


def _resolve_target_project() -> Optional[Path]:
    current = get_current_project()
    if current is not None:
        return current
    last = load_last_project_path()
    if last is not None and last.exists() and last.is_dir():
        return last
    return None


def _register_running_job(
    command: str,
    state: str,
    project_dir: Path,
    *,
    proc: Optional[subprocess.Popen[str]] = None,
) -> _RunningJob:
    global _RUNNING_JOB_SEQ, _RUNNING_JOB
    _RUNNING_JOB_SEQ += 1
    job = _RunningJob(
        job_id=_RUNNING_JOB_SEQ,
        command=command,
        state=state,
        project_dir=project_dir.expanduser().resolve(),
        started_at=time.time(),
        proc=proc,
    )
    _RUNNING_JOB = job
    return job


def _attach_running_task(job: _RunningJob, task: asyncio.Task[Any]) -> None:
    job.task = task

    def _cleanup(_task: asyncio.Task[Any]) -> None:  # noqa: ARG001
        _clear_running_job(job.job_id)

    task.add_done_callback(_cleanup)


def _busy_message(job: _RunningJob) -> str:
    progress = _progress_text(job.project_dir, fallback=_progress_fallback_for_command(job.command))
    return (
        "ArchMind is already processing a command.\n"
        f"Current state: {job.state}\n"
        f"Current command: {job.command}\n"
        f"Project: {job.project_dir.name}\n"
        f"Progress: {progress}\n"
        "Use /status to inspect current progress."
    )


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


def resolve_projects_dir() -> Path:
    raw = os.getenv("ARCHMIND_PROJECTS_DIR", "").strip()
    if raw:
        return Path(raw).expanduser().resolve()
    return DEFAULT_PROJECTS_DIR.expanduser().resolve()


def resolve_default_template() -> str:
    return os.getenv("ARCHMIND_DEFAULT_TEMPLATE", DEFAULT_TEMPLATE).strip() or DEFAULT_TEMPLATE


def resolve_template_for_idea(idea: str) -> str:
    project_type = normalize_project_type(detect_project_type(idea))
    selected_template = select_template_for_project_type(project_type, idea)
    if is_supported_template(selected_template):
        return selected_template
    return resolve_default_template()


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


def build_pipeline_command(
    idea: str,
    base_dir: Path,
    project_name: str,
    *,
    auto_deploy: bool = False,
    deploy_target: str = "local",
) -> list[str]:
    cmd = [
        "archmind",
        "pipeline",
        "--idea",
        idea,
        "--out",
        str(base_dir),
        "--name",
        project_name,
        "--apply",
    ]
    if auto_deploy:
        cmd.append("--auto-deploy")
        target = str(deploy_target or "local").strip().lower() or "local"
        cmd += ["--deploy-target", target]
    return cmd


def build_continue_command(project_dir: Path) -> list[str]:
    return ["archmind", "pipeline", "--path", str(project_dir.expanduser().resolve())]


def build_fix_command(project_dir: Path) -> list[str]:
    return ["archmind", "fix", "--path", str(project_dir.expanduser().resolve()), "--apply"]


def build_retry_commands(project_dir: Path) -> list[list[str]]:
    return [
        build_fix_command(project_dir),
        build_continue_command(project_dir),
    ]


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
    return HELP_TEXT


def _help_quick_text() -> str:
    return (
        "ArchMind quick actions\n\n"
        "Create\n"
        "- /idea_local <idea>\n"
        "- /design <idea>\n"
        "- /plan <idea>\n\n"
        "Current project\n"
        "- /inspect\n"
        "- /next\n"
        "- /improve\n\n"
        "Runtime\n"
        "- /run backend\n"
        "- /run all\n"
        "- /running\n"
        "- /restart\n"
        "- /stop\n"
        "- /stop all\n\n"
        "More help\n"
        "- /help create\n"
        "- /help runtime\n"
        "- /help project\n"
        "- /help deploy\n"
        "- /help code\n"
        "- /help cleanup\n"
        "- /help all\n\n"
        "Example workflow\n"
        "/design defect tracker\n"
        "/plan defect tracker\n"
        "/idea_local defect tracker\n"
        "/inspect\n"
        "/next"
    )


def _help_section_text(section: str) -> str:
    key = str(section or "").strip().lower()
    if key == "create":
        return (
            "Help: create\n\n"
            "- /idea <idea>           generate project\n"
            "- /idea_local <idea>     generate + run locally\n"
            "- /pipeline <idea>       alias of /idea\n"
            "- /preview <idea>        preview Brain reasoning\n"
            "- /suggest <idea>        show architecture suggestions\n"
            "- /design <idea>         generate architecture design document\n"
            "- /plan <idea>           build development plan from an idea\n"
            "- /apply_plan            execute saved development plan"
        )
    if key == "runtime":
        return (
            "Help: runtime\n\n"
            "- /run backend           start backend locally\n"
            "- /run all               start backend + frontend locally\n"
            "- /running               show running local services\n"
            "- /restart               restart current project services\n"
            "- /stop                  stop current project services\n"
            "- /stop all              stop all local services\n"
            "- /logs backend          show backend runtime logs\n"
            "- /logs frontend         show frontend runtime logs"
        )
    if key == "project":
        return (
            "Help: project\n\n"
            "- /inspect               show project summary\n"
            "- /next                  suggest next development steps\n"
            "- /improve               analyze mismatches and corrections\n"
            "- /projects              list projects\n"
            "- /use <n>               select project\n"
            "- /current               show selected project\n"
            "- /status                show current status\n"
            "- /state                 show raw pipeline state"
        )
    if key == "deploy":
        return (
            "Help: deploy\n\n"
            "- /deploy local\n"
            "- /deploy railway\n\n"
            "Deploy current project to target runtime."
        )
    if key == "code":
        return (
            "Help: code\n\n"
            "- /tree                  show file tree\n"
            "- /open <file>           open file\n"
            "- /diff                  show changes"
        )
    if key == "cleanup":
        return (
            "Help: cleanup\n\n"
            "- /delete_project\n"
            "- /delete_project repo\n"
            "- /delete_project all\n\n"
            "repo/all requires confirmation: DELETE YES"
        )
    return _help_quick_text()


def _help_sections_keyboard(section: str = "") -> Any:
    key = str(section or "").strip().lower()
    InlineKeyboardButton, InlineKeyboardMarkup = _inline_keyboard_classes()
    if key in ("", "quick"):
        return InlineKeyboardMarkup(
            [
                [
                    InlineKeyboardButton(text="Create", callback_data=_encode_callback_data("help", "create")),
                    InlineKeyboardButton(text="Runtime", callback_data=_encode_callback_data("help", "runtime")),
                ],
                [
                    InlineKeyboardButton(text="Project", callback_data=_encode_callback_data("help", "project")),
                    InlineKeyboardButton(text="Deploy", callback_data=_encode_callback_data("help", "deploy")),
                ],
                [
                    InlineKeyboardButton(text="Code", callback_data=_encode_callback_data("help", "code")),
                    InlineKeyboardButton(text="Cleanup", callback_data=_encode_callback_data("help", "cleanup")),
                ],
                [InlineKeyboardButton(text="All Commands", callback_data=_encode_callback_data("help", "all"))],
            ]
        )
    if key == "runtime":
        return InlineKeyboardMarkup(
            [
                [
                    InlineKeyboardButton(text="Run backend", callback_data=_encode_callback_data("cmd", "/run backend")),
                    InlineKeyboardButton(text="Run all", callback_data=_encode_callback_data("cmd", "/run all")),
                ],
                [
                    InlineKeyboardButton(text="Running", callback_data=_encode_callback_data("cmd", "/running")),
                ],
                [
                    InlineKeyboardButton(text="Restart", callback_data=_encode_callback_data("cmd", "/restart")),
                    InlineKeyboardButton(text="Stop", callback_data=_encode_callback_data("cmd", "/stop")),
                ],
                [
                    InlineKeyboardButton(text="Stop all", callback_data=_encode_callback_data("cmd", "/stop all")),
                    InlineKeyboardButton(text="Logs backend", callback_data=_encode_callback_data("cmd", "/logs backend")),
                ],
                [InlineKeyboardButton(text="Logs frontend", callback_data=_encode_callback_data("cmd", "/logs frontend"))],
                [InlineKeyboardButton(text="Back", callback_data=_encode_callback_data("help", "quick"))],
            ]
        )
    if key == "create":
        return InlineKeyboardMarkup(
            [
                [
                    InlineKeyboardButton(text="Project help", callback_data=_encode_callback_data("help", "project")),
                    InlineKeyboardButton(text="Runtime help", callback_data=_encode_callback_data("help", "runtime")),
                ],
                [InlineKeyboardButton(text="Back", callback_data=_encode_callback_data("help", "quick"))],
            ]
        )
    if key == "project":
        return InlineKeyboardMarkup(
            [
                [
                    InlineKeyboardButton(text="Inspect", callback_data=_encode_callback_data("cmd", "/inspect")),
                    InlineKeyboardButton(text="Next", callback_data=_encode_callback_data("cmd", "/next")),
                ],
                [InlineKeyboardButton(text="Improve", callback_data=_encode_callback_data("cmd", "/improve"))],
                [InlineKeyboardButton(text="Back", callback_data=_encode_callback_data("help", "quick"))],
            ]
        )
    if key == "deploy":
        return InlineKeyboardMarkup(
            [
                [
                    InlineKeyboardButton(text="Deploy local", callback_data=_encode_callback_data("cmd", "/deploy local")),
                    InlineKeyboardButton(text="Deploy railway", callback_data=_encode_callback_data("cmd", "/deploy railway")),
                ],
                [InlineKeyboardButton(text="Back", callback_data=_encode_callback_data("help", "quick"))],
            ]
        )
    if key == "code":
        return InlineKeyboardMarkup(
            [
                [
                    InlineKeyboardButton(text="Tree", callback_data=_encode_callback_data("cmd", "/tree")),
                    InlineKeyboardButton(text="Diff", callback_data=_encode_callback_data("cmd", "/diff")),
                ],
                [InlineKeyboardButton(text="Back", callback_data=_encode_callback_data("help", "quick"))],
            ]
        )
    if key in {"cleanup", "all"}:
        return InlineKeyboardMarkup([[InlineKeyboardButton(text="Back", callback_data=_encode_callback_data("help", "quick"))]])
    return None


def _help_topic_text(topic: str) -> str:
    key = str(topic or "").strip().lower()
    if key in ("", "quick"):
        return _help_quick_text()
    if key in {"create", "runtime", "project", "deploy", "code", "cleanup"}:
        return _help_section_text(key)
    if key in {"all", "full"}:
        return _help_text()
    if key == "idea":
        return (
            "/idea <idea>\n\n"
            "Generate a new project from an idea.\n\n"
            "Example:\n"
            " /idea simple notes api with fastapi"
        )
    if key == "deploy":
        return (
            "/deploy local\n"
            "/deploy railway\n\n"
            "Deploy current project to target runtime."
        )
    if key == "logs":
        return (
            "/logs\n"
            "/logs backend\n"
            "/logs frontend\n\n"
            "Show local runtime logs (default: backend + frontend, last 20 lines)."
        )
    if key == "delete":
        return (
            "/delete_project\n"
            "/delete_project repo\n"
            "/delete_project all\n\n"
            "Delete project resources.\n"
            "repo/all requires confirmation: DELETE YES"
        )
    return _help_text()


def _truncate_message(text: str, limit: int = 3900) -> str:
    if len(text) <= limit:
        return text
    return text[: limit - 3] + "..."


def _inline_keyboard_classes() -> tuple[Any, Any]:
    try:
        from telegram import InlineKeyboardButton as _InlineKeyboardButton, InlineKeyboardMarkup as _InlineKeyboardMarkup

        return _InlineKeyboardButton, _InlineKeyboardMarkup
    except Exception:
        class _InlineKeyboardButton:  # pragma: no cover - fallback only when telegram package is unavailable
            def __init__(self, text: str, callback_data: str) -> None:
                self.text = text
                self.callback_data = callback_data

        class _InlineKeyboardMarkup:  # pragma: no cover - fallback only when telegram package is unavailable
            def __init__(self, inline_keyboard: list[list[Any]]) -> None:
                self.inline_keyboard = inline_keyboard

        return _InlineKeyboardButton, _InlineKeyboardMarkup


def _remember_callback_payload(payload: str) -> str:
    raw = str(payload or "")
    digest = hashlib.sha1(raw.encode("utf-8")).hexdigest()[:20]
    _CALLBACK_PAYLOADS[digest] = raw
    if len(_CALLBACK_PAYLOADS) > 512:
        oldest = next(iter(_CALLBACK_PAYLOADS))
        _CALLBACK_PAYLOADS.pop(oldest, None)
    return digest


def _encode_callback_data(action: str, payload: str) -> str:
    action_key = str(action or "").strip().lower()
    payload_text = str(payload or "")
    direct = f"{action_key}|{payload_text}"
    if len(direct.encode("utf-8")) <= 64:
        return direct
    token = _remember_callback_payload(payload_text)
    return f"{action_key}|{token}"


def _decode_callback_data(data: str) -> tuple[str, str]:
    raw = str(data or "").strip()
    separator = "|" if "|" in raw else (":" if ":" in raw else "")
    if not separator:
        if raw.startswith("/"):
            return "suggest", raw
        return "", ""
    action, payload = raw.split(separator, 1)
    resolved = _CALLBACK_PAYLOADS.get(payload, payload)
    return str(action).strip().lower(), str(resolved)


def _parse_command_string(command_text: str) -> tuple[str, list[str]]:
    parts = [x for x in str(command_text or "").strip().split() if x]
    if not parts:
        return "", []
    return parts[0].lower(), parts[1:]


def _normalize_recommended_command(text: str) -> str:
    raw = str(text or "").strip()
    if not raw:
        return ""
    lowered = raw.lower()
    if lowered.startswith("command:"):
        raw = raw.split(":", 1)[1].strip()
        lowered = raw.lower()
    if lowered.startswith("run "):
        raw = raw[4:].strip()
    if not raw.startswith("/"):
        return ""
    cmd, args = _parse_command_string(raw)
    if not cmd:
        return ""
    if args:
        return " ".join([cmd] + args)
    return cmd


def _normalize_recommended_action_text(text: str) -> str:
    normalized = _normalize_recommended_command(text)
    if normalized:
        return normalized
    return str(text or "").strip()


def _extract_recommended_commands_from_text(text: str) -> list[str]:
    commands: list[str] = []
    for raw in str(text or "").splitlines():
        line = str(raw).strip()
        if not line:
            continue
        if line.startswith("- "):
            line = line[2:].strip()
        cmd = _normalize_recommended_command(line)
        if cmd and cmd not in commands:
            commands.append(cmd)
    return commands


def _command_handler_map() -> dict[str, Any]:
    return {
        "/help": command_help,
        "/inspect": command_inspect,
        "/next": command_next,
        "/improve": command_improve,
        "/running": command_running,
        "/restart": command_restart,
        "/fix": command_fix,
        "/retry": command_retry,
        "/logs": command_logs,
        "/deploy": command_deploy,
        "/run": command_run,
        "/stop": command_stop,
        "/tree": command_tree,
        "/diff": command_diff,
        "/continue": command_continue,
        "/projects": command_projects,
        "/current": command_current,
        "/use": command_use,
        "/add_entity": command_add_entity,
        "/add_field": command_add_field,
        "/add_api": command_add_api,
        "/add_page": command_add_page,
    }


async def _dispatch_command_text(update: Any, context: Any, command_text: str) -> bool:
    cmd, args = _parse_command_string(command_text)
    handler = _command_handler_map().get(cmd)
    if handler is None:
        return False
    context.args = args
    await handler(update, context)
    return True


def _build_action_keyboard(commands: list[str], *, max_buttons: int = 6) -> Any:
    unique: list[str] = []
    for item in commands:
        cmd = _normalize_recommended_command(item)
        if not cmd or cmd in unique:
            continue
        unique.append(cmd)
        if len(unique) >= max_buttons:
            break
    if not unique:
        return None
    InlineKeyboardButton, InlineKeyboardMarkup = _inline_keyboard_classes()
    rows: list[list[Any]] = []
    for idx in range(0, len(unique), 2):
        row_cmds = unique[idx : idx + 2]
        row: list[Any] = []
        for cmd in row_cmds:
            label = cmd
            if len(label) > 28:
                label = label[:25] + "..."
            row.append(InlineKeyboardButton(text=label, callback_data=_encode_callback_data("cmd", cmd)))
        rows.append(row)
    return InlineKeyboardMarkup(rows)


def _resolve_project_by_id(project_id: str) -> Optional[Path]:
    key = str(project_id or "").strip()
    if not key:
        return None
    projects_dir = resolve_projects_dir()
    if not projects_dir.exists() or not projects_dir.is_dir():
        return None
    for child in projects_dir.iterdir():
        if child.is_dir() and child.name == key:
            return child.resolve()
    return None


def _build_callback_update_context(update: Any, context: Any, args: list[str]) -> tuple[Any, Any, Any, Any]:
    query = getattr(update, "callback_query", None)
    message = getattr(query, "message", None)
    callback_update = type("CallbackUpdate", (), {"message": message, "effective_chat": getattr(update, "effective_chat", None)})()
    callback_context = type(
        "CallbackContext",
        (),
        {"args": args, "application": getattr(context, "application", None)},
    )()
    return query, message, callback_update, callback_context


def _no_active_project_guidance() -> str:
    return (
        "No active project.\n\n"
        "To start a project:\n\n"
        "1. /design <idea>\n"
        "2. /plan <idea>\n"
        "3. /idea_local <idea>\n\n"
        "or\n\n"
        "1. /projects\n"
        "2. /use <n>"
    )


def _load_json(path: Path) -> Optional[dict[str, Any]]:
    if not path.exists():
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None
    return payload if isinstance(payload, dict) else None


def _ordered_modules(values: list[str]) -> list[str]:
    requested = [str(item).strip().lower() for item in values if str(item).strip()]
    seen: set[str] = set()
    ordered: list[str] = []
    for mod in SUPPORTED_MODULES:
        if mod in requested and mod not in seen:
            seen.add(mod)
            ordered.append(mod)
    for mod in requested:
        if mod not in seen:
            seen.add(mod)
            ordered.append(mod)
    return ordered


def _normalize_entity_name(value: str) -> str:
    text = str(value or "").strip()
    if not text:
        return ""
    return text[0].upper() + text[1:]


def _normalize_entities(values: Any) -> list[dict[str, Any]]:
    if not isinstance(values, list):
        return []
    normalized: list[dict[str, Any]] = []
    seen: set[str] = set()
    for item in values:
        name = ""
        fields: list[dict[str, str]] = []
        if isinstance(item, dict):
            name = _normalize_entity_name(str(item.get("name") or ""))
            fields_raw = item.get("fields") if isinstance(item.get("fields"), list) else []
            seen_fields: set[str] = set()
            for field in fields_raw:
                if not isinstance(field, dict):
                    continue
                field_name = str(field.get("name") or "").strip()
                field_type = str(field.get("type") or "").strip().lower()
                if not field_name or not field_type:
                    continue
                key = field_name.lower()
                if key in seen_fields:
                    continue
                seen_fields.add(key)
                fields.append({"name": field_name, "type": field_type})
        elif isinstance(item, str):
            name = _normalize_entity_name(item)
        if not name:
            continue
        key = name.lower()
        if key in seen:
            continue
        seen.add(key)
        normalized.append({"name": name, "fields": fields})
    return normalized


def _entity_names(entities: Any) -> list[str]:
    return [str(item.get("name")) for item in _normalize_entities(entities) if str(item.get("name") or "").strip()]


def _entity_slug(entity_name: str) -> str:
    normalized = _normalize_entity_name(entity_name)
    if not normalized:
        return ""
    return re.sub(r"(?<!^)(?=[A-Z])", "_", normalized).lower()


def _entity_exists_in_files(project_path: Path, entity_name: str) -> bool:
    slug = _entity_slug(entity_name)
    if not slug:
        return False
    model_path = project_path / "app" / "models" / f"{slug}.py"
    schema_path = project_path / "app" / "schemas" / f"{slug}.py"
    return model_path.exists() or schema_path.exists()


def _find_entity_in_spec(entities: list[dict[str, Any]], entity_name: str) -> Optional[dict[str, Any]]:
    key = _normalize_entity_name(entity_name).lower()
    if not key:
        return None
    for entity in entities:
        if str(entity.get("name") or "").strip().lower() == key:
            return entity
    return None


def _entity_summaries(entities: Any) -> list[str]:
    summaries: list[str] = []
    for entity in _normalize_entities(entities):
        name = str(entity.get("name") or "").strip()
        if not name:
            continue
        fields = entity.get("fields") if isinstance(entity.get("fields"), list) else []
        pairs: list[str] = []
        for field in fields:
            if not isinstance(field, dict):
                continue
            field_name = str(field.get("name") or "").strip()
            field_type = str(field.get("type") or "").strip().lower()
            if field_name and field_type:
                pairs.append(f"{field_name}:{field_type}")
        summaries.append(f"{name}({', '.join(pairs)})" if pairs else name)
    return summaries


def _entity_summaries_for_inspect(entities: Any, max_fields: int = 5) -> list[str]:
    summaries: list[str] = []
    for entity in _normalize_entities(entities):
        name = str(entity.get("name") or "").strip()
        if not name:
            continue
        fields = entity.get("fields") if isinstance(entity.get("fields"), list) else []
        pairs: list[str] = []
        for field in fields:
            if not isinstance(field, dict):
                continue
            field_name = str(field.get("name") or "").strip()
            field_type = str(field.get("type") or "").strip().lower()
            if field_name and field_type:
                pairs.append(f"{field_name}:{field_type}")
        if len(pairs) > max_fields:
            shown = ", ".join(pairs[:max_fields])
            summaries.append(f"{name}({shown}, ... +{len(pairs) - max_fields} more)")
        elif pairs:
            summaries.append(f"{name}({', '.join(pairs)})")
        else:
            summaries.append(name)
    return summaries


def _entity_tree_lines_for_inspect(entities: Any, max_entities: int = 10, max_fields: int = 8) -> list[str]:
    lines: list[str] = []
    normalized = _normalize_entities(entities)
    if not normalized:
        return ["- (none)"]
    for entity in normalized[:max_entities]:
        name = str(entity.get("name") or "").strip()
        if not name:
            continue
        lines.append(f"- {name}")
        fields = entity.get("fields") if isinstance(entity.get("fields"), list) else []
        pairs: list[str] = []
        for field in fields:
            if not isinstance(field, dict):
                continue
            field_name = str(field.get("name") or "").strip()
            field_type = str(field.get("type") or "").strip().lower()
            if field_name and field_type:
                pairs.append(f"{field_name}:{field_type}")
        if not pairs:
            lines.append("  - (no fields)")
            continue
        for pair in pairs[:max_fields]:
            lines.append(f"  - {pair}")
        if len(pairs) > max_fields:
            lines.append(f"  - ... +{len(pairs) - max_fields} more fields")
    extra_entities = len(normalized) - max_entities
    if extra_entities > 0:
        lines.append(f"- ... +{extra_entities} more entities")
    return lines


def _append_truncated_bullets(lines: list[str], title: str, items: list[str], limit: int, suffix_label: str) -> None:
    if not items:
        return
    lines += ["", title]
    for item in items[:limit]:
        lines.append(f"- {item}")
    extra = len(items) - limit
    if extra > 0:
        lines.append(f"- ... +{extra} more {suffix_label}")


def _entity_endpoint_set(entity_name: str) -> list[str]:
    normalized = _normalize_entity_name(entity_name)
    if not normalized:
        return []
    slug = re.sub(r"(?<!^)(?=[A-Z])", "_", normalized).lower()
    plural = f"{slug}s"
    return [
        f"GET /{plural}",
        f"POST /{plural}",
        f"GET /{plural}/{{id}}",
        f"PATCH /{plural}/{{id}}",
        f"DELETE /{plural}/{{id}}",
    ]


def _normalize_api_path(value: str) -> str:
    path = str(value or "").strip()
    if not path:
        return ""
    if not path.startswith("/"):
        path = "/" + path
    path = re.sub(r"/{2,}", "/", path)
    if " " in path:
        return ""
    return path


def _normalize_api_endpoint(method: str, path: str) -> tuple[str, str, str]:
    normalized_method = str(method or "").strip().upper()
    normalized_path = _normalize_api_path(path)
    if normalized_method not in set(SUPPORTED_API_METHODS):
        return "", "", ""
    if not normalized_path:
        return "", "", ""
    return normalized_method, normalized_path, f"{normalized_method} {normalized_path}"


def _normalize_api_endpoint_text(value: str) -> str:
    text = str(value or "").strip()
    if not text:
        return ""
    parts = text.split(maxsplit=1)
    if len(parts) != 2:
        return ""
    _, _, endpoint = _normalize_api_endpoint(parts[0], parts[1])
    return endpoint


def _rebuild_api_endpoints(spec: dict[str, Any]) -> list[str]:
    endpoints: list[str] = []
    seen: set[str] = set()
    existing = spec.get("api_endpoints")
    if isinstance(existing, list):
        for item in existing:
            endpoint = _normalize_api_endpoint_text(str(item))
            if not endpoint:
                continue
            key = endpoint.upper()
            if key in seen:
                continue
            seen.add(key)
            endpoints.append(endpoint)
    for entity in _normalize_entities(spec.get("entities")):
        name = str(entity.get("name") or "").strip()
        for endpoint in _entity_endpoint_set(name):
            key = endpoint.upper()
            if key in seen:
                continue
            seen.add(key)
            endpoints.append(endpoint)
    spec["api_endpoints"] = endpoints
    return endpoints


def _entity_frontend_pages(entity_name: str) -> list[str]:
    normalized = _normalize_entity_name(entity_name)
    if not normalized:
        return []
    slug = re.sub(r"(?<!^)(?=[A-Z])", "_", normalized).lower()
    plural = f"{slug}s"
    return [f"{plural}/list", f"{plural}/detail"]


def _normalize_frontend_page_path(value: str) -> str:
    page = str(value or "").strip().replace("\\", "/")
    page = re.sub(r"/{2,}", "/", page).strip("/")
    if not page or " " in page:
        return ""
    return page


def _rebuild_frontend_pages(spec: dict[str, Any]) -> list[str]:
    pages: list[str] = []
    seen: set[str] = set()
    existing = spec.get("frontend_pages")
    if isinstance(existing, list):
        for item in existing:
            page = _normalize_frontend_page_path(str(item))
            if not page:
                continue
            key = page.lower()
            if key in seen:
                continue
            seen.add(key)
            pages.append(page)
    for entity in _normalize_entities(spec.get("entities")):
        name = str(entity.get("name") or "").strip()
        for page in _entity_frontend_pages(name):
            key = page.lower()
            if key in seen:
                continue
            seen.add(key)
            pages.append(page)
    spec["frontend_pages"] = pages
    return pages


def _merge_entities(existing: Any, incoming: Any) -> tuple[list[dict[str, Any]], int]:
    base = _normalize_entities(existing)
    add = _normalize_entities(incoming)
    seen = {str(item.get("name") or "").strip().lower() for item in base}
    merged = list(base)
    added = 0
    for entity in add:
        name = str(entity.get("name") or "").strip()
        if not name:
            continue
        key = name.lower()
        if key in seen:
            continue
        seen.add(key)
        merged.append(entity)
        added += 1
    return merged, added


def _merge_string_list(existing: Any, incoming: Any) -> tuple[list[str], int]:
    current = [str(x).strip() for x in (existing or []) if str(x).strip()] if isinstance(existing, list) else []
    to_add = [str(x).strip() for x in (incoming or []) if str(x).strip()] if isinstance(incoming, list) else []
    seen = set(current)
    added = 0
    for item in to_add:
        if item in seen:
            continue
        seen.add(item)
        current.append(item)
        added += 1
    return current, added


def _auto_restart_backend_lines(project_path: Path) -> tuple[list[str], bool]:
    try:
        from archmind.deploy import get_local_runtime_status, restart_local_services
    except Exception:
        return (["Auto-restart:", "Skipped (runtime unavailable)"], False)

    runtime = get_local_runtime_status(project_path)
    backend = runtime.get("backend") if isinstance(runtime, dict) else {}
    backend_status = str((backend or {}).get("status") or "").strip().upper()
    if backend_status != "RUNNING":
        return (["Auto-restart:", "Skipped (backend not running)"], False)

    result = restart_local_services(project_path)
    runtime_after = get_local_runtime_status(project_path)
    backend_after = runtime_after.get("backend") if isinstance(runtime_after, dict) else {}
    after_status = str((backend_after or {}).get("status") or "").strip().upper()

    if after_status == "RUNNING":
        return (["Auto-restart:", "Backend: RESTARTED"], False)

    restart_backend = result.get("backend") if isinstance(result, dict) and isinstance(result.get("backend"), dict) else {}
    detail = str(restart_backend.get("detail") or "").strip()
    lines = ["Auto-restart:", f"Backend: {after_status or 'FAILED'}"]
    if detail:
        lines += ["Detail:", detail]
    return (lines, True)


def _ensure_evolution_block(spec: dict[str, Any]) -> dict[str, Any]:
    evolution_raw = spec.get("evolution")
    evolution = evolution_raw if isinstance(evolution_raw, dict) else {}
    version = int(evolution.get("version") or 1)
    added_modules = evolution.get("added_modules")
    history = evolution.get("history")
    evolution["version"] = version if version > 0 else 1
    evolution["added_modules"] = _ordered_modules(added_modules if isinstance(added_modules, list) else [])
    evolution["history"] = history if isinstance(history, list) else []
    spec["evolution"] = evolution
    return evolution


def _append_evolution_event(spec: dict[str, Any], event: dict[str, Any]) -> None:
    evolution = _ensure_evolution_block(spec)
    history = evolution.get("history") if isinstance(evolution.get("history"), list) else []
    history.append(dict(event))
    evolution["history"] = history
    evolution["history"] = history


def _format_evolution_event(event: Any) -> str:
    if not isinstance(event, dict):
        return ""
    action = str(event.get("action") or "").strip()
    if not action:
        return ""

    if action == "add_entity":
        entity = str(event.get("entity") or "").strip()
        return f"add_entity {entity}".strip()
    if action == "add_field":
        entity = str(event.get("entity") or "").strip()
        field = str(event.get("field") or "").strip()
        field_type = str(event.get("type") or "").strip()
        suffix = f"{field}:{field_type}" if field and field_type else field
        return f"add_field {entity} {suffix}".strip()
    if action == "add_api":
        method = str(event.get("method") or "").strip().upper()
        path = str(event.get("path") or "").strip()
        return f"add_api {method} {path}".strip()
    if action == "auto_add_api":
        method = str(event.get("method") or "").strip().upper()
        path = str(event.get("path") or "").strip()
        return f"auto_add_api {method} {path}".strip()
    if action == "add_page":
        page = str(event.get("page") or "").strip()
        return f"add_page {page}".strip()
    if action == "auto_add_page":
        page = str(event.get("page") or "").strip()
        return f"auto_add_page {page}".strip()
    if action == "add_module":
        module = str(event.get("module") or "").strip()
        return f"add_module {module}".strip()

    details: list[str] = []
    for key in ("entity", "field", "type", "method", "path", "page", "module"):
        value = str(event.get(key) or "").strip()
        if value:
            details.append(value)
    return f"{action} {' '.join(details)}".strip()


def summarize_recent_evolution(spec_or_history: Any, limit: int = 5) -> list[str]:
    history: list[Any]
    if isinstance(spec_or_history, dict):
        evolution = spec_or_history.get("evolution") if isinstance(spec_or_history.get("evolution"), dict) else {}
        raw_history = evolution.get("history")
        history = raw_history if isinstance(raw_history, list) else []
    elif isinstance(spec_or_history, list):
        history = spec_or_history
    else:
        history = []

    clipped = history[-max(1, int(limit)) :] if history else []
    lines: list[str] = []
    for item in clipped:
        text = _format_evolution_event(item)
        if text:
            lines.append(text)
    return lines


def _read_or_init_project_spec(project_path: Path) -> tuple[dict[str, Any], Path]:
    spec_path = project_path / ".archmind" / "project_spec.json"
    spec = _load_json(spec_path) or {}
    reasoning = _load_json(project_path / ".archmind" / "architecture_reasoning.json") or {}
    state = _load_json(project_path / ".archmind" / "state.json") or {}

    if "shape" not in spec:
        spec["shape"] = str(reasoning.get("app_shape") or "unknown")
    if "domains" not in spec or not isinstance(spec.get("domains"), list):
        spec["domains"] = [str(x) for x in (reasoning.get("domains") or []) if str(x).strip()]
    if "template" not in spec or not str(spec.get("template") or "").strip():
        spec["template"] = str(
            state.get("effective_template") or reasoning.get("recommended_template") or state.get("selected_template") or "fastapi"
        )
    if "modules" not in spec or not isinstance(spec.get("modules"), list):
        spec["modules"] = [str(x) for x in (reasoning.get("modules") or []) if str(x).strip()]
    spec["modules"] = _ordered_modules([str(x) for x in (spec.get("modules") or [])])
    if "reason_summary" not in spec:
        spec["reason_summary"] = str(reasoning.get("reason_summary") or "")
    spec["entities"] = _normalize_entities(spec.get("entities"))
    _rebuild_api_endpoints(spec)
    _rebuild_frontend_pages(spec)
    _ensure_evolution_block(spec)
    return spec, spec_path


def _format_brain_preview_text(idea: str) -> str:
    normalized_payload = normalize_idea(idea)
    normalized = str(normalized_payload.get("normalized") or idea)
    language = str(normalized_payload.get("language") or "en")
    reasoning = reason_architecture_from_idea(normalized)

    shape = str(reasoning.get("app_shape") or "unknown")
    template = str(reasoning.get("recommended_template") or "unknown")
    reason = str(reasoning.get("reason_summary") or "n/a")
    domains = [str(x) for x in (reasoning.get("domains") or []) if str(x).strip()]
    modules = [str(x) for x in (reasoning.get("modules") or []) if str(x).strip()]
    modules_text = "\n".join([f"- {m}" for m in modules]) if modules else "- (none)"

    return (
        "Idea analysis\n\n"
        "Shape:\n"
        f"{shape}\n\n"
        "Domains:\n"
        f"{', '.join(domains) if domains else '(none)'}\n\n"
        "Template:\n"
        f"{template}\n\n"
        "Modules:\n"
        f"{modules_text}\n\n"
        "Reason:\n"
        f"{reason}\n\n"
        "Language:\n"
        f"{language}"
    )


def get_template_suggestions(idea: str, reasoning: dict[str, Any]) -> list[str]:
    text = str(idea or "").strip().lower()
    domains = [str(x).lower() for x in (reasoning.get("domains") or [])]
    recommended = str(reasoning.get("recommended_template") or "").strip().lower()
    app_shape = str(reasoning.get("app_shape") or "unknown").strip().lower()
    internal_tool = bool(reasoning.get("internal_tool"))
    dashboard_needed = bool(reasoning.get("dashboard_needed"))
    worker_needed = bool(reasoning.get("worker_needed"))
    backend_needed = bool(reasoning.get("backend_needed"))
    frontend_needed = bool(reasoning.get("frontend_needed"))
    db_needed = bool(reasoning.get("db_needed"))
    file_upload_needed = bool(reasoning.get("file_upload_needed"))

    candidates: list[str] = []
    if recommended:
        candidates.append(recommended)
    if internal_tool and dashboard_needed:
        candidates.append("internal-tool")
    if worker_needed and backend_needed and not frontend_needed:
        candidates.append("worker-api")

    data_domains = {"inventory", "reports", "analytics", "data"}
    if (set(domains) & data_domains) and (dashboard_needed or db_needed or "tool" in text):
        candidates.append("data-tool")

    if app_shape == "fullstack":
        candidates.append("fullstack-ddd")
    elif app_shape == "backend":
        candidates.append("fastapi")
    elif app_shape == "frontend":
        candidates.append("nextjs")
    else:
        candidates.extend(["internal-tool", "data-tool", "fullstack-ddd", "fastapi", "worker-api", "nextjs"])

    if file_upload_needed and dashboard_needed:
        candidates.extend(["internal-tool", "data-tool"])

    deduped: list[str] = []
    seen: set[str] = set()
    for item in candidates:
        val = str(item).strip().lower()
        if not val or val in seen:
            continue
        seen.add(val)
        deduped.append(val)
    return deduped[:6]


def _status_from_sources(project_dir: Path) -> str:
    project_dir = project_dir.expanduser().resolve()
    archmind_dir = project_dir / ".archmind"
    evaluation = _load_json(archmind_dir / "evaluation.json") or {}
    state = load_state(project_dir) or {}
    result = _load_json(archmind_dir / "result.json") or {}
    if not (evaluation or state or result):
        return "UNKNOWN"

    eval_status = str(evaluation.get("status") or "").strip().upper()
    if eval_status in {"STUCK", "BLOCKED"}:
        return eval_status

    final_status = str(result.get("final_status") or state.get("final_status") or "").strip().upper()
    if final_status == "DONE":
        return "DONE"

    if not eval_status:
        raw_status = str(result.get("status") or state.get("last_status") or "").strip().upper()
        if raw_status in {"FAIL", "FAILED", "ERROR", "PARTIAL", "NOT_DONE"}:
            return "NOT_DONE"

    steps = result.get("steps") if isinstance(result.get("steps"), dict) else {}
    generation_failed = False
    generate_step = steps.get("generate") if isinstance(steps, dict) else {}
    if isinstance(generate_step, dict):
        if generate_step.get("ok") is False:
            generation_failed = True
        if str(generate_step.get("failure_class") or "").strip():
            generation_failed = True

    runtime_block = state.get("runtime") if isinstance(state.get("runtime"), dict) else {}
    explicit_runtime_failure = str(
        _state_block_value(
            runtime_block,
            "failure_class",
            state.get("runtime_failure_class") or state.get("last_failure_class"),
        )
        or ""
    ).strip()

    runtime_ctx = _improve_runtime_context(project_dir, state)
    runtime_failure = str(runtime_ctx.get("failure_class") or "").strip()
    detect_ok = bool(runtime_ctx.get("detect_ok"))
    detect_required = _runtime_detect_required(project_dir, state, result)
    if generation_failed:
        return "NOT_DONE"
    if explicit_runtime_failure:
        return "NOT_DONE"
    if runtime_failure and (detect_ok or detect_required):
        return "NOT_DONE"

    step_failed = False
    for key in ("run_before_fix", "run_after_fix"):
        step = steps.get(key) if isinstance(steps, dict) else {}
        if not isinstance(step, dict):
            continue
        detail = step.get("detail") if isinstance(step.get("detail"), dict) else {}
        backend_status = str((detail.get("backend_status") if isinstance(detail, dict) else "") or step.get("status") or "").strip().upper()
        frontend_status = str((detail.get("frontend_status") if isinstance(detail, dict) else "") or "").strip().upper()
        if backend_status == "FAIL" or frontend_status == "FAIL":
            step_failed = True
            break
    if step_failed:
        return "NOT_DONE"

    if detect_required and not detect_ok:
        return "NOT_DONE"

    if detect_ok:
        return "DONE"

    if final_status == "NOT_DONE":
        return "NOT_DONE"

    if eval_status in {"DONE", "NOT_DONE"}:
        return eval_status

    return "DONE"


def _runtime_detect_required(project_dir: Path, state: dict[str, Any], result: dict[str, Any]) -> bool:
    root = project_dir.expanduser().resolve()
    if (
        (root / "app" / "main.py").exists()
        or (root / "backend" / "app" / "main.py").exists()
        or (root / "requirements.txt").exists()
        or (root / "backend" / "requirements.txt").exists()
    ):
        return True

    runtime_block = state.get("runtime") if isinstance(state.get("runtime"), dict) else {}
    runtime_signals = (
        "backend_entry",
        "backend_run_mode",
        "backend_run_command",
        "backend_status",
        "failure_class",
    )
    if any(str(_state_block_value(runtime_block, key, state.get(key)) or "").strip() for key in runtime_signals):
        return True

    steps = result.get("steps") if isinstance(result.get("steps"), dict) else {}
    for key in ("run_before_fix", "run_after_fix"):
        step = steps.get(key) if isinstance(steps, dict) else {}
        if isinstance(step, dict) and step:
            return True
    return False


def _current_runtime_actionable_failure(project_dir: Path, state: dict[str, Any], result: dict[str, Any]) -> bool:
    project_dir = project_dir.expanduser().resolve()
    runtime_block = state.get("runtime") if isinstance(state.get("runtime"), dict) else {}
    explicit_runtime_failure = str(
        _state_block_value(
            runtime_block,
            "failure_class",
            state.get("runtime_failure_class") or state.get("last_failure_class"),
        )
        or ""
    ).strip()
    if explicit_runtime_failure:
        return True

    steps = result.get("steps") if isinstance(result.get("steps"), dict) else {}
    generate_step = steps.get("generate") if isinstance(steps, dict) else {}
    if isinstance(generate_step, dict) and (
        generate_step.get("ok") is False or str(generate_step.get("failure_class") or "").strip()
    ):
        return True

    runtime_ctx = _improve_runtime_context(project_dir, state or {})
    detect_ok = bool(runtime_ctx.get("detect_ok"))
    detect_required = _runtime_detect_required(project_dir, state or {}, result or {})
    runtime_failure = str(runtime_ctx.get("failure_class") or "").strip()
    if runtime_failure and (detect_ok or detect_required):
        return True
    if detect_required and not detect_ok:
        return True
    for key in ("run_before_fix", "run_after_fix"):
        step = steps.get(key) if isinstance(steps, dict) else {}
        if not isinstance(step, dict):
            continue
        detail = step.get("detail") if isinstance(step.get("detail"), dict) else {}
        backend_status = str((detail.get("backend_status") if isinstance(detail, dict) else "") or step.get("status") or "").strip().upper()
        frontend_status = str((detail.get("frontend_status") if isinstance(detail, dict) else "") or "").strip().upper()
        if backend_status == "FAIL" or frontend_status == "FAIL":
            return True
    return False


def _progress_fallback_for_command(command: str) -> str:
    cmd = str(command or "").strip().lower()
    if cmd in ("/idea", "/pipeline", "/idea_local"):
        return "Planning architecture"
    if cmd == "/continue":
        return "Running checks"
    if cmd == "/fix":
        return "Applying fixes"
    if cmd == "/retry":
        return "Applying fixes"
    return "Running"


def _progress_text(project_dir: Path, fallback: str = "") -> str:
    state = _load_json(project_dir / ".archmind" / "state.json") or {}
    label = str(state.get("current_step_label") or "").strip()
    detail = str(state.get("current_step_detail") or "").strip()
    if label and detail:
        return f"{label} ({detail})"
    if label:
        return label
    return fallback or "unknown"


def _current_task_label(project_dir: Path, status: str) -> Optional[str]:
    archmind_dir = project_dir / ".archmind"
    state = load_state(project_dir) or {}
    signature = str(state.get("last_failure_signature") or "").strip()
    derived_label = str(state.get("derived_task_label") or "").strip() or derive_task_label_from_failure_signature(signature)
    if derived_label and str(status).upper() == "STUCK":
        return derived_label
    if derived_label:
        return derived_label
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


def _humanize_summary_line(line: str) -> str:
    text = str(line or "").strip()
    if not text:
        return ""
    text = text.lstrip("-").strip()
    lower = text.lower()
    if lower.startswith("command:"):
        return ""
    if lower.startswith("project_dir:"):
        return ""
    if lower.startswith("timestamp:"):
        return ""
    if lower.startswith("current_task:"):
        return ""
    if lower.startswith("generate:"):
        return ""
    if lower.startswith("state:"):
        return ""
    if lower.startswith("task queue:"):
        return ""
    if lower.startswith("cwd:"):
        return ""
    if lower.startswith("duration"):
        return ""
    if "strict (recommended)" in lower:
        return ""
    if "how would you like to configure eslint" in lower:
        return ""
    if "need to disable some eslint rules" in lower:
        return ""
    if "learn more here: https://nextjs.org/docs/app/api-reference/config/eslint#disabling-rules" in lower:
        return ""
    if "next.js eslint plugin" in lower:
        return ""
    if lower.startswith("base") or lower.startswith("cancel"):
        return ""
    if "{" in text and "}" in text:
        return ""
    if "backend" in lower and ("fail" in lower or "failed" in lower):
        if "pytest" in lower or "test" in lower:
            return "Backend tests still failing"
        return "Backend step still failing"
    if "frontend" in lower and "lint" in lower and ("fail" in lower or "failed" in lower):
        return "Frontend lint still failing"
    if "frontend" in lower and "build" in lower and ("fail" in lower or "failed" in lower):
        return "Frontend build still failing"
    if "further work remains" in lower:
        return "Further work remains"
    if "latest run failed" in lower:
        return "Latest run failed"
    if "status:" in lower:
        value = text.split(":", 1)[1].strip() if ":" in text else text
        return f"Status detail: {value}"
    return text[:140]


def _result_summary_lines(project_dir: Path, temp_log: Path) -> list[str]:
    archmind_dir = project_dir / ".archmind"
    result_txt = archmind_dir / "result.txt"
    if result_txt.exists():
        lines = [line.strip() for line in result_txt.read_text(encoding="utf-8", errors="replace").splitlines()]
        lines = [line for line in lines if line and not line.startswith("ArchMind Pipeline Result")]
        out: list[str] = []
        for line in lines:
            cleaned = _humanize_summary_line(line)
            if cleaned and cleaned not in out:
                out.append(cleaned)
        return out[:8]

    result_json = _load_json(archmind_dir / "result.json")
    if result_json:
        lines: list[str] = []
        if result_json.get("status"):
            lines.append(f"Status detail: {result_json.get('status')}")
        evaluation = result_json.get("evaluation")
        if isinstance(evaluation, dict) and evaluation.get("status"):
            lines.append(f"Evaluation status: {evaluation.get('status')}")
        steps = result_json.get("steps")
        if isinstance(steps, dict):
            run_before = steps.get("run_before_fix")
            if isinstance(run_before, dict):
                step_status = run_before.get("status")
                if step_status:
                    lines.append(f"Run before fix: {step_status}")
        out: list[str] = []
        for line in lines:
            cleaned = _humanize_summary_line(line)
            if cleaned and cleaned not in out:
                out.append(cleaned)
        return out[:8]

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
            out: list[str] = []
            for line in lines:
                cleaned = _humanize_summary_line(line)
                if cleaned and cleaned not in out:
                    out.append(cleaned)
            return out[:8]

    if temp_log.exists():
        lines = temp_log.read_text(encoding="utf-8", errors="replace").splitlines()
        tail = [line.strip() for line in lines[-20:] if line.strip()]
        out: list[str] = []
        for line in tail:
            cleaned = _humanize_summary_line(line)
            if cleaned and cleaned not in out:
                out.append(cleaned)
        return out[-8:]

    return ["no summary available"]


def sanitize_log_excerpt(text: str, max_lines: int = 40) -> str:
    if not text:
        return ""
    ansi_escape = re.compile(r"\x1b\[[0-9;]*[a-zA-Z]")
    cleaned_lines: list[str] = []
    for raw in text.splitlines():
        line = ansi_escape.sub("", raw).strip()
        if not line:
            continue
        lower = line.lower()
        if lower.startswith("command:") or lower.startswith("$ archmind"):
            continue
        if lower.startswith(("project_dir:", "timestamp:", "cwd:", "duration", "base", "cancel")):
            continue
        if "strict (recommended)" in lower:
            continue
        if "how would you like to configure eslint" in lower:
            continue
        if "if you set up eslint yourself" in lower:
            continue
        if "need to disable some eslint rules" in lower:
            continue
        if "learn more here: https://nextjs.org/docs/app/api-reference/config/eslint#disabling-rules" in lower:
            continue
        if "next.js eslint plugin" in lower:
            continue
        if lower in ("traceback:", "-----", "=====", "---", "==="):
            continue
        line = re.sub(r"\s+", " ", line)
        line = re.sub(r"/(?:Users|home)/[^ ]+/([^/ ]+)", r".../\1", line)
        line = re.sub(r"/tmp/[^ ]+/([^/ ]+)", r".../\1", line)
        cleaned_lines.append(line)
    if not cleaned_lines:
        return ""
    return "\n".join(cleaned_lines[:max_lines])


def extract_key_error_lines(text: str, max_lines: int = 6) -> list[str]:
    lines = sanitize_log_excerpt(text, max_lines=120).splitlines()
    priority_patterns = [
        r"AssertionError",
        r"ModuleNotFoundError",
        r"ImportError",
        r"^FAILED ",
        r"^E\s+",
        r"\bTS2304\b|\bTS2322\b|is not assignable",
        r"ESLint|Parsing error|Cannot find module",
        r"npm ERR!",
        r"build failed|failed to compile|next build|vite build",
        r"\.py:\d+|\.tsx?:\d+",
    ]
    picked: list[str] = []
    for pattern in priority_patterns:
        rx = re.compile(pattern, flags=re.IGNORECASE)
        for line in lines:
            if rx.search(line) and line not in picked:
                picked.append(line)
                if len(picked) >= max_lines:
                    return picked
    for line in lines:
        if line not in picked:
            picked.append(line)
            if len(picked) >= max_lines:
                break
    return picked


def _first_matching_path(key_lines: list[str], patterns: tuple[str, ...]) -> str:
    for line in key_lines:
        for pat in patterns:
            match = re.search(pat, line, flags=re.IGNORECASE)
            if match:
                return str(match.group(1)).strip()
    return ""


def build_log_focus(log_type: str, failure_class: Optional[str], key_lines: list[str]) -> list[str]:
    klass = str(failure_class or "").lower()
    frontend_path = _first_matching_path(
        key_lines,
        (
            r"((?:frontend/)?(?:app|pages)/[^\s:]+\.(?:tsx?|jsx?))(?::\d+)?",
            r"((?:frontend/)?[^\s:]+\.(?:tsx?|jsx?))(?::\d+)?",
        ),
    )
    backend_path = _first_matching_path(
        key_lines,
        (
            r"(tests/[^\s:]+\.py)(?::\d+)?",
            r"(app/[^\s:]+\.py)(?::\d+)?",
        ),
    )

    if klass == "backend-pytest:assertion":
        if backend_path:
            return [f"inspect pytest failure in {backend_path}", "compare API response with test expectations"]
        return ["inspect backend implementation", "compare API response with test expectations"]
    if klass in ("backend-pytest:import", "backend-pytest:module-not-found"):
        if backend_path:
            return [f"inspect import/module path in {backend_path}"]
        return ["inspect imports and module paths"]
    if klass in ("backend-pytest:other", "backend-dependency"):
        if backend_path:
            return [f"inspect pytest failure in {backend_path}"]
        return ["inspect pytest failure"]
    if klass == "frontend-lint-warning":
        if frontend_path:
            return [f"inspect frontend warning file {frontend_path}", "promote to fail only when real errors exist"]
        return ["review frontend lint warnings", "promote to fail only when real errors exist"]
    if klass == "frontend-lint":
        if frontend_path:
            return [f"inspect frontend file {frontend_path}", "inspect lint config if rule mismatch exists"]
        return ["inspect frontend lint config", "inspect failing frontend file"]
    if klass == "frontend-typescript":
        if frontend_path:
            return [f"inspect TypeScript error in {frontend_path}", "inspect shared type definitions"]
        return ["inspect type definitions", "inspect failing TS file"]
    if klass == "frontend-build":
        if frontend_path:
            return [f"inspect build failure file {frontend_path}", "inspect build config/import path"]
        return ["inspect build config/import path"]
    if klass in ("frontend-install", "frontend-missing-package"):
        return ["inspect frontend package.json and install step", "verify npm install output"]
    if klass == "environment-node-missing":
        return ["install node/npm runtime on target host"]
    if klass in ("generation-error", "runtime-entrypoint-error"):
        return ["inspect backend entrypoint and run command", "verify app/main.py structure"]
    if klass == "dependency-error":
        return ["inspect backend dependency installation", "verify requirements and virtualenv"]
    if klass == "environment-python":
        return ["inspect python environment and virtualenv"]
    if klass in ("filesystem-overwrite", "filesystem-path-validation"):
        return ["inspect path/overwrite safety constraints"]
    if log_type == "last":
        has_backend = any("assert" in line.lower() or "pytest" in line.lower() or "failed tests/" in line.lower() for line in key_lines)
        has_frontend = any("eslint" in line.lower() or "ts" in line.lower() or "frontend" in line.lower() for line in key_lines)
        if has_backend and has_frontend:
            return ["inspect backend failure first", "then inspect frontend lint issues"]
    return ["inspect recent failure details"]


def build_logs_message(
    project_name: str,
    log_type: str,
    failure: str,
    key_lines: list[str],
    focus: list[str],
) -> str:
    lines = [
        f"Logs: {log_type}",
        "",
        "Project:",
        project_name,
        "",
        "Failure:",
        failure or "unknown failure",
        "",
        "Key lines:",
    ]
    if key_lines:
        lines.extend(f"- {line}" for line in key_lines[:10])
    else:
        lines.append("- (no key lines found)")
    lines += ["", "Focus:"]
    if focus:
        lines.extend(f"- {item}" for item in focus[:3])
    else:
        lines.append("- inspect recent failure details")
    return "\n".join(lines)


def _collect_recent_failures(project_dir: Path, limit: int = 5) -> list[str]:
    state = _load_json(project_dir / ".archmind" / "state.json") or {}
    failures = state.get("recent_failures")
    if not isinstance(failures, list):
        return []
    out: list[str] = []
    for line in failures:
        item = sanitize_log_excerpt(str(line), max_lines=1).strip()
        if item and item not in out:
            out.append(item)
        if len(out) >= limit:
            break
    return out


def _latest_run_logs(project_dir: Path) -> list[Path]:
    run_logs = project_dir / ".archmind" / "run_logs"
    if not run_logs.exists():
        return []
    candidates: list[Path] = []
    for pattern in ("run_*.summary.txt", "run_*.summary.json", "run_*.log"):
        candidates.extend(run_logs.glob(pattern))
    return sorted(candidates, key=lambda p: p.stat().st_mtime, reverse=True)


def list_recent_projects(projects_dir: Optional[Path] = None, limit: int = 10) -> list[Path]:
    root = (projects_dir or resolve_projects_dir()).expanduser().resolve()
    if not root.exists() or not root.is_dir():
        return []
    projects = [path for path in root.iterdir() if path.is_dir()]
    projects.sort(key=lambda p: p.stat().st_mtime, reverse=True)
    return projects[: max(0, int(limit))]


def resolve_project_selection(selection: str, projects: Optional[list[Path]] = None) -> Optional[Path]:
    value = str(selection or "").strip()
    if not value:
        return None
    candidates = projects if projects is not None else list_recent_projects()
    if value.isdigit():
        idx = int(value)
        if idx <= 0 or idx > len(candidates):
            return None
        return candidates[idx - 1]
    for project in candidates:
        if project.name == value:
            return project
    return None


def _latest_run_summary_payload(project_dir: Path) -> dict[str, Any]:
    run_logs = project_dir / ".archmind" / "run_logs"
    if not run_logs.exists():
        return {}
    matches = sorted(run_logs.glob("run_*.summary.json"), key=lambda p: p.stat().st_mtime, reverse=True)
    if not matches:
        return {}
    payload = _load_json(matches[0])
    return payload or {}


def _detect_external_ip() -> Optional[str]:
    try:
        result = subprocess.run(
            ["tailscale", "ip", "-4"],
            capture_output=True,
            text=True,
            timeout=1,
            shell=False,
            check=False,
        )
        ip = str(result.stdout or "").strip().splitlines()[0]
        if ip:
            return ip
    except Exception:
        pass
    return None


def _external_url_for(local_url: str, external_ip: Optional[str]) -> str:
    if not external_ip:
        return ""
    text = str(local_url or "").strip()
    match = re.match(r"^https?://[^:/]+:(\d+)", text)
    if not match:
        return ""
    return f"http://{external_ip}:{match.group(1)}"


def _status_component_summary(project_dir: Path, result_payload: dict[str, Any]) -> tuple[str, str]:
    summary_payload = _latest_run_summary_payload(project_dir)
    backend = str((summary_payload.get("backend") or {}).get("status") or "").strip()
    frontend = str((summary_payload.get("frontend") or {}).get("status") or "").strip()

    if not backend or not frontend:
        steps = result_payload.get("steps") if isinstance(result_payload, dict) else {}
        if isinstance(steps, dict):
            for key in ("run_after_fix", "run_before_fix"):
                section = steps.get(key)
                detail = section.get("detail") if isinstance(section, dict) else {}
                if isinstance(detail, dict):
                    backend = backend or str(detail.get("backend_status") or "").strip()
                    frontend = frontend or str(detail.get("frontend_status") or "").strip()
                if backend and frontend:
                    break

    return (_normalize_component_status(backend), _normalize_component_status(frontend))


def _normalize_runtime_state_label(value: str) -> str:
    state = str(value or "").strip().upper()
    if state in {"RUNNING"}:
        return "RUNNING"
    if state in {"FAIL", "FAILED", "ERROR", "WARNING"}:
        return "FAIL"
    if state in {"STOPPED", "NOT RUNNING", "IDLE", "SKIPPED", "SUCCESS", ""}:
        return "STOPPED"
    return "STOPPED"


def _project_runtime_status(
    project_dir: Path,
    state_payload: dict[str, Any],
    result_payload: dict[str, Any],
    runtime_payload: Optional[dict[str, Any]] = None,
) -> str:
    runtime_block = state_payload.get("runtime") if isinstance(state_payload.get("runtime"), dict) else {}
    services = runtime_block.get("services") if isinstance(runtime_block.get("services"), dict) else {}
    backend_service = services.get("backend") if isinstance(services.get("backend"), dict) else {}
    frontend_service = services.get("frontend") if isinstance(services.get("frontend"), dict) else {}
    backend_live = runtime_payload.get("backend") if isinstance(runtime_payload, dict) and isinstance(runtime_payload.get("backend"), dict) else {}
    frontend_live = runtime_payload.get("frontend") if isinstance(runtime_payload, dict) and isinstance(runtime_payload.get("frontend"), dict) else {}

    backend_states = [
        str(backend_live.get("status") or ""),
        str(backend_service.get("status") or ""),
        str(runtime_block.get("backend_status") or ""),
    ]
    frontend_states = [
        str(frontend_live.get("status") or ""),
        str(frontend_service.get("status") or ""),
        str(runtime_block.get("frontend_status") or ""),
    ]

    normalized_backend = [_normalize_runtime_state_label(x) for x in backend_states if str(x).strip()]
    normalized_frontend = [_normalize_runtime_state_label(x) for x in frontend_states if str(x).strip()]
    runtime_signal_present = bool(normalized_backend or normalized_frontend)

    live_backend_status = _normalize_runtime_state_label(str(backend_live.get("status") or ""))
    live_frontend_status = _normalize_runtime_state_label(str(frontend_live.get("status") or ""))
    live_signal_present = bool(str(backend_live.get("status") or "").strip() or str(frontend_live.get("status") or "").strip())

    if live_signal_present:
        if live_backend_status == "RUNNING" or live_frontend_status == "RUNNING":
            return "RUNNING"
    elif "RUNNING" in normalized_backend or "RUNNING" in normalized_frontend:
        return "RUNNING"

    runtime_failure_class = str(runtime_block.get("failure_class") or "").strip()
    preflight = runtime_block.get("preflight") if isinstance(runtime_block.get("preflight"), dict) else {}
    preflight_failed = str(preflight.get("status") or "").strip().upper() == "FAILED"
    step_failed = False
    steps = result_payload.get("steps") if isinstance(result_payload.get("steps"), dict) else {}
    for key in ("run_before_fix", "run_after_fix"):
        step = steps.get(key) if isinstance(steps, dict) else {}
        if not isinstance(step, dict):
            continue
        detail = step.get("detail") if isinstance(step.get("detail"), dict) else {}
        backend_status = str((detail.get("backend_status") if isinstance(detail, dict) else "") or step.get("status") or "").strip().upper()
        frontend_status = str((detail.get("frontend_status") if isinstance(detail, dict) else "") or "").strip().upper()
        if backend_status in {"FAIL", "FAILED", "ERROR"} or frontend_status in {"FAIL", "FAILED", "ERROR"}:
            step_failed = True
            break

    if live_signal_present:
        if live_backend_status == "FAIL" or live_frontend_status == "FAIL":
            return "FAIL"
        if preflight_failed or (runtime_failure_class and step_failed):
            return "FAIL"
        return "STOPPED"

    if runtime_failure_class:
        return "FAIL"

    if preflight_failed:
        return "FAIL"

    if "FAIL" in normalized_backend or "FAIL" in normalized_frontend:
        return "FAIL"

    if step_failed:
        return "FAIL"

    if bool(state_payload.get("backend_pid")) or bool(state_payload.get("frontend_pid")):
        return "RUNNING"

    if runtime_signal_present or _runtime_detect_required(project_dir, state_payload, result_payload):
        return "STOPPED"

    last_status = str(state_payload.get("last_status") or result_payload.get("status") or "").strip().upper()
    if last_status in {"FAIL", "FAILED", "ERROR"}:
        return "FAIL"
    if last_status in {"RUNNING"}:
        return "RUNNING"
    return "STOPPED"


def _resolve_project_type(state_payload: dict[str, Any], project_path: Optional[Path] = None) -> str:
    explicit = normalize_project_type(str(state_payload.get("project_type") or "").strip())
    if explicit != "unknown":
        return explicit

    template = str(state_payload.get("effective_template") or state_payload.get("selected_template") or "").strip().lower()
    shape = str(state_payload.get("architecture_app_shape") or state_payload.get("shape") or "").strip().lower()

    has_backend = False
    has_frontend = False
    if project_path is not None:
        root = project_path.expanduser().resolve()
        has_backend = (root / "app").is_dir() or (root / "requirements.txt").exists()
        has_frontend = (root / "frontend").is_dir() or (root / "package.json").exists() or (root / "next.config.mjs").exists()

    if template in ("worker-api",):
        return "worker-api"
    if template in ("fastapi", "fastapi-ddd"):
        return "backend-api"
    if template in ("nextjs",):
        return "frontend-web"
    if template in ("fullstack-ddd",):
        if has_frontend or shape == "fullstack":
            return "fullstack-web"

    if shape == "backend":
        return "backend-api"
    if shape == "fullstack":
        return "fullstack-web"
    if shape == "frontend":
        return "frontend-web"

    if has_backend and has_frontend:
        return "fullstack-web"
    if has_backend:
        return "backend-api"
    if has_frontend:
        return "frontend-web"
    return "unknown"


def format_status_text(project_dir: Path) -> str:
    project_dir = project_dir.expanduser().resolve()
    archmind_dir = project_dir / ".archmind"
    state_payload = load_state(project_dir) or {}
    result_payload = _load_json(archmind_dir / "result.json") or {}
    evaluation_payload = _load_json(archmind_dir / "evaluation.json") or {}
    running = _get_running_job()

    if running is not None and running.project_dir == project_dir:
        state_value = running.state
    else:
        state_value = str(state_payload.get("agent_state") or "").strip().upper() or "IDLE"
        if state_value not in ("RUNNING", "IDLE", "FIXING", "RETRYING"):
            state_value = "IDLE"

    iterations = int(state_payload.get("iterations") or 0)
    fix_attempts = int(state_payload.get("fix_attempts") or 0)
    project_type = _resolve_project_type(state_payload, project_dir)
    template = str(state_payload.get("effective_template") or "unknown").strip() or "unknown"
    architecture_shape = str(state_payload.get("architecture_app_shape") or "").strip()
    architecture_summary = str(state_payload.get("architecture_reason_summary") or "").strip()
    github_repo_url = str(state_payload.get("github_repo_url") or result_payload.get("github_repo_url") or "").strip()
    backend_status, frontend_status = _status_component_summary(project_dir, result_payload)
    if running is not None and running.project_dir == project_dir:
        progress = _progress_text(project_dir, fallback=_progress_fallback_for_command(running.command))
    else:
        progress = _progress_text(project_dir, fallback="none")
    state_next_action = str(state_payload.get("next_action") or "").strip()
    eval_next_action = str((evaluation_payload.get("next_actions") or [""])[0]).strip()
    if state_next_action and state_next_action.upper() not in ("STOP", "UNKNOWN"):
        next_action = state_next_action
    elif eval_next_action:
        next_action = eval_next_action
    elif state_next_action:
        next_action = state_next_action
    else:
        next_action = "none"
    if next_action != "none":
        next_action = _normalize_recommended_action_text(next_action)

    lines = [
        "ArchMind status",
        "",
        "Project:",
        project_dir.name,
        "",
        "Status:",
        state_value,
        "",
        "Backend:",
        backend_status,
        "",
        "Frontend:",
        frontend_status,
        "",
        "Next:",
        next_action,
        "",
        f"Progress: {progress}",
        f"Iterations: {iterations}",
        f"Fix attempts: {fix_attempts}",
        f"Project type: {project_type}",
        f"Template: {template}",
    ]
    if architecture_shape or architecture_summary:
        lines.append(f"Reasoning: {(architecture_shape or 'unknown')} / {(architecture_summary or '(none)')}")
    if github_repo_url:
        lines.append(f"GitHub repo: {github_repo_url}")
    return _truncate_message("\n".join(lines), limit=1200)


def format_projects_list(projects_dir: Optional[Path] = None, limit: int = 10) -> str:
    picked = list_recent_projects(projects_dir=projects_dir, limit=limit)
    if not picked:
        return "Recent ArchMind projects\n\n(no projects found)"

    current = get_current_project()
    lines: list[str] = ["Recent ArchMind projects", ""]
    for idx, project_dir in enumerate(picked, start=1):
        state_payload = _load_json(project_dir / ".archmind" / "state.json") or {}
        result_payload = _load_json(project_dir / ".archmind" / "result.json") or {}
        status = "STOPPED"
        project_type = _resolve_project_type(state_payload, project_dir)
        template = str(state_payload.get("effective_template") or "unknown").strip() or "unknown"
        marker = " [current]" if current is not None and project_dir.resolve() == current.resolve() else ""
        lines.append(f"{idx}. {project_dir.name}{marker}")

        runtime_backend_running = False
        runtime_frontend_running = False
        backend_url = str(state_payload.get("backend_deploy_url") or "").strip()
        frontend_url = str(state_payload.get("frontend_deploy_url") or "").strip()
        try:
            from archmind.deploy import get_local_runtime_status

            runtime_payload = get_local_runtime_status(project_dir)
            backend = runtime_payload.get("backend") if isinstance(runtime_payload, dict) else {}
            frontend = runtime_payload.get("frontend") if isinstance(runtime_payload, dict) else {}
            if isinstance(backend, dict):
                runtime_backend_running = str(backend.get("status") or "").strip().upper() == "RUNNING"
                backend_url = str(backend.get("url") or backend_url).strip()
            if isinstance(frontend, dict):
                runtime_frontend_running = str(frontend.get("status") or "").strip().upper() == "RUNNING"
                frontend_url = str(frontend.get("url") or frontend_url).strip()
        except Exception:
            runtime_backend_running = bool(state_payload.get("backend_pid"))
            runtime_frontend_running = bool(state_payload.get("frontend_pid"))
            runtime_payload = {}

        status = _project_runtime_status(project_dir, state_payload, result_payload, runtime_payload)
        lines.append(f"   Status: {status}")
        lines.append(f"   Type: {project_type}")
        lines.append(f"   Template: {template}")

        if status == "RUNNING":
            if runtime_backend_running and runtime_frontend_running:
                lines.append("   Runtime: RUNNING (backend+frontend)")
            elif runtime_backend_running:
                lines.append("   Runtime: RUNNING (backend)")
            elif runtime_frontend_running:
                lines.append("   Runtime: RUNNING (frontend)")
            else:
                lines.append("   Runtime: RUNNING")
        elif status == "FAIL":
            lines.append("   Runtime: FAIL")
        else:
            lines.append("   Runtime: STOPPED")
        if runtime_backend_running and backend_url:
            lines.append(f"   Backend: {backend_url}")
        if runtime_frontend_running and frontend_url:
            lines.append(f"   Frontend: {frontend_url}")
        if idx != len(picked):
            lines.append("")
    return _truncate_message("\n".join(lines), limit=3500)


def _persist_delete_outcome(project_dir: Path, mode: str, result: dict[str, Any]) -> None:
    project = project_dir.expanduser().resolve()
    if not project.exists() or not project.is_dir():
        return
    payload = load_state(project) or {}
    payload["deletion"] = {
        "attempted": True,
        "mode": str(mode or "").strip().lower() or "local",
        "local_status": str(result.get("local_status") or "UNCHANGED").strip().upper(),
        "local_detail": str(result.get("local_detail") or "").strip(),
        "repo_status": str(result.get("repo_status") or "UNCHANGED").strip().upper(),
        "repo_detail": str(result.get("repo_detail") or "").strip(),
        "updated_at": datetime.now().isoformat(timespec="seconds"),
    }
    try:
        write_state(project, payload)
    except Exception:
        pass


def format_project_tree(project_dir: Path, depth: int = 2, max_depth: int = 4, max_lines: int = 80) -> str:
    root = project_dir.expanduser().resolve()
    effective_depth = max(1, min(int(depth), int(max_depth)))
    exclude_names = {
        "node_modules",
        ".git",
        "__pycache__",
        ".pytest_cache",
        ".mypy_cache",
        ".venv",
        "dist",
        "build",
        ".next",
        "coverage",
    }

    lines: list[str] = ["Project tree", "", f"Project: {root.name}", "", "."]
    truncated = False

    def _children(path: Path) -> list[Path]:
        try:
            entries = sorted(path.iterdir(), key=lambda p: (not p.is_dir(), p.name.lower()))
        except Exception:
            return []
        return [entry for entry in entries if entry.name not in exclude_names]

    def _walk(path: Path, prefix: str, level: int) -> None:
        nonlocal truncated
        if truncated or level > effective_depth:
            return
        children = _children(path)
        for idx, child in enumerate(children):
            branch = "└── " if idx == len(children) - 1 else "├── "
            lines.append(f"{prefix}{branch}{child.name}")
            if len(lines) >= max_lines:
                truncated = True
                return
            if child.is_dir() and level < effective_depth:
                next_prefix = f"{prefix}{'    ' if idx == len(children) - 1 else '│   '}"
                _walk(child, next_prefix, level + 1)
            if truncated:
                return

    _walk(root, "", 1)
    if truncated:
        lines.append("... (truncated)")
    return _truncate_message("\n".join(lines), limit=3900)


def format_file_preview(project_dir: Path, rel_path: str, max_lines: int = 120) -> str:
    root = project_dir.expanduser().resolve()
    value = str(rel_path or "").strip()
    if not value:
        return "Usage: /open <path>"

    target = Path(value)
    if target.is_absolute() or ".." in target.parts:
        return "Invalid path. Use a project-relative file path."

    file_path = (root / target).resolve()
    try:
        file_path.relative_to(root)
    except Exception:
        return "Invalid path. Use a project-relative file path."

    if not file_path.exists():
        return f"File not found: {value}"
    if file_path.is_dir():
        return f"Path is a directory: {value}"
    if file_path.stat().st_size > 1_000_000:
        return f"File too large to preview: {value}"

    raw = file_path.read_bytes()
    if b"\x00" in raw:
        return f"Binary file not supported: {value}"

    try:
        text = raw.decode("utf-8")
    except Exception:
        return f"Could not decode file as UTF-8: {value}"

    lines = text.splitlines()
    out: list[str] = [f"File: {value}", ""]
    for idx, line in enumerate(lines[:max_lines], start=1):
        out.append(f"{idx} | {line}")
    if len(lines) > max_lines:
        out.append("... (truncated)")
    return _truncate_message("\n".join(out), limit=3900)


def format_recent_diff(project_dir: Path, max_lines: int = 120) -> str:
    root = project_dir.expanduser().resolve()
    run_logs = root / ".archmind" / "run_logs"
    patch_content = ""
    if run_logs.exists():
        candidates = sorted(run_logs.glob("fix_*.patch.diff"), key=lambda p: p.stat().st_mtime, reverse=True)
        for candidate in candidates:
            text = candidate.read_text(encoding="utf-8", errors="replace")
            if text.strip():
                patch_content = text
                break

    if not patch_content:
        git_dir = root / ".git"
        if git_dir.exists():
            try:
                completed = subprocess.run(  # noqa: S603
                    ["git", "diff", "--", "."],
                    cwd=root,
                    capture_output=True,
                    text=True,
                    timeout=10,
                    shell=False,
                    check=False,
                )
                patch_content = (completed.stdout or "").strip()
            except Exception:
                patch_content = ""

    if not patch_content.strip():
        return "No recent diff available."

    lines = patch_content.splitlines()
    out = ["Recent diff", ""]
    out.extend(lines[:max_lines])
    if len(lines) > max_lines:
        out.append("... (truncated)")
    return _truncate_message("\n".join(out), limit=3900)


def _extract_candidate_lines(text: str, mode: str) -> list[str]:
    keywords_backend = ("backend", "pytest", "assert", "traceback", "failed", "error", "e ")
    keywords_frontend = ("frontend", "eslint", "lint", "build", "tsc", "npm", "failed", "error", "warning", "tsx", "jsx")
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    if mode == "backend":
        picked = [line for line in lines if any(k in line.lower() for k in keywords_backend)]
    elif mode == "frontend":
        picked = [line for line in lines if any(k in line.lower() for k in keywords_frontend)]
    else:
        picked = lines[-30:]
    if not picked:
        picked = lines[-20:]
    return picked[:30]


def _read_json_clues(project_dir: Path, mode: str) -> list[str]:
    archmind_dir = project_dir / ".archmind"
    result_payload = _load_json(archmind_dir / "result.json") or {}
    out: list[str] = []
    failure_summary = result_payload.get("failure_summary")
    if isinstance(failure_summary, list):
        for item in failure_summary:
            line = str(item).strip()
            lower = line.lower()
            if mode == "backend" and "backend" not in lower and "pytest" not in lower:
                continue
            if mode == "frontend" and all(k not in lower for k in ("frontend", "lint", "build", "eslint")):
                continue
            out.append(line)
    if mode == "backend":
        step = ((result_payload.get("steps") or {}).get("run_before_fix") or {})
        detail = step.get("detail") if isinstance(step, dict) else {}
        if isinstance(detail, dict) and str(detail.get("backend_status") or "").upper() == "FAIL":
            out.append("Backend tests are still failing")
    if mode == "frontend":
        step = ((result_payload.get("steps") or {}).get("run_before_fix") or {})
        detail = step.get("detail") if isinstance(step, dict) else {}
        if isinstance(detail, dict) and str(detail.get("frontend_status") or "").upper() == "FAIL":
            out.append("Frontend checks are still failing")
    return out[:10]


def _failure_class_from_state(project_dir: Path) -> str:
    state = _load_json(project_dir / ".archmind" / "state.json") or {}
    return str(state.get("last_failure_class") or "").strip()


def _read_frontend_api_base_url(project_dir: Path) -> str:
    root = project_dir.expanduser().resolve()
    candidates = [root / "frontend" / ".env.local", root / ".env.local"]
    for path in candidates:
        env_map = _read_env_key_values(path)
        if env_map.get("NEXT_PUBLIC_API_BASE_URL"):
            return str(env_map.get("NEXT_PUBLIC_API_BASE_URL") or "").strip()
    return ""


def _read_env_key_values(path: Path) -> dict[str, str]:
    if not path.exists() or not path.is_file():
        return {}
    try:
        lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    except Exception:
        return {}
    out: dict[str, str] = {}
    for raw in lines:
        line = str(raw).strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key_clean = key.strip()
        if not key_clean:
            continue
        out[key_clean] = value.strip()
    return out


def _runtime_env_missing_parts(project_path: Path, *, fullstack_expected: bool, has_frontend: bool) -> list[str]:
    root = project_path.expanduser().resolve()
    missing: list[str] = []
    if fullstack_expected:
        backend_env_path = root / "backend" / ".env"
    elif (root / "backend").is_dir():
        backend_env_path = root / "backend" / ".env"
    else:
        backend_env_path = root / ".env"
    backend_env = _read_env_key_values(backend_env_path)
    root_env = _read_env_key_values(root / ".env")
    merged_backend_env = dict(root_env)
    merged_backend_env.update(backend_env)
    if not backend_env_path.exists():
        missing.append(backend_env_path.relative_to(root).as_posix())
    for key in ("APP_PORT", "BACKEND_BASE_URL", "CORS_ALLOW_ORIGINS"):
        if not str(merged_backend_env.get(key) or "").strip():
            missing.append(key)
    if has_frontend:
        frontend_env_path = root / "frontend" / ".env.local"
        frontend_env = _read_env_key_values(frontend_env_path)
        if not frontend_env_path.exists():
            missing.append("frontend/.env.local")
        if not str(frontend_env.get("NEXT_PUBLIC_API_BASE_URL") or "").strip():
            missing.append("NEXT_PUBLIC_API_BASE_URL")
    return missing


def _backend_env_values(project_path: Path, *, fullstack_expected: bool) -> dict[str, str]:
    root = project_path.expanduser().resolve()
    if fullstack_expected:
        backend_env_path = root / "backend" / ".env"
    elif (root / "backend").is_dir():
        backend_env_path = root / "backend" / ".env"
    else:
        backend_env_path = root / ".env"
    backend_env = _read_env_key_values(backend_env_path)
    root_env = _read_env_key_values(root / ".env")
    merged = dict(root_env)
    merged.update(backend_env)
    return merged


def _backend_runtime_diagnostics_lines(project_dir: Path) -> list[str]:
    state = _load_json(project_dir / ".archmind" / "state.json") or {}
    runtime = state.get("runtime") if isinstance(state.get("runtime"), dict) else {}
    backend_entry = str((runtime.get("backend_entry") if isinstance(runtime, dict) else "") or state.get("backend_entry") or "").strip()
    backend_run_mode = str((runtime.get("backend_run_mode") if isinstance(runtime, dict) else "") or state.get("backend_run_mode") or "").strip()
    backend_run_cwd = str((runtime.get("backend_run_cwd") if isinstance(runtime, dict) else "") or state.get("backend_run_cwd") or "").strip()
    backend_run_command = str((runtime.get("backend_run_command") if isinstance(runtime, dict) else "") or state.get("backend_run_command") or "").strip()
    runtime_failure_class = str(
        (runtime.get("failure_class") if isinstance(runtime, dict) else "")
        or state.get("runtime_failure_class")
        or state.get("last_failure_class")
        or ""
    ).strip()
    backend_detail = str((runtime.get("detail") if isinstance(runtime, dict) else "") or "").strip()
    backend_log_path = Path(
        str((runtime.get("backend_log_path") if isinstance(runtime, dict) else "") or (project_dir / ".archmind" / "backend.log"))
    )

    try:
        detected = detect_backend_runtime_entry(project_dir, port=8000)
    except Exception:
        detected = {"ok": False}

    if bool(detected.get("ok")):
        backend_entry = str(detected.get("backend_entry") or backend_entry or "").strip()
        backend_run_mode = str(detected.get("backend_run_mode") or backend_run_mode or "").strip()
        backend_run_cwd = str(detected.get("run_cwd") or backend_run_cwd or "").strip()
        cmd_items = [str(item) for item in (detected.get("run_command") or [])]
        backend_run_command = " ".join(cmd_items).strip() or backend_run_command
        runtime_failure_class = ""
    elif (not backend_entry or not backend_run_mode or not backend_run_command) and not runtime_failure_class:
        runtime_failure_class = str(detected.get("failure_class") or "generation-error").strip()

    lines = [
        "Backend runtime diagnostics:",
        f"- Detected backend target: {backend_entry or '(none)'}",
        f"- Backend run mode: {backend_run_mode or '(none)'}",
        f"- Run cwd: {backend_run_cwd or str(project_dir)}",
        f"- Run command: {backend_run_command or '(none)'}",
        f"- Failure class: {runtime_failure_class or '(none)'}",
        f"- Log path: {backend_log_path}",
    ]
    if backend_detail:
        lines += ["", "Last backend detail:", backend_detail]
    return lines


def _failure_summary_from_class(mode: str, failure_class: str, key_lines: list[str]) -> str:
    klass = (failure_class or "").lower()
    if mode == "backend":
        if klass.startswith("backend-pytest"):
            return "backend pytest failed"
        if klass == "backend-dependency":
            return "backend dependency install failed"
        if klass == "generation-error":
            return "backend generation structure error"
        if klass == "runtime-entrypoint-error":
            return "backend runtime entrypoint mismatch"
        if klass == "dependency-error":
            return "backend dependency import error"
        if klass.startswith("environment"):
            return "backend environment issue detected"
        return "backend failure detected"
    if mode == "frontend":
        if klass == "frontend-lint-warning":
            return "frontend lint warning detected"
        if klass == "frontend-lint":
            return "frontend lint failed"
        if klass == "frontend-typescript":
            return "frontend typescript failed"
        if klass == "frontend-build":
            return "frontend build failed"
        if klass == "frontend-install":
            return "frontend npm install failed"
        if klass == "frontend-missing-package":
            return "frontend package.json missing"
        if klass == "environment-node-missing":
            return "node/npm missing on host"
        return "frontend failure detected"
    if mode == "last":
        has_backend = any("assert" in line.lower() or "pytest" in line.lower() or line.lower().startswith("failed tests/") for line in key_lines)
        has_frontend = any(
            token in line.lower() for line in key_lines for token in ("eslint", "ts2304", "ts2322", "is not assignable")
        )
        if klass in ("filesystem-overwrite", "filesystem-path-validation"):
            return "filesystem validation blocked the run"
        if klass == "environment-node-missing":
            return "node/npm missing on host"
        if klass == "frontend-install":
            return "frontend npm install failed"
        if klass == "backend-dependency":
            return "backend dependency install failed"
        if has_backend and has_frontend:
            return "backend pytest failed\nfrontend lint failed"
        if has_backend:
            return "backend pytest failed"
        if has_frontend:
            return "frontend lint failed"
    return "recent failure detected"


def read_recent_backend_logs(project_dir: Path) -> str:
    clues = _read_json_clues(project_dir, "backend")
    files = _latest_run_logs(project_dir)
    excerpt = ""
    for path in files:
        text = path.read_text(encoding="utf-8", errors="replace")
        candidate = _extract_candidate_lines(text, "backend")
        if candidate:
            excerpt = sanitize_log_excerpt("\n".join(clues + candidate), max_lines=60)
            if excerpt:
                break
    if clues:
        excerpt = excerpt or sanitize_log_excerpt("\n".join(clues), max_lines=40)
    key_lines = extract_key_error_lines(excerpt)
    if not key_lines:
        diagnostics = _backend_runtime_diagnostics_lines(project_dir)
        return build_logs_message(
            project_dir.name,
            "backend",
            "No backend logs found. Showing runtime diagnostics instead.",
            diagnostics,
            ["inspect backend entrypoint and run command"],
        )
    failure_class = _failure_class_from_state(project_dir) or classify_failure(excerpt, "backend-pytest:FAIL")
    failure = _failure_summary_from_class("backend", failure_class, key_lines)
    focus = build_log_focus("backend", failure_class, key_lines)
    return build_logs_message(project_dir.name, "backend", failure, key_lines, focus)


def read_recent_frontend_logs(project_dir: Path) -> str:
    clues = _read_json_clues(project_dir, "frontend")
    files = _latest_run_logs(project_dir)
    excerpt = ""
    for path in files:
        text = path.read_text(encoding="utf-8", errors="replace")
        candidate = _extract_candidate_lines(text, "frontend")
        if candidate:
            excerpt = sanitize_log_excerpt("\n".join(clues + candidate), max_lines=60)
            if excerpt:
                break
    if clues:
        excerpt = excerpt or sanitize_log_excerpt("\n".join(clues), max_lines=40)
    key_lines = extract_key_error_lines(excerpt)
    if not key_lines:
        return build_logs_message(project_dir.name, "frontend", "No frontend logs found.", [], ["inspect recent failure details"])
    failure_class = _failure_class_from_state(project_dir) or classify_failure(excerpt, "frontend-lint:FAIL")
    failure = _failure_summary_from_class("frontend", failure_class, key_lines)
    focus = build_log_focus("frontend", failure_class, key_lines)
    return build_logs_message(project_dir.name, "frontend", failure, key_lines, focus)


def read_recent_last_logs(project_dir: Path, temp_log: Optional[Path] = None) -> str:
    files = _latest_run_logs(project_dir)
    excerpt = ""
    for path in files:
        text = path.read_text(encoding="utf-8", errors="replace")
        candidate = _extract_candidate_lines(text, "last")
        if candidate:
            excerpt = sanitize_log_excerpt("\n".join(candidate), max_lines=80)
            if excerpt:
                break
    if temp_log and temp_log.exists():
        text = temp_log.read_text(encoding="utf-8", errors="replace")
        excerpt = excerpt or sanitize_log_excerpt("\n".join(_extract_candidate_lines(text, "last")), max_lines=60)
    key_lines = extract_key_error_lines(excerpt)
    if not key_lines:
        return build_logs_message(project_dir.name, "last", "No recent logs found.", [], ["inspect recent failure details"])
    failure_class = _failure_class_from_state(project_dir) or classify_failure(excerpt, "")
    failure = _failure_summary_from_class("last", failure_class, key_lines)
    focus = build_log_focus("last", failure_class, key_lines)
    return build_logs_message(project_dir.name, "last", failure, key_lines, focus)


def _summary_from_failure_signature(signature: str) -> list[str]:
    raw = (signature or "").strip().lower()
    if not raw:
        return []
    head = raw.split(":", 1)[0]
    parts = [item.strip() for item in head.split("+") if item.strip()]
    out: list[str] = []
    if "backend-pytest" in parts:
        out.append("Backend tests are still failing")
    if "frontend-lint" in parts:
        out.append("Frontend lint is still failing")
    if "frontend-build" in parts:
        out.append("Frontend build is still failing")
    return out


def _build_human_summary(
    status: str,
    state: dict[str, Any],
    result: dict[str, Any],
    fallback_lines: list[str],
) -> list[str]:
    out: list[str] = []
    normalized = str(status or "UNKNOWN").upper()
    signature = str(state.get("last_failure_signature") or "").strip()
    for line in _summary_from_failure_signature(signature):
        if line not in out:
            out.append(line)

    if normalized == "STUCK" and "Automatic retries are no longer making progress" not in out:
        out.append("Automatic retries are no longer making progress")
    elif normalized in ("NOT_DONE", "FAIL", "BLOCKED") and "Further work remains" not in out:
        out.append("Further work remains")

    fallback_cleaned: list[str] = []
    for line in fallback_lines[-8:]:
        cleaned = _humanize_summary_line(line)
        if cleaned and cleaned not in fallback_cleaned:
            fallback_cleaned.append(cleaned)
    for line in fallback_cleaned[-3:]:
        if line and line not in out:
            out.append(line)

    if not out and isinstance(result, dict):
        failure_summary = result.get("failure_summary")
        if isinstance(failure_summary, list):
            for item in failure_summary[:5]:
                cleaned = _humanize_summary_line(str(item))
                if cleaned and cleaned not in out:
                    out.append(cleaned)

    return out[:3]


def _normalize_component_status(value: str) -> str:
    normalized = str(value or "").strip().upper()
    if normalized in ("SUCCESS", "PASS", "OK"):
        return "SUCCESS"
    if normalized in ("SKIP", "SKIPPED"):
        return "SKIP"
    if normalized:
        return normalized
    return "UNKNOWN"


def _extract_done_component_summary(result: dict[str, Any], fallback_lines: list[str]) -> list[str]:
    backend = ""
    frontend = ""
    steps = result.get("steps")
    if isinstance(steps, dict):
        for key in ("run_after_fix", "run_before_fix"):
            section = steps.get(key)
            if not isinstance(section, dict):
                continue
            detail = section.get("detail")
            if not isinstance(detail, dict):
                continue
            if not backend and detail.get("backend_status"):
                backend = _normalize_component_status(str(detail.get("backend_status")))
            if not frontend and detail.get("frontend_status"):
                frontend = _normalize_component_status(str(detail.get("frontend_status")))
            if backend and frontend:
                break

    if not backend or not frontend:
        for raw in fallback_lines:
            line = str(raw or "").strip()
            lower = line.lower()
            if not backend and "backend" in lower:
                if "skip" in lower:
                    backend = "SKIP"
                elif "success" in lower or "ok" in lower or "pass" in lower:
                    backend = "SUCCESS"
            if not frontend and "frontend" in lower:
                if "skip" in lower:
                    frontend = "SKIP"
                elif "success" in lower or "ok" in lower or "pass" in lower:
                    frontend = "SUCCESS"

    out: list[str] = []
    out.append(f"Backend: {backend or 'SUCCESS'}")
    out.append(f"Frontend: {frontend or 'SKIP'}")
    out.append("All tasks complete")
    out.append("Evaluation complete")
    return out[:4]


def _reconcile_summary_with_smoke_status(summary_lines: list[str], state: dict[str, Any]) -> list[str]:
    frontend_smoke = str(state.get("frontend_smoke_status") or "").strip().upper()
    if frontend_smoke == "SUCCESS":
        out: list[str] = []
        for line in summary_lines:
            if str(line).startswith("Frontend:"):
                out.append("Frontend: SUCCESS")
            else:
                out.append(line)
        return out
    return summary_lines


def _recommend_next_actions(
    project_dir: Path,
    status: str,
    summary_lines: list[str],
    state: dict[str, Any],
    evaluation: dict[str, Any],
    result: dict[str, Any],
) -> list[str]:
    del summary_lines
    normalized = str(status or "").strip().upper()
    if normalized == "DONE" and not _current_runtime_actionable_failure(project_dir, state or {}, result or {}):
        return next_action_suggestions("DONE")
    decision = decide_next_action(state, evaluation, result)
    return next_action_suggestions(str(decision.get("action") or "STOP"))


def build_finished_message(
    evaluation: dict[str, Any],
    state: dict[str, Any],
    result: dict[str, Any],
    *,
    project_name: str,
    status: str,
    project_dir: Optional[Path] = None,
    fallback_summary_lines: Optional[list[str]] = None,
    max_len: int = 1200,
    failure_class_override: Optional[str] = None,
) -> str:
    iterations = state.get("iterations")
    fix_attempts = state.get("fix_attempts")
    signature = str(state.get("last_failure_signature") or "").strip()
    failure_class = str(failure_class_override if failure_class_override is not None else (state.get("last_failure_class") or "")).strip()
    current_task = str(state.get("derived_task_label") or "").strip() or derive_task_label_from_failure_signature(signature)
    if not current_task:
        current_task = str(state.get("current_task_label") or "").strip()

    stuck_reason = ""
    if str(status).upper() == "STUCK":
        reasons = evaluation.get("reasons")
        if isinstance(reasons, list) and reasons:
            stuck_reason = str(reasons[0]).strip()
        if not stuck_reason:
            stuck_reason = str(state.get("stuck_reason") or "").strip()

    fallback_lines = list(fallback_summary_lines or [])
    normalized_status = str(status or "").upper()
    if normalized_status == "DONE":
        summary_lines = _extract_done_component_summary(result, fallback_lines)
    else:
        summary_lines = _build_human_summary(
            status=status,
            state=state,
            result=result,
            fallback_lines=fallback_lines,
        )
    summary_lines = _reconcile_summary_with_smoke_status(summary_lines, state)
    auto_deploy_enabled = bool(state.get("auto_deploy_enabled"))
    auto_deploy_target = str(state.get("auto_deploy_target") or "").strip() or "local"
    auto_deploy_status = str(state.get("auto_deploy_status") or "").strip().upper() or "SKIPPED"
    if auto_deploy_enabled:
        summary_lines.append(f"Auto deploy: {auto_deploy_target} {auto_deploy_status}")
    candidate_project = project_dir
    if candidate_project is None:
        candidate_path = str(state.get("project_dir") or result.get("project_dir") or "").strip()
        if candidate_path:
            try:
                candidate_project = Path(candidate_path).expanduser().resolve()
            except Exception:
                candidate_project = None
    next_actions: list[str] = []
    if candidate_project is not None:
        next_actions = _recommend_next_actions(candidate_project, status, summary_lines, state, evaluation, result)[:3]
    else:
        next_actions = next_action_suggestions("DONE" if str(status or "").upper() == "DONE" else "STOP")[:3]
    next_actions = [_normalize_recommended_action_text(item) for item in next_actions if str(item).strip()]
    repository_info = _repository_summary_from_state(state)
    github_repo_url = str(repository_info.get("url") or result.get("github_repo_url") or "").strip()
    repository_status = str(repository_info.get("status") or "").strip().upper()
    repository_reason = str(repository_info.get("reason") or "").strip()

    lines = [
        "ArchMind finished",
        "",
        "Project:",
        project_name,
        "",
        f"Status: {status}",
    ]
    if iterations is not None:
        lines.append(f"Iterations: {iterations}")
    if fix_attempts is not None:
        lines.append(f"Fix attempts: {fix_attempts}")
    if current_task:
        lines.append(f"Current task: {current_task}")
    if failure_class and normalized_status != "DONE":
        lines.append(f"Failure class: {failure_class}")
    if stuck_reason:
        lines.append(f"Reason: {stuck_reason}")
    lines += [
        "",
        "Summary:",
    ]
    summary_limit = 6 if auto_deploy_enabled else 5
    lines.extend(f"- {line}" for line in summary_lines[:summary_limit])
    if repository_status or github_repo_url or repository_reason:
        lines += [
            "",
            "GitHub Repo:",
            repository_status or ("CREATED" if github_repo_url else "SKIPPED"),
        ]
        if github_repo_url:
            lines.append(github_repo_url)
        if repository_reason:
            lines.append(f"Reason: {repository_reason}")
    if auto_deploy_enabled:
        backend_url = str(state.get("backend_deploy_url") or "").strip()
        frontend_url = str(state.get("frontend_deploy_url") or "").strip()
        deploy_url = str(state.get("deploy_url") or "").strip()
        backend_smoke_status = str(state.get("backend_smoke_status") or "").strip().upper()
        backend_smoke_url = str(state.get("backend_smoke_url") or "").strip()
        frontend_smoke_status = str(state.get("frontend_smoke_status") or "").strip().upper()
        frontend_smoke_url = str(state.get("frontend_smoke_url") or "").strip()
        deploy_detail = str(state.get("last_deploy_detail") or "").strip()
        lines += [
            "",
            f"Auto deploy target: {auto_deploy_target}",
            f"Auto deploy status: {auto_deploy_status}",
        ]
        if backend_url:
            lines += ["", "Backend URL:", backend_url]
        if backend_smoke_status:
            lines += ["", "Backend smoke:", backend_smoke_status]
            if backend_smoke_url:
                lines.append(backend_smoke_url)
        if frontend_url:
            lines += ["", "Frontend URL:", frontend_url]
        elif deploy_url and not backend_url:
            lines += ["", "Deploy URL:", deploy_url]
        if frontend_smoke_status:
            lines += ["", "Frontend smoke:", frontend_smoke_status]
            if frontend_smoke_url:
                lines.append(frontend_smoke_url)
        if auto_deploy_status == "FAIL" and deploy_detail:
            lines += ["", "Auto deploy detail:", deploy_detail]
    if next_actions:
        lines += [
            "",
            "Next:",
        ]
        lines.extend(f"- {line}" for line in next_actions[:3])
    lines += ["", "Next:", "- /inspect", "- /next"]
    return _truncate_message("\n".join(lines), limit=max_len)


def build_completion_message(
    project_dir: Path,
    temp_log: Path,
    *,
    max_len: int = 1200,
    exit_code: Optional[int] = None,
) -> str:
    project_dir = project_dir.expanduser().resolve()
    archmind_dir = project_dir / ".archmind"
    evaluation = _load_json(archmind_dir / "evaluation.json") or {}
    state = load_state(project_dir) or {}
    result = _load_json(archmind_dir / "result.json") or {}
    status = _status_from_sources(project_dir)
    runtime_ctx = _improve_runtime_context(project_dir, state)
    display_failure_class = str(runtime_ctx.get("failure_class") or "").strip()
    fallback_summary = _result_summary_lines(project_dir, temp_log)
    message = build_finished_message(
        evaluation=evaluation,
        state=state,
        result=result,
        project_name=project_dir.name,
        status=status,
        project_dir=project_dir,
        fallback_summary_lines=fallback_summary,
        max_len=max_len,
        failure_class_override=display_failure_class,
    )
    if exit_code is not None and str(status).upper() == "UNKNOWN":
        message = _truncate_message(f"{message}\n(exit code: {exit_code})", limit=max_len)
    return message


def _wait_for_latest_artifacts(project_dir: Path, started_at: float, attempts: int = 6, sleep_s: float = 0.15) -> None:
    archmind_dir = project_dir / ".archmind"
    state_path = archmind_dir / "state.json"
    optional_targets = [archmind_dir / "evaluation.json", archmind_dir / "result.json"]
    for _ in range(attempts):
        if state_path.exists() and state_path.stat().st_mtime >= started_at:
            return
        optional_newer = False
        for path in optional_targets:
            if path.exists() and path.stat().st_mtime >= started_at:
                optional_newer = True
                break
        if optional_newer and not state_path.exists():
            return
        time.sleep(sleep_s)


async def watch_pipeline_and_notify(
    proc: subprocess.Popen[str],
    project_dir: Path,
    temp_log: Path,
    chat_id: int,
    application: Any,
    started_at: Optional[float] = None,
    auto_run_backend: bool = False,
) -> None:
    try:
        exit_code = await asyncio.to_thread(proc.wait)
        await asyncio.to_thread(_wait_for_latest_artifacts, project_dir, started_at or time.time())
        message = build_completion_message(project_dir, temp_log, max_len=1200, exit_code=exit_code)
        if auto_run_backend and exit_code == 0:
            auto_run_message = await asyncio.to_thread(_auto_run_backend_after_idea_local, project_dir)
            if auto_run_message:
                message = _truncate_message(f"{message}\n\n{auto_run_message}", limit=3500)
    except Exception as exc:
        message = f"ArchMind finished with notification error: {exc}"

    try:
        suggested = _extract_recommended_commands_from_text(message)
        await _send_message_with_action_buttons(application.bot, chat_id=chat_id, text=message, commands=suggested)
    except Exception:
        # Notification errors should never crash the bot loop.
        pass


def _run_command_to_log(cmd: list[str], temp_log: Path) -> int:
    temp_log.parent.mkdir(parents=True, exist_ok=True)
    with open(temp_log, "a", encoding="utf-8") as handle:
        proc = subprocess.Popen(  # noqa: S603
            cmd,
            stdout=handle,
            stderr=handle,
            text=True,
            shell=False,
            start_new_session=True,
        )
        return proc.wait()


async def watch_retry_and_notify(
    project_dir: Path,
    temp_log: Path,
    chat_id: int,
    application: Any,
    started_at: Optional[float] = None,
) -> None:
    try:
        commands = build_retry_commands(project_dir)
        last_exit = 0
        for cmd in commands:
            if cmd[:2] == ["archmind", "fix"]:
                await asyncio.to_thread(
                    set_agent_state, project_dir, "FIXING", action="telegram retry fix", summary="retry fix step started"
                )
            elif cmd[:2] == ["archmind", "pipeline"]:
                await asyncio.to_thread(
                    set_agent_state,
                    project_dir,
                    "RUNNING",
                    action="telegram retry continue",
                    summary="retry continue step started",
                )
            last_exit = await asyncio.to_thread(_run_command_to_log, cmd, temp_log)
            if last_exit != 0 and cmd[:2] == ["archmind", "fix"]:
                break
        await asyncio.to_thread(_wait_for_latest_artifacts, project_dir, started_at or time.time())
        message = build_completion_message(project_dir, temp_log, max_len=1200, exit_code=last_exit)
    except Exception as exc:
        message = f"ArchMind finished with notification error: {exc}"
    try:
        suggested = _extract_recommended_commands_from_text(message)
        await _send_message_with_action_buttons(application.bot, chat_id=chat_id, text=message, commands=suggested)
    except Exception:
        pass


async def _send_message_with_action_buttons(bot: Any, *, chat_id: int, text: str, commands: list[str]) -> None:
    reply_markup = _build_action_keyboard(commands)
    if reply_markup is not None:
        try:
            await bot.send_message(chat_id=chat_id, text=text, reply_markup=reply_markup)
            return
        except TypeError:
            pass
    await bot.send_message(chat_id=chat_id, text=text)


def _missing_project_message() -> str:
    return "No previous project found. Use /idea first."


def _temp_log_for_project(project_dir: Path) -> Path:
    root = project_dir.expanduser().resolve().parent
    return root / f"{project_dir.name}.telegram.log"


def _should_auto_run_backend_for_template(state_payload: dict[str, Any]) -> bool:
    template = str(state_payload.get("effective_template") or state_payload.get("selected_template") or "").strip().lower()
    return template in {"fullstack-ddd", "fastapi", "fastapi-ddd"}


def _auto_run_backend_after_idea_local(project_dir: Path) -> str:
    project_path = project_dir.expanduser().resolve()
    state_payload = load_state(project_path) or {}
    if not _should_auto_run_backend_for_template(state_payload):
        return ""

    from archmind.deploy import ensure_runtime_env_defaults, get_local_runtime_status, run_backend_local_with_health

    ensure_runtime_env_defaults(project_path)

    runtime = get_local_runtime_status(project_path)
    runtime_backend = runtime.get("backend") if isinstance(runtime.get("backend"), dict) else {}
    if str(runtime_backend.get("status") or "").upper() == "RUNNING":
        backend_url = str(runtime_backend.get("url") or "").strip()
        lines = [
            "Backend auto-run",
            "",
            "Backend:",
            "Backend already running",
        ]
        if backend_url:
            lines += ["", "Backend URL:", backend_url]
        lines += ["", "Next:", "- /logs backend", "- /running"]
        return "\n".join(lines)

    detect = detect_backend_runtime_entry(project_path, port=8000)
    if not bool(detect.get("ok")):
        failure_reason = str(detect.get("failure_reason") or "backend runtime entry detection failed").strip()
        lines = [
            "Backend auto-run",
            "",
            "Backend:",
            "SKIPPED",
            "",
            "Reason:",
            failure_reason,
            "",
            "Next:",
            "- /inspect",
            "- /next",
        ]
        return "\n".join(lines)

    result = run_backend_local_with_health(project_path)
    update_runtime_state(project_path, result, action="telegram /idea_local auto-run backend")
    backend_status = "RUNNING" if str(result.get("status") or "").upper() == "SUCCESS" else "FAIL"
    lines = ["Backend auto-run", "", "Backend:", backend_status]
    backend_url = str(result.get("url") or "").strip()
    if backend_url:
        lines += ["", "Backend URL:", backend_url]
    backend_smoke_status = str(result.get("backend_smoke_status") or result.get("healthcheck_status") or "").strip().upper()
    backend_smoke_url = str(result.get("backend_smoke_url") or result.get("healthcheck_url") or "").strip()
    if backend_smoke_status:
        lines += ["", "Backend smoke:", backend_smoke_status]
        if backend_smoke_url:
            lines.append(backend_smoke_url)
    if backend_status == "FAIL":
        lines += [
            "",
            "Failure class:",
            str(result.get("failure_class") or "runtime-execution-error").strip(),
            "",
            "Next:",
            "- /logs backend",
            "- /fix",
        ]
    else:
        lines += ["", "Next:", "- /logs backend", "- /running"]
    return "\n".join(lines)


async def _handle_idea_like(
    update: Any,
    context: Any,
    cmd_name: str,
    *,
    auto_deploy: bool = False,
    auto_deploy_target: str = "local",
) -> None:
    running = _get_running_job()
    if running is not None:
        await update.message.reply_text(_busy_message(running))
        return

    idea = extract_idea(getattr(context, "args", []))
    if not idea:
        await update.message.reply_text(f"Usage: /{cmd_name} <idea text>")
        return

    base_dir = resolve_base_dir()
    base_dir.mkdir(parents=True, exist_ok=True)
    project_dir = planned_project_dir(base_dir, idea)
    save_last_project_path(project_dir)

    command = build_pipeline_command(
        idea=idea,
        base_dir=base_dir,
        project_name=project_dir.name,
        auto_deploy=auto_deploy,
        deploy_target=auto_deploy_target,
    )
    try:
        proc, log_path = start_pipeline_process(command, base_dir=base_dir, project_name=project_dir.name)
    except Exception as exc:
        await update.message.reply_text(f"Failed to start pipeline: {exc}")
        return

    job = _register_running_job(f"/{cmd_name}", "RUNNING", project_dir, proc=proc)
    application = getattr(context, "application", None)
    chat = getattr(update, "effective_chat", None)
    chat_id = getattr(chat, "id", None)
    if application is not None and chat_id is not None:
        started_at = time.time()
        task = asyncio.create_task(
            watch_pipeline_and_notify(
                proc=proc,
                project_dir=project_dir,
                temp_log=log_path,
                chat_id=int(chat_id),
                application=application,
                started_at=started_at,
                auto_run_backend=(cmd_name == "idea_local"),
            )
        )
        _attach_running_task(job, task)

    start_msg = (
        f"started: pid={proc.pid}\n"
        f"command=/{cmd_name}\n"
        f"project={project_dir}\n"
        f"state=RUNNING\n"
        f"progress={_progress_fallback_for_command(f'/{cmd_name}')}\n"
    )
    if auto_deploy:
        start_msg += f"auto_deploy={auto_deploy_target}\n"
    start_msg += f"log={log_path}"
    if cmd_name == "idea_local":
        InlineKeyboardButton, InlineKeyboardMarkup = _inline_keyboard_classes()
        project_id = project_dir.name
        next_label = f"NEXT (for {project_id})"
        callback_data = _encode_callback_data("next", project_id)
        reply_markup = InlineKeyboardMarkup([[InlineKeyboardButton(text=next_label, callback_data=callback_data)]])
        await update.message.reply_text(start_msg, reply_markup=reply_markup)
        return
    await update.message.reply_text(start_msg)


async def _handle_continue(update: Any, context: Any) -> None:
    running = _get_running_job()
    if running is not None:
        await update.message.reply_text(_busy_message(running))
        return

    project_dir = _resolve_target_project()
    if project_dir is None:
        await update.message.reply_text(_missing_project_message())
        return

    command = build_continue_command(project_dir)
    temp_log = _temp_log_for_project(project_dir)
    try:
        set_agent_state(project_dir, "RUNNING", action="telegram /continue", summary="continue started")
        proc = start_background_process(command, temp_log=temp_log)
    except Exception as exc:
        await update.message.reply_text(f"Failed to continue pipeline: {exc}")
        return

    job = _register_running_job("/continue", "RUNNING", project_dir, proc=proc)
    application = getattr(context, "application", None)
    chat = getattr(update, "effective_chat", None)
    chat_id = getattr(chat, "id", None)
    if application is not None and chat_id is not None:
        started_at = time.time()
        task = asyncio.create_task(
            watch_pipeline_and_notify(
                proc=proc,
                project_dir=project_dir,
                temp_log=temp_log,
                chat_id=int(chat_id),
                application=application,
                started_at=started_at,
            )
        )
        _attach_running_task(job, task)
    await update.message.reply_text(
        f"continuing: pid={proc.pid}\n"
        f"command=/continue\n"
        f"project={project_dir}\n"
        f"state=RUNNING\n"
        f"progress={_progress_text(project_dir, fallback='Running checks')}"
    )


async def _handle_fix(update: Any, context: Any) -> None:
    running = _get_running_job()
    if running is not None:
        await update.message.reply_text(_busy_message(running))
        return

    project_dir = _resolve_target_project()
    if project_dir is None:
        await update.message.reply_text(_missing_project_message())
        return

    command = build_fix_command(project_dir)
    temp_log = _temp_log_for_project(project_dir)
    try:
        set_agent_state(project_dir, "FIXING", action="telegram /fix", summary="fix started")
        proc = start_background_process(command, temp_log=temp_log)
    except Exception as exc:
        await update.message.reply_text(f"Failed to start fix: {exc}")
        return

    job = _register_running_job("/fix", "FIXING", project_dir, proc=proc)
    application = getattr(context, "application", None)
    chat = getattr(update, "effective_chat", None)
    chat_id = getattr(chat, "id", None)
    if application is not None and chat_id is not None:
        started_at = time.time()
        task = asyncio.create_task(
            watch_pipeline_and_notify(
                proc=proc,
                project_dir=project_dir,
                temp_log=temp_log,
                chat_id=int(chat_id),
                application=application,
                started_at=started_at,
            )
        )
        _attach_running_task(job, task)
    await update.message.reply_text(
        f"fix started: pid={proc.pid}\n"
        f"command=/fix\n"
        f"project={project_dir}\n"
        f"state=FIXING\n"
        f"progress={_progress_text(project_dir, fallback='Applying fixes')}"
    )


async def _handle_retry(update: Any, context: Any) -> None:
    running = _get_running_job()
    if running is not None:
        await update.message.reply_text(_busy_message(running))
        return

    project_dir = _resolve_target_project()
    if project_dir is None:
        await update.message.reply_text(_missing_project_message())
        return

    status = _status_from_sources(project_dir).upper()
    if status in ("DONE", "SUCCESS"):
        await update.message.reply_text("Project already complete.")
        return

    warn = ""
    if status == "STUCK":
        warn = "\nwarning=Project is currently STUCK; retry may repeat the same failure."
    set_agent_state(project_dir, "RETRYING", action="telegram /retry", summary="retry orchestration started")

    application = getattr(context, "application", None)
    chat = getattr(update, "effective_chat", None)
    chat_id = getattr(chat, "id", None)
    if application is not None and chat_id is not None:
        started_at = time.time()
        job = _register_running_job("/retry", "RETRYING", project_dir)
        task = asyncio.create_task(
            watch_retry_and_notify(
                project_dir=project_dir,
                temp_log=_temp_log_for_project(project_dir),
                chat_id=int(chat_id),
                application=application,
                started_at=started_at,
            )
        )
        _attach_running_task(job, task)

    await update.message.reply_text(
        f"retry started\n"
        f"command=/retry\n"
        f"project={project_dir}\n"
        f"mode=fix -> continue\n"
        f"state=RETRYING\n"
        f"progress={_progress_text(project_dir, fallback='Applying fixes')}{warn}"
    )


async def command_idea(update: Any, context: Any) -> None:
    await _handle_idea_like(update, context, "idea")


async def command_idea_local(update: Any, context: Any) -> None:
    await _handle_idea_like(
        update,
        context,
        "idea_local",
        auto_deploy=True,
        auto_deploy_target="local",
    )


async def command_pipeline(update: Any, context: Any) -> None:
    await _handle_idea_like(update, context, "pipeline")


async def command_preview(update: Any, context: Any) -> None:
    idea = extract_idea(getattr(context, "args", []))
    if not idea:
        await update.message.reply_text("Usage: /preview <idea>")
        return
    await update.message.reply_text(_truncate_message(_format_brain_preview_text(idea)))


async def command_suggest(update: Any, context: Any) -> None:
    idea = extract_idea(getattr(context, "args", []))
    if not idea:
        await update.message.reply_text("Usage: /suggest <idea>")
        return

    normalized_payload = normalize_idea(idea)
    normalized = str(normalized_payload.get("normalized") or idea)
    reasoning = reason_architecture_from_idea(normalized)
    suggestions = get_template_suggestions(normalized, reasoning) or [str(reasoning.get("recommended_template") or "fastapi")]
    spec_suggestion = suggest_project_spec(normalized, reasoning)
    target_project = _resolve_target_project()
    if target_project is not None:
        suggestion_path = target_project / ".archmind" / "suggestion.json"
        suggestion_path.parent.mkdir(parents=True, exist_ok=True)
        suggestion_path.write_text(json.dumps(spec_suggestion, ensure_ascii=False, indent=2), encoding="utf-8")

    shape = str(reasoning.get("app_shape") or "unknown")
    template = str(reasoning.get("recommended_template") or "unknown")
    modules = [str(x) for x in (reasoning.get("modules") or []) if str(x).strip()]
    entities = spec_suggestion.get("entities") if isinstance(spec_suggestion.get("entities"), list) else []
    apis = [str(x) for x in (spec_suggestion.get("api_endpoints") or []) if str(x).strip()]
    pages = [str(x) for x in (spec_suggestion.get("frontend_pages") or []) if str(x).strip()]

    entity_lines: list[str] = []
    for entity in entities:
        if not isinstance(entity, dict):
            continue
        name = str(entity.get("name") or "").strip()
        fields = entity.get("fields") if isinstance(entity.get("fields"), list) else []
        pairs = []
        for field in fields:
            if not isinstance(field, dict):
                continue
            field_name = str(field.get("name") or "").strip()
            field_type = str(field.get("type") or "").strip()
            if field_name and field_type:
                pairs.append(f"{field_name}:{field_type}")
        if name:
            entity_lines.append(f"- {name}({', '.join(pairs)})" if pairs else f"- {name}")

    template_lines = "\n".join([f"- {name}" for name in suggestions[:3]])
    reason = str(reasoning.get("reason_summary") or "unclear architecture")
    message = (
        "Architecture suggestion\n\n"
        "Shape:\n"
        f"{shape}\n\n"
        "Template:\n"
        f"{template}\n\n"
        "Modules:\n"
        f"{', '.join(modules) if modules else '(none)'}\n\n"
        "Template candidates:\n"
        f"{template_lines}\n\n"
        "Suggested entities:\n"
        f"{chr(10).join(entity_lines) if entity_lines else '- (none)'}\n\n"
        "Suggested APIs:\n"
        f"{chr(10).join([f'- {x}' for x in apis]) if apis else '- (none)'}\n\n"
        "Suggested pages:\n"
        f"{chr(10).join([f'- {x}' for x in pages]) if pages else '- (none)'}\n\n"
        "Reasoning:\n"
        f"{reason}"
    )
    await update.message.reply_text(_truncate_message(message))


async def command_design(update: Any, context: Any) -> None:
    idea = extract_idea(getattr(context, "args", []))
    if not idea:
        await update.message.reply_text("Usage: /design <idea>")
        return

    normalized_payload = normalize_idea(idea)
    normalized = str(normalized_payload.get("normalized") or idea)
    reasoning = reason_architecture_from_idea(normalized)
    suggestion = suggest_project_spec(normalized, reasoning)
    design = build_architecture_design(idea, reasoning, suggestion)

    modules = [str(x) for x in (design.get("modules") or []) if str(x).strip()]
    domains = [str(x) for x in (design.get("domains") or []) if str(x).strip()]
    entities = design.get("entities") if isinstance(design.get("entities"), list) else []
    relationships = [str(x) for x in (design.get("relationships") or []) if str(x).strip()]
    apis = [str(x) for x in (design.get("api_endpoints") or []) if str(x).strip()]
    pages = [str(x) for x in (design.get("frontend_pages") or []) if str(x).strip()]

    entity_lines: list[str] = []
    for entity in entities:
        if not isinstance(entity, dict):
            continue
        name = str(entity.get("name") or "").strip()
        if not name:
            continue
        fields = entity.get("fields") if isinstance(entity.get("fields"), list) else []
        pairs: list[str] = []
        for field in fields:
            if not isinstance(field, dict):
                continue
            fname = str(field.get("name") or "").strip()
            ftype = str(field.get("type") or "").strip().lower()
            if fname and ftype:
                pairs.append(f"{fname}:{ftype}")
        entity_lines.append(f"- {name}({', '.join(pairs)})" if pairs else f"- {name}")

    lines = [
        "Architecture design",
        "",
        "Overview:",
        str(design.get("overview") or idea),
        "",
        "Architecture:",
        f"Shape: {str(design.get('shape') or 'unknown')}",
        f"Template: {str(design.get('template') or 'unknown')}",
        f"Modules: {', '.join(modules) if modules else '(none)'}",
        "",
        "Domains:",
    ]
    lines += [f"- {x}" for x in domains] if domains else ["- (none)"]
    lines += ["", "Entities:"]
    lines += entity_lines if entity_lines else ["- (none)"]
    if relationships:
        lines += ["", "Relationships:"] + [f"- {x}" for x in relationships]
    lines += ["", "APIs:"]
    lines += [f"- {x}" for x in apis] if apis else ["- (none)"]
    lines += ["", "Frontend:"]
    lines += [f"- {x}" for x in pages] if pages else ["- (none)"]
    lines += [
        "",
        "Reasoning:",
        str(design.get("reasoning") or reasoning.get("reason_summary") or "unclear architecture"),
        "",
        "Next step",
        "",
        "1. generate development plan",
        f"   /plan {idea}",
        "",
        "2. generate project",
        f"   /idea_local {idea}",
    ]
    InlineKeyboardButton, InlineKeyboardMarkup = _inline_keyboard_classes()
    reply_markup = InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton(text="PLAN", callback_data=_encode_callback_data("plan", idea)),
                InlineKeyboardButton(text="GENERATE", callback_data=_encode_callback_data("generate", idea)),
            ]
        ]
    )
    await update.message.reply_text(_truncate_message("\n".join(lines)), reply_markup=reply_markup)


def _format_plan_message(plan: dict[str, Any]) -> str:
    phases = plan.get("phases") if isinstance(plan.get("phases"), list) else []
    if not phases:
        return "No plan suggestions available.\n\nNext:\n- /inspect\n- /next"
    lines = ["Development plan", ""]
    step_no = 1
    for phase in phases:
        if not isinstance(phase, dict):
            continue
        title = str(phase.get("title") or "").strip()
        steps = [str(x).strip() for x in (phase.get("steps") or []) if str(x).strip()]
        if not title or not steps:
            continue
        lines.append(f"Phase {len([x for x in lines if str(x).startswith('Phase ')]) + 1} - {title}")
        for step in steps:
            lines.append(f"{step_no}. {step}")
            step_no += 1
        lines.append("")
    if step_no == 1:
        return "No plan suggestions available.\n\nNext:\n- /inspect\n- /next"
    lines += ["Next:", "- run suggested commands", "- /inspect"]
    return "\n".join(lines)


def _save_plan_execution(project_path: Path, plan: dict[str, Any]) -> None:
    plan_path = project_path / ".archmind" / "plan_execution.json"
    plan_path.parent.mkdir(parents=True, exist_ok=True)
    plan_path.write_text(json.dumps(plan, ensure_ascii=False, indent=2), encoding="utf-8")


def _flatten_plan_steps(plan: dict[str, Any], max_steps: int = 20) -> list[str]:
    out: list[str] = []
    phases = plan.get("phases") if isinstance(plan.get("phases"), list) else []
    for phase in phases:
        if not isinstance(phase, dict):
            continue
        steps = phase.get("steps") if isinstance(phase.get("steps"), list) else []
        for step in steps:
            cmd = str(step).strip()
            if cmd:
                out.append(cmd)
            if len(out) >= max_steps:
                return out
    return out


class _PlanExecMessage:
    def __init__(self) -> None:
        self.sent: list[str] = []

    async def reply_text(self, text: str) -> None:
        self.sent.append(text)


class _PlanExecUpdate:
    def __init__(self, message: _PlanExecMessage) -> None:
        self.message = message


class _PlanExecContext:
    def __init__(self, args: list[str]) -> None:
        self.args = args


async def _execute_plan_step(step: str) -> tuple[str, str]:
    parts = [x for x in str(step).strip().split(" ") if x]
    if not parts:
        return "SKIPPED", "empty step"
    command = parts[0].strip()
    args = parts[1:]

    message = _PlanExecMessage()
    update = _PlanExecUpdate(message)
    ctx = _PlanExecContext(args)

    if command == "/add_entity":
        await command_add_entity(update, ctx)
    elif command == "/add_field":
        await command_add_field(update, ctx)
    elif command == "/add_api":
        await command_add_api(update, ctx)
    elif command == "/add_page":
        await command_add_page(update, ctx)
    else:
        return "SKIPPED", "unsupported step"

    result = message.sent[-1] if message.sent else ""
    text = str(result or "")
    lower = text.lower()
    skip_markers = (
        "entity already exists",
        "field already exists",
        "api already exists",
        "page already exists",
        "module already present",
    )
    if any(marker in lower for marker in skip_markers):
        return "SKIPPED", text
    fail_markers = (
        "usage:",
        "unknown module",
        "unknown field type",
        "unknown method",
        "invalid path",
        "invalid page path",
        "entity not found",
        "no project selected",
        "no active project",
    )
    if any(marker in lower for marker in fail_markers):
        return "FAILED", text
    return "SUCCESS", text


async def command_plan(update: Any, context: Any) -> None:
    args = [str(x).strip() for x in getattr(context, "args", []) if str(x).strip()]
    if args:
        idea = " ".join(args).strip()
        normalized_payload = normalize_idea(idea)
        normalized = str(normalized_payload.get("normalized") or idea)
        reasoning = reason_architecture_from_idea(normalized)
        suggestion = suggest_project_spec(normalized, reasoning)
        plan = build_plan_from_suggestion(normalized, reasoning, suggestion)
        target_project = _resolve_target_project()
        if target_project is not None:
            _save_plan_execution(target_project, plan)
        InlineKeyboardButton, InlineKeyboardMarkup = _inline_keyboard_classes()
        reply_markup = InlineKeyboardMarkup(
            [[InlineKeyboardButton(text="GENERATE", callback_data=_encode_callback_data("generate", idea))]]
        )
        await update.message.reply_text(_truncate_message(_format_plan_message(plan)), reply_markup=reply_markup)
        return

    project_path = _resolve_target_project()
    if project_path is None:
        await update.message.reply_text(_no_active_project_guidance())
        return
    spec_path = project_path / ".archmind" / "project_spec.json"
    raw = _load_json(spec_path) or {}
    if not raw:
        raw, _ = _read_or_init_project_spec(project_path)
    plan = build_plan_from_project_spec(raw)
    _save_plan_execution(project_path, plan)
    await update.message.reply_text(_truncate_message(_format_plan_message(plan)))


async def command_apply_plan(update: Any, context: Any) -> None:
    del context
    project_path = _resolve_target_project()
    if project_path is None:
        await update.message.reply_text(
            "No active project.\n\n"
            "To execute a development plan, first create or select a project.\n\n"
            "Recommended workflow:\n\n"
            "1. /design <idea>\n"
            "2. /plan <idea>\n"
            "3. /idea_local <idea>\n"
            "4. /apply_plan\n\n"
            "Or use an existing project:\n\n"
            "1. /projects\n"
            "2. /use <n>\n"
            "3. /apply_plan\n\n"
            "Next:\n"
            "- /idea_local <idea>\n"
            "- /projects"
        )
        return

    plan_path = project_path / ".archmind" / "plan_execution.json"
    plan_payload = _load_json(plan_path)
    if plan_payload is None:
        await update.message.reply_text("No saved plan available.\n\nRun:\n- /plan <idea>\nor\n- /plan")
        return

    steps = _flatten_plan_steps(plan_payload, max_steps=20)
    if not steps:
        await update.message.reply_text("No saved plan available.\n\nRun:\n- /plan <idea>\nor\n- /plan")
        return

    lines = ["Applying development plan...", ""]
    success = 0
    skipped = 0
    failed = 0
    for i, step in enumerate(steps, start=1):
        status, detail = await _execute_plan_step(step)
        lines.append(f"{i}. {step}")
        if status == "SUCCESS":
            success += 1
            lines.append("✓ SUCCESS")
        elif status == "SKIPPED":
            skipped += 1
            lines.append("~ SKIPPED")
        else:
            failed += 1
            lines.append("✗ FAILED")
        if status == "FAILED":
            reason = str(detail).strip().splitlines()[0] if str(detail).strip() else "unknown"
            lines.append(f"reason: {reason}")
        lines.append("")

    lines += [
        "Plan execution complete.",
        "",
        "Applied:",
        f"Success: {success}",
        f"Skipped: {skipped}",
        f"Failed: {failed}",
        "",
        "Next:",
        "- /inspect",
        "- /next",
    ]
    await update.message.reply_text(_truncate_message("\n".join(lines)))


async def command_continue(update: Any, context: Any) -> None:
    await _handle_continue(update, context)


async def command_fix(update: Any, context: Any) -> None:
    await _handle_fix(update, context)


async def command_retry(update: Any, context: Any) -> None:
    await _handle_retry(update, context)


async def command_state(update: Any, context: Any) -> None:
    del context
    project_path = _resolve_target_project()
    if project_path is None:
        await update.message.reply_text("No project yet. Start with /idea <text> first.")
        return
    running = _get_running_job()
    if running is not None:
        await update.message.reply_text(
            _truncate_message(
                f"Current state: {running.state}\n"
                f"Current command: {running.command}\n"
                f"Project: {running.project_dir}\n"
                f"Progress: {_progress_text(running.project_dir, fallback=_progress_fallback_for_command(running.command))}\n"
                "Use /state again later for a full snapshot."
            )
        )
        return
    ok, output = run_state_command(project_path)
    if not ok:
        await update.message.reply_text(_truncate_message(output))
        return
    await update.message.reply_text(_truncate_message(output))


async def command_status(update: Any, context: Any) -> None:
    del context
    project_path = _resolve_target_project()
    if project_path is None:
        await update.message.reply_text("No project yet. Start with /idea <text> first.")
        return
    await update.message.reply_text(format_status_text(project_path))


async def command_current(update: Any, context: Any) -> None:
    del context
    project_path = get_current_project()
    if project_path is None:
        await update.message.reply_text("No current project selected. Use /projects then /use <n>.")
        return

    state_payload = _load_json(project_path / ".archmind" / "state.json") or {}
    result_payload = _load_json(project_path / ".archmind" / "result.json") or {}
    status = "STOPPED"
    project_type = _resolve_project_type(state_payload, project_path)
    template = str(state_payload.get("effective_template") or "unknown").strip() or "unknown"
    runtime_backend = "STOPPED"
    runtime_frontend = "NOT RUNNING"
    backend_url = str(state_payload.get("backend_deploy_url") or "").strip()
    frontend_url = str(state_payload.get("frontend_deploy_url") or "").strip()
    try:
        from archmind.deploy import get_local_runtime_status

        runtime_payload = get_local_runtime_status(project_path)
        backend = runtime_payload.get("backend") if isinstance(runtime_payload, dict) else {}
        frontend = runtime_payload.get("frontend") if isinstance(runtime_payload, dict) else {}
        if isinstance(backend, dict):
            runtime_backend = "RUNNING" if str(backend.get("status") or "").strip().upper() == "RUNNING" else "STOPPED"
            backend_url = str(backend.get("url") or backend_url).strip()
        if isinstance(frontend, dict):
            runtime_frontend = (
                "RUNNING" if str(frontend.get("status") or "").strip().upper() == "RUNNING" else "NOT RUNNING"
            )
            frontend_url = str(frontend.get("url") or frontend_url).strip()
    except Exception:
        runtime_payload = {}
        if state_payload.get("backend_pid") is not None:
            runtime_backend = "RUNNING"
        if state_payload.get("frontend_pid") is not None:
            runtime_frontend = "RUNNING"

    status = _project_runtime_status(project_path, state_payload, result_payload, runtime_payload)

    external_ip = _detect_external_ip()
    runtime_lines = [
        "Runtime",
        f"Backend: {runtime_backend}",
    ]
    if backend_url:
        runtime_lines.append(f"Backend URL: {backend_url}")
        external_backend_url = _external_url_for(backend_url, external_ip)
        if runtime_backend == "RUNNING" and external_backend_url:
            runtime_lines.append(f"External URL: {external_backend_url}")
    runtime_lines.append(f"Frontend: {runtime_frontend}")
    if runtime_frontend == "RUNNING" and frontend_url:
        runtime_lines.append(f"Frontend URL: {frontend_url}")
        external_frontend_url = _external_url_for(frontend_url, external_ip)
        if external_frontend_url:
            runtime_lines.append(f"External URL: {external_frontend_url}")

    message = (
        "Current project\n\n"
        f"Project: {project_path.name}\n"
        f"Status: {status}\n"
        f"Type: {project_type}\n"
        f"Template: {template}\n\n"
        + "\n".join(runtime_lines)
        + "\n\n"
        "Next:\n"
        "- /inspect\n"
        "- /next"
    )
    await update.message.reply_text(message)


async def command_inspect(update: Any, context: Any) -> None:
    del context
    project_path = _resolve_target_project()
    if project_path is None:
        await update.message.reply_text(_no_active_project_guidance())
        return

    archmind_dir = project_path / ".archmind"
    raw_spec = _load_json(archmind_dir / "project_spec.json") or {}
    spec, _ = _read_or_init_project_spec(project_path)
    reasoning = _load_json(archmind_dir / "architecture_reasoning.json") or {}
    state = load_state(project_path) or {}

    shape = str(spec.get("shape") or reasoning.get("app_shape") or "unknown").strip() or "unknown"
    template = str(spec.get("template") or reasoning.get("recommended_template") or "unknown").strip() or "unknown"
    domains = [str(x) for x in (spec.get("domains") or reasoning.get("domains") or []) if str(x).strip()]
    modules = [str(x) for x in (spec.get("modules") or reasoning.get("modules") or []) if str(x).strip()]
    entities = _entity_summaries_for_inspect(spec.get("entities"), max_fields=5)
    entity_tree_lines = _entity_tree_lines_for_inspect(spec.get("entities"), max_entities=10, max_fields=8)
    api_endpoints = [str(x) for x in (spec.get("api_endpoints") or []) if str(x).strip()]
    frontend_pages = [str(x) for x in (spec.get("frontend_pages") or []) if str(x).strip()]
    reason_summary = str(spec.get("reason_summary") or reasoning.get("reason_summary") or "").strip()
    evolution = spec.get("evolution") if isinstance(spec.get("evolution"), dict) else {}
    evolution_version = int(evolution.get("version") or 1) if evolution else 1
    evolution_added = _ordered_modules([str(x) for x in (evolution.get("added_modules") or [])]) if evolution else []
    evolution_history_count = len(evolution.get("history") or []) if isinstance(evolution.get("history"), list) else 0
    recent_evolution = summarize_recent_evolution(spec, limit=5)
    progression_spec = raw_spec if isinstance(raw_spec, dict) and raw_spec else spec
    progression = analyze_spec_progression(progression_spec if isinstance(progression_spec, dict) else {})

    root_backend_main = project_path / "app" / "main.py"
    nested_backend_main = project_path / "backend" / "app" / "main.py"
    has_backend = (
        root_backend_main.exists()
        or nested_backend_main.exists()
        or (project_path / "app").is_dir()
        or (project_path / "backend" / "app").is_dir()
        or (project_path / "requirements.txt").exists()
        or (project_path / "backend" / "requirements.txt").exists()
    )
    has_frontend = (
        (project_path / "frontend").is_dir()
        or (project_path / "package.json").exists()
        or (project_path / "next.config.mjs").exists()
    )
    if has_backend and has_frontend:
        structure = "backend + frontend"
    elif has_backend:
        structure = "backend"
    elif has_frontend:
        structure = "frontend"
    else:
        structure = ""

    core_candidates = [
        ("app", True),
        ("frontend", True),
        ("README.md", False),
        ("requirements.txt", False),
        ("package.json", False),
        ("next.config.mjs", False),
    ]
    core_files: list[str] = []
    for name, as_dir in core_candidates:
        p = project_path / name
        if not p.exists():
            continue
        if as_dir:
            core_files.append(f"{name}/")
        else:
            core_files.append(name)

    lines = [
        "Project:",
        project_path.name,
        "",
        "Architecture:",
        f"Shape: {shape}",
        f"Template: {template}",
        f"Domains: {', '.join(domains) if domains else '(none)'}",
        f"Modules: {', '.join(modules) if modules else '(none)'}",
    ]
    lines += [
        "",
        "Spec Summary:",
        f"- Stage: {progression.get('stage_label')}",
        f"- Entities: {int(progression.get('entities_count') or 0)}",
        f"- APIs: {int(progression.get('apis_count') or 0)}",
        f"- Pages: {int(progression.get('pages_count') or 0)}",
        f"- Evolution history: {evolution_history_count}",
    ]
    _append_truncated_bullets(lines, "Entities:", entities, limit=10, suffix_label="entities")
    lines += ["", "Entity Fields:"] + entity_tree_lines
    _append_truncated_bullets(lines, "APIs:", api_endpoints, limit=10, suffix_label="endpoints")
    _append_truncated_bullets(lines, "Pages:", frontend_pages, limit=10, suffix_label="pages")
    if reason_summary:
        lines += ["", "Reasoning:", reason_summary]
    if structure:
        lines += ["", "Structure:", structure]
    if core_files:
        lines += ["", "Files:"] + core_files[:6]
    entrypoint_label = "app.main:app" if (root_backend_main.exists() or nested_backend_main.exists()) else "(missing)"
    lines += [
        "",
        "Project Structure:",
        f"- backend: {'OK' if has_backend else 'MISSING'}",
        f"- frontend: {'OK' if has_frontend else 'MISSING'}",
        f"- entrypoint: {entrypoint_label}",
    ]

    deploy_block = state.get("deploy") if isinstance(state.get("deploy"), dict) else {}
    runtime_block = state.get("runtime") if isinstance(state.get("runtime"), dict) else {}
    runtime_ctx = _improve_runtime_context(project_path, state)
    runtime_detect_ok = bool(runtime_ctx.get("detect_ok"))
    runtime_services = runtime_block.get("services") if isinstance(runtime_block.get("services"), dict) else {}
    backend_service = runtime_services.get("backend") if isinstance(runtime_services.get("backend"), dict) else {}
    frontend_service = runtime_services.get("frontend") if isinstance(runtime_services.get("frontend"), dict) else {}
    backend_entry = str(runtime_ctx.get("backend_entry") or "").strip()
    backend_run_mode = str(runtime_ctx.get("backend_run_mode") or "").strip()
    runtime_failure_class = str(runtime_ctx.get("failure_class") or "").strip()
    api_base_url = _read_frontend_api_base_url(project_path)

    try:
        from archmind.deploy import get_local_runtime_status

        live_runtime = get_local_runtime_status(project_path)
        live_services = live_runtime.get("services") if isinstance(live_runtime.get("services"), dict) else {}
        if isinstance(live_services.get("backend"), dict):
            backend_service = dict(live_services.get("backend") or {})
        elif isinstance(live_runtime.get("backend"), dict):
            backend_raw = live_runtime.get("backend") or {}
            backend_service = {
                "status": str(backend_raw.get("status") or "").strip().upper(),
                "pid": backend_raw.get("pid"),
                "url": str(backend_raw.get("url") or "").strip(),
                "port": None,
                "log_path": "",
            }
        if isinstance(live_services.get("frontend"), dict):
            frontend_service = dict(live_services.get("frontend") or {})
        elif isinstance(live_runtime.get("frontend"), dict):
            frontend_raw = live_runtime.get("frontend") or {}
            frontend_service = {
                "status": str(frontend_raw.get("status") or "").strip().upper(),
                "pid": frontend_raw.get("pid"),
                "url": str(frontend_raw.get("url") or "").strip(),
                "port": None,
                "log_path": "",
            }
    except Exception:
        pass

    runtime_backend = str(backend_service.get("status") or runtime_block.get("backend_status") or "").strip().upper()
    runtime_frontend = str(frontend_service.get("status") or runtime_block.get("frontend_status") or "").strip().upper()
    if not runtime_backend:
        runtime_backend = "NOT RUNNING"
    if not runtime_frontend:
        runtime_frontend = "NOT RUNNING"
    state_backend_status = str(runtime_block.get("backend_status") or "").strip().upper()
    if runtime_backend in {"NOT RUNNING", "STOPPED"} and runtime_failure_class and state_backend_status in {"FAIL", "FAILED", "WARNING"}:
        runtime_backend = "FAIL"
    backend_pid = backend_service.get("pid") or runtime_block.get("backend_pid") or state.get("backend_pid")
    frontend_pid = frontend_service.get("pid") or runtime_block.get("frontend_pid") or state.get("frontend_pid")
    backend_url = str(backend_service.get("url") or runtime_block.get("backend_url") or state.get("backend_deploy_url") or "").strip()
    frontend_url = str(frontend_service.get("url") or runtime_block.get("frontend_url") or state.get("frontend_deploy_url") or "").strip()

    if runtime_backend == "RUNNING":
        runtime_failure_class = ""

    lines += ["", "Runtime:"]
    lines.append(f"Backend: {runtime_backend}")
    if backend_pid:
        lines.append(f"Backend PID: {backend_pid}")
    lines.append(f"Frontend: {runtime_frontend}")
    if frontend_pid:
        lines.append(f"Frontend PID: {frontend_pid}")

    if backend_url:
        lines += ["", "Backend URL:", backend_url]
    if frontend_url:
        lines += ["", "Frontend URL:", frontend_url]
    if api_base_url:
        lines += ["", "API Base URL:", api_base_url]
    if backend_entry or backend_run_mode:
        lines += ["", "Backend Runtime:"]
        if backend_entry:
            lines.append(f"Backend Entry: {backend_entry}")
        if backend_run_mode:
            lines.append(f"Backend Run Mode: {backend_run_mode}")

    deploy_target = str(
        (deploy_block.get("target") if isinstance(deploy_block, dict) else "")
        or state.get("deploy_target")
        or state.get("auto_deploy_target")
        or ""
    ).strip()
    deploy_status = str(
        (deploy_block.get("status") if isinstance(deploy_block, dict) else "")
        or state.get("last_deploy_status")
        or state.get("auto_deploy_status")
        or ""
    ).strip().upper()
    if deploy_target or deploy_status:
        lines += ["", "Deploy:"]
        if deploy_target:
            lines.append(f"Target: {deploy_target}")
        if deploy_status:
            lines.append(f"Status: {deploy_status}")
    repository_info = _repository_summary_from_state(state)
    repository_status = str(repository_info.get("status") or "").strip()
    repository_url = str(repository_info.get("url") or "").strip()
    repository_reason = str(repository_info.get("reason") or "").strip()
    if repository_status or repository_url or repository_reason:
        lines += ["", "Repository:"]
        lines.append(f"Status: {repository_status or 'SKIPPED'}")
        if repository_url:
            lines.append(f"URL: {repository_url}")
        if repository_reason:
            lines.append(f"Reason: {repository_reason}")
    if runtime_failure_class:
        lines += ["", f"Failure Class: {runtime_failure_class}"]
    elif runtime_detect_ok or backend_entry or backend_run_mode or has_backend:
        lines += ["", "Failure Class: (none)"]

    if evolution:
        lines += ["", "Evolution:", f"Version: {evolution_version}"]
        if evolution_added:
            lines.append(f"Added modules: {', '.join(evolution_added)}")
        lines.append(f"History count: {evolution_history_count}")
        lines.append("")
        lines.append("Recent evolution:")
        if recent_evolution:
            for item in recent_evolution:
                lines.append(f"- {item}")
        else:
            lines.append("(none)")
    lines += [
        "",
        "Try next:",
        "- /next",
        "- /add_entity <name>",
        "- /add_field <Entity> <field>:<type>",
    ]

    await update.message.reply_text(_truncate_message("\n".join(lines)))


async def command_improve(update: Any, context: Any) -> None:
    del context
    project_path = _resolve_target_project()
    if project_path is None:
        await update.message.reply_text(_no_active_project_guidance())
        return
    report = _build_improvement_report(project_path)
    commands = _extract_recommended_commands_from_text(report)
    for fallback in ("/inspect", "/next"):
        if fallback not in commands:
            commands.append(fallback)
    reply_markup = _build_action_keyboard(commands)
    if reply_markup is not None:
        await update.message.reply_text(report, reply_markup=reply_markup)
    else:
        await update.message.reply_text(report)


def _build_selected_project_summary(project_path: Path) -> str:
    archmind_dir = project_path / ".archmind"
    spec, _ = _read_or_init_project_spec(project_path)
    reasoning = _load_json(archmind_dir / "architecture_reasoning.json") or {}
    state = _load_json(archmind_dir / "state.json") or {}

    shape = str(spec.get("shape") or reasoning.get("app_shape") or "unknown").strip() or "unknown"
    template = str(spec.get("template") or reasoning.get("recommended_template") or "unknown").strip() or "unknown"
    domains = [str(x) for x in (spec.get("domains") or reasoning.get("domains") or []) if str(x).strip()]
    modules = [str(x) for x in (spec.get("modules") or reasoning.get("modules") or []) if str(x).strip()]
    evolution = spec.get("evolution") if isinstance(spec.get("evolution"), dict) else {}
    evolution_version = int(evolution.get("version") or 1) if evolution else 1
    evolution_added = _ordered_modules([str(x) for x in (evolution.get("added_modules") or [])]) if evolution else []

    lines = [
        f"Selected project: {project_path.name}",
        "",
        "Shape:",
        shape,
        "",
        "Template:",
        template,
    ]

    if domains:
        lines += ["", "Domains:", ", ".join(domains)]
    if modules:
        lines += ["", "Modules:", ", ".join(modules)]
    if evolution_added:
        lines += ["", "Evolution:", f"Version: {evolution_version}", f"Added modules: {', '.join(evolution_added)}"]

    root_backend_main = project_path / "app" / "main.py"
    nested_backend_main = project_path / "backend" / "app" / "main.py"
    has_backend = bool(root_backend_main.exists() or nested_backend_main.exists())
    has_frontend = (project_path / "frontend").is_dir()
    deploy_block = state.get("deploy") if isinstance(state.get("deploy"), dict) else {}
    runtime_block = state.get("runtime") if isinstance(state.get("runtime"), dict) else {}
    runtime_ctx = _improve_runtime_context(project_path, state)
    runtime_detect_ok = bool(runtime_ctx.get("detect_ok"))
    runtime_backend = ""
    runtime_frontend = ""
    backend_url = str(
        (runtime_block.get("backend_url") if isinstance(runtime_block, dict) else "")
        or state.get("backend_deploy_url")
        or ""
    ).strip()
    frontend_url = str(
        (deploy_block.get("frontend_url") if isinstance(deploy_block, dict) else "")
        or state.get("frontend_deploy_url")
        or ""
    ).strip()
    backend_entry = str(runtime_ctx.get("backend_entry") or "").strip()
    backend_run_mode = str(runtime_ctx.get("backend_run_mode") or "").strip()
    runtime_failure_class = str(runtime_ctx.get("failure_class") or "").strip()
    api_base_url = _read_frontend_api_base_url(project_path)
    try:
        from archmind.deploy import get_local_runtime_status

        runtime_payload = get_local_runtime_status(project_path)
        backend = runtime_payload.get("backend") if isinstance(runtime_payload, dict) else {}
        frontend = runtime_payload.get("frontend") if isinstance(runtime_payload, dict) else {}
        if isinstance(backend, dict):
            runtime_backend = "RUNNING" if str(backend.get("status") or "").strip().upper() == "RUNNING" else "STOPPED"
            backend_url = str(backend.get("url") or backend_url).strip()
        if isinstance(frontend, dict):
            runtime_frontend = "RUNNING" if str(frontend.get("status") or "").strip().upper() == "RUNNING" else "STOPPED"
            frontend_url = str(frontend.get("url") or frontend_url).strip()
    except Exception:
        backend_pid = (runtime_block.get("backend_pid") if isinstance(runtime_block, dict) else None) or state.get("backend_pid")
        frontend_pid = (runtime_block.get("frontend_pid") if isinstance(runtime_block, dict) else None) or state.get("frontend_pid")
        if backend_pid is not None:
            runtime_backend = "RUNNING"
        if frontend_pid is not None:
            runtime_frontend = "RUNNING"

    if runtime_backend or runtime_frontend:
        lines += ["", "Runtime:"]
        if runtime_backend:
            lines.append(f"Backend: {runtime_backend}")
        if runtime_frontend:
            lines.append(f"Frontend: {runtime_frontend}")

    if backend_url:
        lines += ["", "Backend URL:", backend_url]
    if frontend_url:
        lines += ["", "Frontend URL:", frontend_url]
    if api_base_url:
        lines += ["", "API Base URL:", api_base_url]
    lines += [
        "",
        "Project Structure:",
        f"- backend: {'OK' if has_backend else 'MISSING'}",
        f"- frontend: {'OK' if has_frontend else 'MISSING'}",
        f"- entrypoint: {'app.main:app' if has_backend else '(missing)'}",
    ]
    if backend_entry or backend_run_mode:
        lines += ["", "Backend Runtime:"]
        if backend_entry:
            lines.append(f"Backend Entry: {backend_entry}")
        if backend_run_mode:
            lines.append(f"Backend Run Mode: {backend_run_mode}")

    deploy_target = str(
        (deploy_block.get("target") if isinstance(deploy_block, dict) else "")
        or state.get("deploy_target")
        or state.get("auto_deploy_target")
        or ""
    ).strip()
    deploy_status = str(
        (deploy_block.get("status") if isinstance(deploy_block, dict) else "")
        or state.get("last_deploy_status")
        or state.get("auto_deploy_status")
        or ""
    ).strip().upper()
    if deploy_target or deploy_status:
        lines += ["", "Deploy:"]
        if deploy_target:
            lines.append(f"Target: {deploy_target}")
        if deploy_status:
            lines.append(f"Status: {deploy_status}")
    repository_info = _repository_summary_from_state(state)
    repository_status = str(repository_info.get("status") or "").strip()
    repository_url = str(repository_info.get("url") or "").strip()
    repository_reason = str(repository_info.get("reason") or "").strip()
    if repository_status or repository_url or repository_reason:
        lines += ["", "Repository:"]
        lines.append(f"Status: {repository_status or 'SKIPPED'}")
        if repository_url:
            lines.append(f"URL: {repository_url}")
        if repository_reason:
            lines.append(f"Reason: {repository_reason}")
    if runtime_failure_class:
        lines.append(f"Failure Class: {runtime_failure_class}")
    elif runtime_detect_ok or backend_entry or backend_run_mode or has_backend:
        lines.append("Failure Class: (none)")

    lines += ["", "Try next:", "- /inspect", "- /next"]

    return "\n".join(lines)


def _frontend_dir_for_project(project_path: Path) -> Optional[Path]:
    root = project_path.expanduser().resolve()
    frontend_subdir = root / "frontend"
    if frontend_subdir.is_dir():
        return frontend_subdir
    if (root / "package.json").exists() and ((root / "app").is_dir() or (root / "pages").is_dir()):
        return root
    return None


def _fullstack_intent_from_text(text: str) -> bool:
    raw = str(text or "").strip().lower()
    if not raw:
        return False
    keywords = ("webapp", "웹앱", "블로그", "다이어리", "게시판", "대시보드", "관리화면")
    return any(token in raw for token in keywords)


def _extract_project_idea_hint(reasoning: dict[str, Any], state_payload: dict[str, Any], spec: dict[str, Any]) -> str:
    candidates = [
        str(reasoning.get("idea_original") or ""),
        str(reasoning.get("idea_normalized") or ""),
        str(spec.get("reason_summary") or ""),
        str(state_payload.get("architecture_reason_summary") or ""),
    ]
    for value in candidates:
        text = str(value).strip()
        if text:
            return text
    return ""


def _repository_summary_from_state(state_payload: dict[str, Any]) -> dict[str, str]:
    repository_block = state_payload.get("repository") if isinstance(state_payload.get("repository"), dict) else {}
    status = str((repository_block.get("status") if isinstance(repository_block, dict) else "") or "").strip().upper()
    url = str(
        (repository_block.get("url") if isinstance(repository_block, dict) else "")
        or state_payload.get("github_repo_url")
        or ""
    ).strip()
    reason = str((repository_block.get("reason") if isinstance(repository_block, dict) else "") or "").strip()
    if not status:
        status = "CREATED" if url else "SKIPPED"
    return {
        "status": status,
        "url": url,
        "reason": reason,
    }


def _state_block_value(block: dict[str, Any], key: str, fallback: Any) -> Any:
    if key in block:
        return block.get(key)
    return fallback


def _improve_runtime_context(project_path: Path, state_payload: dict[str, Any]) -> dict[str, Any]:
    runtime_block = state_payload.get("runtime") if isinstance(state_payload.get("runtime"), dict) else {}
    backend_status_raw = _state_block_value(runtime_block, "backend_status", state_payload.get("backend_status"))
    backend_status = str(backend_status_raw or "").strip().upper()
    if backend_status == "NOT RUNNING":
        backend_status = "STOPPED"
    runtime_failure_raw = _state_block_value(
        runtime_block,
        "failure_class",
        state_payload.get("runtime_failure_class") or state_payload.get("last_failure_class"),
    )
    runtime_failure_class = str(runtime_failure_raw or "").strip()
    backend_entry = str(_state_block_value(runtime_block, "backend_entry", state_payload.get("backend_entry")) or "").strip()
    backend_run_mode = str(_state_block_value(runtime_block, "backend_run_mode", state_payload.get("backend_run_mode")) or "").strip()
    backend_run_command = str(_state_block_value(runtime_block, "backend_run_command", state_payload.get("backend_run_command")) or "").strip()
    auto_fix = runtime_block.get("auto_fix") if isinstance(runtime_block.get("auto_fix"), dict) else {}
    preflight = runtime_block.get("preflight") if isinstance(runtime_block.get("preflight"), dict) else {}
    try:
        detected = detect_backend_runtime_entry(project_path, port=8000)
    except Exception:
        detected = {"ok": False}
    detect_ok = bool(detected.get("ok"))
    if detect_ok:
        backend_entry = str(detected.get("backend_entry") or backend_entry or "").strip()
        backend_run_mode = str(detected.get("backend_run_mode") or backend_run_mode or "").strip()
        cmd_items = [str(item).strip() for item in (detected.get("run_command") or []) if str(item).strip()]
        backend_run_command = " ".join(cmd_items) if cmd_items else backend_run_command
        runtime_failure_class = ""
    elif not runtime_failure_class:
        runtime_failure_class = str(detected.get("failure_class") or "").strip()
    return {
        "backend_status": backend_status,
        "failure_class": runtime_failure_class,
        "backend_entry": backend_entry,
        "backend_run_mode": backend_run_mode,
        "backend_run_command": backend_run_command,
        "auto_fix": auto_fix,
        "preflight": preflight,
        "detect_ok": detect_ok,
        "detected": detected,
    }


def _improve_deploy_context(state_payload: dict[str, Any]) -> dict[str, str]:
    deploy_block = state_payload.get("deploy") if isinstance(state_payload.get("deploy"), dict) else {}
    target = str(
        _state_block_value(
            deploy_block,
            "target",
            state_payload.get("deploy_target") or state_payload.get("auto_deploy_target"),
        )
        or ""
    ).strip()
    status = str(
        _state_block_value(
            deploy_block,
            "status",
            state_payload.get("last_deploy_status") or state_payload.get("auto_deploy_status"),
        )
        or ""
    ).strip().upper()
    failure_class = str(_state_block_value(deploy_block, "failure_class", "") or "").strip()
    return {
        "target": target,
        "status": status,
        "failure_class": failure_class,
    }


def _build_improvement_report(project_path: Path) -> str:
    root = project_path.expanduser().resolve()
    archmind_dir = root / ".archmind"
    spec, _ = _read_or_init_project_spec(root)
    raw_spec = _load_json(archmind_dir / "project_spec.json") or {}
    reasoning = _load_json(archmind_dir / "architecture_reasoning.json") or {}
    state_payload = load_state(root) or {}
    shape = str(spec.get("shape") or reasoning.get("app_shape") or state_payload.get("architecture_app_shape") or "unknown").strip().lower()
    template = str(
        state_payload.get("effective_template")
        or spec.get("template")
        or reasoning.get("recommended_template")
        or "unknown"
    ).strip().lower()
    fullstack_expected = shape == "fullstack" or template == "fullstack-ddd"

    backend_entry_root = root / "app" / "main.py"
    backend_entry_nested = root / "backend" / "app" / "main.py"
    backend_entry_ok = backend_entry_nested.exists() if fullstack_expected else (backend_entry_root.exists() or backend_entry_nested.exists())
    has_backend = backend_entry_ok or (root / "app").is_dir() or (root / "backend" / "app").is_dir()
    frontend_dir = _frontend_dir_for_project(root)
    has_frontend = frontend_dir is not None
    frontend_root_ok = (root / "frontend").is_dir()
    requirements_ok = (root / "backend" / "requirements.txt").exists() if fullstack_expected else (
        (root / "requirements.txt").exists() or (root / "backend" / "requirements.txt").exists()
    )
    runtime_ctx = _improve_runtime_context(root, state_payload)
    env_fullstack_expected = fullstack_expected
    if bool(runtime_ctx.get("detect_ok")):
        if backend_entry_root.exists() and not backend_entry_nested.exists():
            env_fullstack_expected = False
        elif backend_entry_nested.exists():
            env_fullstack_expected = True
    env_missing_parts = _runtime_env_missing_parts(
        root,
        fullstack_expected=env_fullstack_expected,
        has_frontend=has_frontend,
    )
    deploy_ctx = _improve_deploy_context(state_payload)
    runtime_backend_status = str(runtime_ctx.get("backend_status") or "").strip().upper()
    runtime_failure_class = str(runtime_ctx.get("failure_class") or "").strip()
    runtime_detect_ok = bool(runtime_ctx.get("detect_ok"))
    live_backend_status = ""
    live_backend_url = ""
    live_frontend_status = ""
    live_frontend_url = ""
    try:
        from archmind.deploy import get_local_runtime_status

        live_runtime = get_local_runtime_status(root)
        live_backend = live_runtime.get("backend") if isinstance(live_runtime.get("backend"), dict) else {}
        live_frontend = live_runtime.get("frontend") if isinstance(live_runtime.get("frontend"), dict) else {}
        live_backend_status = str(live_backend.get("status") or "").strip().upper()
        live_backend_url = str(live_backend.get("url") or "").strip()
        live_frontend_status = str(live_frontend.get("status") or "").strip().upper()
        live_frontend_url = str(live_frontend.get("url") or "").strip()
    except Exception:
        live_backend_status = ""
        live_backend_url = ""
        live_frontend_status = ""
        live_frontend_url = ""
    runtime_block = state_payload.get("runtime") if isinstance(state_payload.get("runtime"), dict) else {}
    services_block = runtime_block.get("services") if isinstance(runtime_block.get("services"), dict) else {}
    backend_service_block = services_block.get("backend") if isinstance(services_block.get("backend"), dict) else {}
    frontend_service_block = services_block.get("frontend") if isinstance(services_block.get("frontend"), dict) else {}
    latest_health_status = str(
        (runtime_block.get("healthcheck_status") if isinstance(runtime_block, dict) else "")
        or state_payload.get("healthcheck_status")
        or state_payload.get("backend_smoke_status")
        or ""
    ).strip().upper()
    backend_service_health = str(backend_service_block.get("health") or "").strip().upper()
    frontend_service_health = str(frontend_service_block.get("health") or "").strip().upper()
    api_base_url = _read_frontend_api_base_url(root)
    frontend_detect_ok = False
    if has_frontend:
        try:
            frontend_detect_ok = bool(detect_frontend_runtime_entry(root).get("ok"))
        except Exception:
            frontend_detect_ok = False
    backend_running = live_backend_status == "RUNNING" or runtime_backend_status == "RUNNING"
    frontend_running = live_frontend_status == "RUNNING" or str(
        _state_block_value(runtime_block, "frontend_status", state_payload.get("frontend_status")) or ""
    ).strip().upper() == "RUNNING"
    backend_health_ok = latest_health_status == "SUCCESS" or backend_service_health == "SUCCESS"
    frontend_health_ok = frontend_service_health == "SUCCESS"
    backend_env_values = _backend_env_values(root, fullstack_expected=env_fullstack_expected)
    backend_base_url = str(backend_env_values.get("BACKEND_BASE_URL") or "").strip()
    runtime_usable = (
        runtime_detect_ok
        and not runtime_failure_class
        and (
            backend_running
            or backend_health_ok
            or bool(live_backend_url)
            or bool(backend_base_url)
        )
    )
    if runtime_usable and env_missing_parts:
        filtered_missing: list[str] = []
        for item in env_missing_parts:
            key = str(item).strip()
            if not key:
                continue
            # If runtime is already healthy/running, CORS-only gaps are not actionable.
            if key == "CORS_ALLOW_ORIGINS" and (backend_running or backend_health_ok or bool(live_backend_url)):
                continue
            # Backend can be considered usable when runtime URL is available even if env file/key is absent.
            if key in {"backend/.env", ".env", "APP_PORT", "BACKEND_BASE_URL"} and (
                backend_running or backend_health_ok or bool(live_backend_url) or bool(backend_base_url)
            ):
                continue
            # Frontend API URL key/file can be skipped when frontend runtime/detect is already usable.
            if key in {"frontend/.env.local", "NEXT_PUBLIC_API_BASE_URL"} and (
                bool(api_base_url) or bool(live_frontend_url) or frontend_running or frontend_health_ok or frontend_detect_ok
            ):
                continue
            filtered_missing.append(key)
        env_missing_parts = filtered_missing
    deploy_target = str(deploy_ctx.get("target") or "").strip()
    deploy_status = str(deploy_ctx.get("status") or "").strip().upper()
    deploy_failure_class = str(deploy_ctx.get("failure_class") or "").strip()
    project_display_name = root.name
    github_repo_url = str(state_payload.get("github_repo_url") or "").strip()
    idea_hint = _extract_project_idea_hint(reasoning, state_payload, spec)
    fullstack_intent = _fullstack_intent_from_text(idea_hint)
    current_selected = get_current_project()
    last_selected = load_last_project_path()

    runtime_suggestions: list[dict[str, str]] = []
    structure_suggestions: list[dict[str, str]] = []
    evolution_suggestions: list[dict[str, str]] = []
    entities_for_spec = _normalize_entities(spec.get("entities"))
    if fullstack_expected and (not backend_entry_nested.exists() or not frontend_root_ok):
        structure_suggestions.append(
            {
                "title": "Fix fullstack structure contract",
                "reason": "shape/template는 fullstack이지만 backend/app/main.py 또는 frontend 구조가 누락되었습니다.",
                "command": "/idea_local <same idea>",
            }
        )
    if fullstack_intent and (shape == "backend" or template in ("fastapi", "fastapi-ddd")):
        structure_suggestions.append(
            {
                "title": "Align intent with fullstack template",
                "reason": "아이디어는 webapp 성격인데 현재 shape/template가 backend 중심입니다.",
                "command": f"/idea_local {idea_hint}" if idea_hint else "/idea_local <idea>",
            }
        )
    if not has_backend:
        structure_suggestions.append(
            {
                "title": "Restore backend entrypoint",
                "reason": "backend entrypoint를 찾지 못해 runtime에서 실행 실패 가능성이 높습니다.",
                "command": "/inspect",
            }
        )
    if not requirements_ok:
        structure_suggestions.append(
            {
                "title": "Add backend requirements file",
                "reason": "requirements.txt가 없어 python dependency 설치/실행이 불안정합니다.",
                "command": "/inspect",
            }
        )
    if not has_frontend and (fullstack_expected or fullstack_intent):
        structure_suggestions.append(
            {
                "title": "Add missing frontend structure",
                "reason": "web/fullstack 프로젝트인데 frontend 경로가 없습니다.",
                "command": "/idea_local <same idea>",
            }
        )
    normalized_api_endpoints = [
        endpoint
        for endpoint in (_normalize_api_endpoint_text(str(x)) for x in (spec.get("api_endpoints") or []))
        if endpoint
    ]
    normalized_frontend_pages = [
        page
        for page in (_normalize_frontend_page_path(str(x)) for x in (spec.get("frontend_pages") or []))
        if page
    ]
    explicit_api_endpoints = [
        endpoint
        for endpoint in (_normalize_api_endpoint_text(str(x)) for x in (raw_spec.get("api_endpoints") or []))
        if endpoint
    ]
    explicit_frontend_pages = [
        page
        for page in (_normalize_frontend_page_path(str(x)) for x in (raw_spec.get("frontend_pages") or []))
        if page
    ]

    progression_spec = {
        "shape": shape or "unknown",
        "modules": spec.get("modules") if isinstance(spec.get("modules"), list) else [],
        "entities": entities_for_spec,
        "api_endpoints": explicit_api_endpoints if isinstance(raw_spec.get("api_endpoints"), list) else normalized_api_endpoints,
        "frontend_pages": explicit_frontend_pages if isinstance(raw_spec.get("frontend_pages"), list) else normalized_frontend_pages,
    }
    progression = analyze_spec_progression(progression_spec)
    stage = int(progression.get("stage") or 0)
    progression_gap_open = stage < 4

    if env_missing_parts and not progression_gap_open:
        missing_parts = list(dict.fromkeys(env_missing_parts))
        runtime_suggestions.append(
            {
                "title": "Repair runtime env injection",
                "reason": f"runtime 연결 설정 누락: {', '.join(missing_parts)}",
                "command": "/deploy local",
            }
        )
    runtime_failure_needs_fix = runtime_backend_status in {"FAIL", "STOPPED"} and bool(runtime_failure_class) and (not runtime_detect_ok)
    if runtime_failure_needs_fix:
        runtime_suggestions.append(
            {
                "title": "Resolve runtime failure classification",
                "reason": f"최근 failure class가 `{runtime_failure_class}`로 남아 있습니다.",
                "command": "/logs backend",
            }
        )
    if deploy_status == "FAIL" and deploy_failure_class and not progression_gap_open:
        runtime_suggestions.append(
            {
                "title": "Investigate deploy failure classification",
                "reason": (
                    f"deploy target `{deploy_target or 'unknown'}` 가 FAIL 이고 "
                    f"failure class가 `{deploy_failure_class}`입니다."
                ),
                "command": "/deploy railway",
            }
        )

    if github_repo_url:
        slug = ""
        m = re.search(r"github\.com[:/]+([A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+?)(?:\.git)?$", github_repo_url)
        if m:
            slug = m.group(1).split("/", 1)[1]
        if slug and ("_-_-" in slug or not re.search(r"[a-z]", slug)):
            structure_suggestions.append(
                {
                    "title": "Normalize repository slug",
                    "reason": f"repo slug `{slug}`가 가독성이 낮아 관리가 어렵습니다.",
                    "command": "/inspect",
                }
            )
    if re.search(r"[^\x00-\x7F]", project_display_name) and not github_repo_url:
        structure_suggestions.append(
            {
                "title": "Separate display name and repo slug",
                "reason": "프로젝트명이 비ASCII라 repo slug 정책 점검이 필요합니다.",
                "command": "/inspect",
            }
        )

    if current_selected is not None and last_selected is not None and current_selected.resolve() != last_selected.resolve():
        structure_suggestions.append(
            {
                "title": "Confirm target project selection",
                "reason": f"current와 last project가 다릅니다: current={current_selected.name}, last={last_selected.name}",
                "command": "/projects",
            }
        )

    # B-category: feature/model progression suggestions
    evolution_suggestions.extend(suggest_spec_improvements(progression_spec, limit=2))

    if not progression_gap_open:
        next_commands = suggest_next_commands(progression_spec, limit=3)
        existing_cmds = {str(item.get("command") or "").strip() for item in evolution_suggestions}
        deduped_next = [item for item in next_commands if str(item.get("command") or "").strip() not in existing_cmds]
        if deduped_next:
            top = deduped_next[0]
            cmd = str(top.get("command") or "").strip()
            reason = str(top.get("reason") or "").strip() or "기능 확장 관점의 다음 단계입니다."
            runtime_consistent = runtime_detect_ok and runtime_backend_status not in {"FAIL", "STOPPED"} and not runtime_failure_class
            if runtime_consistent:
                reason = f"Runtime diagnostics look consistent; {reason}"
            evolution_suggestions.append(
                {
                    "title": "Expand features incrementally",
                    "reason": reason,
                    "command": cmd or "/next",
                }
            )
        else:
            runtime_consistent = runtime_detect_ok and runtime_backend_status not in {"FAIL", "STOPPED"} and not runtime_failure_class
            reason = "기능 확장을 위해 엔티티/필드/페이지를 점진적으로 추가하세요."
            if runtime_consistent:
                reason = "Runtime diagnostics look consistent; expand model or pages next."
            evolution_suggestions.append(
                {
                    "title": "Expand domain model",
                    "reason": reason,
                    "command": "/add_entity <name>",
                }
            )

    # Keep spec progression gaps as highest-priority improvements.
    if progression_gap_open:
        suggestions = evolution_suggestions[:2] + runtime_suggestions[:1]
    else:
        suggestions = evolution_suggestions + runtime_suggestions + structure_suggestions
    suggestions = suggestions[:3]
    if not suggestions:
        suggestions.append(
            {
                "title": "No immediate correction needed",
                "reason": "치명적 구조 불일치는 감지되지 않았습니다.",
                "command": "/next",
            }
        )

    lines = [
        "Project:",
        root.name,
        "",
        "Improve suggestions",
    ]
    for idx, item in enumerate(suggestions, start=1):
        command_hint = str(item.get("command") or "").strip().splitlines()[0].strip() if str(item.get("command") or "").strip() else "/next"
        lines += [
            "",
            f"{idx}. {item['title']}",
            f"   reason: {item['reason']}",
            f"   command: {command_hint}",
        ]
    lines += [
        "",
        "Next:",
        "- /inspect",
        "- /next",
    ]
    return _truncate_message("\n".join(lines), limit=3900)


async def command_add_module(update: Any, context: Any) -> None:
    project_path = _resolve_target_project()
    if project_path is None:
        await update.message.reply_text(_no_active_project_guidance())
        return

    args = [str(x).strip().lower() for x in getattr(context, "args", []) if str(x).strip()]
    if not args:
        await update.message.reply_text("Usage: /add_module <name>")
        return
    module_name = args[0]
    if module_name not in set(SUPPORTED_MODULES):
        await update.message.reply_text(
            "Unknown module: "
            + module_name
            + "\n\nAvailable modules:\n"
            + ", ".join(SUPPORTED_MODULES)
        )
        return

    spec, spec_path = _read_or_init_project_spec(project_path)
    modules = _ordered_modules([str(x) for x in (spec.get("modules") or [])])
    already_present = module_name in modules
    if not already_present:
        modules.append(module_name)
        modules = _ordered_modules(modules)
        spec["modules"] = modules
        evolution = _ensure_evolution_block(spec)
        added_modules = _ordered_modules([str(x) for x in (evolution.get("added_modules") or [])] + [module_name])
        evolution["added_modules"] = added_modules
        _append_evolution_event(spec, {"action": "add_module", "module": module_name})

        template_name = str(spec.get("template") or "").strip().lower()
        if not template_name:
            state = _load_json(project_path / ".archmind" / "state.json") or {}
            template_name = str(state.get("effective_template") or state.get("selected_template") or "fastapi").strip().lower()
            spec["template"] = template_name

        apply_modules_to_project(project_path, template_name, modules)
        spec_path.parent.mkdir(parents=True, exist_ok=True)
        spec_path.write_text(json.dumps(spec, ensure_ascii=False, indent=2), encoding="utf-8")
        await update.message.reply_text(
            "Module added\n\n"
            "Project:\n"
            f"{project_path.name}\n\n"
            "Added module:\n"
            f"{module_name}\n\n"
            "Modules:\n"
            f"{', '.join(modules)}\n\n"
            "Next:\n"
            "- /inspect\n"
            "- /restart"
        )
        return

    await update.message.reply_text(
        "Module already present\n\n"
        "Project:\n"
        f"{project_path.name}\n\n"
        "Module:\n"
        f"{module_name}\n\n"
        "Modules:\n"
        f"{', '.join(modules)}"
    )


async def command_add_entity(update: Any, context: Any) -> None:
    project_path = _resolve_target_project()
    if project_path is None:
        await update.message.reply_text(_no_active_project_guidance())
        return

    args = [str(x).strip() for x in getattr(context, "args", []) if str(x).strip()]
    if not args:
        await update.message.reply_text("Usage: /add_entity <name>")
        return

    entity_name = _normalize_entity_name(args[0])
    if not entity_name:
        await update.message.reply_text("Usage: /add_entity <name>")
        return

    spec, spec_path = _read_or_init_project_spec(project_path)
    entities = _normalize_entities(spec.get("entities"))
    exists_in_spec = _find_entity_in_spec(entities, entity_name) is not None
    exists_in_files = _entity_exists_in_files(project_path, entity_name)
    if exists_in_spec or exists_in_files:
        if not exists_in_spec:
            entities.append({"name": entity_name, "fields": []})
            spec["entities"] = _normalize_entities(entities)
            _rebuild_api_endpoints(spec)
            _rebuild_frontend_pages(spec)
            spec_path.parent.mkdir(parents=True, exist_ok=True)
            spec_path.write_text(json.dumps(spec, ensure_ascii=False, indent=2), encoding="utf-8")
        await update.message.reply_text(
            "Entity already exists\n\n"
            "Project:\n"
            f"{project_path.name}\n\n"
            "Entity:\n"
            f"{entity_name}"
        )
        return

    prev_api = [
        endpoint
        for endpoint in (_normalize_api_endpoint_text(str(x)) for x in (spec.get("api_endpoints") or []))
        if endpoint
    ]
    prev_pages = [
        page
        for page in (_normalize_frontend_page_path(str(x)) for x in (spec.get("frontend_pages") or []))
        if page
    ]

    entities.append({"name": entity_name, "fields": []})
    spec["entities"] = _normalize_entities(entities)
    rebuilt_api = _rebuild_api_endpoints(spec)
    rebuilt_pages = _rebuild_frontend_pages(spec)
    _append_evolution_event(spec, {"action": "add_entity", "entity": entity_name})

    prev_api_set = {endpoint.upper() for endpoint in prev_api}
    auto_api_candidates = {endpoint.upper() for endpoint in _entity_endpoint_set(entity_name)[:2]}
    for endpoint in rebuilt_api:
        upper = str(endpoint).upper()
        if upper in prev_api_set:
            continue
        if upper not in auto_api_candidates:
            continue
        parts = str(endpoint).split(maxsplit=1)
        if len(parts) != 2:
            continue
        _append_evolution_event(spec, {"action": "auto_add_api", "method": parts[0], "path": parts[1]})

    prev_pages_set = {page.lower() for page in prev_pages}
    auto_page_candidates = {page.lower() for page in _entity_frontend_pages(entity_name)}
    for page in rebuilt_pages:
        key = str(page).lower()
        if key in prev_pages_set:
            continue
        if key not in auto_page_candidates:
            continue
        _append_evolution_event(spec, {"action": "auto_add_page", "page": str(page)})

    generated_files = apply_entity_scaffold(project_path, entity_name)
    frontend_generated = apply_frontend_page_scaffold(project_path, entity_name)
    for path in frontend_generated:
        if path not in generated_files:
            generated_files.append(path)
    frontend_exists = has_frontend_structure(project_path)

    spec_path.parent.mkdir(parents=True, exist_ok=True)
    spec_path.write_text(json.dumps(spec, ensure_ascii=False, indent=2), encoding="utf-8")

    code_lines = []
    if generated_files:
        code_lines = ["Generated:"] + [f"- {path}" for path in generated_files]
        next_lines = ["Next:", "- /inspect"] + (["- /restart"] if frontend_exists else [])
    else:
        code_lines = ["Code scaffold:", "SKIPPED (no backend structure)"]
        next_lines = ["Next:", "- /inspect"]

    if not frontend_exists:
        code_lines += ["", "Frontend scaffold:", "SKIPPED (no frontend structure)"]

    auto_restart_lines, restart_failed = _auto_restart_backend_lines(project_path)
    if restart_failed and "- /logs" not in next_lines:
        next_lines.append("- /logs")

    await update.message.reply_text(
        "Entity added\n\n"
        "Project:\n"
        f"{project_path.name}\n\n"
        "Entity:\n"
        f"{entity_name}\n\n"
        + "\n".join(code_lines)
        + "\n\n"
        + "\n".join(auto_restart_lines)
        + "\n\n"
        + "\n".join(next_lines)
    )


async def command_add_field(update: Any, context: Any) -> None:
    project_path = _resolve_target_project()
    if project_path is None:
        await update.message.reply_text(_no_active_project_guidance())
        return

    args = [str(x).strip() for x in getattr(context, "args", []) if str(x).strip()]
    if len(args) < 2 or ":" not in args[1]:
        await update.message.reply_text("Usage: /add_field <Entity> <field_name>:<field_type>")
        return

    entity_name = _normalize_entity_name(args[0])
    field_name, field_type = [part.strip() for part in args[1].split(":", 1)]
    field_type = field_type.lower()
    if not entity_name or not field_name or not field_type:
        await update.message.reply_text("Usage: /add_field <Entity> <field_name>:<field_type>")
        return

    if field_type not in set(SUPPORTED_FIELD_TYPES):
        await update.message.reply_text(
            "Unknown field type: "
            + field_type
            + "\n\nAvailable types:\n"
            + ", ".join(SUPPORTED_FIELD_TYPES)
        )
        return

    spec, spec_path = _read_or_init_project_spec(project_path)
    entities = _normalize_entities(spec.get("entities"))
    target_entity = _find_entity_in_spec(entities, entity_name)
    if target_entity is None and _entity_exists_in_files(project_path, entity_name):
        entities.append({"name": entity_name, "fields": []})
        entities = _normalize_entities(entities)
        target_entity = _find_entity_in_spec(entities, entity_name)

    if target_entity is None:
        await update.message.reply_text(
            f"Entity not found: {entity_name}\n\n"
            "Use:\n"
            f" /add_entity {entity_name}"
        )
        return

    existing_fields = target_entity.get("fields") if isinstance(target_entity.get("fields"), list) else []
    existing_names = {str(item.get("name") or "").strip().lower() for item in existing_fields if isinstance(item, dict)}
    if field_name.lower() in existing_names:
        _rebuild_api_endpoints(spec)
        _rebuild_frontend_pages(spec)
        spec_path.parent.mkdir(parents=True, exist_ok=True)
        spec_path.write_text(json.dumps(spec, ensure_ascii=False, indent=2), encoding="utf-8")
        pairs = []
        for item in existing_fields:
            if not isinstance(item, dict):
                continue
            n = str(item.get("name") or "").strip()
            t = str(item.get("type") or "").strip().lower()
            if n and t:
                pairs.append(f"{n}:{t}")
        await update.message.reply_text(
            "Field already exists\n\n"
            "Project:\n"
            f"{project_path.name}\n\n"
            "Entity:\n"
            f"{entity_name}\n\n"
            "Field:\n"
            f"{field_name}:{field_type}\n\n"
            "Fields:\n"
            f"{', '.join(pairs)}"
        )
        return

    existing_fields.append({"name": field_name, "type": field_type})
    target_entity["fields"] = existing_fields
    spec["entities"] = _normalize_entities(entities)
    _rebuild_api_endpoints(spec)
    _rebuild_frontend_pages(spec)
    _append_evolution_event(spec, {"action": "add_field", "entity": entity_name, "field": field_name, "type": field_type})

    apply_entity_scaffold(project_path, entity_name)
    apply_entity_fields_to_scaffold(
        project_path,
        entity_name,
        target_entity.get("fields") if isinstance(target_entity.get("fields"), list) else [],
    )

    spec_path.parent.mkdir(parents=True, exist_ok=True)
    spec_path.write_text(json.dumps(spec, ensure_ascii=False, indent=2), encoding="utf-8")

    fields_after = []
    for item in target_entity.get("fields") if isinstance(target_entity.get("fields"), list) else []:
        if not isinstance(item, dict):
            continue
        n = str(item.get("name") or "").strip()
        t = str(item.get("type") or "").strip().lower()
        if n and t:
            fields_after.append(f"{n}:{t}")

    auto_restart_lines, restart_failed = _auto_restart_backend_lines(project_path)
    next_lines = ["- /inspect", "- /restart"]
    if restart_failed:
        next_lines.append("- /logs")

    await update.message.reply_text(
        "Field added\n\n"
        "Project:\n"
        f"{project_path.name}\n\n"
        "Entity:\n"
        f"{entity_name}\n\n"
        "Field:\n"
        f"{field_name}:{field_type}\n\n"
        "Fields:\n"
        f"{', '.join(fields_after)}\n\n"
        + "\n".join(auto_restart_lines)
        + "\n\n"
        "Next:\n"
        + "\n".join(next_lines)
    )


async def command_add_api(update: Any, context: Any) -> None:
    project_path = _resolve_target_project()
    if project_path is None:
        await update.message.reply_text(_no_active_project_guidance())
        return

    args = [str(x).strip() for x in getattr(context, "args", []) if str(x).strip()]
    if len(args) < 2:
        await update.message.reply_text("Usage: /add_api <METHOD> <path>")
        return

    raw_method = str(args[0]).upper().strip()
    if raw_method not in set(SUPPORTED_API_METHODS):
        await update.message.reply_text(
            "Unknown method: " + raw_method + "\n\nAvailable methods:\n" + ", ".join(SUPPORTED_API_METHODS)
        )
        return
    method, path, endpoint = _normalize_api_endpoint(raw_method, args[1])
    if not path:
        await update.message.reply_text("Invalid path. Use /add_api <METHOD> /path")
        return

    spec, spec_path = _read_or_init_project_spec(project_path)
    current = _rebuild_api_endpoints(spec)
    current_keys = {str(item).upper() for item in current}
    if endpoint.upper() in current_keys:
        await update.message.reply_text(
            "API already exists\n\n"
            "Project:\n"
            f"{project_path.name}\n\n"
            "Endpoint:\n"
            f"{endpoint}"
        )
        return

    spec["api_endpoints"] = current + [endpoint]
    _rebuild_api_endpoints(spec)
    _append_evolution_event(spec, {"action": "add_api", "method": method, "path": path})

    apply_api_scaffold(project_path, method, path)
    spec_path.parent.mkdir(parents=True, exist_ok=True)
    spec_path.write_text(json.dumps(spec, ensure_ascii=False, indent=2), encoding="utf-8")

    auto_restart_lines, restart_failed = _auto_restart_backend_lines(project_path)
    next_lines = ["- /inspect", "- /restart"]
    if method == "GET" and "{id}" not in path:
        next_lines.insert(0, f"- /add_api POST {path}")
    elif method == "POST" and "{id}" not in path:
        next_lines.insert(0, f"- /add_api GET {path}")
    if restart_failed:
        next_lines.append("- /logs")

    await update.message.reply_text(
        "API added\n\n"
        "Project:\n"
        f"{project_path.name}\n\n"
        "Endpoint:\n"
        f"{endpoint}\n\n"
        + "\n".join(auto_restart_lines)
        + "\n\n"
        "Next:\n"
        + "\n".join(next_lines)
    )


async def command_add_page(update: Any, context: Any) -> None:
    project_path = _resolve_target_project()
    if project_path is None:
        await update.message.reply_text(_no_active_project_guidance())
        return

    args = [str(x).strip() for x in getattr(context, "args", []) if str(x).strip()]
    if not args:
        await update.message.reply_text("Usage: /add_page <path>")
        return
    page_path = _normalize_frontend_page_path(args[0])
    if not page_path:
        await update.message.reply_text("Invalid page path. Use /add_page reports/list")
        return

    spec, spec_path = _read_or_init_project_spec(project_path)
    current = _rebuild_frontend_pages(spec)
    current_keys = {str(item).lower() for item in current}
    if page_path.lower() in current_keys:
        await update.message.reply_text(
            "Page already exists\n\n"
            "Project:\n"
            f"{project_path.name}\n\n"
            "Page:\n"
            f"{page_path}"
        )
        return

    spec["frontend_pages"] = current + [page_path]
    _rebuild_frontend_pages(spec)
    _append_evolution_event(spec, {"action": "add_page", "page": page_path})

    generated = apply_page_scaffold(project_path, page_path)
    frontend_exists = has_frontend_structure(project_path)
    spec_path.parent.mkdir(parents=True, exist_ok=True)
    spec_path.write_text(json.dumps(spec, ensure_ascii=False, indent=2), encoding="utf-8")

    auto_restart_lines, restart_failed = _auto_restart_backend_lines(project_path)
    lines = [
        "Page added",
        "",
        "Project:",
        project_path.name,
        "",
        "Page:",
        page_path,
    ]
    if not frontend_exists:
        lines += ["", "Frontend scaffold:", "SKIPPED (no frontend structure)"]
    elif generated:
        lines += ["", "Generated:"] + [f"- {item}" for item in generated]
    next_lines = ["- /inspect", "- /restart"]
    if page_path.endswith("/list"):
        next_lines.insert(0, f"- /add_page {page_path[:-5]}/detail")
    elif page_path.endswith("/detail"):
        next_lines.insert(0, f"- /add_page {page_path[:-7]}/list")
    lines += ["", *auto_restart_lines, "", "Next:", *next_lines]
    if restart_failed:
        lines.append("- /logs")
    await update.message.reply_text("\n".join(lines))


async def command_apply_suggestion(update: Any, context: Any) -> None:
    project_path = _resolve_target_project()
    if project_path is None:
        await update.message.reply_text(
            "No active project.\n\n"
            "If you want to generate a project from an idea:\n\n"
            "1. run /idea_local <your idea>\n\n"
            "If you want to apply suggestions to an existing project:\n\n"
            "1. run /projects\n"
            "2. run /use <n>\n"
            "3. run /apply_suggestion\n\n"
            "Next:\n"
            "- /idea_local <idea>\n"
            "- /projects"
        )
        return

    args = [str(x).strip().lower() for x in getattr(context, "args", []) if str(x).strip()]
    mode = args[0] if args else "all"
    if mode not in {"all", "entities", "api", "pages"}:
        await update.message.reply_text("Usage: /apply_suggestion [entities|api|pages|all]")
        return

    suggestion_path = project_path / ".archmind" / "suggestion.json"
    suggestion_payload = _load_json(suggestion_path)
    if suggestion_payload is None:
        await update.message.reply_text("No suggestion available\n\nRun:\n/suggest <idea>")
        return

    spec, spec_path = _read_or_init_project_spec(project_path)
    evolution = _ensure_evolution_block(spec)
    history = evolution.get("history") if isinstance(evolution.get("history"), list) else []

    applied_entities = 0
    applied_api = 0
    applied_pages = 0

    if mode in {"all", "entities"}:
        merged_entities, applied_entities = _merge_entities(spec.get("entities"), suggestion_payload.get("entities"))
        spec["entities"] = merged_entities
        _append_evolution_event(spec, {"action": "apply_suggestion", "type": "entities", "count": applied_entities})
    if mode in {"all", "api"}:
        merged_api, applied_api = _merge_string_list(spec.get("api_endpoints"), suggestion_payload.get("api_endpoints"))
        spec["api_endpoints"] = merged_api
        _append_evolution_event(spec, {"action": "apply_suggestion", "type": "api", "count": applied_api})
    if mode in {"all", "pages"}:
        merged_pages, applied_pages = _merge_string_list(spec.get("frontend_pages"), suggestion_payload.get("frontend_pages"))
        spec["frontend_pages"] = merged_pages
        _append_evolution_event(spec, {"action": "apply_suggestion", "type": "pages", "count": applied_pages})
    _rebuild_api_endpoints(spec)
    _rebuild_frontend_pages(spec)
    spec_path.parent.mkdir(parents=True, exist_ok=True)
    spec_path.write_text(json.dumps(spec, ensure_ascii=False, indent=2), encoding="utf-8")

    await update.message.reply_text(
        "Suggestion applied\n\n"
        "Project:\n"
        f"{project_path.name}\n\n"
        "Applied:\n"
        f"Entities: {applied_entities}\n"
        f"APIs: {applied_api}\n"
        f"Pages: {applied_pages}\n\n"
        "Next:\n"
        "- /inspect\n"
        "- /restart"
    )


async def command_next(update: Any, context: Any) -> None:
    del context
    project_path = _resolve_target_project()
    if project_path is None:
        await update.message.reply_text(_no_active_project_guidance())
        return

    spec_path = project_path / ".archmind" / "project_spec.json"
    raw = _load_json(spec_path) or {}
    if not raw:
        raw, _ = _read_or_init_project_spec(project_path)
    spec = dict(raw)
    if not isinstance(spec.get("modules"), list):
        spec["modules"] = []
    spec["entities"] = _normalize_entities(spec.get("entities"))
    if not isinstance(spec.get("api_endpoints"), list):
        spec["api_endpoints"] = []
    if not isinstance(spec.get("frontend_pages"), list):
        spec["frontend_pages"] = []
    spec["shape"] = str(spec.get("shape") or "unknown")

    suggestions = suggest_next_commands(spec, limit=3)
    if not suggestions:
        await update.message.reply_text(
            "Next development suggestions\n"
            f"Target Project: {project_path.name}\n\n"
            "No immediate suggestions.\n\n"
            "Next:\n- /inspect\n- continue evolving the project"
        )
        return

    lines = [
        "Next development suggestions",
        f"Target Project: {project_path.name}",
        "",
    ]
    callback_rows: list[list[Any]] = []
    InlineKeyboardButton, InlineKeyboardMarkup = _inline_keyboard_classes()
    for i, item in enumerate(suggestions, start=1):
        command = str(item.get("command") or "").strip()
        reason = str(item.get("reason") or "").strip()
        lines.append(f"{i}. {command}")
        if reason:
            lines.append(f"   reason: {reason}")
        lines.append("")
        callback_rows.append([InlineKeyboardButton(text=command, callback_data=_encode_callback_data("cmd", command))])
    lines += ["Next:", "- run suggested commands", "- /inspect"]
    if callback_rows:
        await update.message.reply_text(_truncate_message("\n".join(lines)), reply_markup=InlineKeyboardMarkup(callback_rows))
    else:
        await update.message.reply_text(_truncate_message("\n".join(lines)))


async def command_suggestion_callback(update: Any, context: Any) -> None:
    query, message, callback_update, callback_context = _build_callback_update_context(update, context, [])
    if query is None or message is None:
        return

    answer = getattr(query, "answer", None)
    if callable(answer):
        await answer()

    action, payload = _decode_callback_data(str(getattr(query, "data", "") or ""))
    if not action:
        return

    if action == "plan":
        callback_context.args = [x for x in str(payload).split() if x]
        await command_plan(callback_update, callback_context)
        return
    if action == "generate":
        callback_context.args = [x for x in str(payload).split() if x]
        await command_idea_local(callback_update, callback_context)
        return
    if action == "next":
        project_id = str(payload or "").strip()
        project_path = _resolve_project_by_id(project_id)
        if project_path is None:
            await message.reply_text(f"Project not found: {project_id}")
            return
        set_current_project(project_path)
        save_last_project_path(project_path)
        callback_context.args = []
        await command_next(callback_update, callback_context)
        return
    if action == "suggest":
        # Backward compatibility for older suggest| callbacks.
        command_text = _normalize_recommended_command(str(payload or "")) or str(payload or "")
        dispatched = await _dispatch_command_text(callback_update, callback_context, command_text)
        if not dispatched:
            await message.reply_text(f"Unsupported suggestion command: {payload}")
            return
        return
    if action == "help":
        topic = str(payload or "").strip().lower()
        callback_context.args = [topic] if topic else []
        await command_help(callback_update, callback_context)
        return
    if action == "cmd":
        dispatched = await _dispatch_command_text(callback_update, callback_context, str(payload or ""))
        if not dispatched:
            await message.reply_text(f"Unsupported command action: {payload}")
            return
        return
    await message.reply_text(f"Unsupported callback action: {action}")


async def command_unknown(update: Any, context: Any) -> None:
    del context
    await update.message.reply_text(
        "알 수 없는 명령어입니다.\n"
        "다음 명령어를 확인해주세요:\n\n"
        "/help\n"
        "/design {아이디어}\n"
        "/plan {아이디어}\n"
        "/idea_local {아이디어}\n"
        "/inspect\n"
        "/next"
    )


async def command_use(update: Any, context: Any) -> None:
    args = [str(x).strip() for x in getattr(context, "args", []) if str(x).strip()]
    if not args:
        await update.message.reply_text("Usage: /use <n|project_name>")
        return

    projects = list_recent_projects()
    selection = args[0]
    target = resolve_project_selection(selection, projects=projects)
    if target is None:
        if selection.isdigit():
            await update.message.reply_text("invalid index")
        else:
            await update.message.reply_text("project not found")
        return

    set_current_project(target)
    save_last_project_path(target)
    await update.message.reply_text(_truncate_message(_build_selected_project_summary(target), limit=1500))


async def command_projects(update: Any, context: Any) -> None:
    del context
    await update.message.reply_text(format_projects_list())


async def command_tree(update: Any, context: Any) -> None:
    args = [str(x).strip() for x in getattr(context, "args", []) if str(x).strip()]
    depth = 2
    if args:
        try:
            depth = int(args[0])
        except Exception:
            await update.message.reply_text("Invalid depth. Use /tree or /tree <n>.")
            return
        if depth <= 0:
            await update.message.reply_text("Invalid depth. Use /tree or /tree <n>.")
            return

    project_path = _resolve_target_project()
    if project_path is None:
        await update.message.reply_text("No project selected. Use /projects then /use <n>.")
        return
    await update.message.reply_text(format_project_tree(project_path, depth=depth))


async def command_open(update: Any, context: Any) -> None:
    args = [str(x).strip() for x in getattr(context, "args", []) if str(x).strip()]
    if not args:
        await update.message.reply_text("Usage: /open <path>")
        return
    project_path = _resolve_target_project()
    if project_path is None:
        await update.message.reply_text("No project selected. Use /projects then /use <n>.")
        return
    await update.message.reply_text(format_file_preview(project_path, " ".join(args)))


async def command_diff(update: Any, context: Any) -> None:
    del context
    project_path = _resolve_target_project()
    if project_path is None:
        await update.message.reply_text("No project selected. Use /projects then /use <n>.")
        return
    await update.message.reply_text(format_recent_diff(project_path))


async def command_logs(update: Any, context: Any) -> None:
    project_path = _resolve_target_project()
    if project_path is None:
        await update.message.reply_text(_missing_project_message())
        return

    args = [str(x).strip().lower() for x in getattr(context, "args", []) if str(x).strip()]
    mode = args[0] if args else "local"
    if mode not in ("backend", "frontend", "last", "local"):
        await update.message.reply_text("Usage: /logs [backend|frontend|local [backend|frontend]|last]")
        return

    if mode in ("local", "backend", "frontend"):
        from archmind.deploy import get_local_runtime_status, read_last_lines

        if mode == "backend":
            local_scope = "backend"
        elif mode == "frontend":
            local_scope = "frontend"
        else:
            local_scope = args[1] if len(args) > 1 else "all"
        if local_scope not in ("all", "backend", "frontend"):
            await update.message.reply_text("Usage: /logs local [backend|frontend]")
            return
        show_backend = local_scope in ("all", "backend")
        show_frontend = local_scope in ("all", "frontend")

        runtime_payload = get_local_runtime_status(project_path)
        services = runtime_payload.get("services") if isinstance(runtime_payload.get("services"), dict) else {}
        backend_service = services.get("backend") if isinstance(services.get("backend"), dict) else {}
        frontend_service = services.get("frontend") if isinstance(services.get("frontend"), dict) else {}
        backend_log = str(backend_service.get("log_path") or "").strip() or str(project_path / ".archmind" / "backend.log")
        frontend_log = str(frontend_service.get("log_path") or "").strip() or str(project_path / ".archmind" / "frontend.log")
        backend_text = read_last_lines(Path(backend_log), lines=20) if show_backend else None
        frontend_text = read_last_lines(Path(frontend_log), lines=20) if show_frontend else None

        frontend_known = bool(frontend_service) or bool((project_path / "frontend").exists()) or bool((project_path / "package.json").exists())
        if show_frontend and not frontend_known and local_scope != "all":
            await update.message.reply_text(
                _truncate_message(
                    "\n".join(
                        [
                            "Local logs",
                            "",
                            "Project:",
                            project_path.name,
                            "",
                            "Frontend service not detected for this project.",
                        ]
                    ),
                    limit=3500,
                )
            )
            return
        if (show_backend and not backend_text) and (show_frontend and not frontend_text):
            lines = [
                "Local logs",
                "",
                "Project:",
                project_path.name,
                "",
                "No log files found. Showing backend runtime diagnostics instead.",
                "",
                *_backend_runtime_diagnostics_lines(project_path),
            ]
            await update.message.reply_text(_truncate_message("\n".join(lines), limit=3500))
            return

        lines = ["Local logs", "", "Project:", project_path.name]
        if show_backend:
            lines.extend(["", "Backend logs (last 20 lines):", "", backend_text or "(no backend log lines captured)"])
            if not backend_text:
                lines += ["", *_backend_runtime_diagnostics_lines(project_path)]
        if show_frontend:
            lines.extend(["", "Frontend logs (last 20 lines):", "", frontend_text or "(no frontend log lines captured)"])
        await update.message.reply_text(_truncate_message("\n".join(lines), limit=3500))
        return

    if mode == "backend":
        msg = read_recent_backend_logs(project_path)
    elif mode == "frontend":
        msg = read_recent_frontend_logs(project_path)
    else:
        msg = read_recent_last_logs(project_path, temp_log=_temp_log_for_project(project_path))

    await update.message.reply_text(_truncate_message(msg, limit=1500))


async def command_running(update: Any, context: Any) -> None:
    del context
    from archmind.deploy import list_running_local_projects

    projects_root = resolve_projects_dir()
    rows = list_running_local_projects(projects_root)
    if not rows:
        await update.message.reply_text("No local services running.")
        return

    current = get_current_project()
    external_ip = _detect_external_ip()
    lines = ["Running local services", ""]
    for idx, item in enumerate(rows, start=1):
        project_dir = item.get("project_dir")
        project_name = str(item.get("project_name") or "")
        marker = ""
        if isinstance(project_dir, Path) and current is not None and project_dir.resolve() == current.resolve():
            marker = " [current]"

        backend = item.get("backend") if isinstance(item.get("backend"), dict) else {}
        frontend = item.get("frontend") if isinstance(item.get("frontend"), dict) else {}
        lines.append(f"{idx}. {project_name}{marker}")
        backend_status = str(backend.get("status") or "NOT RUNNING")
        backend_pid = backend.get("pid")
        lines.append(f"   Backend: {backend_status}" + (f" (pid {backend_pid})" if backend_pid else ""))
        backend_url = str(backend.get("url") or "").strip()
        if backend_url:
            lines.append(f"   URL: {backend_url}")
            external_backend_url = _external_url_for(backend_url, external_ip)
            if backend_status.upper() == "RUNNING" and external_backend_url:
                lines.append(f"   External URL: {external_backend_url}")
        frontend_status = str(frontend.get("status") or "NOT RUNNING")
        frontend_pid = frontend.get("pid")
        lines.append(f"   Frontend: {frontend_status}" + (f" (pid {frontend_pid})" if frontend_pid else ""))
        frontend_url = str(frontend.get("url") or "").strip()
        if frontend_url:
            lines.append(f"   URL: {frontend_url}")
            external_frontend_url = _external_url_for(frontend_url, external_ip)
            if frontend_status.upper() == "RUNNING" and external_frontend_url:
                lines.append(f"   External URL: {external_frontend_url}")
        if idx != len(rows):
            lines.append("")
    await update.message.reply_text(_truncate_message("\n".join(lines), limit=3500))


async def command_deploy(update: Any, context: Any) -> None:
    running = _get_running_job()
    if running is not None:
        await update.message.reply_text(_busy_message(running))
        return

    project_path = _resolve_target_project()
    if project_path is None:
        await update.message.reply_text("No project selected. Use /projects then /use <n>.")
        return

    args = [str(x).strip().lower() for x in getattr(context, "args", []) if str(x).strip()]
    target = "railway"
    allow_real_deploy = False
    if args:
        if args[0] in ("railway", "local"):
            target = args[0]
            args = args[1:]
        allow_real_deploy = "real" in args

    from archmind.deploy import deploy_project

    result = deploy_project(project_path, target=target, allow_real_deploy=allow_real_deploy)
    action = f"telegram /deploy {target}" + (" real" if allow_real_deploy else "")
    update_after_deploy(project_path, result, action=action.strip())

    lines = [
        "Deploy finished",
        "",
        "Project:",
        project_path.name,
        "",
        "Target:",
        str(result.get("target") or target),
    ]
    mode = str(result.get("mode") or ("real" if allow_real_deploy else "mock")).strip()
    kind = str(result.get("kind") or "backend").strip().lower()
    lines.append("")
    lines.append(f"Mode: {mode}")
    lines.extend(["", "Kind:", kind])

    if kind == "fullstack":
        backend = result.get("backend") if isinstance(result.get("backend"), dict) else {}
        frontend = result.get("frontend") if isinstance(result.get("frontend"), dict) else {}
        lines.extend(["", "Backend:", str(backend.get("status") or "UNKNOWN")])
        backend_url = str(backend.get("url") or "").strip()
        if backend_url:
            lines.append(backend_url)
        backend_detail = str(backend.get("detail") or "").strip()
        if backend_detail and str(backend.get("status") or "").upper() != "SUCCESS":
            lines.append(backend_detail)
        backend_smoke_status = str(result.get("backend_smoke_status") or "").strip().upper()
        backend_smoke_url = str(result.get("backend_smoke_url") or "").strip()
        backend_smoke_detail = str(result.get("backend_smoke_detail") or "").strip()
        if backend_smoke_status:
            lines.extend(["", "Backend smoke:", backend_smoke_status])
            if backend_smoke_url:
                lines.append(backend_smoke_url)
            if backend_smoke_detail and backend_smoke_status != "SUCCESS":
                lines.extend(["", "Detail:", backend_smoke_detail])

        lines.extend(["", "Frontend:", str(frontend.get("status") or "UNKNOWN")])
        frontend_url = str(frontend.get("url") or "").strip()
        if frontend_url:
            lines.append(frontend_url)
        frontend_detail = str(frontend.get("detail") or "").strip()
        if frontend_detail and str(frontend.get("status") or "").upper() != "SUCCESS":
            lines.append(frontend_detail)
        frontend_smoke_status = str(result.get("frontend_smoke_status") or "").strip().upper()
        frontend_smoke_url = str(result.get("frontend_smoke_url") or "").strip()
        frontend_smoke_detail = str(result.get("frontend_smoke_detail") or "").strip()
        if frontend_smoke_status:
            lines.extend(["", "Frontend smoke:", frontend_smoke_status])
            if frontend_smoke_url:
                lines.append(frontend_smoke_url)
            if frontend_smoke_detail and frontend_smoke_status != "SUCCESS":
                lines.extend(["", "Detail:", frontend_smoke_detail])
    else:
        lines.extend(
            [
                "",
                "Status:",
                str(result.get("status") or "UNKNOWN"),
            ]
        )
        url = str(result.get("url") or "").strip()
        if url:
            lines.extend(["", "Deploy URL:", url])
        if mode == "real":
            health_status = str(result.get("healthcheck_status") or "").strip().upper()
            health_url = str(result.get("healthcheck_url") or "").strip()
            health_detail = str(result.get("healthcheck_detail") or "").strip()
            if health_status:
                lines.extend(["", "Health check:", health_status])
                if health_url:
                    lines.extend(["", "Health URL:", health_url])
                if health_detail and health_status != "SUCCESS":
                    lines.extend(["", "Detail:", health_detail])
        detail = str(result.get("detail") or "").strip()
        if detail:
            lines.extend(["", "Detail:", detail])
        backend_smoke_status = str(result.get("backend_smoke_status") or "").strip().upper()
        backend_smoke_url = str(result.get("backend_smoke_url") or "").strip()
        backend_smoke_detail = str(result.get("backend_smoke_detail") or "").strip()
        if backend_smoke_status:
            lines.extend(["", "Backend smoke:", backend_smoke_status])
            if backend_smoke_url:
                lines.append(backend_smoke_url)
            if backend_smoke_detail and backend_smoke_status != "SUCCESS":
                lines.extend(["", "Detail:", backend_smoke_detail])
        frontend_smoke_status = str(result.get("frontend_smoke_status") or "").strip().upper()
        frontend_smoke_url = str(result.get("frontend_smoke_url") or "").strip()
        frontend_smoke_detail = str(result.get("frontend_smoke_detail") or "").strip()
        if frontend_smoke_status:
            lines.extend(["", "Frontend smoke:", frontend_smoke_status])
            if frontend_smoke_url:
                lines.append(frontend_smoke_url)
            if frontend_smoke_detail and frontend_smoke_status != "SUCCESS":
                lines.extend(["", "Detail:", frontend_smoke_detail])
    await update.message.reply_text(_truncate_message("\n".join(lines)))


async def command_run(update: Any, context: Any) -> None:
    running = _get_running_job()
    if running is not None:
        await update.message.reply_text(_busy_message(running))
        return

    project_path = _resolve_target_project()
    if project_path is None:
        await update.message.reply_text("No project selected. Use /projects then /use <n>.")
        return

    args = [str(x).strip().lower() for x in getattr(context, "args", []) if str(x).strip()]
    if len(args) != 1 or args[0] not in {"backend", "all"}:
        await update.message.reply_text("Usage: /run backend|all")
        return

    if args[0] == "all":
        from archmind.runtime_orchestrator import run_all_local_services

        result = run_all_local_services(project_path)
        update_runtime_state(project_path, result, action="telegram /run all")
        services = result.get("services") if isinstance(result.get("services"), dict) else {}
        backend = services.get("backend") if isinstance(services.get("backend"), dict) else {}
        frontend = services.get("frontend") if isinstance(services.get("frontend"), dict) else {}
        backend_status = str(backend.get("status") or result.get("backend_status") or "UNKNOWN").strip().upper()
        frontend_status = str(frontend.get("status") or result.get("frontend_status") or "UNKNOWN").strip().upper()
        lines = [
            "Run all finished",
            "",
            "Project:",
            project_path.name,
            "",
            "Backend:",
            backend_status,
        ]
        backend_url = str(backend.get("url") or "").strip()
        if backend_url:
            lines += ["", "Backend URL:", backend_url]
        lines += ["", "Frontend:", frontend_status]
        frontend_url = str(frontend.get("url") or "").strip()
        if frontend_url:
            lines += ["", "Frontend URL:", frontend_url]
        if str(result.get("status") or "").strip().upper() == "FAIL":
            failure_class = str(result.get("failure_class") or "runtime-execution-error").strip()
            detail = str(result.get("detail") or "").strip()
            if failure_class:
                lines += ["", "Failure class:", failure_class]
            if detail:
                lines += ["", "Detail:", detail]
        lines += ["", "Next:", "- /running", "- /logs", "- /inspect"]
        await update.message.reply_text(_truncate_message("\n".join(lines)))
        return

    from archmind.deploy import get_local_runtime_status, run_backend_local_with_health

    runtime = get_local_runtime_status(project_path)
    backend_runtime = runtime.get("backend") if isinstance(runtime.get("backend"), dict) else {}
    backend_running = str(backend_runtime.get("status") or "").upper() == "RUNNING"
    if backend_running:
        backend_url = str(backend_runtime.get("url") or "").strip()
        lines = [
            "Run skipped",
            "",
            "Project:",
            project_path.name,
            "",
            "Backend:",
            "RUNNING",
        ]
        if backend_url:
            lines += ["", "Backend URL:", backend_url]
        lines += ["", "Next:", "- /logs backend", "- /running", "- /restart"]
        await update.message.reply_text(_truncate_message("\n".join(lines)))
        return

    result = run_backend_local_with_health(project_path)
    update_runtime_state(project_path, result, action="telegram /run backend")

    backend_entry = str(result.get("backend_entry") or "").strip()
    backend_run_mode = str(result.get("backend_run_mode") or "").strip()
    run_cwd = str(result.get("run_cwd") or "").strip()
    run_command = str(result.get("run_command") or "").strip()
    backend_url = str(result.get("url") or "").strip()
    backend_smoke_status = str(result.get("backend_smoke_status") or result.get("healthcheck_status") or "").strip().upper()
    backend_smoke_url = str(result.get("backend_smoke_url") or result.get("healthcheck_url") or "").strip()
    auto_fix = result.get("auto_fix") if isinstance(result.get("auto_fix"), dict) else {}
    auto_fix_attempts = int(auto_fix.get("attempts") or 0) if str(auto_fix.get("attempts") or "").isdigit() else 0
    auto_fix_last_fix = str(auto_fix.get("last_fix") or "").strip()
    auto_fix_last_detail = str(auto_fix.get("last_detail") or "").strip()
    auto_fix_status = str(auto_fix.get("status") or "").strip().upper()
    preflight = result.get("preflight") if isinstance(result.get("preflight"), dict) else {}
    preflight_status = str(preflight.get("status") or "").strip().upper()
    preflight_fixes = preflight.get("fixes_applied")
    if not isinstance(preflight_fixes, list):
        preflight_fixes = preflight.get("fixes") if isinstance(preflight.get("fixes"), list) else []
    backend_status = "RUNNING" if str(result.get("status") or "").upper() == "SUCCESS" else "FAIL"
    if backend_status == "RUNNING":
        backend_header = "RUNNING (after auto-fix)" if auto_fix_attempts > 0 and auto_fix_status == "SUCCESS" else "RUNNING"
        lines = [
            "Run finished",
            "",
            "Project:",
            project_path.name,
            "",
            "Backend:",
            backend_header,
        ]
        if preflight_status:
            lines += ["", "Preflight:", preflight_status]
            if preflight_status == "FIXED":
                for item in preflight_fixes[:5]:
                    value = str(item).strip()
                    if value:
                        lines.append(f"- {value}")
        if backend_url:
            lines += ["", "Backend URL:", backend_url]
        if backend_smoke_status:
            lines += ["", "Backend smoke:", backend_smoke_status]
            if backend_smoke_url:
                lines.append(backend_smoke_url)
        if auto_fix_attempts > 0:
            lines += ["", "Fix applied:", auto_fix_last_detail or auto_fix_last_fix or "auto-fix applied"]
        lines += [
            "",
            "Detected backend target:",
            backend_entry or "(none)",
            "",
            "Run mode:",
            backend_run_mode or "(none)",
            "",
            "Next:",
            "- /logs backend",
            "- /running",
            "- /restart",
        ]
        await update.message.reply_text(_truncate_message("\n".join(lines)))
        return

    failure_class = str(result.get("failure_class") or "runtime-execution-error").strip()
    detail = str(result.get("detail") or "backend run failed").strip()
    lines = [
        "Run failed",
        "",
        "Project:",
        project_path.name,
        "",
        "Backend:",
        "FAIL",
    ]
    if preflight_status:
        lines += ["", "Preflight:", preflight_status]
        if preflight_status == "FIXED":
            for item in preflight_fixes[:5]:
                value = str(item).strip()
                if value:
                    lines.append(f"- {value}")
    lines += [
        "",
        "Failure class:",
        failure_class,
        "",
        "Detail:",
        detail,
        "",
        "Detected backend target:",
        backend_entry or "(none)",
        "",
        "Run cwd:",
        run_cwd or str(project_path),
        "",
        "Run command:",
        run_command or "(none)",
    ]
    if auto_fix_attempts > 0:
        lines += [
            "",
            "Auto-fix attempts:",
            str(auto_fix_attempts),
        ]
        if auto_fix_last_fix:
            lines += ["", "Last auto-fix:", auto_fix_last_fix]
        if auto_fix_last_detail:
            lines += ["", "Last error:", auto_fix_last_detail]
    lines += [
        "",
        "Next:",
        "- /logs backend",
        "- /inspect",
    ]
    await update.message.reply_text(_truncate_message("\n".join(lines)))


async def command_stop(update: Any, context: Any) -> None:
    running = _get_running_job()
    if running is not None:
        await update.message.reply_text(_busy_message(running))
        return

    args = [str(x).strip().lower() for x in getattr(context, "args", []) if str(x).strip()]
    if args and args[0] not in ("local", "all"):
        await update.message.reply_text("Usage: /stop or /stop local or /stop all")
        return

    if args and args[0] == "all":
        from archmind.deploy import stop_all_local_services

        projects_root = resolve_projects_dir()
        result = stop_all_local_services(projects_root)
        counts = result.get("counts") if isinstance(result.get("counts"), dict) else {}
        failed = result.get("failed") if isinstance(result.get("failed"), list) else []
        lines = [
            "All services stop finished",
            "",
            "Details:",
            f"- stopped: {int(counts.get('stopped') or 0)}",
            f"- already stopped: {int(counts.get('already_stopped') or 0)}",
            f"- failed: {int(counts.get('failed') or 0)}",
        ]
        if failed:
            lines += ["", "Failed:"]
            for item in failed[:10]:
                if not isinstance(item, dict):
                    continue
                project_name = str(item.get("project_name") or "").strip() or "(unknown)"
                backend_detail = str(item.get("backend_detail") or "").strip()
                frontend_detail = str(item.get("frontend_detail") or "").strip()
                detail = backend_detail or frontend_detail or "unknown error"
                lines.append(f"- {project_name}: {detail}")
        await update.message.reply_text(_truncate_message("\n".join(lines)))
        return

    project_path = _resolve_target_project()
    if project_path is None:
        await update.message.reply_text("No project selected. Use /projects then /use <n>.")
        return

    from archmind.deploy import stop_local_services

    result = stop_local_services(project_path)
    backend = result.get("backend") if isinstance(result.get("backend"), dict) else {}
    frontend = result.get("frontend") if isinstance(result.get("frontend"), dict) else {}
    warnings = result.get("warnings") if isinstance(result.get("warnings"), list) else []
    backend_status = str(backend.get("status") or "NOT RUNNING")
    frontend_status = str(frontend.get("status") or "NOT RUNNING")

    lines = [
        "Local services stopped",
        "",
        "Project:",
        project_path.name,
        "",
        "Backend:",
        backend_status,
        "",
        "Frontend:",
        frontend_status,
    ]
    backend_detail = str(backend.get("detail") or "").strip()
    frontend_detail = str(frontend.get("detail") or "").strip()
    if backend_detail and backend_status.upper() in {"WARNING", "FAIL"}:
        lines.extend(["", "Backend detail:", backend_detail])
    if frontend_detail and frontend_status.upper() in {"WARNING", "FAIL"}:
        lines.extend(["", "Frontend detail:", frontend_detail])
    warning_lines = [str(item).strip() for item in warnings if str(item).strip()]
    if warning_lines:
        lines += ["", "Warnings:"]
        lines += [f"- {item}" for item in warning_lines[:5]]
    await update.message.reply_text(_truncate_message("\n".join(lines)))


async def command_restart(update: Any, context: Any) -> None:
    running = _get_running_job()
    if running is not None:
        await update.message.reply_text(_busy_message(running))
        return

    project_path = _resolve_target_project()
    if project_path is None:
        await update.message.reply_text("No project selected. Use /projects then /use <n>.")
        return

    args = [str(x).strip().lower() for x in getattr(context, "args", []) if str(x).strip()]
    if args and args[0] not in ("local",):
        await update.message.reply_text("Usage: /restart or /restart local")
        return

    from archmind.deploy import get_local_runtime_status, restart_local_services

    result = restart_local_services(project_path)
    runtime = get_local_runtime_status(project_path)
    backend = runtime.get("backend") if isinstance(runtime.get("backend"), dict) else {}
    frontend = runtime.get("frontend") if isinstance(runtime.get("frontend"), dict) else {}

    lines = [
        "Restart result",
        "",
        "Project:",
        project_path.name,
        "",
        "Backend:",
        str(backend.get("status") or "NOT RUNNING"),
    ]
    backend_url = str(backend.get("url") or "").strip()
    if str(backend.get("status") or "").upper() == "RUNNING" and backend_url:
        lines += ["Backend URL:", backend_url]
    lines.extend(
        [
            "",
            "Frontend:",
            str(frontend.get("status") or "NOT RUNNING"),
        ]
    )
    frontend_url = str(frontend.get("url") or "").strip()
    if str(frontend.get("status") or "").upper() == "RUNNING" and frontend_url:
        lines += ["Frontend URL:", frontend_url]

    restart_backend = result.get("backend") if isinstance(result.get("backend"), dict) else {}
    restart_frontend = result.get("frontend") if isinstance(result.get("frontend"), dict) else {}
    deploy_result = result.get("deploy") if isinstance(result.get("deploy"), dict) else {}
    preflight = deploy_result.get("preflight") if isinstance(deploy_result.get("preflight"), dict) else {}
    preflight_status = str(preflight.get("status") or "").strip().upper()
    preflight_fixes = preflight.get("fixes_applied")
    if not isinstance(preflight_fixes, list):
        preflight_fixes = []
    backend_detail = str(restart_backend.get("detail") or "").strip()
    frontend_detail = str(restart_frontend.get("detail") or "").strip()
    if backend_detail and str(backend.get("status") or "").upper() != "RUNNING":
        lines.extend(["", "Backend detail:", backend_detail])
    if frontend_detail and str(frontend.get("status") or "").upper() != "RUNNING":
        lines.extend(["", "Frontend detail:", frontend_detail])
    if preflight_status:
        lines.extend(["", "Preflight:", preflight_status])
        if preflight_status == "FIXED":
            for item in preflight_fixes[:5]:
                value = str(item).strip()
                if value:
                    lines.append(f"- {value}")
    lines += ["", "Next:", "- /running", "- /logs"]
    await update.message.reply_text(_truncate_message("\n".join(lines)))


async def command_delete_project(update: Any, context: Any) -> None:
    running = _get_running_job()
    if running is not None:
        await update.message.reply_text(_busy_message(running))
        return

    project_path = _resolve_target_project()
    if project_path is None:
        await update.message.reply_text("No project selected. Use /projects then /use <n>.")
        return

    args = [str(x).strip().lower() for x in getattr(context, "args", []) if str(x).strip()]
    mode = args[0] if args else "local"
    if mode not in ("local", "repo", "all"):
        await update.message.reply_text("Usage: /delete_project [local|repo|all]")
        return

    chat = getattr(update, "effective_chat", None)
    chat_id = int(getattr(chat, "id", 0) or 0)
    if mode in ("repo", "all"):
        if chat_id <= 0:
            await update.message.reply_text("Delete confirmation unavailable for this chat.")
            return
        _set_pending_delete(chat_id, project_path, mode)
        lines = [
            "Delete confirmation required",
            "",
            "Project:",
            project_path.name,
            "",
            "This will permanently delete:",
        ]
        if mode in ("local", "all"):
            lines.append("- local project directory")
            lines.append("- local running services")
        if mode in ("repo", "all"):
            lines.append("- GitHub repository")
        lines += [
            "",
            "Reply exactly with:",
            "DELETE YES",
        ]
        await update.message.reply_text("\n".join(lines))
        return

    from archmind.deploy import delete_project

    result = delete_project(project_path, mode="local")
    _persist_delete_outcome(project_path, "local", result)
    if str(result.get("local_status") or "").upper() == "DELETED":
        _clear_project_selection_if_deleted(project_path)

    lines = [
        "Project deleted",
        "",
        "Project:",
        project_path.name,
        "",
        "Mode:",
        "local",
        "",
        "Local directory:",
        str(result.get("local_status") or "UNCHANGED"),
        "",
        "GitHub repository:",
        "UNCHANGED",
    ]
    detail = str(result.get("local_detail") or "").strip()
    if detail and str(result.get("local_status") or "").upper() != "DELETED":
        lines.extend(["", "Detail:", detail])
    await update.message.reply_text(_truncate_message("\n".join(lines)))


async def command_text(update: Any, context: Any) -> None:
    del context
    message = getattr(update, "message", None)
    text = str(getattr(message, "text", "") or "").strip()
    if text != "DELETE YES":
        return
    chat = getattr(update, "effective_chat", None)
    chat_id = int(getattr(chat, "id", 0) or 0)
    pending = _get_pending_delete(chat_id)
    if pending is None:
        return

    from archmind.deploy import delete_project

    result = delete_project(pending.project_dir, mode=pending.mode)
    _persist_delete_outcome(pending.project_dir, pending.mode, result)
    if str(result.get("local_status") or "").upper() == "DELETED":
        _clear_project_selection_if_deleted(pending.project_dir)
    lines = [
        "Project deleted",
        "",
        "Project:",
        pending.project_dir.name,
        "",
        "Mode:",
        pending.mode,
        "",
        "Local directory:",
        str(result.get("local_status") or "UNCHANGED"),
        "",
        "GitHub repository:",
        str(result.get("repo_status") or "UNCHANGED"),
    ]
    local_detail = str(result.get("local_detail") or "").strip()
    repo_detail = str(result.get("repo_detail") or "").strip()
    if local_detail and str(result.get("local_status") or "").upper() != "DELETED":
        lines.extend(["", "Local detail:", local_detail])
    if repo_detail and str(result.get("repo_status") or "").upper() != "DELETED":
        lines.extend(["", "Repo detail:", repo_detail])
    _clear_pending_delete()
    await update.message.reply_text(_truncate_message("\n".join(lines)))


async def command_help(update: Any, context: Any) -> None:
    args = [str(x).strip() for x in getattr(context, "args", []) if str(x).strip()]
    topic = str(args[0]).lower() if args else ""
    text = _help_topic_text(topic)
    reply_markup = _help_sections_keyboard(topic)
    if reply_markup is not None:
        await update.message.reply_text(text, reply_markup=reply_markup)
        return
    await update.message.reply_text(text)


def run_bot() -> None:
    token = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
    if not token:
        raise SystemExit("TELEGRAM_BOT_TOKEN is required")

    try:
        from telegram.ext import ApplicationBuilder, CallbackQueryHandler, CommandHandler, MessageHandler, filters
    except Exception as exc:
        raise SystemExit(f"python-telegram-bot is required: {exc}") from exc

    app = ApplicationBuilder().token(token).build()
    app.add_handler(CommandHandler("idea", command_idea))
    app.add_handler(CommandHandler("idea_local", command_idea_local))
    app.add_handler(CommandHandler("pipeline", command_pipeline))
    app.add_handler(CommandHandler("preview", command_preview))
    app.add_handler(CommandHandler("suggest", command_suggest))
    app.add_handler(CommandHandler("design", command_design))
    app.add_handler(CommandHandler("plan", command_plan))
    app.add_handler(CommandHandler("add_module", command_add_module))
    app.add_handler(CommandHandler("add_entity", command_add_entity))
    app.add_handler(CommandHandler("add_field", command_add_field))
    app.add_handler(CommandHandler("add_api", command_add_api))
    app.add_handler(CommandHandler("add_page", command_add_page))
    app.add_handler(CommandHandler("apply_suggestion", command_apply_suggestion))
    app.add_handler(CommandHandler("apply_plan", command_apply_plan))
    app.add_handler(CommandHandler("next", command_next))
    app.add_handler(CallbackQueryHandler(command_suggestion_callback))
    app.add_handler(CommandHandler("continue", command_continue))
    app.add_handler(CommandHandler("fix", command_fix))
    app.add_handler(CommandHandler("retry", command_retry))
    app.add_handler(CommandHandler("use", command_use))
    app.add_handler(CommandHandler("current", command_current))
    app.add_handler(CommandHandler("inspect", command_inspect))
    app.add_handler(CommandHandler("improve", command_improve))
    app.add_handler(CommandHandler("logs", command_logs))
    app.add_handler(CommandHandler("running", command_running))
    app.add_handler(CommandHandler("tree", command_tree))
    app.add_handler(CommandHandler("open", command_open))
    app.add_handler(CommandHandler("diff", command_diff))
    app.add_handler(CommandHandler("projects", command_projects))
    app.add_handler(CommandHandler("state", command_state))
    app.add_handler(CommandHandler("status", command_status))
    app.add_handler(CommandHandler("deploy", command_deploy))
    app.add_handler(CommandHandler("run", command_run))
    app.add_handler(CommandHandler("stop", command_stop))
    app.add_handler(CommandHandler("restart", command_restart))
    app.add_handler(CommandHandler("delete_project", command_delete_project))
    app.add_handler(CommandHandler("help", command_help))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, command_text))
    app.add_handler(MessageHandler(filters.COMMAND, command_unknown))
    app.run_polling()
