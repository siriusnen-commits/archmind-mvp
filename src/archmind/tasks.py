from __future__ import annotations

import json
import re
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Optional

VALID_STATUSES = ("todo", "doing", "done", "blocked")


@dataclass
class TaskItem:
    id: int
    title: str
    status: str
    source: str
    notes: str


def _tasks_path(project_dir: Path) -> Path:
    return project_dir.expanduser().resolve() / ".archmind" / "tasks.json"


def _plan_json_path(project_dir: Path) -> Path:
    return project_dir.expanduser().resolve() / ".archmind" / "plan.json"


def _plan_md_path(project_dir: Path) -> Path:
    return project_dir.expanduser().resolve() / ".archmind" / "plan.md"


def _fallback_tasks() -> list[TaskItem]:
    return [
        TaskItem(
            id=1,
            title="review plan and define implementation steps",
            status="todo",
            source="manual",
            notes="",
        )
    ]


def _normalize_task(id_value: int, title: str, source: str) -> TaskItem:
    clean_title = re.sub(r"\s+", " ", (title or "").strip())
    if not clean_title:
        clean_title = f"task {id_value}"
    return TaskItem(id=id_value, title=clean_title, status="todo", source=source, notes="")


def _tasks_from_plan_json(plan_json_path: Path) -> list[TaskItem]:
    try:
        payload = json.loads(plan_json_path.read_text(encoding="utf-8"))
    except Exception:
        return []
    raw_steps = payload.get("steps")
    if not isinstance(raw_steps, list):
        return []
    out: list[TaskItem] = []
    for idx, step in enumerate(raw_steps, start=1):
        if isinstance(step, dict):
            title = str(step.get("title") or step.get("description") or step.get("id") or "")
        else:
            title = str(step)
        out.append(_normalize_task(idx, title, "plan"))
    return [t for t in out if t.title]  # keep stable order


_PLAN_MD_LIST_RE = re.compile(r"^\s*(?:[-*+]\s+|\d+\.\s+)(.+?)\s*$")


def _tasks_from_plan_md(plan_md_path: Path) -> list[TaskItem]:
    lines = plan_md_path.read_text(encoding="utf-8", errors="replace").splitlines()
    titles: list[str] = []
    for line in lines:
        m = _PLAN_MD_LIST_RE.match(line)
        if not m:
            continue
        candidate = m.group(1).strip()
        candidate = re.sub(r"^\[[ xX]\]\s*", "", candidate)
        if not candidate:
            continue
        lower = candidate.lower()
        if lower.startswith("설명:") or lower.startswith("검증:") or lower.startswith("대응:"):
            continue
        titles.append(candidate)
    tasks = [_normalize_task(i, title, "plan") for i, title in enumerate(titles, start=1)]
    return tasks


def _serialize_tasks(project_dir: Path, tasks: list[TaskItem], created_at: Optional[str] = None) -> dict[str, Any]:
    return {
        "project_dir": str(project_dir.expanduser().resolve()),
        "created_at": created_at or datetime.now().strftime("%Y%m%d_%H%M%S"),
        "tasks": [
            {
                "id": t.id,
                "title": t.title,
                "status": t.status if t.status in VALID_STATUSES else "todo",
                "source": t.source,
                "notes": t.notes,
            }
            for t in tasks
        ],
    }


def _deserialize_tasks(payload: dict[str, Any]) -> list[TaskItem]:
    out: list[TaskItem] = []
    raw = payload.get("tasks")
    if not isinstance(raw, list):
        return out
    for idx, item in enumerate(raw, start=1):
        if not isinstance(item, dict):
            continue
        status = str(item.get("status") or "todo")
        if status not in VALID_STATUSES:
            status = "todo"
        out.append(
            TaskItem(
                id=int(item.get("id") or idx),
                title=str(item.get("title") or f"task {idx}"),
                status=status,
                source=str(item.get("source") or "manual"),
                notes=str(item.get("notes") or ""),
            )
        )
    return out


def load_tasks(project_dir: Path) -> Optional[dict[str, Any]]:
    path = _tasks_path(project_dir)
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None


def initialize_tasks_from_plan(project_dir: Path) -> dict[str, Any]:
    project_dir = project_dir.expanduser().resolve()
    tasks_path = _tasks_path(project_dir)
    tasks_path.parent.mkdir(parents=True, exist_ok=True)

    tasks = _tasks_from_plan_json(_plan_json_path(project_dir))
    if not tasks and _plan_md_path(project_dir).exists():
        tasks = _tasks_from_plan_md(_plan_md_path(project_dir))
    if not tasks:
        tasks = _fallback_tasks()

    payload = _serialize_tasks(project_dir, tasks)
    tasks_path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    return payload


def ensure_tasks(project_dir: Path) -> dict[str, Any]:
    payload = load_tasks(project_dir)
    if payload is not None:
        return payload
    return initialize_tasks_from_plan(project_dir)


def list_tasks(project_dir: Path) -> list[TaskItem]:
    payload = ensure_tasks(project_dir)
    return _deserialize_tasks(payload)


def next_task(project_dir: Path) -> Optional[TaskItem]:
    for task in list_tasks(project_dir):
        if task.status == "todo":
            return task
    return None


def current_task(project_dir: Path) -> Optional[TaskItem]:
    tasks = list_tasks(project_dir)
    for task in tasks:
        if task.status == "doing":
            return task
    for task in tasks:
        if task.status == "todo":
            return task
    return None


def update_task_status(project_dir: Path, task_id: int, status: str) -> Optional[TaskItem]:
    if status not in VALID_STATUSES:
        return None
    payload = ensure_tasks(project_dir)
    tasks = _deserialize_tasks(payload)
    updated: Optional[TaskItem] = None
    for task in tasks:
        if task.id == task_id:
            task.status = status
            updated = task
            break
    if updated is None:
        return None

    created_at = str(payload.get("created_at") or datetime.now().strftime("%Y%m%d_%H%M%S"))
    saved = _serialize_tasks(project_dir, tasks, created_at=created_at)
    _tasks_path(project_dir).write_text(json.dumps(saved, indent=2, ensure_ascii=False), encoding="utf-8")
    return updated


def format_task_line(task: TaskItem) -> str:
    return f"[{task.id}] {task.status:<7} {task.title}"

