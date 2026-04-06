from __future__ import annotations

import json
import os
import socket
import subprocess
from collections import deque
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import urlparse, urlunparse

from archmind.deploy import get_local_runtime_status
from archmind.next_suggester import analyze_spec_progression
from archmind.project_analysis import analyze_project
from archmind.execution_history import load_recent_execution_events
from archmind.flow_execution import load_flow_execution, start_flow_execution
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


_UI_LOG_MAX_LINES = 200
_UI_LOG_MAX_CHARS = 24_000


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


def _is_runtime_url_reachable(url: str, timeout_s: float = 0.35) -> bool:
    parsed = urlparse(str(url or "").strip())
    host = str(parsed.hostname or "").strip()
    if not host:
        return False
    port = parsed.port
    if port is None:
        if parsed.scheme == "https":
            port = 443
        elif parsed.scheme == "http":
            port = 80
    if not port:
        return False
    try:
        with socket.create_connection((host, int(port)), timeout=timeout_s):
            return True
    except Exception:
        return False


def _expand_frontend_urls_from_backend_hosts(frontend_primary_url: str, backend_urls: list[str]) -> list[str]:
    base = str(frontend_primary_url or "").strip()
    if not base:
        return []
    out: list[str] = [base]
    seen: set[str] = {base}
    for backend_url in backend_urls:
        parsed = urlparse(str(backend_url or "").strip())
        host = str(parsed.hostname or "").strip()
        if not host:
            continue
        candidate = _replace_url_host(base, host)
        if not candidate or candidate in seen:
            continue
        if not _is_runtime_url_reachable(candidate):
            continue
        seen.add(candidate)
        out.append(candidate)
    return out


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


def _expand_runtime_urls_with_reachability(primary_url: str, component_runtime: dict[str, Any] | None) -> list[str]:
    base = str(primary_url or "").strip()
    if not base:
        return []
    if not isinstance(component_runtime, dict):
        return _expand_runtime_urls(base)
    reachability = component_runtime.get("reachability") if isinstance(component_runtime.get("reachability"), dict) else {}
    if not reachability:
        return _expand_runtime_urls(base)
    lan_urls = reachability.get("lan_urls") if isinstance(reachability, dict) else []
    external_urls = reachability.get("external_urls") if isinstance(reachability, dict) else []
    if not isinstance(lan_urls, list):
        lan_urls = []
    if not isinstance(external_urls, list):
        external_urls = []
    out: list[str] = [base]
    seen: set[str] = {base}
    for candidate in [*lan_urls, *external_urls]:
        text = str(candidate or "").strip()
        if not text or text in seen:
            continue
        seen.add(text)
        out.append(text)
    return out


def _verified_nonlocal_urls(component_runtime: dict[str, Any] | None) -> list[str]:
    if not isinstance(component_runtime, dict):
        return []
    reachability = component_runtime.get("reachability")
    if not isinstance(reachability, dict):
        return []
    out: list[str] = []
    seen: set[str] = set()
    for key in ("lan_urls", "external_urls"):
        values = reachability.get(key)
        if not isinstance(values, list):
            continue
        for candidate in values:
            text = str(candidate or "").strip()
            if not text or text in seen:
                continue
            seen.add(text)
            out.append(text)
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
    live_backend = runtime_payload.get("backend") if isinstance(runtime_payload.get("backend"), dict) else {}
    live_frontend = runtime_payload.get("frontend") if isinstance(runtime_payload.get("frontend"), dict) else {}
    backend_url = str(backend.get("url") or "").strip()
    frontend_url = str(frontend.get("url") or "").strip()
    if status != "RUNNING":
        backend_url = ""
        frontend_url = ""
    backend_runtime = live_backend if live_backend else backend
    frontend_runtime = live_frontend if live_frontend else frontend
    backend_urls = _expand_runtime_urls_with_reachability(backend_url, backend_runtime)
    frontend_urls = _expand_runtime_urls_with_reachability(frontend_url, frontend_runtime)
    verified_backend_nonlocal = _verified_nonlocal_urls(backend_runtime)
    if (
        frontend_url
        and len(frontend_urls) <= 1
        and bool(verified_backend_nonlocal)
    ):
        expanded_from_backend = _expand_frontend_urls_from_backend_hosts(
            frontend_url,
            [backend_url, *verified_backend_nonlocal],
        )
        if len(expanded_from_backend) > len(frontend_urls):
            frontend_urls = expanded_from_backend
    return (
        backend_url,
        frontend_url,
        backend_urls,
        frontend_urls,
    )


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


def _extract_spec_api_endpoints(spec_payload: dict[str, Any]) -> list[str]:
    endpoints = spec_payload.get("api_endpoints")
    if not isinstance(endpoints, list):
        return []
    rows: list[str] = []
    seen: set[str] = set()
    for item in endpoints:
        text = str(item or "").strip()
        if not text:
            continue
        key = text.lower()
        if key in seen:
            continue
        seen.add(key)
        rows.append(text)
    return rows


def _extract_spec_pages(spec_payload: dict[str, Any]) -> list[str]:
    pages = spec_payload.get("frontend_pages")
    if not isinstance(pages, list):
        return []
    rows: list[str] = []
    seen: set[str] = set()
    for item in pages:
        text = str(item or "").strip()
        if not text:
            continue
        key = text.lower()
        if key in seen:
            continue
        seen.add(key)
        rows.append(text)
    return rows


def _runtime_state_from_status(status: str) -> str:
    normalized = str(status or "").strip().upper()
    if normalized == "RUNNING":
        return "RUNNING"
    if normalized == "FAIL":
        return "FAIL"
    return "NOT_RUNNING"


def _normalize_evolution_status(value: Any) -> str:
    text = str(value or "").strip().lower()
    if text in {"verified", "partial", "failed"}:
        return text.upper()
    if text == "ok":
        return "OK"
    if text == "fail":
        return "FAILED"
    if text == "stop":
        return "STOPPED"
    if text in {"synced", "commit_only", "push_failed"}:
        return text.upper()
    return "UNKNOWN"


def _action_type_from_command(command: str) -> str:
    text = str(command or "").strip().lower()
    if not text:
        return "command"
    if text.startswith("/auto"):
        return "auto"
    if text.startswith("/fix"):
        return "fix"
    if text.startswith("/continue"):
        return "continue"
    if text.startswith("/add_api"):
        return "add_api"
    if text.startswith("/add_page"):
        return "add_page"
    if text.startswith("/implement_page"):
        return "implement_page"
    if text.startswith("/add_field"):
        return "add_field"
    if text.startswith("/add_entity"):
        return "add_entity"
    return "command"


def _normalize_auto_summary(auto_summary: dict[str, Any] | None) -> dict[str, Any]:
    row = auto_summary if isinstance(auto_summary, dict) else {}
    planned_steps = [
        {
            "command": str(item.get("command") or "").strip(),
            "priority": str(item.get("priority") or "").strip().lower() or "unknown",
            "kind": str(item.get("kind") or "").strip().lower(),
        }
        for item in (row.get("planned_steps") or [])
        if isinstance(item, dict) and str(item.get("command") or "").strip()
    ]
    executed_steps = [
        {
            "command": str(item.get("command") or "").strip(),
            "priority": str(item.get("priority") or "").strip().lower() or "unknown",
            "goal": str(item.get("goal") or "").strip().lower(),
        }
        for item in (row.get("executed_steps") or [])
        if isinstance(item, dict) and str(item.get("command") or "").strip()
    ]
    skipped_steps = [
        {
            "command": str(item.get("command") or "").strip(),
            "reason": str(item.get("reason") or "").strip().lower() or "unknown",
        }
        for item in (row.get("skipped_steps") or [])
        if isinstance(item, dict) and str(item.get("command") or "").strip()
    ]
    plan_goal = str(row.get("plan_goal") or "").strip().lower()
    plan_reason = str(row.get("plan_reason") or "").strip()
    goal_satisfied_raw = row.get("goal_satisfied")
    goal_satisfied = bool(goal_satisfied_raw) if isinstance(goal_satisfied_raw, bool) else False
    normalized = dict(row)
    normalized["plan_goal"] = plan_goal
    normalized["plan_reason"] = plan_reason
    normalized["planned_steps"] = planned_steps
    normalized["executed_steps"] = executed_steps
    normalized["skipped_steps"] = skipped_steps
    normalized["goal_satisfied"] = goal_satisfied
    return normalized


