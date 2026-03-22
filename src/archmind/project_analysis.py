from __future__ import annotations

import re
from pathlib import Path
from typing import Any


def _normalize_entity_name(value: Any) -> str:
    name = str(value or "").strip()
    if not name:
        return ""
    return name[0].upper() + name[1:]


def _entity_slug(entity_name: str) -> str:
    value = str(entity_name or "").strip()
    if not value:
        return ""
    return re.sub(r"(?<!^)(?=[A-Z])", "_", value).lower()


def _entity_resource(entity_name: str) -> str:
    slug = _entity_slug(entity_name)
    if not slug:
        return ""
    if slug.endswith("s"):
        return slug
    return f"{slug}s"


def _normalize_page(value: Any) -> str:
    page = str(value or "").strip().replace("\\", "/")
    page = re.sub(r"/{2,}", "/", page).strip("/")
    if not page or " " in page:
        return ""
    return page.lower()


def _parse_api_endpoint(value: Any) -> tuple[str, str] | None:
    text = str(value or "").strip()
    if not text:
        return None
    parts = text.split(maxsplit=1)
    if len(parts) != 2:
        return None
    method = str(parts[0] or "").strip().upper()
    path = str(parts[1] or "").strip()
    if not method or not path:
        return None
    if not path.startswith("/"):
        path = "/" + path
    return method, path


def _normalize_fields(item: Any) -> list[dict[str, str]]:
    rows = item if isinstance(item, list) else []
    out: list[dict[str, str]] = []
    seen: set[str] = set()
    for raw in rows:
        if not isinstance(raw, dict):
            continue
        field_name = str(raw.get("name") or "").strip()
        field_type = str(raw.get("type") or "").strip().lower()
        if not field_name or not field_type:
            continue
        key = field_name.lower()
        if key in seen:
            continue
        seen.add(key)
        out.append({"name": field_name, "type": field_type})
    return out


def _extract_entities(spec_payload: dict[str, Any]) -> tuple[list[str], dict[str, list[dict[str, str]]]]:
    entities = spec_payload.get("entities") if isinstance(spec_payload.get("entities"), list) else []
    names: list[str] = []
    fields_by_entity: dict[str, list[dict[str, str]]] = {}
    seen: set[str] = set()
    for raw in entities:
        if not isinstance(raw, dict):
            continue
        name = _normalize_entity_name(raw.get("name"))
        if not name:
            continue
        key = name.lower()
        if key in seen:
            continue
        seen.add(key)
        names.append(name)
        fields_by_entity[name] = _normalize_fields(raw.get("fields"))
    return names, fields_by_entity


def _normalize_inferred_field_name(raw_name: str) -> str:
    field = str(raw_name or "").strip()
    if not field:
        return ""
    if field.startswith("_") or field in {"self", "cls"}:
        return ""
    if field.lower() in {"config", "model_config"}:
        return ""
    if re.match(r"^[A-Z]", field):
        return ""
    return field


def _infer_fields_from_python_model(path: Path) -> list[dict[str, str]]:
    try:
        content = path.read_text(encoding="utf-8")
    except Exception:
        return []
    out: list[dict[str, str]] = []
    seen: set[str] = set()
    for raw_line in content.splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        match = re.match(r"^([a-zA-Z_][a-zA-Z0-9_]*)\s*:\s*([^=]+)", line)
        if not match:
            continue
        field_name = _normalize_inferred_field_name(match.group(1))
        if not field_name:
            continue
        key = field_name.lower()
        if key in seen:
            continue
        seen.add(key)
        out.append({"name": field_name, "type": "string"})
    return out


def _candidate_entity_model_files(project_dir: Path, entity_name: str) -> list[Path]:
    slug = _entity_slug(entity_name)
    if not slug:
        return []
    names = [slug, entity_name.lower()]
    roots = [
        project_dir / "backend" / "app" / "models",
        project_dir / "backend" / "app" / "schemas",
        project_dir / "app" / "models",
        project_dir / "app" / "schemas",
    ]
    candidates: list[Path] = []
    for root in roots:
        for name in names:
            candidates.append(root / f"{name}.py")
    return candidates


