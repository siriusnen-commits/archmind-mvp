from __future__ import annotations

import asyncio
import json
import os
import re
import subprocess
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Optional

from archmind.failure import classify_failure
from archmind.state import derive_task_label_from_failure_signature

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
    return (
        "Commands:\n"
        "/idea <text> - run archmind pipeline from an idea\n"
        "/pipeline <text> - alias of /idea\n"
        "/continue - continue the last project with pipeline\n"
        "/fix - run fix on the last project\n"
        "/retry - run fix and then continue on the last project\n"
        "/logs [backend|frontend|last] - show recent failure logs\n"
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


def _current_task_label(project_dir: Path, status: str) -> Optional[str]:
    archmind_dir = project_dir / ".archmind"
    state = _load_json(archmind_dir / "state.json") or {}
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


def build_log_focus(log_type: str, failure_class: Optional[str], key_lines: list[str]) -> list[str]:
    klass = str(failure_class or "").lower()
    if klass == "backend-pytest:assertion":
        return ["inspect backend implementation", "compare API response with test expectations"]
    if klass in ("backend-pytest:import", "backend-pytest:module-not-found"):
        return ["inspect imports and module paths"]
    if klass == "frontend-lint":
        return ["inspect frontend lint config", "inspect failing frontend file"]
    if klass == "frontend-typescript":
        return ["inspect type definitions", "inspect failing TS file"]
    if klass == "frontend-build":
        return ["inspect build config/import path"]
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
        lines.extend(f"- {line}" for line in key_lines[:6])
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


def _extract_candidate_lines(text: str, mode: str) -> list[str]:
    keywords_backend = ("backend", "pytest", "assert", "traceback", "failed", "error", "e ")
    keywords_frontend = ("frontend", "eslint", "lint", "build", "tsc", "npm", "failed", "error")
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


def _failure_summary_from_class(mode: str, failure_class: str, key_lines: list[str]) -> str:
    klass = (failure_class or "").lower()
    if mode == "backend":
        if klass.startswith("backend-pytest"):
            return "backend pytest failed"
        return "backend failure detected"
    if mode == "frontend":
        if klass == "frontend-lint":
            return "frontend lint failed"
        if klass == "frontend-typescript":
            return "frontend typescript failed"
        if klass == "frontend-build":
            return "frontend build failed"
        return "frontend failure detected"
    if mode == "last":
        has_backend = any("assert" in line.lower() or "pytest" in line.lower() or line.lower().startswith("failed tests/") for line in key_lines)
        has_frontend = any(
            token in line.lower() for line in key_lines for token in ("eslint", "ts2304", "ts2322", "is not assignable")
        )
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
        return build_logs_message(project_dir.name, "backend", "No backend logs found.", [], ["inspect recent failure details"])
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


def _recommend_next_actions(status: str, summary_lines: list[str], state: dict[str, Any]) -> list[str]:
    normalized = (status or "UNKNOWN").upper()
    text = "\n".join(summary_lines).lower()
    last_action = str(state.get("last_action") or "").lower()

    if normalized == "STUCK":
        return [
            "run /logs backend",
            "inspect backend failure details",
            "revise current task",
            "then run /fix or /continue",
        ]
    if normalized == "BLOCKED":
        return ["inspect logs with /state and review backend/frontend failures"]
    if normalized in ("DONE", "SUCCESS"):
        return ["review project artifacts"]

    has_backend_pytest_fail = "backend" in text and ("fail" in text or "pytest" in text)
    recent_fix = "fix" in last_action

    if normalized == "NOT_DONE":
        if has_backend_pytest_fail and not recent_fix:
            return ["run /logs backend", "run /fix", "then /continue"]
        if recent_fix:
            return ["run /logs backend", "run /continue"]
        return ["run /logs backend", "run /fix", "then /continue"]

    if normalized in ("FAIL", "SKIP", "UNKNOWN"):
        return ["run /fix", "then /continue"]
    return ["run /state"]


def build_finished_message(
    evaluation: dict[str, Any],
    state: dict[str, Any],
    result: dict[str, Any],
    *,
    project_name: str,
    status: str,
    fallback_summary_lines: Optional[list[str]] = None,
    max_len: int = 1200,
) -> str:
    iterations = state.get("iterations")
    fix_attempts = state.get("fix_attempts")
    signature = str(state.get("last_failure_signature") or "").strip()
    failure_class = str(state.get("last_failure_class") or "").strip()
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

    summary_lines = _build_human_summary(
        status=status,
        state=state,
        result=result,
        fallback_lines=list(fallback_summary_lines or []),
    )
    next_actions = _recommend_next_actions(status, summary_lines, state)[:3]

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
    if failure_class:
        lines.append(f"Failure class: {failure_class}")
    if stuck_reason:
        lines.append(f"Reason: {stuck_reason}")
    lines += [
        "",
        "Summary:",
    ]
    lines.extend(f"- {line}" for line in summary_lines[:5])
    if next_actions:
        lines += [
            "",
            "Next:",
        ]
        lines.extend(f"- {line}" for line in next_actions[:3])
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
    state = _load_json(archmind_dir / "state.json") or {}
    result = _load_json(archmind_dir / "result.json") or {}
    status = _status_from_sources(project_dir)
    fallback_summary = _result_summary_lines(project_dir, temp_log)
    message = build_finished_message(
        evaluation=evaluation,
        state=state,
        result=result,
        project_name=project_dir.name,
        status=status,
        fallback_summary_lines=fallback_summary,
        max_len=max_len,
    )
    if exit_code is not None and str(status).upper() == "UNKNOWN":
        message = _truncate_message(f"{message}\n(exit code: {exit_code})", limit=max_len)
    return message


def _wait_for_latest_artifacts(project_dir: Path, started_at: float, attempts: int = 6, sleep_s: float = 0.15) -> None:
    archmind_dir = project_dir / ".archmind"
    targets = [
        archmind_dir / "state.json",
        archmind_dir / "evaluation.json",
        archmind_dir / "result.json",
    ]
    for _ in range(attempts):
        newest = 0.0
        for path in targets:
            if path.exists():
                newest = max(newest, path.stat().st_mtime)
        if newest >= started_at:
            return
        time.sleep(sleep_s)


async def watch_pipeline_and_notify(
    proc: subprocess.Popen[str],
    project_dir: Path,
    temp_log: Path,
    chat_id: int,
    application: Any,
    started_at: Optional[float] = None,
) -> None:
    try:
        exit_code = await asyncio.to_thread(proc.wait)
        await asyncio.to_thread(_wait_for_latest_artifacts, project_dir, started_at or time.time())
        message = build_completion_message(project_dir, temp_log, max_len=1200, exit_code=exit_code)
    except Exception as exc:
        message = f"ArchMind finished with notification error: {exc}"

    try:
        await application.bot.send_message(chat_id=chat_id, text=message)
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
            last_exit = await asyncio.to_thread(_run_command_to_log, cmd, temp_log)
            if last_exit != 0 and cmd[:2] == ["archmind", "fix"]:
                break
        await asyncio.to_thread(_wait_for_latest_artifacts, project_dir, started_at or time.time())
        message = build_completion_message(project_dir, temp_log, max_len=1200, exit_code=last_exit)
    except Exception as exc:
        message = f"ArchMind finished with notification error: {exc}"
    try:
        await application.bot.send_message(chat_id=chat_id, text=message)
    except Exception:
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
        started_at = time.time()
        asyncio.create_task(
            watch_pipeline_and_notify(
                proc=proc,
                project_dir=project_dir,
                temp_log=log_path,
                chat_id=int(chat_id),
                application=application,
                started_at=started_at,
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
        started_at = time.time()
        asyncio.create_task(
            watch_pipeline_and_notify(
                proc=proc,
                project_dir=project_dir,
                temp_log=temp_log,
                chat_id=int(chat_id),
                application=application,
                started_at=started_at,
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
        started_at = time.time()
        asyncio.create_task(
            watch_pipeline_and_notify(
                proc=proc,
                project_dir=project_dir,
                temp_log=temp_log,
                chat_id=int(chat_id),
                application=application,
                started_at=started_at,
            )
        )
    await update.message.reply_text(f"fix started: pid={proc.pid}\nproject={project_dir}")


async def _handle_retry(update: Any, context: Any) -> None:
    project_dir = load_last_project_path()
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

    application = getattr(context, "application", None)
    chat = getattr(update, "effective_chat", None)
    chat_id = getattr(chat, "id", None)
    if application is not None and chat_id is not None:
        started_at = time.time()
        asyncio.create_task(
            watch_retry_and_notify(
                project_dir=project_dir,
                temp_log=_temp_log_for_project(project_dir),
                chat_id=int(chat_id),
                application=application,
                started_at=started_at,
            )
        )

    await update.message.reply_text(
        f"retry started\nproject={project_dir}\nmode=fix -> continue{warn}"
    )


async def command_idea(update: Any, context: Any) -> None:
    await _handle_idea_like(update, context, "idea")


async def command_pipeline(update: Any, context: Any) -> None:
    await _handle_idea_like(update, context, "pipeline")


async def command_continue(update: Any, context: Any) -> None:
    await _handle_continue(update, context)


async def command_fix(update: Any, context: Any) -> None:
    await _handle_fix(update, context)


async def command_retry(update: Any, context: Any) -> None:
    await _handle_retry(update, context)


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


async def command_logs(update: Any, context: Any) -> None:
    project_path = load_last_project_path()
    if project_path is None:
        await update.message.reply_text(_missing_project_message())
        return

    args = [str(x).strip().lower() for x in getattr(context, "args", []) if str(x).strip()]
    mode = args[0] if args else "last"
    if mode not in ("backend", "frontend", "last"):
        await update.message.reply_text("Usage: /logs [backend|frontend|last]")
        return

    if mode == "backend":
        msg = read_recent_backend_logs(project_path)
    elif mode == "frontend":
        msg = read_recent_frontend_logs(project_path)
    else:
        msg = read_recent_last_logs(project_path, temp_log=_temp_log_for_project(project_path))

    await update.message.reply_text(_truncate_message(msg, limit=1500))


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
    app.add_handler(CommandHandler("retry", command_retry))
    app.add_handler(CommandHandler("logs", command_logs))
    app.add_handler(CommandHandler("state", command_state))
    app.add_handler(CommandHandler("help", command_help))
    app.run_polling()
