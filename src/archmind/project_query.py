from __future__ import annotations

import json
import os
import socket
import subprocess
from pathlib import Path
from typing import Any
from urllib.parse import urlparse, urlunparse

from archmind.deploy import get_local_runtime_status
from archmind.next_suggester import analyze_spec_progression
from archmind.project_analysis import analyze_project
from archmind.execution_history import load_recent_execution_events
from archmind.runtime_orchestrator import run_all_local_services
from archmind.state import load_provider_mode, load_state, set_provider_mode, update_runtime_state, write_state
from archmind.telegram_bot import (
    _load_json,
    _project_runtime_status,
    _read_or_init_project_spec,
    _repository_summary_from_state,
    _resolve_project_type,
    add_api_to_project,
    add_page_to_project,
    add_field_to_project,
    add_entity_to_project,
    save_last_project_path,
    summarize_recent_evolution,
)
from archmind.current_project import get_validated_current_project, set_current_project
from archmind.deploy import delete_project, restart_local_services, run_backend_local_with_health, stop_local_services
from archmind.runtime_status import build_runtime_snapshot
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
    hosts = _resolved_runtime_hosts()
    for host in hosts:
        if not host:
            continue
        alt = _replace_url_host(base, host)
        if not alt or alt in seen:
            continue
        seen.add(alt)
        out.append(alt)
    return out


def _runtime_hosts_config_path() -> Path:
    override = str(os.getenv("ARCHMIND_UI_RUNTIME_HOSTS_PATH", "") or "").strip()
    if override:
        return Path(override).expanduser().resolve()
    return (Path.home() / ".archmind" / "ui_runtime_hosts.json").expanduser().resolve()


def _load_persisted_runtime_hosts() -> dict[str, str]:
    path = _runtime_hosts_config_path()
    if not path.exists():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}
    if not isinstance(payload, dict):
        return {}
    out: dict[str, str] = {}
    for key in ("lan_host", "tailscale_host"):
        value = str(payload.get(key) or "").strip()
        if value:
            out[key] = value
    return out


def _save_persisted_runtime_hosts(lan_host: str, tailscale_host: str) -> None:
    path = _runtime_hosts_config_path()
    payload = {
        "lan_host": str(lan_host or "").strip(),
        "tailscale_host": str(tailscale_host or "").strip(),
    }
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    except Exception:
        return


def _detect_lan_host() -> str:
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        sock.connect(("8.8.8.8", 80))
        return str(sock.getsockname()[0] or "").strip()
    except Exception:
        return ""
    finally:
        sock.close()


def _detect_tailscale_host() -> str:
    try:
        result = subprocess.run(
            ["tailscale", "ip", "-4"],
            capture_output=True,
            text=True,
            timeout=1,
            shell=False,
            check=False,
        )
        lines = [str(line).strip() for line in str(result.stdout or "").splitlines() if str(line).strip()]
        return lines[0] if lines else ""
    except Exception:
        return ""


def _resolved_runtime_hosts() -> list[str]:
    persisted = _load_persisted_runtime_hosts()
    lan_host = str(os.getenv("ARCHMIND_LAN_HOST", "") or "").strip()
    tailscale_host = str(os.getenv("ARCHMIND_TAILSCALE_HOST", "") or "").strip()

    if not lan_host:
        lan_host = str(persisted.get("lan_host") or "").strip()
    if not tailscale_host:
        tailscale_host = str(persisted.get("tailscale_host") or "").strip()

    if not lan_host:
        lan_host = _detect_lan_host()
    if not tailscale_host:
        tailscale_host = _detect_tailscale_host()

    _save_persisted_runtime_hosts(lan_host, tailscale_host)

    out: list[str] = []
    for host in (lan_host, tailscale_host):
        value = str(host or "").strip()
        if not value or value in out:
            continue
        out.append(value)
    return out


def _runtime_urls_for_display(
    status: str, runtime_payload: dict[str, Any], state_payload: dict[str, Any]
) -> tuple[str, str, list[str], list[str]]:
    snapshot = build_runtime_snapshot(runtime_payload if isinstance(runtime_payload, dict) else {}, state_payload)
    backend = snapshot.get("backend") if isinstance(snapshot.get("backend"), dict) else {}
    frontend = snapshot.get("frontend") if isinstance(snapshot.get("frontend"), dict) else {}
    backend_url = str(backend.get("url") or "").strip()
    frontend_url = str(frontend.get("url") or "").strip()
    if status != "RUNNING":
        backend_url = ""
        frontend_url = ""
    return backend_url, frontend_url, _expand_runtime_urls(backend_url), _expand_runtime_urls(frontend_url)