def _merge_fields_with_code_inference(
    project_dir: Path,
    entities: list[str],
    fields_by_entity: dict[str, list[dict[str, str]]],
) -> dict[str, list[dict[str, str]]]:
    merged: dict[str, list[dict[str, str]]] = {}
    for entity in entities:
        current = list(fields_by_entity.get(entity) or [])
        seen = {str(item.get("name") or "").strip().lower() for item in current if str(item.get("name") or "").strip()}
        for candidate in _candidate_entity_model_files(project_dir, entity):
            if not candidate.exists():
                continue
            for item in _infer_fields_from_python_model(candidate):
                field_name = str(item.get("name") or "").strip()
                if not field_name:
                    continue
                key = field_name.lower()
                if key in seen:
                    continue
                seen.add(key)
                current.append(item)
        merged[entity] = current
    return merged


def _extract_apis(spec_payload: dict[str, Any]) -> list[dict[str, str]]:
    rows = spec_payload.get("api_endpoints") if isinstance(spec_payload.get("api_endpoints"), list) else []
    out: list[dict[str, str]] = []
    seen: set[str] = set()
    for raw in rows:
        parsed = _parse_api_endpoint(raw)
        if parsed is None:
            continue
        method, path = parsed
        key = f"{method} {path}"
        if key in seen:
            continue
        seen.add(key)
        out.append({"method": method, "path": path})
    return out


def _extract_pages(spec_payload: dict[str, Any]) -> list[str]:
    rows = spec_payload.get("frontend_pages") if isinstance(spec_payload.get("frontend_pages"), list) else []
    out: list[str] = []
    seen: set[str] = set()
    for raw in rows:
        page = _normalize_page(raw)
        if not page or page in seen:
            continue
        seen.add(page)
        out.append(page)
    return out


def _is_detail_path(path: str) -> bool:
    return bool(re.search(r"/\{[^}]+\}$", path))


def _compute_entity_crud_status(
    entities: list[str],
    fields_by_entity: dict[str, list[dict[str, str]]],
    apis: list[dict[str, str]],
    pages: list[str],
) -> dict[str, dict[str, Any]]:
    by_method_path = {(str(item.get("method") or ""), str(item.get("path") or "")) for item in apis}
    page_set = {str(page) for page in pages}
    status: dict[str, dict[str, Any]] = {}

    for entity in entities:
        resource = _entity_resource(entity)
        base = f"/{resource}" if resource else ""
        has_list = ("GET", base) in by_method_path if base else False
        has_create = ("POST", base) in by_method_path if base else False
        has_detail = any(method == "GET" and path.startswith(f"{base}/") for method, path in by_method_path) if base else False
        has_update = any(
            method in {"PUT", "PATCH"} and path.startswith(f"{base}/")
            for method, path in by_method_path
        ) if base else False
        has_delete = any(method == "DELETE" and path.startswith(f"{base}/") for method, path in by_method_path) if base else False

        page_list = f"{resource}/list" in page_set if resource else False
        page_detail = f"{resource}/detail" in page_set if resource else False

        missing_api: list[str] = []
        if not has_list:
            missing_api.append("GET list")
        if not has_create:
            missing_api.append("POST create")
        if not has_detail:
            missing_api.append("GET detail")
        if not has_update:
            missing_api.append("PUT/PATCH update")
        if not has_delete:
            missing_api.append("DELETE")

        missing_pages: list[str] = []
        if not page_list:
            missing_pages.append("list")
        if not page_detail:
            missing_pages.append("detail")

        field_names = {str(item.get("name") or "").strip().lower() for item in (fields_by_entity.get(entity) or [])}
        missing_important_fields: list[str] = []
        if not ({"title", "name"} & field_names):
            missing_important_fields.append("title")
        if "created_at" not in field_names:
            missing_important_fields.append("created_at")

        status[entity] = {
            "resource": resource,
            "api": {
                "list": has_list,
                "create": has_create,
                "detail": has_detail,
                "update": has_update,
                "delete": has_delete,
            },
            "pages": {
                "list": page_list,
                "detail": page_detail,
            },
            "missing_api": missing_api,
            "missing_pages": missing_pages,
            "missing_important_fields": missing_important_fields,
        }
    return status


