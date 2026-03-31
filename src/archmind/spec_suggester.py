from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from .reasoning import try_generate_reasoning_json


DOMAIN_ENTITY_MAP: dict[str, str] = {
    "tasks": "Task",
    "defects": "Defect",
    "teams": "Team",
    "documents": "Document",
    "expenses": "Expense",
    "inventory": "Item",
    "notes": "Note",
    "bookmarks": "Bookmark",
    "recipes": "Recipe",
    "boards": "Board",
    "entries": "Entry",
    "diary": "Entry",
    "journal": "Entry",
    "journals": "Entry",
    "journaling": "Entry",
}

ENTITY_FIELD_MAP: dict[str, list[dict[str, str]]] = {
    "Task": [{"name": "title", "type": "string"}, {"name": "status", "type": "string"}],
    "Defect": [{"name": "title", "type": "string"}, {"name": "status", "type": "string"}],
    "Device": [{"name": "model_name", "type": "string"}, {"name": "firmware_version", "type": "string"}],
    "TestRun": [{"name": "result", "type": "string"}, {"name": "executed_at", "type": "datetime"}],
    "Team": [{"name": "name", "type": "string"}],
    "Project": [{"name": "name", "type": "string"}],
    "Document": [{"name": "title", "type": "string"}],
    "Expense": [{"name": "amount", "type": "float"}, {"name": "category", "type": "string"}],
    "Item": [{"name": "name", "type": "string"}, {"name": "quantity", "type": "int"}],
    "Note": [{"name": "title", "type": "string"}, {"name": "content", "type": "string"}],
    "Entry": [
        {"name": "title", "type": "string"},
        {"name": "content", "type": "string"},
        {"name": "created_at", "type": "datetime"},
    ],
    "Bookmark": [{"name": "title", "type": "string"}, {"name": "url", "type": "string"}],
    "Recipe": [{"name": "title", "type": "string"}, {"name": "instructions", "type": "string"}],
    "Board": [{"name": "title", "type": "string"}, {"name": "description", "type": "string"}],
    "Card": [
        {"name": "title", "type": "string"},
        {"name": "description", "type": "string"},
        {"name": "board_id", "type": "string"},
        {"name": "status", "type": "string"},
    ],
    "Tag": [{"name": "name", "type": "string"}, {"name": "entry_id", "type": "int"}],
    "Category": [{"name": "name", "type": "string"}],
    "User": [{"name": "name", "type": "string"}, {"name": "email", "type": "string"}],
}

DIARY_SIGNAL_WORDS = ("diary", "journal", "journaling")
TAGGING_SIGNAL_WORDS = ("tag", "tags", "tagging", "label", "labels", "category", "categories")


def _add_entity_once(out: list[str], seen: set[str], entity_name: str) -> None:
    key = str(entity_name or "").strip()
    if not key or key in seen:
        return
    seen.add(key)
    out.append(key)


def _entity_slug_and_plural(entity_name: str) -> tuple[str, str]:
    value = str(entity_name or "").strip()
    if not value:
        return "", ""
    slug = re.sub(r"(?<!^)(?=[A-Z])", "_", value).lower()
    if slug.endswith("y") and len(slug) > 1 and slug[-2] not in "aeiou":
        return slug, f"{slug[:-1]}ies"
    if slug.endswith(("s", "x", "z", "ch", "sh")):
        return slug, f"{slug}es"
    return slug, f"{slug}s"


def _pluralize_slug(slug: str) -> str:
    value = str(slug or "").strip().lower().strip("/")
    if not value:
        return ""
    if value.endswith("y") and len(value) > 1 and value[-2] not in "aeiou":
        return f"{value[:-1]}ies"
    if value.endswith(("s", "x", "z", "ch", "sh")):
        return f"{value}es"
    return f"{value}s"


