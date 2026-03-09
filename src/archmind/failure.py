from __future__ import annotations

import re
from typing import Any, Iterable


def extract_failure_excerpt(*sources: Any, max_lines: int = 40) -> str:
    lines: list[str] = []
    for source in sources:
        if source is None:
            continue
        if isinstance(source, str):
            lines.extend(source.splitlines())
        elif isinstance(source, Iterable):
            for item in source:
                lines.extend(str(item).splitlines())
        else:
            lines.extend(str(source).splitlines())

    ansi_escape = re.compile(r"\x1b\[[0-9;]*[a-zA-Z]")
    out: list[str] = []
    for raw in lines:
        line = ansi_escape.sub("", str(raw)).strip()
        if not line:
            continue
        if line.lower().startswith(("command:", "$ archmind")):
            continue
        line = re.sub(r"\s+", " ", line)
        out.append(line[:220])
        if len(out) >= max_lines:
            break
    return "\n".join(out)


def classify_failure(excerpt: str, failure_signature: str = "") -> str:
    text = (excerpt or "").lower()
    sig = (failure_signature or "").lower()

    if any(token in text for token in ("npm err!", "command not found: npm", "command not found: node", "pip install")):
        return "env-dependency"

    if "module not found error" in text or "modulenotfounderror" in text:
        return "backend-pytest:module-not-found"
    if "importerror" in text:
        return "backend-pytest:import"
    if "assertionerror" in text:
        return "backend-pytest:assertion"
    if re.search(r"expected.+got", text) or "status code" in text or "response" in text:
        if "backend-pytest" in sig or "pytest" in text or "backend" in text:
            return "backend-pytest:api-response"

    if "eslint" in text or ("lint" in text and "frontend" in text):
        return "frontend-lint"
    if re.search(r"\bts\d{4}\b", text) or "is not assignable" in text:
        return "frontend-typescript"
    if any(token in text for token in ("next build", "build failed", "vite build", "failed to compile")):
        return "frontend-build"
    if any(token in text for token in ("vitest", "jest", "frontend test", "test suite failed")):
        return "frontend-test"
    if any(token in text for token in ("cannot find module", "missing package", "npm err!", "yarn error")):
        if "frontend" in text or "frontend" in sig:
            return "frontend-dependency"
        return "env-dependency"

    if "backend-pytest" in sig or "pytest" in text or "traceback" in text or "failed " in text:
        return "backend-pytest:other"
    if "frontend" in sig or "frontend" in text:
        return "frontend-other"
    return "unknown"


def fix_strategy_for_class(failure_class: str) -> str:
    klass = (failure_class or "unknown").lower()
    if klass == "backend-pytest:assertion":
        return "backend-assertion"
    if klass in ("backend-pytest:import", "backend-pytest:module-not-found"):
        return "backend-import-resolution"
    if klass == "backend-pytest:api-response":
        return "backend-api-response"
    if klass == "frontend-lint":
        return "frontend-lint-only"
    if klass == "frontend-typescript":
        return "frontend-typescript-safety"
    if klass == "frontend-build":
        return "frontend-build-stability"
    if klass in ("frontend-dependency", "env-dependency"):
        return "dependency-environment"
    return "generic"


def strategy_instructions(failure_class: str) -> list[str]:
    klass = (failure_class or "unknown").lower()
    if klass == "backend-pytest:assertion":
        return [
            "failing tests를 통과시키기 위해 구현을 수정하라.",
            "테스트는 명백히 잘못된 경우가 아니면 수정하지 마라.",
        ]
    if klass in ("backend-pytest:import", "backend-pytest:module-not-found"):
        return [
            "누락된 import/module/dependency를 먼저 해결하라.",
            "경로/이름 오타를 우선 점검하고 최소 변경으로 수정하라.",
        ]
    if klass == "backend-pytest:api-response":
        return [
            "API 응답 스키마/상태코드 mismatch를 우선 해결하라.",
            "endpoint 구현/serializer/response model을 먼저 점검하라.",
        ]
    if klass == "frontend-lint":
        return [
            "lint 통과를 목표로 하되 로직 변경을 최소화하라.",
        ]
    if klass == "frontend-typescript":
        return [
            "타입 오류를 해결하되 any 남발을 금지하고 동작을 보존하라.",
        ]
    if klass == "frontend-build":
        return [
            "build 통과를 목표로 import/export/path/config를 우선 점검하라.",
        ]
    if klass in ("frontend-dependency", "env-dependency"):
        return [
            "dependency/env 문제를 먼저 해결하라.",
            "코드 수정보다 설치/설정 문제를 우선 의심하라.",
        ]
    return ["generic repair prompt를 적용하고 변경 범위를 최소화하라."]


def failure_signature_from_run_result(run_result: Any) -> str:
    names: set[str] = set()
    backend = getattr(run_result, "backend", None)
    if backend is not None and str(getattr(backend, "status", "")).upper() == "FAIL":
        names.add("backend-pytest")

    frontend = getattr(run_result, "frontend", None)
    if frontend is not None and str(getattr(frontend, "status", "")).upper() == "FAIL":
        names.add("frontend-lint")
        steps = getattr(frontend, "steps", None) or []
        for step in steps:
            exit_code = getattr(step, "exit_code", None)
            if exit_code == 0:
                continue
            name = str(getattr(step, "name", "")).lower()
            cmd = " ".join(str(x) for x in (getattr(step, "cmd", None) or []))
            if "lint" in name or "eslint" in cmd:
                names.add("frontend-lint")
            elif "build" in name or "next build" in cmd or "vite build" in cmd:
                names.add("frontend-build")
            elif "tsc" in name or "typescript" in cmd:
                names.add("frontend-typescript")
            elif "test" in name or "vitest" in cmd or "jest" in cmd:
                names.add("frontend-test")

    if not names:
        return ""
    return f"{'+'.join(sorted(names))}:FAIL"