def _unique_nonempty_strings(values: list[Any]) -> list[str]:
    out: list[str] = []
    seen: set[str] = set()
    for item in values:
        text = str(item or "").strip()
        if not text:
            continue
        key = text.lower()
        if key in seen:
            continue
        seen.add(key)
        out.append(text)
    return out


def _normalize_design_entities(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    rows: list[str] = []
    for item in value:
        if isinstance(item, dict):
            name = str(item.get("name") or "").strip()
            if name:
                rows.append(name)
            continue
        text = str(item or "").strip()
        if text:
            rows.append(text)
    return _unique_nonempty_strings(rows)


def _load_saved_design_payload(project_dir: Path) -> dict[str, Any]:
    for filename in ("design.json", "architecture_design.json"):
        raw = _load_json(project_dir / ".archmind" / filename) or {}
        if isinstance(raw, dict) and raw:
            return raw
    return {}


def _build_design_overview(
    project_dir: Path,
    *,
    state_payload: dict[str, Any],
    spec_payload: dict[str, Any],
    analysis_payload: dict[str, Any],
) -> dict[str, Any]:
    design_row = _load_saved_design_payload(project_dir)
    summary = str(
        design_row.get("architecture_summary")
        or design_row.get("overview")
        or design_row.get("summary")
        or ""
    ).strip()
    notes = str(
        design_row.get("notes")
        or design_row.get("reasoning")
        or state_payload.get("architecture_reason_summary")
        or ""
    ).strip()
    entities = _normalize_design_entities(design_row.get("entities"))
    apis = _unique_nonempty_strings(
        [
            str(item).strip()
            for item in (
                design_row.get("apis")
                if isinstance(design_row.get("apis"), list)
                else design_row.get("api_endpoints") if isinstance(design_row.get("api_endpoints"), list) else []
            )
            if str(item).strip()
        ]
    )
    pages = _unique_nonempty_strings(
        [
            str(item).strip()
            for item in (
                design_row.get("pages")
                if isinstance(design_row.get("pages"), list)
                else design_row.get("frontend_pages") if isinstance(design_row.get("frontend_pages"), list) else []
            )
            if str(item).strip()
        ]
    )

    if not entities:
        entities = _unique_nonempty_strings(
            [str(item).strip() for item in (analysis_payload.get("entities") or []) if str(item).strip()]
        )
    if not apis:
        apis = _unique_nonempty_strings(
            [
                f"{str(item.get('method') or '').strip().upper()} {str(item.get('path') or '').strip()}".strip()
                for item in (analysis_payload.get("apis") or [])
                if isinstance(item, dict) and str(item.get("method") or "").strip() and str(item.get("path") or "").strip()
            ]
        )
    if not pages:
        pages = _unique_nonempty_strings([str(item).strip() for item in (analysis_payload.get("pages") or []) if str(item).strip()])
    if not entities:
        entities = _extract_entity_names(spec_payload)
    if not apis:
        apis = _extract_spec_api_endpoints(spec_payload)
    if not pages:
        pages = _extract_spec_pages(spec_payload)

    if not summary:
        shape = str(state_payload.get("architecture_app_shape") or spec_payload.get("shape") or "").strip()
        template = str(state_payload.get("effective_template") or spec_payload.get("template") or "").strip()
        if shape and template:
            summary = f"{shape} architecture using {template}"
        elif shape:
            summary = f"{shape} architecture"
        elif template:
            summary = f"Template: {template}"

    if not summary and not notes and not entities and not apis and not pages:
        return {}
    return {
        "architecture_summary": summary,
        "entities": entities,
        "apis": apis,
        "pages": pages,
        "notes": notes,
    }


def _load_saved_plan_payload(project_dir: Path) -> dict[str, Any]:
    raw = _load_json(project_dir / ".archmind" / "plan_execution.json") or {}
    return raw if isinstance(raw, dict) else {}


_PLAN_LOW_VALUE_FIELDS = {"created_at", "updated_at", "timestamp", "deleted_at"}
_PLAN_BUCKET_SCORE = {
    "runtime_drift_gap": 400,
    "crud_gap": 320,
    "relation_gap": 280,
    "usability_gap": 220,
    "saved_plan_gap": 120,
}
_PLAN_PRIORITY_SCORE = {"high": 40, "medium": 20, "low": 10, "none": 0}
_PLAN_FLOW_MAX = 2


def _infer_step_type_from_command(command: str) -> str:
    text = str(command or "").strip().lower()
    if text.startswith("/add_api "):
        return "api"
    if text.startswith("/add_field "):
        return "field"
    if text.startswith("/add_page ") or text.startswith("/implement_page "):
        return "page"
    return "api"


def _infer_flow_type(bucket: str, command: str, title: str) -> str:
    normalized_bucket = str(bucket or "").strip().lower()
    text = " ".join([str(command or "").strip().lower(), str(title or "").strip().lower()])
    if "search" in text:
        return "search"
    if normalized_bucket == "relation_gap":
        return "relation"
    if normalized_bucket in {"crud_gap", "runtime_drift_gap"}:
        return "crud"
    if normalized_bucket in {"usability_gap", "saved_plan_gap"}:
        return "usability"
    return "crud"


def _flow_name(flow_type: str) -> str:
    normalized = str(flow_type or "").strip().lower()
    if normalized == "search":
        return "Search Flow"
    if normalized == "relation":
        return "Relation Flow"
    if normalized == "usability":
        return "Usability Flow"
    return "CRUD Flow"


def _normalize_plan_priority(value: Any) -> str:
    text = str(value or "").strip().lower()
    if text in {"high", "medium", "low", "none"}:
        return text
    return "medium"


def _normalize_plan_page(value: Any) -> str:
    return str(value or "").strip().replace("\\", "/").strip("/").lower()


def _normalize_plan_api_endpoint(method: Any, path: Any) -> str:
    method_text = str(method or "").strip().upper()
    path_text = str(path or "").strip()
    if not method_text or not path_text:
        return ""
    if not path_text.startswith("/"):
        path_text = f"/{path_text}"
    return f"{method_text} {path_text}"


def _canonicalize_plan_command(command: Any) -> str:
    text = str(command or "").strip()
    if not text.startswith("/"):
        return ""
    parts = [part for part in text.split() if part]
    if not parts:
        return ""
    cmd = parts[0].strip().lower()
    if cmd in {"/fix", "/inspect", "/next", "/auto"} and len(parts) == 1:
        return cmd
    if cmd == "/add_entity" and len(parts) >= 2:
        entity = str(parts[1] or "").strip()
        return f"/add_entity {entity}" if entity else ""
    if cmd == "/add_field" and len(parts) >= 3:
        entity = str(parts[1] or "").strip()
        expr = str(parts[2] or "").strip()
        if ":" in expr:
            field_name, field_type = expr.split(":", 1)
        else:
            field_name, field_type = expr, "string"
        field_name = str(field_name or "").strip().lower()
        field_type = str(field_type or "").strip().lower() or "string"
        if not entity or not field_name:
            return ""
        return f"/add_field {entity} {field_name}:{field_type}"
    if cmd == "/add_api" and len(parts) >= 3:
        endpoint = _normalize_plan_api_endpoint(parts[1], parts[2])
        return f"/add_api {endpoint}" if endpoint else ""
    if cmd in {"/add_page", "/implement_page"} and len(parts) >= 2:
        page = _normalize_plan_page(parts[1])
        return f"{cmd} {page}" if page else ""
    return ""


def _plan_field_name_from_command(command: str) -> str:
    text = str(command or "").strip()
    if not text.startswith("/add_field "):
        return ""
    parts = [part for part in text.split() if part]
    if len(parts) < 3:
        return ""
    expr = str(parts[2] or "").strip().lower()
    return expr.split(":", 1)[0].strip()


def _detect_plan_profile(
    analysis_payload: dict[str, Any],
    spec_payload: dict[str, Any],
    project_name: str,
) -> str:
    entities = {str(item or "").strip().lower() for item in (analysis_payload.get("entities") or []) if str(item).strip()}
    modules = {
        str(item or "").strip().lower()
        for item in (
            analysis_payload.get("modules")
            if isinstance(analysis_payload.get("modules"), list)
            else spec_payload.get("modules") if isinstance(spec_payload.get("modules"), list) else []
        )
        if str(item).strip()
    }
    domains = {
        str(item or "").strip().lower()
        for item in (
            analysis_payload.get("domains")
            if isinstance(analysis_payload.get("domains"), list)
            else spec_payload.get("domains") if isinstance(spec_payload.get("domains"), list) else []
        )
        if str(item).strip()
    }
    name_text = str(project_name or "").strip().lower()
    tokens = {*(entities), *(modules), *(domains), name_text}
    if any("bookmark" in token for token in tokens):
        return "bookmark"
    if any(token in {"task", "tasks", "todo", "todos"} or "todo" in token for token in tokens):
        return "todo"
    if any(token in {"entry", "entries", "diary", "journal"} or "diary" in token or "journal" in token for token in tokens):
        return "diary"
    return "generic"


def _build_plan_state(
    *,
    analysis_payload: dict[str, Any],
    spec_payload: dict[str, Any],
) -> dict[str, Any]:
    entities = {str(item or "").strip().lower() for item in (analysis_payload.get("entities") or []) if str(item).strip()}
    fields_by_entity_raw = analysis_payload.get("fields_by_entity") if isinstance(analysis_payload.get("fields_by_entity"), dict) else {}
    fields_by_entity: dict[str, set[str]] = {}
    for entity, fields in fields_by_entity_raw.items():
        key = str(entity or "").strip().lower()
        if not key:
            continue
        row_set: set[str] = set()
        if isinstance(fields, list):
            for item in fields:
                if not isinstance(item, dict):
                    continue
                name = str(item.get("name") or "").strip().lower()
                if name:
                    row_set.add(name)
        fields_by_entity[key] = row_set

    api_set: set[str] = set()
    for item in (analysis_payload.get("apis") or []):
        if not isinstance(item, dict):
            continue
        endpoint = _normalize_plan_api_endpoint(item.get("method"), item.get("path"))
        if endpoint:
            api_set.add(endpoint)
    for endpoint in _extract_spec_api_endpoints(spec_payload):
        parts = str(endpoint or "").split(maxsplit=1)
        if len(parts) != 2:
            continue
        normalized = _normalize_plan_api_endpoint(parts[0], parts[1])
        if normalized:
            api_set.add(normalized)

    page_set = {_normalize_plan_page(item) for item in (analysis_payload.get("pages") or []) if _normalize_plan_page(item)}
    page_set.update({_normalize_plan_page(item) for item in _extract_spec_pages(spec_payload) if _normalize_plan_page(item)})
    placeholder_pages = {
        _normalize_plan_page(item)
        for item in (analysis_payload.get("placeholder_pages") or [])
        if _normalize_plan_page(item)
    }
    return {
        "entities": entities,
        "fields_by_entity": fields_by_entity,
        "apis": api_set,
        "pages": page_set,
        "placeholder_pages": placeholder_pages,
    }


def _is_plan_command_already_satisfied(command: str, state: dict[str, Any]) -> bool:
    text = _canonicalize_plan_command(command)
    if not text:
        return True
    entities = state.get("entities") if isinstance(state.get("entities"), set) else set()
    fields_by_entity = state.get("fields_by_entity") if isinstance(state.get("fields_by_entity"), dict) else {}
    api_set = state.get("apis") if isinstance(state.get("apis"), set) else set()
    page_set = state.get("pages") if isinstance(state.get("pages"), set) else set()
    placeholder_pages = state.get("placeholder_pages") if isinstance(state.get("placeholder_pages"), set) else set()

    if text.startswith("/add_entity "):
        entity = str(text.split(maxsplit=1)[1] if len(text.split(maxsplit=1)) > 1 else "").strip().lower()
        return bool(entity and entity in entities)
    if text.startswith("/add_field "):
        parts = [part for part in text.split() if part]
        if len(parts) < 3:
            return True
        entity = str(parts[1] or "").strip().lower()
        field = str(parts[2] or "").strip().split(":", 1)[0].strip().lower()
        existing_fields = fields_by_entity.get(entity) if isinstance(fields_by_entity.get(entity), set) else set()
        return bool(field and field in existing_fields)
    if text.startswith("/add_api "):
        endpoint = str(text.replace("/add_api ", "", 1) or "").strip()
        return bool(endpoint and endpoint in api_set)
    if text.startswith("/add_page "):
        page = _normalize_plan_page(text.replace("/add_page ", "", 1))
        return bool(page and page in page_set)
    if text.startswith("/implement_page "):
        page = _normalize_plan_page(text.replace("/implement_page ", "", 1))
        if not page:
            return True
        return page not in placeholder_pages
    return False


def _plan_candidate_step(
    *,
    bucket: str,
    title: str,
    command: str,
    why: str,
    expected_effect: str,
    priority: str,
    goal: str,
) -> dict[str, str]:
    normalized_command = _canonicalize_plan_command(command)
    step_type = _infer_step_type_from_command(normalized_command)
    flow_type = _infer_flow_type(bucket, normalized_command, title)
    return {
        "bucket": str(bucket or "").strip(),
        "goal": str(goal or "").strip(),
        "flow_type": flow_type,
        "step_type": step_type,
        "title": str(title or "Next step").strip() or "Next step",
        "command": normalized_command,
        "why": str(why or "").strip(),
        "expected_effect": str(expected_effect or "").strip(),
        "priority": _normalize_plan_priority(priority),
    }


def _plan_score(step: dict[str, str]) -> int:
    bucket = str(step.get("bucket") or "").strip()
    priority = _normalize_plan_priority(step.get("priority"))
    score = int(_PLAN_BUCKET_SCORE.get(bucket, 100))
    score += int(_PLAN_PRIORITY_SCORE.get(priority, 0))
    if str(step.get("command") or "").strip():
        score += 5
    if _plan_field_name_from_command(str(step.get("command") or "")) in _PLAN_LOW_VALUE_FIELDS:
        score -= 80
    return score


def _build_usability_candidates(
    *,
    profile: str,
    analysis_payload: dict[str, Any],
) -> list[dict[str, str]]:
    candidates: list[dict[str, str]] = []
    entity_crud = analysis_payload.get("entity_crud_status") if isinstance(analysis_payload.get("entity_crud_status"), dict) else {}
    preferred_field_map: dict[str, list[str]] = {
        "todo": ["priority", "description", "status", "due_date"],
        "bookmark": ["category", "tags", "description", "pinned"],
        "diary": ["mood", "summary", "tags"],
        "generic": ["description", "status", "priority"],
    }
    preferred_fields = preferred_field_map.get(profile, preferred_field_map["generic"])
    for entity, info in entity_crud.items():
        if not isinstance(info, dict):
            continue
        entity_name = str(entity or "").strip()
        if not entity_name:
            continue
        missing_useful = [str(item).strip().lower() for item in (info.get("missing_useful_fields") or []) if str(item).strip()]
        if not missing_useful:
            continue
        for field in preferred_fields:
            if field in missing_useful and field not in _PLAN_LOW_VALUE_FIELDS:
                candidates.append(
                    _plan_candidate_step(
                        bucket="usability_gap",
                        goal="improve_user_flow",
                        title=f"Add useful {field} for {entity_name}",
                        command=f"/add_field {entity_name} {field}:string",
                        why=f"{entity_name} needs a user-facing field ({field}) to improve practical workflow.",
                        expected_effect=f"Improves usability and filtering quality for {entity_name}.",
                        priority="medium",
                    )
                )
                break

    if profile == "bookmark":
        candidates.append(
            _plan_candidate_step(
                bucket="usability_gap",
                goal="improve_discovery_flow",
                title="Add bookmark search endpoint",
                command="/add_api GET /bookmarks/search",
                why="Bookmark projects benefit from quick retrieval by keyword or category.",
                expected_effect="Enables organization/search-oriented bookmark discovery flow.",
                priority="medium",
            )
        )
    if profile == "todo":
        candidates.append(
            _plan_candidate_step(
                bucket="usability_gap",
                goal="improve_task_management_flow",
                title="Add task filtering endpoint",
                command="/add_api GET /tasks/search",
                why="Task projects need filter/search support for practical daily use.",
                expected_effect="Improves task finding and prioritization workflows.",
                priority="medium",
            )
        )
    if profile == "diary":
        candidates.append(
            _plan_candidate_step(
                bucket="usability_gap",
                goal="improve_entry_reflection_flow",
                title="Add diary search endpoint",
                command="/add_api GET /entries/search",
                why="Diary projects need quick lookup across past entries.",
                expected_effect="Improves recall and navigation through entry history.",
                priority="medium",
            )
        )
    return candidates


def _build_runtime_drift_candidate(
    *,
    analysis_payload: dict[str, Any],
    verification_payload: dict[str, Any],
) -> dict[str, str] | None:
    latest_status = str(verification_payload.get("latest_status") or "").strip().upper()
    latest_issues = verification_payload.get("latest_issues") if isinstance(verification_payload.get("latest_issues"), list) else []
    runtime_reflection = str(verification_payload.get("runtime_reflection") or "").strip()
    drift_summary = str(verification_payload.get("drift_summary") or "").strip()
    has_drift_signal = latest_status in {"PARTIAL", "FAILED"} or bool(latest_issues) or bool(runtime_reflection) or bool(drift_summary)
    if not has_drift_signal:
        return None
    next_action = analysis_payload.get("next_action") if isinstance(analysis_payload.get("next_action"), dict) else {}
    suggested = _canonicalize_plan_command(next_action.get("command"))
    command = suggested or "/fix"
    reason_fragments = [str(item).strip() for item in latest_issues if str(item).strip()]
    reason = reason_fragments[0] if reason_fragments else drift_summary or runtime_reflection or "Verification reported runtime/spec drift."
    return _plan_candidate_step(
        bucket="runtime_drift_gap",
        goal="resolve_runtime_drift",
        title="Resolve runtime and verification drift",
        command=command,
        why=reason,
        expected_effect="Aligns runtime behavior with expected spec and improves verification stability.",
        priority="high",
    )


def _build_saved_plan_candidates(plan_row: dict[str, Any]) -> list[dict[str, str]]:
    out: list[dict[str, str]] = []
    phases = plan_row.get("phases") if isinstance(plan_row.get("phases"), list) else []
    for phase in phases:
        if not isinstance(phase, dict):
            continue
        title = str(phase.get("title") or "Saved plan step").strip() or "Saved plan step"
        for step in (phase.get("steps") or []):
            command = _canonicalize_plan_command(step)
            if not command:
                continue
            out.append(
                _plan_candidate_step(
                    bucket="saved_plan_gap",
                    goal="continue_saved_plan",
                    title=title,
                    command=command,
                    why="Previously generated plan step that still appears actionable.",
                    expected_effect="Continues execution of a previously planned improvement.",
                    priority="low",
                )
            )
    return out


def _flow_step_sort_key(step: dict[str, str]) -> tuple[int, int, str]:
    flow_type = str(step.get("flow_type") or "").strip().lower()
    step_type = str(step.get("step_type") or "").strip().lower()
    if flow_type == "search":
        order = {"api": 0, "field": 1, "page": 2}
    elif flow_type == "crud":
        order = {"api": 0, "page": 1, "field": 2}
    elif flow_type == "usability":
        order = {"field": 0, "api": 1, "page": 2}
    elif flow_type == "relation":
        order = {"api": 0, "page": 1, "field": 2}
    else:
        order = {"api": 0, "field": 1, "page": 2}
    return (
        int(order.get(step_type, 99)),
        -_plan_score(step),
        str(step.get("command") or ""),
    )


def _build_flow_payload(steps: list[dict[str, str]], *, flow_type: str, flow_no: int) -> dict[str, Any]:
    ordered = sorted(steps, key=_flow_step_sort_key)
    payload_steps: list[dict[str, Any]] = []
    previous_id = ""
    for idx, step in enumerate(ordered, start=1):
        step_id = f"{flow_type}_{flow_no}_{idx}"
        depends_on = [previous_id] if previous_id else []
        payload_steps.append(
            {
                "id": step_id,
                "title": str(step.get("title") or "Plan step").strip() or "Plan step",
                "command": str(step.get("command") or "").strip(),
                "depends_on": depends_on,
                "why": str(step.get("why") or "").strip(),
                "expected_effect": str(step.get("expected_effect") or "").strip(),
                "priority": _normalize_plan_priority(step.get("priority")),
                "type": str(step.get("step_type") or "").strip().lower() or "api",
            }
        )
        previous_id = step_id
    return {
        "name": _flow_name(flow_type),
        "flow_type": flow_type,
        "steps": payload_steps,
    }


def _build_plan_flows(steps: list[dict[str, str]]) -> list[dict[str, Any]]:
    if not steps:
        return []
    grouped: dict[str, list[dict[str, str]]] = {}
    for step in steps:
        flow_type = str(step.get("flow_type") or "").strip().lower() or "crud"
        grouped.setdefault(flow_type, []).append(step)

    ranked_flows = sorted(
        grouped.items(),
        key=lambda item: (
            -max((_plan_score(step) for step in item[1]), default=0),
            str(item[0]),
        ),
    )[:_PLAN_FLOW_MAX]

    flows: list[dict[str, Any]] = []
    for idx, (flow_type, flow_steps) in enumerate(ranked_flows, start=1):
        flow_payload = _build_flow_payload(flow_steps, flow_type=flow_type, flow_no=idx)
        if flow_payload.get("steps"):
            flows.append(flow_payload)
    return flows


def _build_plan_overview(
    project_dir: Path,
    *,
    analysis_payload: dict[str, Any],
    auto_summary: dict[str, Any],
    spec_payload: dict[str, Any],
    verification_payload: dict[str, Any],
) -> dict[str, Any]:
    plan_row = _load_saved_plan_payload(project_dir)
    explanation = (
        analysis_payload.get("next_action_explanation")
        if isinstance(analysis_payload.get("next_action_explanation"), dict)
        else {}
    )
    profile = _detect_plan_profile(analysis_payload, spec_payload, project_dir.name)
    plan_state = _build_plan_state(analysis_payload=analysis_payload, spec_payload=spec_payload)

    raw_candidates: list[dict[str, str]] = []
    for item in (analysis_payload.get("suggestions") or []):
        if not isinstance(item, dict):
            continue
        kind = str(item.get("kind") or "").strip().lower()
        message = str(item.get("message") or "").strip()
        command = _canonicalize_plan_command(item.get("command"))
        if not command or kind in {"none", ""}:
            continue
        if kind in {"relation_page_behavior", "relation_scoped_api", "relation_placeholder_page"}:
            bucket = "relation_gap"
            goal = "close_relation_gap"
            title = "Complete relation flow"
        elif kind in {"missing_entity", "missing_crud_api", "missing_page", "placeholder_page"}:
            bucket = "crud_gap"
            goal = "complete_crud_flow"
            title = "Close CRUD/page gap"
        else:
            bucket = "usability_gap"
            goal = "improve_user_flow"
            title = "Improve usability"
        priority = "high" if bucket in {"crud_gap", "relation_gap"} else "medium"
        raw_candidates.append(
            _plan_candidate_step(
                bucket=bucket,
                goal=goal,
                title=title,
                command=command,
                why=message or str(explanation.get("reason_summary") or "").strip(),
                expected_effect=str(explanation.get("expected_effect") or "").strip() or "Improves project completeness in the next iteration.",
                priority=priority,
            )
        )

    visualization_gaps = analysis_payload.get("visualization_gaps") if isinstance(analysis_payload.get("visualization_gaps"), list) else []
    for row in visualization_gaps:
        if not isinstance(row, dict):
            continue
        gap_type = str(row.get("gap_type") or "").strip().lower()
        if not gap_type.startswith("missing_relation") and gap_type != "relation_page_placeholder":
            continue
        command = _canonicalize_plan_command(row.get("command"))
        if not command:
            continue
        raw_candidates.append(
            _plan_candidate_step(
                bucket="relation_gap",
                goal="close_relation_gap",
                title="Close relation gap",
                command=command,
                why=str(row.get("actionable") or row.get("gap_type") or "Relation flow is incomplete.").strip(),
                expected_effect="Improves relation-aware API/page behavior for connected entities.",
                priority=str(row.get("priority") or "high"),
            )
        )

    raw_candidates.extend(_build_usability_candidates(profile=profile, analysis_payload=analysis_payload))

    runtime_candidate = _build_runtime_drift_candidate(
        analysis_payload=analysis_payload,
        verification_payload=verification_payload,
    )
    if runtime_candidate is not None:
        raw_candidates.append(runtime_candidate)

    raw_candidates.extend(_build_saved_plan_candidates(plan_row))

    planned_steps = auto_summary.get("planned_steps") if isinstance(auto_summary.get("planned_steps"), list) else []
    for item in planned_steps:
        if not isinstance(item, dict):
            continue
        command = _canonicalize_plan_command(item.get("command"))
        if not command:
            continue
        raw_candidates.append(
            _plan_candidate_step(
                bucket="saved_plan_gap",
                goal=str(auto_summary.get("plan_goal") or "continue_auto_plan").strip().lower() or "continue_auto_plan",
                title="Continue auto plan",
                command=command,
                why=str(auto_summary.get("plan_reason") or "").strip() or "Auto plan identified this step as useful.",
                expected_effect="Continues the last auto-planned improvement path.",
                priority="low",
            )
        )

    deduped: list[dict[str, str]] = []
    seen_keys: set[str] = set()
    for row in raw_candidates:
        command = _canonicalize_plan_command(row.get("command"))
        if not command:
            continue
        if _is_plan_command_already_satisfied(command, plan_state):
            continue
        key = command
        if key in seen_keys:
            continue
        seen_keys.add(key)
        normalized = dict(row)
        normalized["command"] = command
        deduped.append(normalized)

    deduped = [
        item
        for item in deduped
        if _plan_field_name_from_command(str(item.get("command") or "")) not in _PLAN_LOW_VALUE_FIELDS
    ]

    ranked = sorted(
        deduped,
        key=lambda row: (
            -_plan_score(row),
            str(row.get("bucket") or ""),
            str(row.get("command") or ""),
        ),
    )
    steps = ranked[:3]
    flows = _build_plan_flows(steps)

    if not steps or not flows:
        return {
            "goal": "none",
            "priority": "none",
            "why": "No immediate suggestions.",
            "expected_effect": "No immediate action is needed.",
            "steps": [],
            "flows": [],
        }

    top = steps[0]
    goal = str(top.get("goal") or "general_improvement").strip() or "general_improvement"
    priority = _normalize_plan_priority(top.get("priority"))
    why = str(top.get("why") or "").strip() or str(explanation.get("reason_summary") or "").strip()
    expected_effect = str(top.get("expected_effect") or "").strip() or str(explanation.get("expected_effect") or "").strip()
    flattened_steps = [
        {
            "title": str(row.get("title") or "Plan step").strip() or "Plan step",
            "command": str(row.get("command") or "").strip(),
            "why": str(row.get("why") or "").strip(),
            "expected_effect": str(row.get("expected_effect") or "").strip(),
            "priority": _normalize_plan_priority(row.get("priority")),
        }
        for row in steps
    ]
    return {
        "goal": goal,
        "priority": priority,
        "why": why,
        "expected_effect": expected_effect,
        "steps": flattened_steps,
        "flows": flows,
    }


def _build_evolution_history(
    recent_runs: list[dict[str, Any]],
    _recent_evolution: list[str],
    *,
    auto_summary: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    seen_keys: set[str] = set()
    auto_row = _normalize_auto_summary(auto_summary)
    auto_goal = str(auto_row.get("plan_goal") or "").strip()
    auto_stop_reason = str(auto_row.get("stop_reason") or "").strip()
    auto_goal_satisfied = bool(auto_row.get("goal_satisfied")) if isinstance(auto_row.get("goal_satisfied"), bool) else False

    for item in recent_runs:
        if not isinstance(item, dict):
            continue
        command = str(item.get("command") or "").strip()
        status = _normalize_evolution_status(item.get("status"))
        stop_reason = str(item.get("stop_reason") or "").strip()
        message = str(item.get("message") or "").strip()
        timestamp = _normalize_ui_timestamp(item.get("timestamp"))
        source = str(item.get("source") or "").strip()
        title = command or (source if source else "Command run")
        summary = stop_reason or message
        if _action_type_from_command(command) == "auto":
            if auto_goal and auto_goal_satisfied:
                summary = f"{auto_goal} - goal satisfied"
            elif auto_goal and auto_stop_reason:
                summary = f"{auto_goal} - stopped: {auto_stop_reason}"
            elif auto_goal:
                summary = f"{auto_goal} - stopped"
        key = "|".join([timestamp, title, status, summary])
        if key in seen_keys:
            continue
        seen_keys.add(key)
        rows.append(
            {
                "timestamp": timestamp,
                "title": title,
                "status": status,
                "summary": summary,
                "action_type": _action_type_from_command(command),
                "command": command,
                "source": source,
                "stop_reason": stop_reason,
                "verification_status": str(item.get("verification_status") or "").strip().upper(),
                "verification_issues": [str(x) for x in (item.get("verification_issues") or []) if str(x).strip()],
                "drift_summary": str(item.get("drift_summary") or "").strip(),
                "runtime_reflection": str(item.get("runtime_reflection") or "").strip(),
            }
        )

    return rows[:20]


def _normalize_ui_timestamp(value: Any) -> str:
    raw = str(value or "").strip()
    if not raw:
        return ""

    # Keep already-normalized UI format unchanged.
    try:
        normalized = datetime.strptime(raw, "%Y-%m-%d %H:%M:%S")
        return normalized.strftime("%Y-%m-%d %H:%M:%S")
    except ValueError:
        pass

    parsed: datetime | None = None
    try:
        iso_input = raw[:-1] + "+00:00" if raw.endswith("Z") else raw
        parsed = datetime.fromisoformat(iso_input)
    except ValueError:
        parsed = None

    if parsed is None:
        try:
            parsed = datetime.fromtimestamp(float(raw), tz=timezone.utc)
        except (TypeError, ValueError, OverflowError):
            return ""

    if parsed.tzinfo is not None:
        parsed = parsed.astimezone(timezone.utc).replace(tzinfo=None)
    return parsed.strftime("%Y-%m-%d %H:%M:%S")


def _normalize_verification_payload(value: Any) -> dict[str, Any]:
    row = value if isinstance(value, dict) else {}
    status = str(row.get("overall_status") or "").strip().upper()
    if status not in {"VERIFIED", "PARTIAL", "FAILED"}:
        status = ""
    issues = [str(item) for item in (row.get("issues") or []) if str(item).strip()]
    drift_summary = str(row.get("drift_summary") or "").strip()
    runtime_reflection = str(row.get("runtime_reflection") or "").strip()
    return {
        "overall_status": status,
        "issues": issues,
        "drift_summary": drift_summary,
        "runtime_reflection": runtime_reflection,
    }


def _build_verification_overview(recent_runs: list[dict[str, Any]]) -> dict[str, Any]:
    verified = 0
    partial = 0
    failed = 0
    latest_status = ""
    latest_issues: list[str] = []
    latest_runtime_reflection = ""
    latest_drift_summary = ""
    for row in recent_runs:
        status = str(row.get("verification_status") or "").strip().upper()
        if status == "VERIFIED":
            verified += 1
        elif status == "PARTIAL":
            partial += 1
        elif status == "FAILED":
            failed += 1
        if not latest_status and status:
            latest_status = status
            latest_issues = [str(item) for item in (row.get("verification_issues") or []) if str(item).strip()]
            latest_runtime_reflection = str(row.get("runtime_reflection") or "").strip()
            latest_drift_summary = str(row.get("drift_summary") or "").strip()
    return {
        "status_counts": {"verified": verified, "partial": partial, "failed": failed},
        "latest_status": latest_status or ("FAILED" if failed else ("PARTIAL" if partial else ("VERIFIED" if verified else "UNKNOWN"))),
        "latest_issues": latest_issues[:6],
        "runtime_reflection": latest_runtime_reflection,
        "drift_summary": latest_drift_summary,
    }


def _is_within_project(path: Path, project_dir: Path) -> bool:
    try:
        path.resolve().relative_to(project_dir.resolve())
        return True
    except Exception:
        return False


def _tail_log_content(path: Path, *, max_lines: int = _UI_LOG_MAX_LINES, max_chars: int = _UI_LOG_MAX_CHARS) -> tuple[str, bool, int, str]:
    target = path.expanduser().resolve()
    if not target.exists():
        return "", False, 0, ""
    if not target.is_file():
        return "", False, 0, "Log path is not a file"

    line_count = 0
    ring: deque[str] = deque(maxlen=max(1, int(max_lines)))
    try:
        with target.open("r", encoding="utf-8", errors="replace") as handle:
            for raw in handle:
                line_count += 1
                ring.append(raw)
    except Exception as exc:
        return "", False, 0, f"Unable to read log: {exc}"

    content = "".join(ring).strip("\n")
    truncated = line_count > max_lines
    if len(content) > max_chars:
        content = content[-max_chars:]
        truncated = True
    visible_lines = 0 if not content else content.count("\n") + 1
    return content, truncated, visible_lines, ""


def _resolve_log_source(
    project_dir: Path,
    *,
    key: str,
    label: str,
    candidates: list[Path],
    max_lines: int,
) -> dict[str, Any]:
    for candidate in candidates:
        if not _is_within_project(candidate, project_dir):
            continue
        content, truncated, visible_lines, error = _tail_log_content(candidate, max_lines=max_lines)
        if error:
            return {
                "key": key,
                "label": label,
                "path": str(candidate),
                "available": False,
                "content": "",
                "error": error,
                "truncated": False,
                "line_count": 0,
            }
        if content:
            return {
                "key": key,
                "label": label,
                "path": str(candidate),
                "available": True,
                "content": content,
                "error": "",
                "truncated": bool(truncated),
                "line_count": int(visible_lines),
            }
        if candidate.exists():
            return {
                "key": key,
                "label": label,
                "path": str(candidate),
                "available": False,
                "content": "",
                "error": "",
                "truncated": False,
                "line_count": 0,
            }
    return {
        "key": key,
        "label": label,
        "path": "",
        "available": False,
        "content": "",
        "error": "",
        "truncated": False,
        "line_count": 0,
    }


def build_project_logs(project_dir: Path, *, state_payload: dict[str, Any] | None = None) -> dict[str, Any]:
    state = state_payload if isinstance(state_payload, dict) else (load_state(project_dir) or {})
    runtime_block = state.get("runtime") if isinstance(state.get("runtime"), dict) else {}
    services = runtime_block.get("services") if isinstance(runtime_block.get("services"), dict) else {}
    backend_service = services.get("backend") if isinstance(services.get("backend"), dict) else {}
    frontend_service = services.get("frontend") if isinstance(services.get("frontend"), dict) else {}

    def _build_paths(*values: Any) -> list[Path]:
        rows: list[Path] = []
        seen: set[str] = set()
        for value in values:
            raw = str(value or "").strip()
            if not raw:
                continue
            try:
                path = Path(raw).expanduser().resolve()
            except Exception:
                continue
            key = str(path)
            if key in seen:
                continue
            seen.add(key)
            rows.append(path)
        return rows

    backend_candidates = _build_paths(
        backend_service.get("log_path"),
        runtime_block.get("backend_log_path"),
        project_dir / ".archmind" / "backend.log",
    )
    frontend_candidates = _build_paths(
        frontend_service.get("log_path"),
        runtime_block.get("frontend_log_path"),
        project_dir / ".archmind" / "frontend.log",
    )

    backend_source = _resolve_log_source(
        project_dir,
        key="backend",
        label="Backend",
        candidates=backend_candidates,
        max_lines=_UI_LOG_MAX_LINES,
    )
    frontend_source = _resolve_log_source(
        project_dir,
        key="frontend",
        label="Frontend",
        candidates=frontend_candidates,
        max_lines=_UI_LOG_MAX_LINES,
    )

    latest_candidates: list[Path] = []
    logs_dir = (project_dir / ".archmind" / "logs").expanduser().resolve()
    if logs_dir.exists() and logs_dir.is_dir() and _is_within_project(logs_dir, project_dir):
        latest_candidates.extend(
            sorted(
                [p for p in logs_dir.glob("*.log") if p.is_file()],
                key=lambda p: p.stat().st_mtime,
                reverse=True,
            )
        )
    for row in [backend_source.get("path"), frontend_source.get("path"), project_dir / ".archmind" / "backend.log", project_dir / ".archmind" / "frontend.log"]:
        raw = str(row or "").strip()
        if not raw:
            continue
        try:
            path = Path(raw).expanduser().resolve()
        except Exception:
            continue
        if not path.exists() or not path.is_file() or not _is_within_project(path, project_dir):
            continue
        latest_candidates.append(path)
    dedup_latest: list[Path] = []
    seen_latest: set[str] = set()
    for path in latest_candidates:
        key = str(path)
        if key in seen_latest:
            continue
        seen_latest.add(key)
        dedup_latest.append(path)

    latest_source = _resolve_log_source(
        project_dir,
        key="latest",
        label="Latest",
        candidates=dedup_latest,
        max_lines=_UI_LOG_MAX_LINES,
    )

    sources = [backend_source, frontend_source, latest_source]
    default_source = "latest" if bool(latest_source.get("available")) else "backend"
    return {
        "default_source": default_source,
        "max_lines": _UI_LOG_MAX_LINES,
        "sources": sources,
    }


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
        evolution_history=[],
        architecture={
            "app_shape": "unknown",
            "recommended_template": "unknown",
            "reason_summary": "",
            "backend_entry": "",
            "backend_run_mode": "",
        },
        design={},
        plan={},
        flow_execution=load_flow_execution(project_dir),
        logs={"default_source": "latest", "max_lines": _UI_LOG_MAX_LINES, "sources": []},
        auto_summary={},
        verification={},
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
        project_health_status="IDLE",
        is_current=_is_current_project(project_dir),
        warning=str(warning or "").strip(),
    )


def _derive_project_health_status(
    *,
    status: str,
    backend_runtime: dict[str, Any],
    frontend_runtime: dict[str, Any],
    state_payload: dict[str, Any],
    result_payload: dict[str, Any],
) -> str:
    normalized_status = str(status or "").strip().upper()
    backend_status = str(backend_runtime.get("status") or "").strip().upper()
    frontend_status = str(frontend_runtime.get("status") or "").strip().upper()

    if normalized_status == "RUNNING" or backend_status == "RUNNING" or frontend_status == "RUNNING":
        return "RUNNING"

    runtime_block = state_payload.get("runtime") if isinstance(state_payload.get("runtime"), dict) else {}
    deploy_block = state_payload.get("deploy") if isinstance(state_payload.get("deploy"), dict) else {}
    failure_signals = [
        state_payload.get("last_failure_class"),
        state_payload.get("runtime_failure_class"),
        runtime_block.get("failure_class"),
        deploy_block.get("failure_class"),
    ]
    has_failure_signal = any(str(item or "").strip() for item in failure_signals)

    agent_state = str(state_payload.get("agent_state") or "").strip().upper()
    result_status = str(result_payload.get("status") or "").strip().upper()
    not_done_signals = {"NOT_DONE", "BLOCKED", "STUCK"}
    has_not_done_signal = agent_state in not_done_signals or result_status in not_done_signals

    if normalized_status == "FAIL" or (has_failure_signal and has_not_done_signal):
        return "BROKEN"

    if has_not_done_signal or agent_state in {"FIXING", "RETRYING"}:
        return "NEEDS FIX"

    return "IDLE"


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
            status = "EXISTS" if url else "NONE"
        return RepositorySummary(
            status=status or "NONE",
            url=url,
            repo_status=status or "NONE",
            repo_url=url,
            sync_status=str(repository_info.get("sync_status") or "NOT_ATTEMPTED").strip().upper() or "NOT_ATTEMPTED",
            sync_reason=str(repository_info.get("sync_reason") or "").strip(),
            sync_hint=str(repository_info.get("sync_hint") or "").strip(),
            sync_dirty_detail=str(repository_info.get("sync_dirty_detail") or "").strip(),
            sync_remote_url=str(repository_info.get("sync_remote_url") or "").strip(),
            sync_remote_type=str(repository_info.get("sync_remote_type") or "").strip(),
            last_commit_hash=str(repository_info.get("last_commit_hash") or "").strip(),
            working_tree_state=str(repository_info.get("working_tree_state") or "").strip(),
        )
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
        backend_url, frontend_url, backend_urls, frontend_urls = _runtime_urls_for_display(status, runtime_payload, state_payload)
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
            backend_urls=backend_urls,
            frontend_urls=frontend_urls,
            runtime_state=_runtime_state_from_status(status),
            repository=repository,
            project_health_status=_derive_project_health_status(
                status=status,
                backend_runtime=backend_runtime,
                frontend_runtime=frontend_runtime,
                state_payload=state_payload if isinstance(state_payload, dict) else {},
                result_payload=result_payload if isinstance(result_payload, dict) else {},
            ),
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
        live_backend = runtime_payload.get("backend") if isinstance(runtime_payload.get("backend"), dict) else {}
        live_frontend = runtime_payload.get("frontend") if isinstance(runtime_payload.get("frontend"), dict) else {}
        backend_reachability = live_backend.get("reachability") if isinstance(live_backend.get("reachability"), dict) else {}
        frontend_reachability = live_frontend.get("reachability") if isinstance(live_frontend.get("reachability"), dict) else {}
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
        spec_entities_seed = _extract_entity_names(spec if isinstance(spec, dict) else {})
        spec_api_seed = _extract_spec_api_endpoints(spec if isinstance(spec, dict) else {})
        spec_page_seed = _extract_spec_pages(spec if isinstance(spec, dict) else {})
        fallback_reasons: list[str] = []
        if not canonical_entities and spec_entities_seed:
            canonical_entities = spec_entities_seed
            fallback_reasons.append("entities from spec seed")
            analysis["entities"] = canonical_entities
        if not canonical_api_endpoints and spec_api_seed:
            canonical_api_endpoints = spec_api_seed
            fallback_reasons.append("apis from spec seed")
            if not isinstance(analysis.get("apis"), list) or not analysis.get("apis"):
                fallback_api_rows: list[dict[str, str]] = []
                for endpoint in spec_api_seed:
                    method, _, path = str(endpoint).partition(" ")
                    method_text = str(method or "").strip().upper()
                    path_text = str(path or "").strip()
                    if not method_text or not path_text:
                        continue
                    fallback_api_rows.append({"method": method_text, "path": path_text})
                if fallback_api_rows:
                    analysis["apis"] = fallback_api_rows
        if not canonical_pages and spec_page_seed:
            canonical_pages = spec_page_seed
            fallback_reasons.append("pages from spec seed")
            analysis["pages"] = canonical_pages
        canonical_entity_rows = []
        for entity_name in canonical_entities:
            fields = canonical_fields_by_entity.get(entity_name) if isinstance(canonical_fields_by_entity, dict) else []
            canonical_entity_rows.append(
                {
                    "name": entity_name,
                    "fields": fields if isinstance(fields, list) else [],
                }
            )
        consistency_notice = ""
        if fallback_reasons:
            consistency_notice = (
                "Canonical analysis was incomplete while spec seed exists; "
                f"using fallback for {', '.join(fallback_reasons)}."
            )
            analysis["data_consistency_notice"] = consistency_notice
            analysis["data_source"] = "spec_fallback"
        else:
            analysis["data_source"] = "canonical"
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
            verification = _normalize_verification_payload(item.get("verification"))
            recent_runs.append(
                {
                    "timestamp": _normalize_ui_timestamp(item.get("timestamp")),
                    "source": str(item.get("source") or "").strip(),
                    "command": str(item.get("command") or "").strip(),
                    "status": str(item.get("status") or "").strip().lower(),
                    "message": str(item.get("message") or "").strip(),
                    "stop_reason": str(item.get("stop_reason") or "").strip(),
                    "verification_status": str(verification.get("overall_status") or "").strip().upper(),
                    "verification_issues": verification.get("issues") if isinstance(verification.get("issues"), list) else [],
                    "drift_summary": str(verification.get("drift_summary") or "").strip(),
                    "runtime_reflection": str(verification.get("runtime_reflection") or "").strip(),
                }
            )
        auto_summary_raw = state_payload.get("auto_last_result") if isinstance(state_payload.get("auto_last_result"), dict) else {}
        auto_summary = _normalize_auto_summary(auto_summary_raw)
        design_overview = _build_design_overview(
            project_dir,
            state_payload=state_payload if isinstance(state_payload, dict) else {},
            spec_payload=spec if isinstance(spec, dict) else {},
            analysis_payload=analysis if isinstance(analysis, dict) else {},
        )
        recent_evolution = summarize_recent_evolution(spec, limit=5)
        evolution_history = _build_evolution_history(recent_runs, recent_evolution, auto_summary=auto_summary)
        verification_overview = _build_verification_overview(recent_runs)
        plan_overview = _build_plan_overview(
            project_dir,
            analysis_payload=analysis if isinstance(analysis, dict) else {},
            auto_summary=auto_summary,
            spec_payload=spec if isinstance(spec, dict) else {},
            verification_payload=verification_overview if isinstance(verification_overview, dict) else {},
        )
        flow_execution = load_flow_execution(project_dir)
        architecture = {
            "app_shape": str(state_payload.get("architecture_app_shape") or spec.get("shape") or "unknown").strip() or "unknown",
            "recommended_template": (
                str(state_payload.get("architecture_recommended_template") or spec.get("template") or "unknown").strip() or "unknown"
            ),
            "reason_summary": str(state_payload.get("architecture_reason_summary") or "").strip(),
            "backend_entry": str(state_payload.get("backend_entry") or result_payload.get("backend_entry") or "").strip(),
            "backend_run_mode": str(state_payload.get("backend_run_mode") or "").strip(),
        }
        logs = build_project_logs(project_dir, state_payload=state_payload if isinstance(state_payload, dict) else {})
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
                overall_status=_runtime_state_from_status(status),
                backend_status=str(backend_runtime.get("status") or "STOPPED").strip().upper() or "STOPPED",
                frontend_status=str(frontend_runtime.get("status") or "STOPPED").strip().upper() or "STOPPED",
                backend_url=backend_url,
                frontend_url=frontend_url,
                backend_reason=str(backend_runtime.get("reason") or "").strip(),
                frontend_reason=str(frontend_runtime.get("reason") or "").strip(),
                backend_reason_detail=str(backend_runtime.get("reason_detail") or "").strip(),
                frontend_reason_detail=str(frontend_runtime.get("reason_detail") or "").strip(),
                backend_urls=backend_urls,
                frontend_urls=frontend_urls,
                backend_last_known_url=str(backend_runtime.get("last_known_url") or "").strip(),
                frontend_last_known_url=str(frontend_runtime.get("last_known_url") or "").strip(),
                backend_reachability_status=str(backend_reachability.get("status") or "UNREACHABLE").strip().upper() or "UNREACHABLE",
                frontend_reachability_status=str(frontend_reachability.get("status") or "UNREACHABLE").strip().upper() or "UNREACHABLE",
                backend_local_reachable=bool(backend_reachability.get("local_reachable")),
                frontend_local_reachable=bool(frontend_reachability.get("local_reachable")),
                backend_lan_reachable=bool(backend_reachability.get("lan_reachable")),
                frontend_lan_reachable=bool(frontend_reachability.get("lan_reachable")),
                backend_external_reachable=bool(backend_reachability.get("external_reachable")),
                frontend_external_reachable=bool(frontend_reachability.get("external_reachable")),
            ),
            recent_evolution=recent_evolution,
            recent_runs=recent_runs,
            evolution_history=evolution_history,
            architecture=architecture,
            design=design_overview,
            plan=plan_overview,
            flow_execution=flow_execution,
            logs=logs,
            auto_summary=auto_summary,
            verification=verification_overview,
            repository=repository,
            analysis=analysis,
            warning=consistency_notice,
            safe=True,
        )
    except Exception as exc:
        return _empty_project_detail(project_dir, warning=f"Failed to load full project detail: {exc}")