def _resolve_current_project_dir() -> Path | None:
    current = get_validated_current_project()
    if current is None:
        return None
    return current.resolve()


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


def _safe_int(value: Any, default: int = 0) -> int:
    try:
        return int(value)
    except Exception:
        return int(default)


def _extract_entity_names(spec_payload: dict[str, Any]) -> list[str]:
    entities = spec_payload.get("entities")
    if not isinstance(entities, list):
        return []
    names: list[str] = []
    seen: set[str] = set()
    for item in entities:
        if not isinstance(item, dict):
            continue
        name = str(item.get("name") or "").strip()
        if not name:
            continue
        key = name.lower()
        if key in seen:
            continue
        seen.add(key)
        names.append(name)
    return names


def _empty_project_detail(project_dir: Path, warning: str = "") -> ProjectDetailResponse:
    return ProjectDetailResponse(
        name=project_dir.name,
        display_name=project_dir.name,
        is_current=_is_current_project(project_dir),
        shape="unknown",
        template="unknown",
        provider_mode="local",
        spec_summary=SpecSummary(),
        entities=[],
        runtime=RuntimeSummary(),
        recent_evolution=[],
        recent_runs=[],
        repository=RepositorySummary(),
        analysis=analyze_project(project_dir, project_name=project_dir.name, spec_payload={}, runtime_payload={}),
        warning=str(warning or "").strip(),
        safe=True,
    )


def _fallback_list_item(project_dir: Path, warning: str = "") -> ProjectListItem:
    return ProjectListItem(
        name=project_dir.name,
        display_name=project_dir.name,
        path=str(project_dir),
        status="STOPPED",
        runtime="STOPPED",
        type="unknown",
        template="unknown",
        backend_url="",
        frontend_url="",
        repository=RepositorySummary(),
        is_current=_is_current_project(project_dir),
        warning=str(warning or "").strip(),
    )


def resolve_repository_metadata(
    project_dir: Path,
    *,
    state_payload: dict[str, Any] | None = None,
    result_payload: dict[str, Any] | None = None,
) -> RepositorySummary:
    try:
        state = state_payload if isinstance(state_payload, dict) else (load_state(project_dir) or {})
        result = result_payload if isinstance(result_payload, dict) else {}
        if not result:
            result = _load_json(project_dir / ".archmind" / "result.json") or {}
        repository_info = _repository_summary_from_state(state if isinstance(state, dict) else {})
        status = str(repository_info.get("status") or "").strip().upper()
        url = str(repository_info.get("url") or "").strip()
        if not url:
            url = str(result.get("github_repo_url") or "").strip()
        if not status:
            status = "CREATED" if url else "SKIPPED"
        return RepositorySummary(status=status or "SKIPPED", url=url)
    except Exception:
        return RepositorySummary()


def build_project_list_item(project_dir: Path) -> ProjectListItem:
    try:
        archmind_dir = project_dir / ".archmind"
        state_payload = load_state(project_dir) or {}
        spec_payload = _load_json(archmind_dir / "project_spec.json") or {}
        result_payload = _load_json(archmind_dir / "result.json") or {}
        runtime_payload = get_local_runtime_status(project_dir)
        status = _project_runtime_status(project_dir, state_payload, result_payload, runtime_payload)
        snapshot = build_runtime_snapshot(runtime_payload if isinstance(runtime_payload, dict) else {}, state_payload)
        backend_runtime = snapshot.get("backend") if isinstance(snapshot.get("backend"), dict) else {}
        frontend_runtime = snapshot.get("frontend") if isinstance(snapshot.get("frontend"), dict) else {}
        backend_url, frontend_url, _, _ = _runtime_urls_for_display(status, runtime_payload, state_payload)
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
        repository = resolve_repository_metadata(
            project_dir,
            state_payload=state_payload if isinstance(state_payload, dict) else {},
            result_payload=result_payload if isinstance(result_payload, dict) else {},
        )

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
            repository=repository,
            is_current=_is_current_project(project_dir),
            warning="",
        )
    except Exception as exc:
        return _fallback_list_item(project_dir, warning=f"Failed to inspect project metadata: {exc}")


