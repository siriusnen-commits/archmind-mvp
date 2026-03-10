from __future__ import annotations

import os


def resolve_default_template() -> str:
    value = os.getenv("ARCHMIND_DEFAULT_TEMPLATE", "fastapi").strip()
    return value or "fastapi"


def select_template_for_project_type(project_type: str, idea: str | None = None) -> str:
    del idea
    key = (project_type or "").strip().lower()
    mapping = {
        "backend-api": "fastapi",
        "frontend-web": "nextjs",
        "fullstack-web": "fullstack-ddd",
        "cli-tool": "cli",
        "automation-script": "automation",
    }
    return mapping.get(key) or resolve_default_template()


def is_supported_template(template: str) -> bool:
    return (template or "").strip().lower() in {"fastapi", "fastapi-ddd", "fullstack-ddd"}

