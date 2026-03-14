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
        ("tasks", [r"\btask(s)?\b", r"\btodo(s)?\b", r"작업"]),
        ("expenses", [r"\bexpense(s)?\b", r"\bbudget\b", r"가계부"]),
        ("documents", [r"\bdocument(s)?\b", r"\bsummary\b", r"문서"]),
        ("defects", [r"\bdefect(s)?\b", r"\bbug(s)?\b", r"\bissue(s)?\b", r"결함"]),
        ("teams", [r"\bteam(s)?\b", r"\bcollaboration\b", r"협업"]),
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
            "backend_needed": False,
            "frontend_needed": False,
            "persistence_needed": False,
            "auth_needed": False,
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
            r"회원",
            r"로그인",
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
            r"저장",
            r"관리",
            r"추적",
        ],
    )

    domains = _extract_domains(text)

    if backend_needed and frontend_needed:
        app_shape = "fullstack"
    elif backend_needed and not frontend_needed:
        app_shape = "backend"
    elif frontend_needed and not backend_needed:
        app_shape = "frontend"
    else:
        app_shape = "unknown"

    if app_shape == "fullstack":
        recommended_template = "fullstack-ddd"
    elif app_shape == "backend" and persistence_needed:
        recommended_template = "fastapi-ddd"
    elif app_shape == "backend":
        recommended_template = "fastapi"
    elif app_shape == "frontend":
        recommended_template = "nextjs"
    else:
        recommended_template = "fastapi"

    if frontend_needed and not backend_needed:
        deployment_intent = "web-app"
    elif backend_needed and frontend_needed:
        deployment_intent = "web-app"
    elif backend_needed:
        deployment_intent = "api"
    else:
        deployment_intent = "unknown"

    domain_text = ", ".join(domains) if domains else "general"
    reason_summary = f"{app_shape} app for {domain_text}" if app_shape != "unknown" else "unclear architecture from idea"

    return {
        "app_shape": app_shape,
        "domains": domains,
        "backend_needed": backend_needed,
        "frontend_needed": frontend_needed,
        "persistence_needed": persistence_needed,
        "auth_needed": auth_needed,
        "realtime_needed": realtime_needed,
        "deployment_intent": deployment_intent,
        "recommended_template": recommended_template,
        "reason_summary": reason_summary,
    }