def _resource_segment_from_text(value: str) -> str:
    token = re.sub(r"[^a-z0-9_]", "", str(value or "").strip().lower().replace("-", "_"))
    if not token:
        return ""
    if "_" in token:
        token = token.split("_")[-1]
    if token.endswith("ies"):
        return token
    if token.endswith(("ses", "xes", "zes", "ches", "shes")):
        return token
    if token.endswith("s") and len(token) > 2:
        return token
    return _pluralize_slug(token)


def _normalize_api_endpoint(value: str) -> str:
    text = str(value or "").strip()
    match = re.match(r"^([A-Za-z]+)\s+(.+)$", text)
    if not match:
        return ""
    method = match.group(1).upper()
    path = match.group(2).strip()
    if not path:
        return ""
    if not path.startswith("/"):
        path = f"/{path}"
    segments = [seg for seg in path.split("/") if seg]
    if segments:
        head = segments[0]
        if not head.startswith("{") and not head.startswith("["):
            segments[0] = _resource_segment_from_text(head)
    normalized_path = "/" + "/".join(segments)
    return f"{method} {normalized_path}"


def _normalize_frontend_page(value: str) -> str:
    raw = str(value or "").strip().replace("\\", "/").strip("/")
    if not raw:
        return ""
    parts = [part for part in raw.split("/") if part]
    if not parts:
        return ""
    resource = _resource_segment_from_text(parts[0])
    if not resource:
        return ""
    if len(parts) == 1:
        return f"{resource}/list"
    action = str(parts[1]).strip().lower()
    if action in {"index", "home"}:
        action = "list"
    elif action in {"create"}:
        action = "new"
    elif action in {"view", "show", "item"}:
        action = "detail"
    elif action not in {"list", "new", "detail"}:
        return f"{resource}/{action}"
    return f"{resource}/{action}"


def _has_auth_signal(text: str, reasoning: dict[str, Any]) -> bool:
    if bool(reasoning.get("auth_needed")):
        return True
    modules = [str(x).strip().lower() for x in (reasoning.get("modules") or []) if str(x).strip()]
    if "auth" in modules:
        return True
    return any(
        token in text
        for token in (
            "login",
            "auth",
            "oauth",
            "signup",
            "sign up",
            "sign-in",
            "sign in",
            "account",
            "password",
            "session",
            "multi-user",
            "multi user",
            "member login",
            "rbac",
        )
    )


def _is_auth_entity(name: str) -> bool:
    key = str(name or "").strip().lower()
    return key in {"user", "account", "profile", "member", "session"}


def _is_auth_api(endpoint: str) -> bool:
    lower = str(endpoint or "").strip().lower()
    return any(token in lower for token in ("/users", "/auth", "/login", "/accounts", "/profiles", "/sessions"))


def _is_auth_page(page: str) -> bool:
    lower = str(page or "").strip().lower()
    return lower.startswith("users/") or lower.startswith("profiles/") or lower.startswith("auth/")


def _has_word(text: str, word: str) -> bool:
    return bool(re.search(rf"\b{re.escape(str(word or '').strip().lower())}\b", str(text or "").strip().lower()))


def _has_any_word(text: str, words: tuple[str, ...]) -> bool:
    return any(_has_word(text, token) for token in words)


def _build_crud_endpoints(resource_plural: str, *, full: bool) -> list[str]:
    resource = str(resource_plural or "").strip().lower().strip("/")
    if not resource:
        return []
    if full:
        return [
            f"GET /{resource}",
            f"POST /{resource}",
            f"GET /{resource}/{{id}}",
            f"PATCH /{resource}/{{id}}",
            f"DELETE /{resource}/{{id}}",
        ]
    return [
        f"GET /{resource}",
        f"POST /{resource}",
        f"GET /{resource}/{{id}}",
    ]


def _build_core_pages(resource_plural: str) -> list[str]:
    resource = str(resource_plural or "").strip().lower().strip("/")
    if not resource:
        return []
    return [f"{resource}/list", f"{resource}/new", f"{resource}/detail"]


