from __future__ import annotations

import re
from pathlib import Path
from typing import Any

LOW_PRIORITY_MISSING_FIELDS = {"created_at", "updated_at"}


def _normalize_entity_name(value: Any) -> str:
    name = str(value or "").strip()
    if not name:
        return ""
    return name[0].upper() + name[1:]


def _pluralize_resource_name(value: str) -> str:
    raw = str(value or "").strip().lower()
    if not raw:
        return ""
    if raw.endswith(("s", "x", "z", "ch", "sh")):
        return raw if raw.endswith("s") else f"{raw}es"
    if raw.endswith("y") and len(raw) > 1 and raw[-2] not in "aeiou":
        return f"{raw[:-1]}ies"
    return f"{raw}s"


def _canonical_resource_segment(value: str) -> str:
    normalized = re.sub(r"[^a-z0-9_]+", "_", str(value or "").strip().lower()).strip("_")
    if not normalized:
        return ""
    return _pluralize_resource_name(normalized)


def _entity_slug(entity_name: str) -> str:
    value = str(entity_name or "").strip()
    if not value:
        return ""
    return re.sub(r"(?<!^)(?=[A-Z])", "_", value).lower()


def _entity_resource(entity_name: str) -> str:
    slug = _entity_slug(entity_name)
    if not slug:
        return ""
    return _pluralize_resource_name(slug)


def _canonicalize_page_path(value: Any) -> str:
    page = str(value or "").strip().replace("\\", "/")
    page = re.sub(r"/{2,}", "/", page).strip("/")
    if not page or " " in page:
        return ""
    parts = [p for p in page.lower().split("/") if p]
    if not parts:
        return ""
    resource = _canonical_resource_segment(parts[0])
    if not resource:
        return ""
    if len(parts) == 1:
        return f"{resource}/list"
    action_map = {
        "list": "list",
        "lists": "list",
        "index": "list",
        "home": "list",
        "detail": "detail",
        "details": "detail",
        "view": "detail",
        "show": "detail",
    }
    action = action_map.get(parts[1], parts[1])
    return f"{resource}/{action}"


def _normalize_page(value: Any) -> str:
    return _canonicalize_page_path(value)


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
    path = _canonicalize_api_path(path)
    return method, path


def _canonicalize_api_path(value: str) -> str:
    raw = str(value or "").strip().replace("\\", "/")
    if not raw:
        return ""
    if not raw.startswith("/"):
        raw = "/" + raw
    parts = [p for p in raw.split("/") if p]
    if not parts:
        return ""
    canonical_parts: list[str] = []
    for idx, part in enumerate(parts):
        token = str(part).strip()
        if not token:
            continue
        if token.startswith("{") and token.endswith("}"):
            canonical_parts.append(token)
            continue
        normalized = re.sub(r"[^a-z0-9_]+", "_", token.lower()).strip("_")
        if not normalized:
            continue
        if idx == 0:
            normalized = _pluralize_resource_name(normalized)
        canonical_parts.append(normalized)
    if not canonical_parts:
        return ""
    return "/" + "/".join(canonical_parts)


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


def _normalize_class_entity_name(raw_name: str) -> str:
    value = str(raw_name or "").strip()
    if not value:
        return ""
    # Common generated class suffixes
    for suffix in ("Model", "Schema", "Base", "Create", "Update", "Read", "Response", "Request", "InDB"):
        if value.endswith(suffix) and len(value) > len(suffix):
            value = value[: -len(suffix)]
            break
    return _normalize_entity_name(value)