def _resolve_plan_flow_steps(plan_payload: dict[str, Any], flow_name: str) -> list[dict[str, Any]]:
    target_name = str(flow_name or "").strip().lower()
    if not target_name:
        return []
    flows = plan_payload.get("flows") if isinstance(plan_payload.get("flows"), list) else []
    for flow in flows:
        if not isinstance(flow, dict):
            continue
        name = str(flow.get("name") or "").strip()
        if str(name).lower() != target_name:
            continue
        steps_raw = flow.get("steps") if isinstance(flow.get("steps"), list) else []
        steps: list[dict[str, Any]] = []
        for item in steps_raw:
            if not isinstance(item, dict):
                continue
            command = str(item.get("command") or "").strip()
            if not command:
                continue
            steps.append(
                {
                    "id": str(item.get("id") or "").strip(),
                    "title": str(item.get("title") or "").strip() or "Plan step",
                    "command": command,
                    "depends_on": [str(dep).strip() for dep in (item.get("depends_on") or []) if str(dep).strip()],
                    "status": "pending",
                }
            )
        return steps
    return []


def run_project_flow(project_dir: Path, flow_name: str) -> dict[str, Any]:
    target_flow_name = str(flow_name or "").strip()
    if not target_flow_name:
        return {
            "ok": False,
            "started": False,
            "detail": "Flow name is required",
            "error": "flow name is required",
            "flow_execution": load_flow_execution(project_dir),
        }

    state_payload = load_state(project_dir) or {}
    spec, _ = _read_or_init_project_spec(project_dir)
    runtime_payload = get_local_runtime_status(project_dir)
    analysis_payload = analyze_project(
        project_dir,
        project_name=project_dir.name,
        spec_payload=spec if isinstance(spec, dict) else {},
        runtime_payload=runtime_payload if isinstance(runtime_payload, dict) else {},
    )
    recent_runs_raw = load_recent_execution_events(project_dir, limit=10)
    recent_runs: list[dict[str, Any]] = []
    for item in reversed(recent_runs_raw):
        if not isinstance(item, dict):
            continue
        verification = _normalize_verification_payload(item.get("verification"))
        recent_runs.append(
            {
                "timestamp": _normalize_ui_timestamp(item.get("timestamp")),
                "source": str(item.get("source") or "").strip(),
                "command": str(item.get("command") or "").strip(),
                "status": str(item.get("status") or "").strip().lower(),
                "message": str(item.get("message") or "").strip(),
                "stop_reason": str(item.get("stop_reason") or "").strip(),
                "verification_status": str(verification.get("overall_status") or "").strip().upper(),
                "verification_issues": verification.get("issues") if isinstance(verification.get("issues"), list) else [],
                "drift_summary": str(verification.get("drift_summary") or "").strip(),
                "runtime_reflection": str(verification.get("runtime_reflection") or "").strip(),
            }
        )
    auto_summary_raw = state_payload.get("auto_last_result") if isinstance(state_payload.get("auto_last_result"), dict) else {}
    auto_summary = _normalize_auto_summary(auto_summary_raw)
    verification_overview = _build_verification_overview(recent_runs)
    plan_payload = _build_plan_overview(
        project_dir,
        analysis_payload=analysis_payload if isinstance(analysis_payload, dict) else {},
        auto_summary=auto_summary,
        spec_payload=spec if isinstance(spec, dict) else {},
        verification_payload=verification_overview if isinstance(verification_overview, dict) else {},
    )
    steps = _resolve_plan_flow_steps(plan_payload if isinstance(plan_payload, dict) else {}, target_flow_name)
    if not steps:
        return {
            "ok": False,
            "started": False,
            "detail": "Flow not found or flow has no executable steps",
            "error": "flow not found",
            "flow_execution": load_flow_execution(project_dir),
        }

    result = start_flow_execution(
        project_dir,
        project_id=project_dir.name,
        flow_name=target_flow_name,
        steps=steps,
    )
    return {
        "ok": bool(result.get("ok")),
        "started": bool(result.get("started")),
        "detail": str(result.get("detail") or ""),
        "error": str(result.get("error") or ""),
        "flow_execution": result.get("flow_execution") if isinstance(result.get("flow_execution"), dict) else {},
    }


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
    try:
        spec_payload, _ = _read_or_init_project_spec(project_dir)
    except Exception:
        archmind_dir = project_dir / ".archmind"
        spec_payload = _load_json(archmind_dir / "project_spec.json") or {}
    runtime_payload = get_local_runtime_status(project_dir)
    return analyze_project(
        project_dir,
        project_name=project_dir.name,
        spec_payload=spec_payload if isinstance(spec_payload, dict) else {},
        runtime_payload=runtime_payload if isinstance(runtime_payload, dict) else {},
    )