def _build_starter_profile(text: str, domains: list[str], frontend_needed: bool) -> dict[str, Any]:
    normalized = str(text or "").strip().lower()
    domain_set = {str(item).strip().lower() for item in domains if str(item).strip()}
    has_board = any(_has_word(normalized, token) for token in ("board", "boards", "kanban")) or "boards" in domain_set
    has_task = any(_has_word(normalized, token) for token in ("todo", "todos", "task", "tasks")) or "tasks" in domain_set
    has_memo = any(_has_word(normalized, token) for token in ("memo", "memos", "note", "notes")) or "notes" in domain_set
    has_diary_signal = _has_any_word(normalized, DIARY_SIGNAL_WORDS) or any(
        token in domain_set for token in ("diary", "journal", "journals", "journaling", "entries")
    )
    has_tagging_signal = _has_any_word(normalized, TAGGING_SIGNAL_WORDS)

    if has_board:
        entities = ["Board", "Card"]
        entity_fields = {
            "Board": [
                {"name": "title", "type": "string"},
                {"name": "description", "type": "string"},
            ],
            "Card": [
                {"name": "title", "type": "string"},
                {"name": "description", "type": "string"},
                {"name": "board_id", "type": "string"},
                {"name": "status", "type": "string"},
            ],
        }
        if any(_has_word(normalized, token) for token in ("due", "deadline", "schedule", "date")):
            entity_fields["Card"].append({"name": "due_date", "type": "datetime"})
        if any(_has_word(normalized, token) for token in ("assignee", "owner", "member")):
            entity_fields["Card"].append({"name": "assignee", "type": "string"})
        api_endpoints = _build_crud_endpoints("boards", full=True) + _build_crud_endpoints("cards", full=True)
        api_endpoints.append("GET /boards/{id}/cards")
        pages = (_build_core_pages("boards") + _build_core_pages("cards")) if frontend_needed else []
        if frontend_needed:
            pages.append("cards/by_board")
        return {
            "family": "board_kanban",
            "entities": entities,
            "entity_fields": entity_fields,
            "required_api_endpoints": api_endpoints,
            "required_frontend_pages": pages,
        }

    if has_diary_signal:
        diary_entities = ["Entry"]
        diary_fields: dict[str, list[dict[str, str]]] = {
            "Entry": [
                {"name": "title", "type": "string"},
                {"name": "content", "type": "string"},
                {"name": "created_at", "type": "datetime"},
            ]
        }
        diary_apis = _build_crud_endpoints("entries", full=True)
        diary_pages = _build_core_pages("entries") if frontend_needed else []

        if has_tagging_signal:
            diary_entities.append("Tag")
            diary_fields["Tag"] = [
                {"name": "name", "type": "string"},
                {"name": "entry_id", "type": "int"},
            ]
            diary_apis.extend(_build_crud_endpoints("tags", full=True))
            diary_apis.append("GET /entries/{id}/tags")
            if frontend_needed:
                diary_pages.extend(_build_core_pages("tags"))
                diary_pages.append("tags/by_entry")

        return {
            "family": "diary_entries_v2",
            "entities": diary_entities,
            "entity_fields": diary_fields,
            "required_api_endpoints": diary_apis,
            "required_frontend_pages": diary_pages,
        }

    if has_task:
        task_fields = [
            {"name": "title", "type": "string"},
            {"name": "status", "type": "string"},
        ]
        if any(_has_word(normalized, token) for token in ("description", "details", "notes")):
            task_fields.append({"name": "description", "type": "string"})
        if any(_has_word(normalized, token) for token in ("due", "deadline", "schedule", "date")):
            task_fields.append({"name": "due_date", "type": "datetime"})
        return {
            "family": "todo_tasks",
            "entities": ["Task"],
            "entity_fields": {"Task": task_fields[:6]},
            "required_api_endpoints": _build_crud_endpoints("tasks", full=True),
            "required_frontend_pages": _build_core_pages("tasks") if frontend_needed else [],
        }

    if has_memo and not has_diary_signal:
        note_fields = [
            {"name": "title", "type": "string"},
            {"name": "content", "type": "string"},
        ]
        if any(_has_word(normalized, token) for token in ("tag", "tags", "label", "labels", "keyword", "keywords")):
            note_fields.append({"name": "tags", "type": "string"})
        if any(_has_word(normalized, token) for token in ("category", "categories", "folder", "folders")):
            note_fields.append({"name": "category", "type": "string"})
        return {
            "family": "memo_notes",
            "entities": ["Note"],
            "entity_fields": {"Note": note_fields[:6]},
            "required_api_endpoints": _build_crud_endpoints("notes", full=True),
            "required_frontend_pages": _build_core_pages("notes") if frontend_needed else [],
        }

    return {}


