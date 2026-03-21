from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from archmind.deploy import get_local_runtime_status
from archmind.next_suggester import analyze_spec_progression
from archmind.state import load_provider_mode, load_state, set_provider_mode, write_state
from archmind.telegram_bot import (
    _load_json,
    _project_runtime_status,
    _repository_summary_from_state,
    _resolve_project_type,
    get_current_project,
    summarize_recent_evolution,
)
from archmind.ui_models import ProjectDetailResponse, ProjectListItem, RepositorySummary, RuntimeSummary, SpecSummary


def resolve_ui_projects_dir() -> Path:
    raw = str(os.getenv("ARCHMIND_PROJECTS_DIR", "") or "").strip()
    if raw:
        return Path(raw).expanduser().resolve()
    return (Path.home() / "archmind-telegram-projects").expanduser().resolve()


def list_project_dirs(projects_dir: Path | None = None) -> list[Path]:
    root = (projects_dir or resolve_ui_projects_dir()).expanduser().resolve()
    if not root.exists() or not root.is_dir():
        return []
    rows: list[Path] = []
    for child in root.iterdir():
        if not child.is_dir():
            continue
        archmind_dir = child / ".archmind"
        if not archmind_dir.exists():
            continue
        state_path = archmind_dir / "state.json"
        result_path = archmind_dir / "result.json"
        spec_path = archmind_dir / "project_spec.json"
        if state_path.exists() or result_path.exists() or spec_path.exists():
            rows.append(child.resolve())
    return sorted(rows, key=lambda p: p.name.lower())


def _runtime_urls_for_display(status: str, runtime_payload: dict[str, Any], state_payload: dict[str, Any]) -> tuple[str, str]:
    backend = runtime_payload.get("backend") if isinstance(runtime_payload.get("backend"), dict) else {}
    frontend = runtime_payload.get("frontend") if isinstance(runtime_payload.get("frontend"), dict) else {}
    backend_running = str(backend.get("status") or "").strip().upper() == "RUNNING"
    frontend_running = str(frontend.get("status") or "").strip().upper() == "RUNNING"
    backend_url = str(backend.get("url") or "").strip()
    frontend_url = str(frontend.get("url") or "").strip()
    if status != "RUNNING":
        return "", ""
    if not backend_running:
        backend_url = ""
    if not frontend_running:
        frontend_url = ""
    if not backend_url and backend_running:
        backend_url = str(state_payload.get("backend_deploy_url") or "").strip()
    if not frontend_url and frontend_running:
        frontend_url = str(state_payload.get("frontend_deploy_url") or "").strip()
    return backend_url, frontend_url


def build_project_list_item(project_dir: Path) -> ProjectListItem:
    archmind_dir = project_dir / ".archmind"
    state_payload = load_state(project_dir) or {}
    result_payload = _load_json(archmind_dir / "result.json") or {}
    runtime_payload = get_local_runtime_status(project_dir)
    status = _project_runtime_status(project_dir, state_payload, result_payload, runtime_payload)
    backend_url, frontend_url = _runtime_urls_for_display(status, runtime_payload, state_payload)
    backend_runtime = runtime_payload.get("backend") if isinstance(runtime_payload.get("backend"), dict) else {}
    frontend_runtime = runtime_payload.get("frontend") if isinstance(runtime_payload.get("frontend"), dict) else {}
    if status == "RUNNING":
        if str(backend_runtime.get("status") or "").strip().upper() == "RUNNING" and str(frontend_runtime.get("status") or "").strip().upper() == "RUNNING":
            runtime = "RUNNING (backend+frontend)"
        elif str(backend_runtime.get("status") or "").strip().upper() == "RUNNING":
            runtime = "RUNNING (backend)"
        elif str(frontend_runtime.get("status") or "").strip().upper() == "RUNNING":
            runtime = "RUNNING (frontend)"
        else:
            runtime = "RUNNING"
    elif status == "FAIL":
        runtime = "FAIL"
    else:
        runtime = "STOPPED"

    current = get_current_project()
    is_current = bool(current is not None and current.resolve() == project_dir.resolve())
    return ProjectListItem(
        name=project_dir.name,
        path=str(project_dir),
        status=status,
        runtime=runtime,
        type=_resolve_project_type(state_payload, project_dir),
        template=str(state_payload.get("effective_template") or "unknown").strip() or "unknown",
        backend_url=backend_url,
        frontend_url=frontend_url,
        is_current=is_current,
    )


def find_project_by_name(name: str, projects_dir: Path | None = None) -> Path | None:
    key = str(name or "").strip()
    if not key:
        return None
    for project_dir in list_project_dirs(projects_dir):
        if project_dir.name == key:
            return project_dir
    return None


def build_project_detail(project_dir: Path) -> ProjectDetailResponse:
    archmind_dir = project_dir / ".archmind"
    state_payload = load_state(project_dir) or {}
    spec = _load_json(archmind_dir / "project_spec.json") or {}
    result_payload = _load_json(archmind_dir / "result.json") or {}
    runtime_payload = get_local_runtime_status(project_dir)
    status = _project_runtime_status(project_dir, state_payload, result_payload, runtime_payload)
    backend_url, frontend_url = _runtime_urls_for_display(status, runtime_payload, state_payload)
    backend_runtime = runtime_payload.get("backend") if isinstance(runtime_payload.get("backend"), dict) else {}
    frontend_runtime = runtime_payload.get("frontend") if isinstance(runtime_payload.get("frontend"), dict) else {}
    progression = analyze_spec_progression(spec if isinstance(spec, dict) else {})
    evolution = spec.get("evolution") if isinstance(spec.get("evolution"), dict) else {}
    history = evolution.get("history") if isinstance(evolution.get("history"), list) else []

    repository_info = _repository_summary_from_state(state_payload)
    return ProjectDetailResponse(
        name=project_dir.name,
        shape=str(spec.get("shape") or state_payload.get("architecture_app_shape") or "unknown").strip() or "unknown",
        template=str(spec.get("template") or state_payload.get("effective_template") or "unknown").strip() or "unknown",
        provider_mode=load_provider_mode(state_payload, default="local"),  # type: ignore[arg-type]
        spec_summary=SpecSummary(
            stage=str(progression.get("stage_label") or "Stage 0"),
            entities=int(progression.get("entities_count") or 0),
            apis=int(progression.get("apis_count") or 0),
            pages=int(progression.get("pages_count") or 0),
            history_count=len(history),
        ),
        runtime=RuntimeSummary(
            backend_status=str(backend_runtime.get("status") or "STOPPED").strip().upper() or "STOPPED",
            frontend_status=str(frontend_runtime.get("status") or "STOPPED").strip().upper() or "STOPPED",
            backend_url=backend_url,
            frontend_url=frontend_url,
        ),
        recent_evolution=summarize_recent_evolution(spec, limit=5),
        repository=RepositorySummary(
            status=str(repository_info.get("status") or "SKIPPED"),
            url=str(repository_info.get("url") or ""),
        ),
    )


def update_project_provider_mode(project_dir: Path, mode: str) -> str:
    payload = load_state(project_dir) or {}
    set_provider_mode(payload, mode)
    write_state(project_dir, payload)
    return load_provider_mode(payload, default="local")