def _infer_fields_by_entity_from_python_model(path: Path) -> dict[str, list[dict[str, str]]]:
    try:
        content = path.read_text(encoding="utf-8")
    except Exception:
        return {}
    out: dict[str, list[dict[str, str]]] = {}
    seen_by_entity: dict[str, set[str]] = {}
    current_entity = ""
    current_indent = -1
    for raw_line in content.splitlines():
        if not raw_line.strip():
            continue
        stripped = raw_line.strip()
        if stripped.startswith("#"):
            continue
        indent = len(raw_line) - len(raw_line.lstrip(" "))
        class_match = re.match(r"^\s*class\s+([A-Za-z_][A-Za-z0-9_]*)\b", raw_line)
        if class_match:
            current_entity = _normalize_class_entity_name(class_match.group(1))
            current_indent = indent
            if current_entity and current_entity not in out:
                out[current_entity] = []
                seen_by_entity[current_entity] = set()
            continue
        if current_entity and indent <= current_indent and not raw_line.lstrip(" ").startswith("@"):
            current_entity = ""
            current_indent = -1
            continue
        if not current_entity:
            continue
        field_match = re.match(r"^\s*([a-zA-Z_][a-zA-Z0-9_]*)\s*:\s*([^=\n#]+)", raw_line)
        if not field_match:
            continue
        field_name = _normalize_inferred_field_name(field_match.group(1))
        if not field_name:
            continue
        key = field_name.lower()
        seen = seen_by_entity.setdefault(current_entity, set())
        if key in seen:
            continue
        seen.add(key)
        out.setdefault(current_entity, []).append({"name": field_name, "type": "string"})
    return out


def _backend_model_roots(project_dir: Path) -> list[Path]:
    return [
        project_dir / "backend" / "app" / "models",
        project_dir / "backend" / "app" / "schemas",
        project_dir / "app" / "models",
        project_dir / "app" / "schemas",
    ]


def _extract_backend_fields_by_entity(project_dir: Path) -> dict[str, list[dict[str, str]]]:
    out: dict[str, list[dict[str, str]]] = {}
    seen: dict[str, set[str]] = {}
    for root in _backend_model_roots(project_dir):
        if not root.exists():
            continue
        for path in root.glob("*.py"):
            inferred = _infer_fields_by_entity_from_python_model(path)
            for entity, rows in inferred.items():
                bucket = out.setdefault(entity, [])
                seen_bucket = seen.setdefault(entity, set())
                for item in rows:
                    field_name = str(item.get("name") or "").strip()
                    if not field_name:
                        continue
                    key = field_name.lower()
                    if key in seen_bucket:
                        continue
                    seen_bucket.add(key)
                    bucket.append(item)
    return out


def _resolve_fields_by_source(
    project_dir: Path,
    entities: list[str],
    spec_fields_by_entity: dict[str, list[dict[str, str]]],
) -> tuple[dict[str, list[dict[str, str]]], dict[str, bool]]:
    backend_fields_by_entity = _extract_backend_fields_by_entity(project_dir)
    merged: dict[str, list[dict[str, str]]] = {}
    backend_presence: dict[str, bool] = {}
    for entity in entities:
        backend_rows = list(backend_fields_by_entity.get(entity) or [])
        if backend_rows:
            merged[entity] = backend_rows
            backend_presence[entity] = True
            continue
        merged[entity] = list(spec_fields_by_entity.get(entity) or [])
        backend_presence[entity] = False
    return merged, backend_presence


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
    backend_field_presence: dict[str, bool],
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
        has_backend_fields = bool(backend_field_presence.get(entity))
        missing_title = not ({"title", "name"} & field_names)
        # For memo/note projects, avoid title false-positives unless backend classes clearly miss it.
        if _normalize_entity_name(entity) == "Note":
            if missing_title and has_backend_fields:
                missing_important_fields.append("title")
        elif missing_title:
            missing_important_fields.append("title")

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

        filtered_missing_fields = [
            str(field).strip().lower()
            for field in missing_fields
            if str(field).strip().lower() not in LOW_PRIORITY_MISSING_FIELDS
        ]
        if filtered_missing_fields and len(suggestions) < 3 and not added_field_suggestion:
            field_name = str(filtered_missing_fields[0])
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