def _candidate_page_files(project_dir: Path, page: str) -> list[Path]:
    app_root = project_dir / "frontend" / "app"
    if not app_root.exists():
        return []
    page = _normalize_page(page)
    if not page:
        return []
    candidates = [app_root / page / "page.tsx"]
    parts = page.split("/")
    if len(parts) == 2 and parts[1] == "list":
        candidates.append(app_root / parts[0] / "page.tsx")
    if len(parts) == 2 and parts[1] == "detail":
        candidates.append(app_root / parts[0] / "[id]" / "page.tsx")
        candidates.append(app_root / parts[0] / "detail" / "page.tsx")
    return candidates


def _is_placeholder_text(content: str) -> bool:
    text = str(content or "").lower()
    return "placeholder" in text or "todo" in text or "coming soon" in text or "tbd" in text


def _usability_signal_score(content: str) -> int:
    text = str(content or "")
    lowered = text.lower()
    score = 0
    if any(token in text for token in ("fetch(", "await fetch", "axios.", "useEffect(")):
        score += 1
    if any(token in text for token in (".map(", "<li", "<table", "items.map(")):
        score += 1
    if any(token in lowered for token in ("onsubmit", "<form", "textarea", "input", "handlesubmit")):
        score += 1
    if any(token in lowered for token in ("delete", "update", "edit", "create", "router.refresh", "router.push")):
        score += 1
    return score


def _detect_placeholder_pages(project_dir: Path, pages: list[str]) -> list[str]:
    out: list[str] = []
    for page in pages:
        for candidate in _candidate_page_files(project_dir, page):
            if not candidate.exists():
                continue
            try:
                content = candidate.read_text(encoding="utf-8")
            except Exception:
                break
            placeholder_token = _is_placeholder_text(content)
            signal_score = _usability_signal_score(content)
            # A placeholder token alone is not enough when the page already has usable flow signals.
            is_placeholder = placeholder_token and signal_score < 2
            if is_placeholder:
                out.append(page)
            break
    seen: set[str] = set()
    deduped: list[str] = []
    for item in out:
        if item in seen:
            continue
        seen.add(item)
        deduped.append(item)
    return deduped


def _extract_nav_visible_pages(project_dir: Path, pages: list[str]) -> list[str]:
    nav_file = project_dir / "frontend" / "app" / "_lib" / "navigation.ts"
    if nav_file.exists():
        try:
            source = nav_file.read_text(encoding="utf-8")
        except Exception:
            source = ""
        hrefs = re.findall(r"href\s*:\s*['\"]([^'\"]+)['\"]", source)
        out: list[str] = []
        seen: set[str] = set()
        for href in hrefs:
            value = _normalize_page(href)
            if not value:
                continue
            if value in seen:
                continue
            seen.add(value)
            out.append(value)
        return out

    # Fallback to list-like pages from spec when nav manifest is absent.
    out: list[str] = []
    for page in pages:
        if page.endswith("/list"):
            out.append(page)
    return out


def _normalize_runtime_status(runtime_payload: dict[str, Any] | None) -> dict[str, Any]:
    runtime = runtime_payload if isinstance(runtime_payload, dict) else {}
    backend = runtime.get("backend") if isinstance(runtime.get("backend"), dict) else {}
    frontend = runtime.get("frontend") if isinstance(runtime.get("frontend"), dict) else {}
    return {
        "backend_status": str(backend.get("status") or "STOPPED").strip().upper() or "STOPPED",
        "frontend_status": str(frontend.get("status") or "STOPPED").strip().upper() or "STOPPED",
        "backend_url": str(backend.get("url") or "").strip(),
        "frontend_url": str(frontend.get("url") or "").strip(),
        "backend_urls": [str(backend.get("url") or "").strip()] if str(backend.get("url") or "").strip() else [],
        "frontend_urls": [str(frontend.get("url") or "").strip()] if str(frontend.get("url") or "").strip() else [],
    }


