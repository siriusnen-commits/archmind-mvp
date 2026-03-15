from __future__ import annotations

import re
from typing import Any


def _has_any(text: str, keywords: list[str]) -> bool:
    for item in keywords:
        if re.search(item, text):
            return True
    return False


def _extract_domains(text: str) -> list[str]:
    domains: list[str] = []
    mapping: list[tuple[str, list[str]]] = [
        ("notes", [r"\bnote(s)?\b", r"메모"]),
        ("tasks", [r"\btask(s)?\b", r"\btodo(s)?\b", r"작업"]),
        ("expenses", [r"\bexpense(s)?\b", r"\bbudget\b", r"가계부"]),
        ("documents", [r"\bdocument(s)?\b", r"\bsummary\b", r"문서"]),
        ("defects", [r"\bdefect(s)?\b", r"\bbug(s)?\b", r"\bissue(s)?\b", r"결함"]),
        ("teams", [r"\bteam(s)?\b", r"\bcollaboration\b", r"협업"]),
        ("inventory", [r"\binventory\b", r"\bstock\b", r"재고"]),
    ]
    for name, patterns in mapping:
        if _has_any(text, patterns):
            domains.append(name)
    return domains


def reason_architecture_from_idea(idea: str) -> dict[str, Any]:
    text = re.sub(r"\s+", " ", str(idea or "").strip().lower())
    if not text:
        return {
            "app_shape": "unknown",
            "domains": [],
            "modules": [],
            "backend_needed": False,
            "frontend_needed": False,
            "persistence_needed": False,
            "auth_needed": False,
            "db_needed": False,
            "dashboard_needed": False,
            "worker_needed": False,
            "file_upload_needed": False,
            "internal_tool": False,
            "realtime_needed": False,
            "deployment_intent": "unknown",
            "recommended_template": "fastapi",
            "reason_summary": "insufficient idea detail",
        }

    backend_needed = _has_any(
        text,
        [
            r"\bapi\b",
            r"\bbackend\b",
            r"\bfastapi\b",
            r"\bdatabase\b",
            r"\bdb\b",
            r"\bcrud\b",
            r"\bmanagement\b",
            r"저장",
            r"관리",
            r"추적",
        ],
    )
    frontend_needed = _has_any(
        text,
        [
            r"\bui\b",
            r"\bdashboard\b",
            r"\bweb\b",
            r"\bfrontend\b",
            r"\bnextjs\b",
            r"\bnext\.js\b",
            r"\bpage\b",
            r"화면",
            r"대시보드",
        ],
    )
    auth_needed = _has_any(
        text,
        [
            r"\blogin\b",
            r"\bauth\b",
            r"\bauthentication\b",
            r"\buser account\b",
            r"\buser\b",
            r"회원",
            r"로그인",
            r"사용자",
        ],
    )
    db_needed = _has_any(
        text,
        [
            r"\bdb\b",
            r"\bdatabase\b",
            r"저장",
            r"관리",
            r"추적",
            r"\btracker\b",
            r"\bcrud\b",
            r"\bpersistence\b",
        ],
    )
    dashboard_needed = _has_any(
        text,
        [
            r"\bdashboard\b",
            r"\badmin\b",
            r"\bpanel\b",
            r"\banalytics\b",
            r"대시보드",
            r"관리화면",
            r"관리자",
            r"통계",
        ],
    )
    worker_needed = _has_any(
        text,
        [
            r"\bworker\b",
            r"\bqueue\b",
            r"\bbackground\b",
            r"\bbatch\b",
            r"\basync job\b",
            r"백그라운드",
            r"배치",
        ],
    )
    file_upload_needed = _has_any(
        text,
        [
            r"\bupload\b",
            r"\bfile\b",
            r"\battachment\b",
            r"첨부",
            r"업로드",
            r"\bdocument upload\b",
        ],
    )
    internal_tool = _has_any(
        text,
        [
            r"\binternal\b",
            r"\badmin tool\b",
            r"사내용",
            r"내부용",
            r"관리툴",
        ],
    )
    realtime_needed = _has_any(
        text,
        [
            r"\brealtime\b",
            r"\bwebsocket\b",
            r"\blive\b",
            r"\bchat\b",
            r"\bmultiplayer\b",
            r"실시간",
        ],
    )
    persistence_needed = _has_any(
        text,
        [
            r"\bdatabase\b",
            r"\bdb\b",
            r"\bstorage\b",
            r"\bcrud\b",
            r"\btracker\b",
            r"\bmanage\b",
            r"\bmanagement\b",
            r"저장",
            r"관리",
            r"추적",
        ],
    )
    if db_needed:
        persistence_needed = True

    domains = _extract_domains(text)
    modules: list[str] = []
    if auth_needed:
        modules.append("auth")
    if db_needed:
        modules.append("db")
    if dashboard_needed:
        modules.append("dashboard")
    if worker_needed:
        modules.append("worker")
    if file_upload_needed:
        modules.append("file-upload")

    frontend_only_explicit = _has_any(
        text,
        [
            r"\bfrontend only\b",
            r"\bfrontend-only\b",
            r"프론트엔드만",
        ],
    )

    # RULE 1 + RULE 3
    if (auth_needed or db_needed) and not frontend_only_explicit:
        backend_needed = True
    if file_upload_needed:
        backend_needed = True

    # RULE 4
    if dashboard_needed and backend_needed:
        frontend_needed = True

    # RULE 2
    if auth_needed and db_needed:
        app_shape = "fullstack"
    elif backend_needed and frontend_needed:
        app_shape = "fullstack"
    elif backend_needed and not frontend_needed:
        app_shape = "backend"
    elif frontend_needed and not backend_needed:
        app_shape = "frontend"
    else:
        app_shape = "unknown"

    # RULE 5
    if app_shape == "unknown":
        if backend_needed and frontend_needed:
            app_shape = "fullstack"
        elif backend_needed:
            app_shape = "backend"
        elif frontend_needed:
            app_shape = "frontend"

    if app_shape == "fullstack":
        recommended_template = "fullstack-ddd"
    elif app_shape == "backend":
        recommended_template = "fastapi"
    elif app_shape == "frontend":
        recommended_template = "nextjs"
    else:
        recommended_template = "fastapi"

    if app_shape == "fullstack":
        deployment_intent = "web-app"
    elif app_shape == "frontend":
        deployment_intent = "web-app"
    elif app_shape == "backend":
        deployment_intent = "api"
    else:
        deployment_intent = "unknown"

    domain_text = ", ".join(domains) if domains else "general"
    reason_summary = f"{app_shape} app for {domain_text}" if app_shape != "unknown" else "unclear architecture from idea"
    if modules:
        reason_summary = f"{reason_summary} with {', '.join(modules)}"

    return {
        "app_shape": app_shape,
        "domains": domains,
        "modules": modules,
        "backend_needed": backend_needed,
        "frontend_needed": frontend_needed,
        "persistence_needed": persistence_needed,
        "auth_needed": auth_needed,
        "db_needed": db_needed,
        "dashboard_needed": dashboard_needed,
        "worker_needed": worker_needed,
        "file_upload_needed": file_upload_needed,
        "internal_tool": internal_tool,
        "realtime_needed": realtime_needed,
        "deployment_intent": deployment_intent,
        "recommended_template": recommended_template,
        "reason_summary": reason_summary,
    }
