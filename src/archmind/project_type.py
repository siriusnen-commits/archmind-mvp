from __future__ import annotations

import re

PROJECT_TYPES = (
    "backend-api",
    "frontend-web",
    "fullstack-web",
    "cli-tool",
    "automation-script",
    "unknown",
)


def _contains_any(text: str, patterns: list[str]) -> int:
    hits = 0
    for pattern in patterns:
        if re.search(pattern, text):
            hits += 1
    return hits


def normalize_project_type(value: str) -> str:
    candidate = (value or "").strip().lower()
    return candidate if candidate in PROJECT_TYPES else "unknown"


def detect_project_type(idea: str) -> str:
    text = re.sub(r"\s+", " ", str(idea or "").strip().lower())
    if not text:
        return "unknown"

    backend_patterns = [
        r"\bfastapi\b",
        r"\bapi\b",
        r"\bbackend\b",
        r"\bflask\b",
        r"\bdjango api\b",
        r"\brest\b",
        r"\bcrud api\b",
    ]
    frontend_patterns = [
        r"\bnextjs\b",
        r"\bnext\.js\b",
        r"\breact\b",
        r"\bfrontend\b",
        r"\bdashboard\b",
        r"\bweb ui\b",
        r"\btypescript ui\b",
    ]
    cli_patterns = [
        r"\bcli\b",
        r"\bcommand line\b",
        r"\bterminal tool\b",
        r"\bargparse\b",
        r"\btyper\b",
        r"\bclick\b",
    ]
    automation_patterns = [
        r"\bautomation\b",
        r"\bscript\b",
        r"\bbatch\b",
        r"\bcron\b",
        r"\btelegram bot\b",
        r"\bworkflow\b",
        r"\bsync tool\b",
    ]
    fullstack_patterns = [
        r"\bfullstack\b",
        r"\bfrontend and backend\b",
        r"\bapi with frontend\b",
        r"\bweb app with api\b",
    ]

    backend_hits = _contains_any(text, backend_patterns)
    frontend_hits = _contains_any(text, frontend_patterns)
    cli_hits = _contains_any(text, cli_patterns)
    automation_hits = _contains_any(text, automation_patterns)
    fullstack_hits = _contains_any(text, fullstack_patterns)

    if fullstack_hits > 0 or (backend_hits > 0 and frontend_hits > 0):
        return "fullstack-web"
    if backend_hits > 0:
        return "backend-api"
    if frontend_hits > 0:
        return "frontend-web"
    if cli_hits > 0:
        return "cli-tool"
    if automation_hits > 0:
        return "automation-script"
    return "unknown"
