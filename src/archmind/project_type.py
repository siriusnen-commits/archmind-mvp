from __future__ import annotations

import re

PROJECT_TYPES = (
    "backend-api",
    "frontend-web",
    "fullstack-web",
    "internal-tool",
    "worker-api",
    "data-tool",
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

    fullstack_priority_patterns = [
        r"\bwebapp\b",
        r"웹앱",
        r"블로그",
        r"다이어리",
        r"게시판",
        r"대시보드",
        r"관리화면",
    ]
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
    internal_tool_patterns = [
        r"\binternal\b",
        r"\binternal tool\b",
        r"\badmin tool\b",
        r"\binternal admin\b",
        r"사내용",
        r"내부용",
    ]
    worker_api_patterns = [
        r"\bworker\b",
        r"\bbackground\b",
        r"\bbatch\b",
        r"\bqueue\b",
        r"\basync job\b",
        r"백그라운드",
        r"배치",
    ]
    data_tool_patterns = [
        r"\binventory\b",
        r"\breport(s)?\b",
        r"\banalytics?\b",
        r"\bdata viewer\b",
        r"\bdata tool\b",
    ]

    backend_hits = _contains_any(text, backend_patterns)
    frontend_hits = _contains_any(text, frontend_patterns)
    cli_hits = _contains_any(text, cli_patterns)
    automation_hits = _contains_any(text, automation_patterns)
    fullstack_hits = _contains_any(text, fullstack_patterns)
    fullstack_priority_hits = _contains_any(text, fullstack_priority_patterns)
    internal_hits = _contains_any(text, internal_tool_patterns)
    worker_hits = _contains_any(text, worker_api_patterns)
    data_hits = _contains_any(text, data_tool_patterns)

    if fullstack_priority_hits > 0:
        return "fullstack-web"
    if internal_hits > 0 and frontend_hits > 0:
        return "internal-tool"
    if worker_hits > 0 and backend_hits > 0 and frontend_hits == 0:
        return "worker-api"
    if data_hits > 0 and (frontend_hits > 0 or backend_hits > 0 or "tool" in text):
        return "data-tool"

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