def _enforce_starter_profile(out: dict[str, Any], starter_profile: dict[str, Any], *, frontend_needed: bool) -> None:
    if not isinstance(starter_profile, dict) or not starter_profile:
        return

    required_entities = [str(x).strip() for x in (starter_profile.get("entities") or []) if str(x).strip()]
    required_entity_fields = (
        starter_profile.get("entity_fields") if isinstance(starter_profile.get("entity_fields"), dict) else {}
    )
    required_apis = [str(x).strip() for x in (starter_profile.get("required_api_endpoints") or []) if str(x).strip()]
    required_pages = [str(x).strip() for x in (starter_profile.get("required_frontend_pages") or []) if str(x).strip()]

    entities = out.get("entities") if isinstance(out.get("entities"), list) else []
    entity_rows: list[dict[str, Any]] = [row for row in entities if isinstance(row, dict)]
    by_name: dict[str, dict[str, Any]] = {
        str(row.get("name") or "").strip().lower(): row
        for row in entity_rows
        if str(row.get("name") or "").strip()
    }
    for entity_name in required_entities:
        key = entity_name.lower()
        row = by_name.get(key)
        if not isinstance(row, dict):
            row = {"name": entity_name, "fields": []}
            entity_rows.append(row)
            by_name[key] = row
        existing_fields = row.get("fields") if isinstance(row.get("fields"), list) else []
        existing_names = {
            str(field.get("name") or "").strip().lower()
            for field in existing_fields
            if isinstance(field, dict) and str(field.get("name") or "").strip()
        }
        required_fields = required_entity_fields.get(entity_name) if isinstance(required_entity_fields, dict) else []
        for field in required_fields if isinstance(required_fields, list) else []:
            if not isinstance(field, dict):
                continue
            field_name = str(field.get("name") or "").strip()
            field_type = str(field.get("type") or "").strip().lower()
            if not field_name or not field_type or field_name.lower() in existing_names:
                continue
            existing_fields.append({"name": field_name, "type": field_type})
            existing_names.add(field_name.lower())
        row["fields"] = existing_fields[:6]

    out["entities"] = entity_rows[:3]

    current_apis = out.get("api_endpoints") if isinstance(out.get("api_endpoints"), list) else []
    api_rows = [str(x).strip() for x in current_apis if str(x).strip()]
    seen_api = {row.lower() for row in api_rows}
    for endpoint in required_apis:
        key = endpoint.lower()
        if key in seen_api:
            continue
        api_rows.append(endpoint)
        seen_api.add(key)
    out["api_endpoints"] = api_rows[:12]

    current_pages = out.get("frontend_pages") if isinstance(out.get("frontend_pages"), list) else []
    page_rows = [str(x).strip() for x in current_pages if str(x).strip()]
    seen_page = {row.lower() for row in page_rows}
    if frontend_needed:
        for page in required_pages:
            key = page.lower()
            if key in seen_page:
                continue
            page_rows.append(page)
            seen_page.add(key)
    out["frontend_pages"] = page_rows[:12]