def _canonicalize_suggestion_command(command: str) -> str:
    text = str(command or "").strip()
    if not text:
        return ""
    if not text.startswith("/"):
        return ""
    parts = text.split()
    if len(parts) < 2:
        return ""
    cmd = parts[0]
    if cmd == "/add_page":
        page = _canonicalize_page_path(parts[1])
        return f"/add_page {page}" if page else ""
    if cmd == "/add_api" and len(parts) >= 3:
        method = str(parts[1] or "").strip().upper()
        if method not in {"GET", "POST", "PUT", "PATCH", "DELETE"}:
            return ""
        path = _canonicalize_api_path(parts[2])
        return f"/add_api {method} {path}" if path else ""
    if cmd == "/add_entity":
        entity = _normalize_entity_name(parts[1])
        return f"/add_entity {entity}" if entity else ""
    if cmd == "/add_field" and len(parts) >= 3:
        entity = _normalize_entity_name(parts[1])
        field_expr = str(parts[2] or "").strip()
        if ":" in field_expr:
            field_name, field_type = field_expr.split(":", 1)
        else:
            field_name, field_type = field_expr, "string"
        field_name = re.sub(r"[^a-zA-Z0-9_]+", "_", field_name.strip()).strip("_")
        field_type = re.sub(r"[^a-zA-Z0-9_]+", "", field_type.strip().lower())
        if not entity or not field_name or not field_type:
            return ""
        return f"/add_field {entity} {field_name}:{field_type}"
    return text


def canonicalize_analysis_suggestions(rows: list[dict[str, Any]]) -> list[dict[str, str]]:
    out: list[dict[str, str]] = []
    seen: set[tuple[str, str, str]] = set()
    for raw in rows:
        if not isinstance(raw, dict):
            continue
        kind = str(raw.get("kind") or "").strip() or "info"
        message = str(raw.get("message") or "").strip()
        command_raw = str(raw.get("command") or "").strip()
        command = _canonicalize_suggestion_command(command_raw)
        if command_raw and not command:
            continue
        if command.startswith("/add_page "):
            page = command.split(maxsplit=1)[1]
            message = re.sub(
                r"^Page\s+\S+\s+is still placeholder-level\.",
                f"Page {page} is still placeholder-level.",
                message,
                flags=re.IGNORECASE,
            )
        key = (kind, message, command)
        if key in seen:
            continue
        seen.add(key)
        out.append({"kind": kind, "message": message, "command": command})
        if len(out) >= 3:
            break
    if not out:
        return [{"kind": "none", "message": "No immediate suggestions.", "command": ""}]
    return out


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
    fields_by_entity, backend_field_presence = _resolve_fields_by_source(project_dir, entities, fields_by_entity)
    entity_crud_status = _compute_entity_crud_status(entities, fields_by_entity, backend_field_presence, apis, pages)
    placeholder_pages = _detect_placeholder_pages(project_dir, pages)
    nav_visible_pages = _extract_nav_visible_pages(project_dir, pages)
    runtime_status = _normalize_runtime_status(runtime_payload if isinstance(runtime_payload, dict) else {})
    suggestions, next_action = _build_suggestions(entities, entity_crud_status, placeholder_pages)

    # Step 1: backend safety filter (remove false "missing title")
    filtered: list[dict[str, str]] = []
    for row in suggestions:
        if not isinstance(row, dict):
            continue

        kind = str(row.get("kind") or "")
        message = str(row.get("message") or "")
        command = str(row.get("command") or "")

        if kind == "missing_field" and "important field: title" in message:
            matched_entity = ""
            for entity in entities:
                if message.startswith(f"{entity} is missing"):
                    matched_entity = entity
                    break

            names = {
                str(item.get("name") or "").strip().lower()
                for item in (fields_by_entity.get(matched_entity) or [])
            }

            if {"title", "name"} & names:
                continue

        filtered.append({
            "kind": kind,
            "message": message,
            "command": command,
        })

    if filtered:
        suggestions = filtered[:3]

    # Step 2: canonical normalization (main branch logic)
    suggestions = canonicalize_analysis_suggestions(suggestions)

    # Step 3: next_action 결정
    next_action = suggestions[0] if suggestions else {
        "kind": "none",
        "message": "No immediate suggestions.",
        "command": "",
    }

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