def find_project_by_name(name: str, projects_dir: Path | None = None) -> Path | None:
    key = str(name or "").strip()
    if not key:
        return None
    for project_dir in list_project_dirs(projects_dir):
        if project_dir.name == key:
            return project_dir
    return None


def build_project_detail(project_dir: Path) -> ProjectDetailResponse:
    try:
        archmind_dir = project_dir / ".archmind"
        state_payload = load_state(project_dir) or {}
        spec, _ = _read_or_init_project_spec(project_dir)
        result_payload = _load_json(archmind_dir / "result.json") or {}
        runtime_payload = get_local_runtime_status(project_dir)
        status = _project_runtime_status(project_dir, state_payload, result_payload, runtime_payload)
        snapshot = build_runtime_snapshot(runtime_payload if isinstance(runtime_payload, dict) else {}, state_payload)
        backend_url, frontend_url, backend_urls, frontend_urls = _runtime_urls_for_display(status, runtime_payload, state_payload)
        backend_runtime = snapshot.get("backend") if isinstance(snapshot.get("backend"), dict) else {}
        frontend_runtime = snapshot.get("frontend") if isinstance(snapshot.get("frontend"), dict) else {}
        analysis = analyze_project(
            project_dir,
            project_name=project_dir.name,
            spec_payload=spec if isinstance(spec, dict) else {},
            runtime_payload=runtime_payload if isinstance(runtime_payload, dict) else {},
        )
        canonical_entities = [str(x) for x in (analysis.get("entities") or []) if str(x).strip()]
        canonical_fields_by_entity = analysis.get("fields_by_entity") if isinstance(analysis.get("fields_by_entity"), dict) else {}
        canonical_entity_rows: list[dict[str, Any]] = []
        for entity_name in canonical_entities:
            fields = canonical_fields_by_entity.get(entity_name) if isinstance(canonical_fields_by_entity, dict) else []
            canonical_entity_rows.append(
                {
                    "name": entity_name,
                    "fields": fields if isinstance(fields, list) else [],
                }
            )
        canonical_api_endpoints = [
            f"{str(item.get('method') or '').strip().upper()} {str(item.get('path') or '').strip()}"
            for item in (analysis.get("apis") or [])
            if isinstance(item, dict) and str(item.get("method") or "").strip() and str(item.get("path") or "").strip()
        ]
        canonical_pages = [str(x) for x in (analysis.get("pages") or []) if str(x).strip()]
        progression = analyze_spec_progression(
            {
                "shape": str(spec.get("shape") or state_payload.get("architecture_app_shape") or "unknown").strip() or "unknown",
                "modules": spec.get("modules") if isinstance(spec.get("modules"), list) else [],
                "entities": canonical_entity_rows,
                "api_endpoints": canonical_api_endpoints,
                "frontend_pages": canonical_pages,
            }
        )
        evolution = spec.get("evolution") if isinstance(spec.get("evolution"), dict) else {}
        history = evolution.get("history") if isinstance(evolution.get("history"), list) else []
        repository = resolve_repository_metadata(
            project_dir,
            state_payload=state_payload if isinstance(state_payload, dict) else {},
            result_payload=result_payload if isinstance(result_payload, dict) else {},
        )
        recent_runs_raw = load_recent_execution_events(project_dir, limit=10)
        recent_runs: list[dict[str, Any]] = []
        for item in reversed(recent_runs_raw):
            if not isinstance(item, dict):
                continue
            recent_runs.append(
                {
                    "timestamp": str(item.get("timestamp") or "").strip(),
                    "source": str(item.get("source") or "").strip(),
                    "command": str(item.get("command") or "").strip(),
                    "status": str(item.get("status") or "").strip().lower(),
                    "message": str(item.get("message") or "").strip(),
                    "stop_reason": str(item.get("stop_reason") or "").strip(),
                }
            )
        return ProjectDetailResponse(
            name=project_dir.name,
            display_name=_display_name_from_payloads(project_dir, state_payload, spec if isinstance(spec, dict) else {}),
            is_current=_is_current_project(project_dir),
            shape=str(spec.get("shape") or state_payload.get("architecture_app_shape") or "unknown").strip() or "unknown",
            template=str(spec.get("template") or state_payload.get("effective_template") or "unknown").strip() or "unknown",
            provider_mode=load_provider_mode(state_payload, default="local"),  # type: ignore[arg-type]
            spec_summary=SpecSummary(
                stage=str(progression.get("stage_label") or "Stage 0"),
                entities=len(canonical_entities),
                apis=len(canonical_api_endpoints),
                pages=len(canonical_pages),
                history_count=len(history),
            ),
            entities=canonical_entities,
            runtime=RuntimeSummary(
                backend_status=str(backend_runtime.get("status") or "STOPPED").strip().upper() or "STOPPED",
                frontend_status=str(frontend_runtime.get("status") or "STOPPED").strip().upper() or "STOPPED",
                backend_url=backend_url,
                frontend_url=frontend_url,
                backend_urls=backend_urls,
                frontend_urls=frontend_urls,
                backend_last_known_url=str(backend_runtime.get("last_known_url") or "").strip(),
                frontend_last_known_url=str(frontend_runtime.get("last_known_url") or "").strip(),
            ),
            recent_evolution=summarize_recent_evolution(spec, limit=5),
            recent_runs=recent_runs,
            repository=repository,
            analysis=analysis,
            warning="",
            safe=True,
        )
    except Exception as exc:
        return _empty_project_detail(project_dir, warning=f"Failed to load full project detail: {exc}")


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