def suggest_project_spec(
    idea: str,
    reasoning: dict[str, Any],
    *,
    provider_project_dir: Path | None = None,
) -> dict[str, Any]:
    text = str(idea or "").strip().lower()
    auth_signal = _has_auth_signal(text, reasoning)
    domains = [str(x).strip().lower() for x in (reasoning.get("domains") or []) if str(x).strip()]
    frontend_needed = bool(reasoning.get("frontend_needed"))
    starter_profile = _build_starter_profile(text, domains, frontend_needed)
    selected_entities: list[str] = []
    seen: set[str] = set()

    if isinstance(starter_profile, dict) and starter_profile:
        for entity_name in starter_profile.get("entities") if isinstance(starter_profile.get("entities"), list) else []:
            entity_text = str(entity_name).strip()
            if not entity_text or entity_text in seen:
                continue
            seen.add(entity_text)
            selected_entities.append(entity_text)

    for domain in domains:
        entity = DOMAIN_ENTITY_MAP.get(domain)
        if not entity or entity in seen:
            continue
        seen.add(entity)
        selected_entities.append(entity)

    has_team = "teams" in domains
    has_work = any(x in domains for x in ("tasks", "defects"))
    if has_team and has_work and "Project" not in seen:
        seen.add("Project")
        selected_entities.append("Project")

    # Keyword inference for QA/hardware ideas.
    if any(k in text for k in ("device", "hardware", "firmware")) and "Device" not in seen:
        seen.add("Device")
        selected_entities.append("Device")
    if any(k in text for k in ("test run", "test history", "execution")) and "TestRun" not in seen:
        seen.add("TestRun")
        selected_entities.append("TestRun")
    if "qa" in text and any(k in text for k in ("hardware", "defect", "bug", "issue", "tracker")) and "TestRun" not in seen:
        seen.add("TestRun")
        selected_entities.append("TestRun")
    if any(k in text for k in ("defect", "bug", "issue")) and "Defect" not in seen:
        seen.add("Defect")
        selected_entities.append("Defect")
    if _has_any_word(text, DIARY_SIGNAL_WORDS) and "Entry" not in seen:
        seen.add("Entry")
        selected_entities.append("Entry")
    if any(k in text for k in ("bookmark", "reading list", "saved link", "link saver")) and "Bookmark" not in seen:
        seen.add("Bookmark")
        selected_entities.append("Bookmark")
    if any(k in text for k in ("recipe", "meal plan", "cooking")) and "Recipe" not in seen:
        seen.add("Recipe")
        selected_entities.append("Recipe")
    if any(_has_word(text, k) for k in ("board", "boards", "kanban")) and "Board" not in seen:
        seen.add("Board")
        selected_entities.append("Board")
    if any(k in text for k in ("memo", "note")) and "Note" not in seen and "Entry" not in seen:
        seen.add("Note")
        selected_entities.append("Note")
    if auth_signal and "User" not in seen:
        seen.add("User")
        selected_entities.append("User")

    # Companion entity inference for common multi-entity product ideas.
    # This keeps generation and inspect aligned with design/plan expectations.
    expanded_entities: list[str] = []
    expanded_seen: set[str] = set()
    for entity_name in selected_entities:
        _add_entity_once(expanded_entities, expanded_seen, entity_name)
        if entity_name == "Board":
            if any(k in text for k in ("card", "cards", "kanban", "column")):
                _add_entity_once(expanded_entities, expanded_seen, "Card")
        if entity_name == "Entry":
            if _has_any_word(text, TAGGING_SIGNAL_WORDS):
                _add_entity_once(expanded_entities, expanded_seen, "Tag")
        if entity_name == "Bookmark":
            if any(k in text for k in ("category", "categories", "folder", "folders")):
                _add_entity_once(expanded_entities, expanded_seen, "Category")
    selected_entities = expanded_entities[:3]

    entities: list[dict[str, Any]] = []
    for entity_name in selected_entities:
        fields = ENTITY_FIELD_MAP.get(entity_name, [])[:6]
        entities.append({"name": entity_name, "fields": fields})

    api_endpoints: list[str] = []
    pages: list[str] = []
    for entity in entities:
        entity_name = str(entity.get("name") or "")
        _, plural = _entity_slug_and_plural(entity_name)
        if not plural:
            continue
        full_crud = entity_name in {"Task", "Note", "Entry", "Tag"}
        api_endpoints.extend(_build_crud_endpoints(plural, full=full_crud))
        if frontend_needed:
            pages.extend(_build_core_pages(plural))

    fallback_spec = {
        "entities": entities[:3],
        "api_endpoints": api_endpoints[:12],
        "frontend_pages": pages[:12],
    }
    _enforce_starter_profile(fallback_spec, starter_profile, frontend_needed=frontend_needed)
    provider_prompt = (
        "Suggest a compact project spec JSON for the idea.\n"
        "Return JSON object with keys: entities, api_endpoints, frontend_pages.\n"
        "entities: list of {name, fields:[{name,type}]}\n"
        "api_endpoints: list of '<METHOD> /path'\n"
        "frontend_pages: list of page paths without leading slash.\n"
        f"Idea: {idea}\n"
        f"Reasoning: {reasoning}\n"
        f"Fallback: {fallback_spec}"
    )
    provider_spec = try_generate_reasoning_json(
        provider_prompt,
        timeout_s=90,
        temperature=0.1,
        project_dir=provider_project_dir,
    )
    if not isinstance(provider_spec, dict):
        return fallback_spec

    out = dict(fallback_spec)
    raw_entities = provider_spec.get("entities")
    if isinstance(raw_entities, list):
        normalized_entities: list[dict[str, Any]] = []
        seen_entities: set[str] = set()
        for raw_entity in raw_entities:
            if not isinstance(raw_entity, dict):
                continue
            name = str(raw_entity.get("name") or "").strip()
            key = name.lower()
            if not name or key in seen_entities:
                continue
            if not auth_signal and _is_auth_entity(name):
                continue
            seen_entities.add(key)
            raw_fields = raw_entity.get("fields") if isinstance(raw_entity.get("fields"), list) else []
            normalized_fields: list[dict[str, str]] = []
            seen_fields: set[str] = set()
            for raw_field in raw_fields:
                if not isinstance(raw_field, dict):
                    continue
                field_name = str(raw_field.get("name") or "").strip()
                field_type = str(raw_field.get("type") or "").strip().lower()
                field_key = field_name.lower()
                if not field_name or not field_type or field_key in seen_fields:
                    continue
                seen_fields.add(field_key)
                normalized_fields.append({"name": field_name, "type": field_type})
            normalized_entities.append({"name": name, "fields": normalized_fields[:6]})
        if normalized_entities:
            out["entities"] = normalized_entities[:3]

    raw_apis = provider_spec.get("api_endpoints")
    if isinstance(raw_apis, list):
        normalized_apis: list[str] = []
        seen_apis: set[str] = set()
        for raw_api in raw_apis:
            endpoint = _normalize_api_endpoint(str(raw_api or "").strip())
            if not endpoint:
                continue
            if not auth_signal and _is_auth_api(endpoint):
                continue
            key = endpoint.lower()
            if key in seen_apis:
                continue
            seen_apis.add(key)
            normalized_apis.append(endpoint)
        if normalized_apis:
            out["api_endpoints"] = normalized_apis[:12]

    raw_pages = provider_spec.get("frontend_pages")
    if isinstance(raw_pages, list):
        normalized_pages: list[str] = []
        seen_pages: set[str] = set()
        for raw_page in raw_pages:
            page = _normalize_frontend_page(str(raw_page or "").strip())
            if not page:
                continue
            if not auth_signal and _is_auth_page(page):
                continue
            key = page.lower()
            if key in seen_pages:
                continue
            seen_pages.add(key)
            normalized_pages.append(page)
        if normalized_pages:
            out["frontend_pages"] = normalized_pages[:12]

    _enforce_starter_profile(out, starter_profile, frontend_needed=frontend_needed)

    return out
