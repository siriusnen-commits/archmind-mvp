from __future__ import annotations

import os


def get_supported_templates() -> list[str]:
    return [
        "fastapi",
        "fastapi-ddd",
        "fullstack-ddd",
        "nextjs",
        "internal-tool",
        "worker-api",
        "data-tool",
    ]


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
        "internal-tool": "internal-tool",
        "worker-api": "worker-api",
        "data-tool": "data-tool",
        "cli-tool": "cli",
        "automation-script": "automation",
    }
    return mapping.get(key) or resolve_default_template()


def is_supported_template(template: str) -> bool:
    return (template or "").strip().lower() in set(get_supported_templates())


def resolve_effective_template(
    selected_template: str,
    default_template: str,
) -> tuple[str, str | None]:
    selected = (selected_template or "").strip().lower()
    default = (default_template or "").strip().lower()

    if is_supported_template(selected):
        return selected, None

    if is_supported_template(default):
        reason = f"{selected or 'unknown'} template not supported; using default template '{default}'"
        return default, reason

    safe_default = "fastapi"
    reason = (
        f"{selected or 'unknown'} template not supported; "
        f"default template '{default or 'unknown'}' also unsupported; using '{safe_default}'"
    )
    return safe_default, reason
