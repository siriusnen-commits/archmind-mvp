from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from .reasoning import try_generate_reasoning_json


def _entity_slug(name: str) -> str:
    value = str(name or "").strip()
    if not value:
        return ""
    return re.sub(r"(?<!^)(?=[A-Z])", "_", value).lower()


def _pluralize_slug(value: str) -> str:
    slug = str(value or "").strip().lower().strip("/")
    if not slug:
        return ""
    if slug.endswith("s"):
        return slug
    if slug.endswith("ies"):
        return slug
    if slug.endswith(("ses", "xes", "zes", "ches", "shes")):
        return slug
    if slug.endswith("y") and len(slug) > 1 and slug[-2] not in "aeiou":
        return f"{slug[:-1]}ies"
    if slug.endswith(("x", "z", "ch", "sh")):
        return f"{slug}es"
    return f"{slug}s"


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
    parts = [part for part in path.split("/") if part]
    if parts and not parts[0].startswith("{") and not parts[0].startswith("["):
        parts[0] = _pluralize_slug(parts[0].replace("-", "_"))
    return f"{method} /{'/'.join(parts)}"


def _normalize_page_path(value: str) -> str:
    page = str(value or "").strip().replace("\\", "/").strip("/")
    if not page:
        return ""
    parts = [part for part in page.split("/") if part]
    if not parts:
        return ""
    resource = _pluralize_slug(parts[0].replace("-", "_"))
    if not resource:
        return ""
    if len(parts) == 1:
        return f"{resource}/list"
    action = parts[1].lower().strip()
    if action in {"index", "home"}:
        action = "list"
    elif action in {"create"}:
        action = "new"
    elif action in {"show", "view", "item"}:
        action = "detail"
    return f"{resource}/{action}"


def _has_auth_signal(idea: str, reasoning: dict[str, Any]) -> bool:
    if bool(reasoning.get("auth_needed")):
        return True
    modules = [str(x).strip().lower() for x in (reasoning.get("modules") or []) if str(x).strip()]
    if "auth" in modules:
        return True
    text = str(idea or "").lower()
    return any(
        token in text
        for token in (
            "login",
            "auth",
            "oauth",
            "signup",
            "sign up",
            "account",
            "password",
            "multi-user",
            "multi user",
            "rbac",
        )
    )


def _normalize_plan_step_command(value: Any) -> str:
    raw = str(value or "").strip()
    if not raw:
        return ""
    text = raw
    text = re.sub(r"^\s*(?:[-*]|\d+[.)])\s*", "", text).strip()
    text = re.sub(r"^(?:slash\s*command|command|run)\s*:\s*", "", text, flags=re.IGNORECASE).strip()

    command_match = re.search(r"/[a-z_][a-z0-9_]*(?:\s+\S+)*", text, flags=re.IGNORECASE)
    if command_match:
        text = command_match.group(0).strip()
    elif re.match(r"^(?:add_entity|add_field|add_api|add_page|implement_page)\b", text, flags=re.IGNORECASE):
        text = "/" + text
    elif text.startswith("/"):
        parts = [part for part in text.split() if part]
        return " ".join(parts)
    else:
        return ""

    parts = [part for part in text.split() if part]
    if not parts:
        return ""
    command = parts[0].lower()
    args = parts[1:]

    if command == "/add_entity":
        if not args:
            return ""
        return f"/add_entity {args[0]}"
    if command == "/add_field":
        if len(args) < 2:
            return ""
        return f"/add_field {args[0]} {args[1]}"
    if command == "/add_api":
        if len(args) < 2:
            return ""
        method = str(args[0]).upper().strip()
        path = str(args[1]).strip()
        if not path:
            return ""
        if not path.startswith("/"):
            path = f"/{path}"
        return f"/add_api {method} {path}"
    if command == "/add_page":
        if not args:
            return ""
        return f"/add_page {args[0]}"
    if command == "/implement_page":
        if not args:
            return ""
        return f"/implement_page {args[0]}"
    return " ".join([command] + args)


def _limit_steps(phases: list[dict[str, Any]], max_steps: int = 15) -> list[dict[str, Any]]:
    used = 0
    out: list[dict[str, Any]] = []
    for phase in phases:
        title = str(phase.get("title") or "").strip()
        normalized_steps: list[str] = []
        seen_steps: set[str] = set()
        for raw_step in (phase.get("steps") or []):
            step = _normalize_plan_step_command(raw_step)
            if not step:
                continue
            if step in seen_steps:
                continue
            seen_steps.add(step)
            normalized_steps.append(step)
        steps = normalized_steps
        if not title or not steps:
            continue
        remain = max_steps - used
        if remain <= 0:
            break
        selected = steps[:remain]
        if selected:
            out.append({"title": title, "steps": selected})
            used += len(selected)
    return out