def _build_suggestions(
    entities: list[str],
    entity_crud_status: dict[str, dict[str, Any]],
    placeholder_pages: list[str],
) -> tuple[list[dict[str, str]], dict[str, str]]:
    suggestions: list[dict[str, str]] = []
    added_field_suggestion = False

    def add(kind: str, message: str, command: str = "") -> None:
        if len(suggestions) >= 3:
            return
        suggestions.append({"kind": kind, "message": message, "command": command})

    # Priority 1: placeholder pages
    if placeholder_pages:
        target = placeholder_pages[0]
        add(
            "placeholder_page",
            f"Page {target} is still placeholder-level. Implement a usable UI flow.",
            f"/add_page {target}",
        )

    # Priority 2/3/4 per entity
    for entity in entities:
        info = entity_crud_status.get(entity) if isinstance(entity_crud_status.get(entity), dict) else {}
        resource = str(info.get("resource") or "")
        missing_api = info.get("missing_api") if isinstance(info.get("missing_api"), list) else []
        missing_pages = info.get("missing_pages") if isinstance(info.get("missing_pages"), list) else []
        missing_fields = info.get("missing_important_fields") if isinstance(info.get("missing_important_fields"), list) else []

        if missing_api and len(suggestions) < 3:
            if "GET list" in missing_api:
                add(
                    "missing_crud_api",
                    f"{entity} is missing list API coverage.",
                    f"/add_api GET /{resource}",
                )
            elif "POST create" in missing_api:
                add(
                    "missing_crud_api",
                    f"{entity} is missing create API coverage.",
                    f"/add_api POST /{resource}",
                )
            else:
                add(
                    "missing_crud_api",
                    f"{entity} has incomplete CRUD API coverage.",
                    "",
                )

        if missing_pages and len(suggestions) < 3:
            page_kind = str(missing_pages[0])
            add(
                "missing_page",
                f"{entity} is missing {page_kind} page coverage.",
                f"/add_page {resource}/{page_kind}",
            )

        if missing_fields and len(suggestions) < 3 and not added_field_suggestion:
            field_name = str(missing_fields[0])
            add(
                "missing_field",
                f"{entity} is missing an important field: {field_name}",
                f"/add_field {entity} {field_name}:string",
            )
            added_field_suggestion = True

    if not suggestions:
        suggestions.append(
            {
                "kind": "none",
                "message": "No immediate suggestions.",
                "command": "",
            }
        )

    next_action = suggestions[0]
    return suggestions[:3], {"kind": str(next_action.get("kind") or "none"), "message": str(next_action.get("message") or ""), "command": str(next_action.get("command") or "")}


def analyze_project(
    project_dir: Path,
    *,
    project_name: str | None = None,
    spec_payload: dict[str, Any] | None = None,
    runtime_payload: dict[str, Any] | None = None,
) -> dict[str, Any]:
    spec = spec_payload if isinstance(spec_payload, dict) else {}
    entities, fields_by_entity = _extract_entities(spec)
    apis = _extract_apis(spec)
    pages = _extract_pages(spec)
    fields_by_entity = _merge_fields_with_code_inference(project_dir, entities, fields_by_entity)
    entity_crud_status = _compute_entity_crud_status(entities, fields_by_entity, apis, pages)
    placeholder_pages = _detect_placeholder_pages(project_dir, pages)
    nav_visible_pages = _extract_nav_visible_pages(project_dir, pages)
    runtime_status = _normalize_runtime_status(runtime_payload if isinstance(runtime_payload, dict) else {})
    suggestions, next_action = _build_suggestions(entities, entity_crud_status, placeholder_pages)

    return {
        "project_name": str(project_name or project_dir.name),
        "entities": entities,
        "fields_by_entity": fields_by_entity,
        "apis": apis,
        "pages": pages,
        "entity_crud_status": entity_crud_status,
        "placeholder_pages": placeholder_pages,
        "nav_visible_pages": nav_visible_pages,
        "runtime_status": runtime_status,
        "suggestions": suggestions,
        "next_action": next_action,
    }
