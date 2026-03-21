from __future__ import annotations

import os
from pathlib import Path
from typing import Any
from urllib.parse import urlparse, urlunparse

from archmind.deploy import get_local_runtime_status
from archmind.next_suggester import analyze_spec_progression
from archmind.runtime_orchestrator import run_all_local_services
from archmind.state import load_provider_mode, load_state, set_provider_mode, update_runtime_state, write_state
from archmind.telegram_bot import (
    _load_json,
    _project_runtime_status,
    _repository_summary_from_state,
    _resolve_project_type,
    get_current_project,
    load_last_project_path,
    summarize_recent_evolution,
)
from archmind.deploy import restart_local_services, run_backend_local_with_health, stop_local_services
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


def _replace_url_host(url: str, host: str) -> str:
    parsed = urlparse(str(url or "").strip())
    if not parsed.scheme or not parsed.netloc:
        return ""
    hostname = parsed.hostname
    if not hostname:
        return ""
    target_host = str(host or "").strip()
    if not target_host:
        return ""
    if ":" in target_host:
        return ""
    port = parsed.port
    userinfo = ""
    if parsed.username:
        userinfo = parsed.username
        if parsed.password:
            userinfo = f"{userinfo}:{parsed.password}"
        userinfo = f"{userinfo}@"
    netloc = f"{userinfo}{target_host}"
    if port is not None:
        netloc = f"{netloc}:{int(port)}"
    return urlunparse(parsed._replace(netloc=netloc))


def _expand_runtime_urls(primary_url: str) -> list[str]:
    base = str(primary_url or "").strip()
    if not base:
        return []
    out: list[str] = [base]
    seen: set[str] = {base}
    for env_key in ("ARCHMIND_LAN_HOST", "ARCHMIND_TAILSCALE_HOST"):
        host = str(os.getenv(env_key, "") or "").strip()
        if not host:
            continue
        alt = _replace_url_host(base, host)
        if not alt or alt in seen:
            continue
        seen.add(alt)
        out.append(alt)
    return out


def _runtime_urls_for_display(
    status: str, runtime_payload: dict[str, Any], state_payload: dict[str, Any]
) -> tuple[str, str, list[str], list[str]]:
    backend = runtime_payload.get("backend") if isinstance(runtime_payload.get("backend"), dict) else {}
    frontend = runtime_payload.get("frontend") if isinstance(runtime_payload.get("frontend"), dict) else {}
    backend_running = str(backend.get("status") or "").strip().upper() == "RUNNING"
    frontend_running = str(frontend.get("status") or "").strip().upper() == "RUNNING"
    backend_url = str(backend.get("url") or "").strip()
    frontend_url = str(frontend.get("url") or "").strip()
    if status != "RUNNING":
        return "", "", [], []
    if not backend_running:
        backend_url = ""
    if not frontend_running:
        frontend_url = ""
    if not backend_url and backend_running:
        backend_url = str(state_payload.get("backend_deploy_url") or "").strip()
    if not frontend_url and frontend_running:
        frontend_url = str(state_payload.get("frontend_deploy_url") or "").strip()
    return backend_url, frontend_url, _expand_runtime_urls(backend_url), _expand_runtime_urls(frontend_url)


def _resolve_current_project_dir() -> Path | None:
    current = get_current_project()
    if current is not None and current.exists() and current.is_dir():
        return current.resolve()
    last = load_last_project_path()
    if last is not None and last.exists() and last.is_dir():
        return last.resolve()
    return None


def _is_current_project(project_dir: Path) -> bool:
    current = _resolve_current_project_dir()
    return bool(current is not None and current == project_dir.resolve())


def _display_name_from_payloads(project_dir: Path, state_payload: dict[str, Any], spec_payload: dict[str, Any]) -> str:
    candidates = [
        state_payload.get("project_name"),
        state_payload.get("name"),
        state_payload.get("idea"),
        spec_payload.get("project_name"),
        spec_payload.get("name"),
        spec_payload.get("title"),
        project_dir.name,
    ]
    for item in candidates:
        value = str(item or "").strip()
        if value:
            return value
    return project_dir.name


def build_project_list_item(project_dir: Path) -> ProjectListItem:
    archmind_dir = project_dir / ".archmind"
    state_payload = load_state(project_dir) or {}
    spec_payload = _load_json(archmind_dir / "project_spec.json") or {}
    result_payload = _load_json(archmind_dir / "result.json") or {}
    runtime_payload = get_local_runtime_status(project_dir)
    status = _project_runtime_status(project_dir, state_payload, result_payload, runtime_payload)
    backend_url, frontend_url, _, _ = _runtime_urls_for_display(status, runtime_payload, state_payload)
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

    return ProjectListItem(
        name=project_dir.name,
        display_name=_display_name_from_payloads(project_dir, state_payload, spec_payload),
        path=str(project_dir),
        status=status,
        runtime=runtime,
        type=_resolve_project_type(state_payload, project_dir),
        template=str(state_payload.get("effective_template") or "unknown").strip() or "unknown",
        backend_url=backend_url,
        frontend_url=frontend_url,
        is_current=_is_current_project(project_dir),
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
    backend_url, frontend_url, backend_urls, frontend_urls = _runtime_urls_for_display(status, runtime_payload, state_payload)
    backend_runtime = runtime_payload.get("backend") if isinstance(runtime_payload.get("backend"), dict) else {}
    frontend_runtime = runtime_payload.get("frontend") if isinstance(runtime_payload.get("frontend"), dict) else {}
    progression = analyze_spec_progression(spec if isinstance(spec, dict) else {})
    evolution = spec.get("evolution") if isinstance(spec.get("evolution"), dict) else {}
    history = evolution.get("history") if isinstance(evolution.get("history"), list) else []

    repository_info = _repository_summary_from_state(state_payload)
    return ProjectDetailResponse(
        name=project_dir.name,
        display_name=_display_name_from_payloads(project_dir, state_payload, spec if isinstance(spec, dict) else {}),
        is_current=_is_current_project(project_dir),
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
            backend_urls=backend_urls,
            frontend_urls=frontend_urls,
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


def run_project_backend(project_dir: Path) -> dict[str, Any]:
    result = run_backend_local_with_health(project_dir)
    update_runtime_state(project_dir, result, action="ui run-backend")
    return result if isinstance(result, dict) else {}


def run_project_all(project_dir: Path) -> dict[str, Any]:
    result = run_all_local_services(project_dir)
    update_runtime_state(project_dir, result, action="ui run-all")
    return result if isinstance(result, dict) else {}


def restart_project_runtime(project_dir: Path) -> dict[str, Any]:
    result = restart_local_services(project_dir)
    deploy_payload = result.get("deploy") if isinstance(result.get("deploy"), dict) else result
    update_runtime_state(project_dir, deploy_payload if isinstance(deploy_payload, dict) else {}, action="ui restart")
    return result if isinstance(result, dict) else {}


def stop_project_runtime(project_dir: Path) -> dict[str, Any]:
    result = stop_local_services(project_dir)
    return result if isinstance(result, dict) else {}