def build_plan_from_suggestion(
    idea: str,
    reasoning: dict[str, Any],
    suggestion: dict[str, Any],
    *,
    provider_project_dir: Path | None = None,
) -> dict[str, Any]:
    auth_signal = _has_auth_signal(idea, reasoning)
    entities = suggestion.get("entities") if isinstance(suggestion.get("entities"), list) else []
    apis = [_normalize_api_endpoint(str(x).strip()) for x in (suggestion.get("api_endpoints") or []) if str(x).strip()]
    pages = [_normalize_page_path(str(x).strip()) for x in (suggestion.get("frontend_pages") or []) if str(x).strip()]

    entity_steps: list[str] = []
    field_steps: list[str] = []
    for entity in entities:
        if not isinstance(entity, dict):
            continue
        name = str(entity.get("name") or "").strip()
        if not name:
            continue
        if not auth_signal and name.lower() == "user":
            continue
        entity_steps.append(f"/add_entity {name}")
        fields = entity.get("fields") if isinstance(entity.get("fields"), list) else []
        for field in fields:
            if not isinstance(field, dict):
                continue
            fname = str(field.get("name") or "").strip()
            ftype = str(field.get("type") or "").strip().lower()
            if fname and ftype:
                field_steps.append(f"/add_field {name} {fname}:{ftype}")

    api_steps = [f"/add_api {endpoint}" for endpoint in apis if endpoint]
    page_steps = [f"/add_page {page}" for page in pages if page]

    phases = [
        {"title": "Core entities", "steps": entity_steps},
        {"title": "Core fields", "steps": field_steps},
        {"title": "APIs", "steps": api_steps},
        {"title": "Frontend", "steps": page_steps},
    ]
    fallback_plan = {"phases": _limit_steps(phases, max_steps=15)}

    provider_prompt = (
        "Build an implementation plan JSON from the idea and suggestion.\n"
        "Return JSON object with key phases.\n"
        "phases: list of {title, steps:[slash commands]}.\n"
        f"Idea: {idea}\n"
        f"Reasoning: {reasoning}\n"
        f"Suggestion: {suggestion}\n"
        f"Fallback: {fallback_plan}"
    )
    provider_plan = try_generate_reasoning_json(
        provider_prompt,
        timeout_s=90,
        temperature=0.1,
        project_dir=provider_project_dir,
    )
    raw_phases = provider_plan.get("phases") if isinstance(provider_plan, dict) else None
    if not isinstance(raw_phases, list):
        return fallback_plan
    normalized = _limit_steps(
        [phase for phase in raw_phases if isinstance(phase, dict)],
        max_steps=15,
    )
    if not normalized:
        return fallback_plan
    return {"phases": normalized}


def build_plan_from_project_spec(spec: dict[str, Any], *, provider_project_dir: Path | None = None) -> dict[str, Any]:
    modules = [str(x).strip().lower() for x in (spec.get("modules") or []) if str(x).strip()]
    entities = spec.get("entities") if isinstance(spec.get("entities"), list) else []
    api_endpoints = {str(x).strip() for x in (spec.get("api_endpoints") or []) if str(x).strip()}
    pages = {str(x).strip().strip("/") for x in (spec.get("frontend_pages") or []) if str(x).strip()}
    shape = str(spec.get("shape") or "").strip().lower()
    frontend_enabled = shape == "fullstack" or bool(pages)

    names: list[str] = []
    for entity in entities:
        if isinstance(entity, dict):
            name = str(entity.get("name") or "").strip()
            if name:
                names.append(name)
    lower_names = {n.lower() for n in names}

    phase1: list[str] = []
    if "auth" in modules and "user" not in lower_names:
        phase1.append("/add_entity User")

    phase2: list[str] = []
    phase3: list[str] = []
    phase4: list[str] = []
    for entity in entities:
        if not isinstance(entity, dict):
            continue
        name = str(entity.get("name") or "").strip()
        if not name:
            continue
        fields = entity.get("fields") if isinstance(entity.get("fields"), list) else []
        if len(fields) <= 1:
            phase2.append(f"/add_field {name} description:string")

        slug = _entity_slug(name)
        plural = f"{slug}s"
        if slug and f"GET /{plural}/{{id}}" not in api_endpoints:
            phase3.append(f"/add_api GET /{plural}/{{id}}")

        if frontend_enabled and slug:
            list_page = f"{plural}/list"
            create_page = f"{plural}/new"
            if list_page not in pages:
                phase4.append(f"/add_page {list_page}")
            if create_page not in pages:
                phase4.append(f"/add_page {create_page}")

    if "dashboard" in modules and "dashboard/home" not in pages:
        phase4.append("/add_page dashboard/home")

    phases = [
        {"title": "Core entities", "steps": phase1},
        {"title": "Core fields", "steps": phase2},
        {"title": "APIs", "steps": phase3},
        {"title": "Frontend", "steps": phase4},
    ]
    fallback_plan = {"phases": _limit_steps(phases, max_steps=15)}
    provider_prompt = (
        "Build an implementation plan JSON from this project spec.\n"
        "Return JSON object with key phases.\n"
        "phases: list of {title, steps:[slash commands]}.\n"
        f"Spec: {spec}\n"
        f"Fallback: {fallback_plan}"
    )
    provider_plan = try_generate_reasoning_json(
        provider_prompt,
        timeout_s=90,
        temperature=0.1,
        project_dir=provider_project_dir,
    )
    raw_phases = provider_plan.get("phases") if isinstance(provider_plan, dict) else None
    if not isinstance(raw_phases, list):
        return fallback_plan
    normalized = _limit_steps(
        [phase for phase in raw_phases if isinstance(phase, dict)],
        max_steps=15,
    )
    if not normalized:
        return fallback_plan
    return {"phases": normalized}