def delete_project_local(project_dir: Path) -> dict[str, Any]:
    result = delete_project(project_dir, mode="local")
    return result if isinstance(result, dict) else {}


def delete_project_repo(project_dir: Path) -> dict[str, Any]:
    result = delete_project(project_dir, mode="repo")
    return result if isinstance(result, dict) else {}


def delete_project_all(project_dir: Path) -> dict[str, Any]:
    result = delete_project(project_dir, mode="all")
    return result if isinstance(result, dict) else {}


def select_current_project(project_dir: Path) -> dict[str, Any]:
    target = project_dir.expanduser().resolve()
    if not target.exists() or not target.is_dir():
        return {
            "ok": False,
            "project_name": project_dir.name,
            "is_current": False,
            "detail": "Project not found",
            "error": "Project not found",
        }
    try:
        set_current_project(target)
        save_last_project_path(target)
        return {
            "ok": True,
            "project_name": target.name,
            "is_current": _is_current_project(target),
            "detail": "Current project updated",
            "error": "",
        }
    except Exception as exc:
        return {
            "ok": False,
            "project_name": target.name,
            "is_current": False,
            "detail": "Failed to set current project",
            "error": str(exc),
        }


def add_project_entity(project_dir: Path, entity_name: str) -> dict[str, Any]:
    result = add_entity_to_project(project_dir, entity_name, auto_restart_backend=False)
    return result if isinstance(result, dict) else {}


def add_project_field(project_dir: Path, entity_name: str, field_name: str, field_type: str) -> dict[str, Any]:
    result = add_field_to_project(
        project_dir,
        entity_name,
        field_name,
        field_type,
        auto_restart_backend=False,
    )
    return result if isinstance(result, dict) else {}


def add_project_api(project_dir: Path, method: str, path: str) -> dict[str, Any]:
    result = add_api_to_project(
        project_dir,
        method,
        path,
        auto_restart_backend=False,
    )
    return result if isinstance(result, dict) else {}


def add_project_page(project_dir: Path, page_path: str) -> dict[str, Any]:
    result = add_page_to_project(
        project_dir,
        page_path,
        auto_restart_backend=False,
    )
    return result if isinstance(result, dict) else {}


def build_project_analysis(project_dir: Path) -> dict[str, Any]:
    archmind_dir = project_dir / ".archmind"
    spec_payload = _load_json(archmind_dir / "project_spec.json") or {}
    runtime_payload = get_local_runtime_status(project_dir)
    return analyze_project(
        project_dir,
        project_name=project_dir.name,
        spec_payload=spec_payload if isinstance(spec_payload, dict) else {},
        runtime_payload=runtime_payload if isinstance(runtime_payload, dict) else {},
    )
