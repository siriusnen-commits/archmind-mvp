from __future__ import annotations

import re
from pathlib import Path
from typing import Any, Iterable


def _extract_path_like_lines(text: str) -> list[str]:
    out: list[str] = []
    for pat in (
        r"(frontend/[^\s:]+\.(?:tsx?|jsx?))(?::\d+)?",
        r"(app/[^\s:]+\.py)(?::\d+)?",
        r"(tests/[^\s:]+\.py)(?::\d+)?",
        r"File \"([^\"]+\.py)\"",
    ):
        for match in re.findall(pat, text):
            val = str(match).strip()
            if val and val not in out:
                out.append(val)
    return out


def _flatten_lines(*sources: Any) -> list[str]:
    lines: list[str] = []
    for source in sources:
        if source is None:
            continue
        if isinstance(source, str):
            lines.extend(source.splitlines())
            continue
        if isinstance(source, Iterable):
            for item in source:
                lines.extend(str(item).splitlines())
            continue
        lines.extend(str(source).splitlines())
    return lines


def filter_noise_lines(lines: list[str], failure_class: str | None = None) -> list[str]:
    ansi_escape = re.compile(r"\x1b\[[0-9;]*[a-zA-Z]")
    klass = (failure_class or "").lower()
    is_backend = klass.startswith("backend-pytest")
    is_frontend = klass.startswith("frontend")
    out: list[str] = []
    seen: set[str] = set()
    for raw in lines:
        line = ansi_escape.sub("", str(raw)).strip()
        if not line:
            continue
        lower = line.lower()
        if lower.startswith(("command:", "$ archmind")):
            continue
        if lower.startswith(
            (
                "project_dir:",
                "timestamp:",
                "cwd:",
                "duration",
                "base",
                "cancel",
                "traceback:",
                "short test summary info",
            )
        ):
            continue
        if "short test summary info" in lower:
            continue
        if any(
            token in lower
            for token in (
                "how would you like to configure eslint",
                "would you like to install",
                "press enter to continue",
                "learn more",
            )
        ):
            continue
        line = re.sub(r"\s+", " ", line)
        if is_backend and any(
            tok in lower
            for tok in (
                "eslint",
                "frontend",
                "ts2304",
                "ts2322",
                "is not assignable",
                "npm err",
                "next build",
                "vite build",
                "lint ",
                "plugin",
                "base",
                "cancel",
                "next.js",
                "how would you like",
            )
        ):
            continue
        if is_frontend and any(
            tok in lower
            for tok in (
                "pytest",
                "assertionerror",
                "modulenotfounderror",
                "importerror",
                "e   ",
                "failed tests/",
                "traceback",
                "short test summary info",
                "modulenotfounderror",
                "importerror",
            )
        ):
            continue
        if line in seen:
            continue
        seen.add(line)
        out.append(line[:220])
    return out


def extract_core_failure_lines(text: str, failure_class: str | None = None, max_lines: int = 4) -> list[str]:
    del failure_class
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    if not lines:
        return []
    priority_patterns = [
        r"ModuleNotFoundError",
        r"ImportError",
        r"AssertionError",
        r"^E\s+",
        r"^FAILED ",
        r"\bTS2304\b|\bTS2322\b|is not assignable",
        r"ESLint|Parsing error|Cannot find module|npm ERR!",
        r"build failed|failed to compile|next build|vite build",
        r"tests/.+\.py:\d+|frontend/.+\.(?:tsx?|jsx?):\d+",
    ]
    picked: list[str] = []
    for pattern in priority_patterns:
        rx = re.compile(pattern, re.IGNORECASE)
        for line in lines:
            if rx.search(line) and line not in picked:
                picked.append(line)
            if len(picked) >= max_lines:
                return picked[:max_lines]
    if len(picked) < max_lines:
        for line in lines:
            if line not in picked:
                picked.append(line)
            if len(picked) >= max_lines:
                break
    return picked[:max_lines]


def extract_failure_excerpt(*sources: Any, max_lines: int = 6, failure_class: str = "") -> str:
    raw_lines = _flatten_lines(*sources)
    filtered = filter_noise_lines(raw_lines, failure_class=failure_class)
    core = extract_core_failure_lines("\n".join(filtered), failure_class=failure_class, max_lines=max_lines)
    return "\n".join(core)


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


def select_primary_failure_class(failure_signature: str, classified_failure_class: str) -> str:
    klass = (classified_failure_class or "").strip().lower()
    sig = (failure_signature or "").lower()
    if klass and klass != "unknown":
        return klass
    has_backend = "backend-pytest" in sig
    has_frontend = any(tok in sig for tok in ("frontend-lint", "frontend-build", "frontend-typescript", "frontend-test"))
    if has_backend:
        return "backend-pytest:other"
    if has_frontend:
        if "frontend-lint" in sig:
            return "frontend-lint"
        if "frontend-typescript" in sig:
            return "frontend-typescript"
        if "frontend-build" in sig:
            return "frontend-build"
        if "frontend-test" in sig:
            return "frontend-test"
        return "frontend-other"
    return "unknown"


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


def is_safe_repair_target(path: str, project_dir: Path) -> bool:
    raw = (path or "").strip()
    if not raw:
        return False
    lowered = raw.replace("\\", "/").lower()
    blocked_tokens = (
        ".venv/",
        ".pyenv/",
        "site-packages/",
        "/usr/lib/",
        "/opt/homebrew/",
        "/system/library/",
        "/library/frameworks/",
        "/python.framework/",
        "/importlib/",
    )
    if any(token in lowered for token in blocked_tokens):
        return False

    allow_non_project = {
        "requirements.txt",
        "package.json",
        "pyproject.toml",
        "poetry.lock",
        "pipfile",
        "pipfile.lock",
        ".env.example",
        ".env.sample",
        "frontend/package.json",
        "frontend/tsconfig.json",
        "frontend/eslint.config.js",
        "frontend/next.config.js",
    }
    if lowered in allow_non_project:
        return True

    p = Path(raw)
    try:
        project_root = project_dir.expanduser().resolve()
    except Exception:
        project_root = Path(project_dir)
    if p.is_absolute():
        try:
            p.resolve().relative_to(project_root)
            return True
        except Exception:
            return False

    if lowered.startswith("../"):
        return False
    return True


def select_repair_targets(
    failure_class: str,
    excerpt: str,
    project_dir: Any,
    *,
    files_hint: list[str] | None = None,
    failure_file: str | None = None,
) -> list[str]:
    klass = (failure_class or "unknown").lower()
    text = (excerpt or "")
    found_paths = _extract_path_like_lines(text)
    if failure_file:
        found_paths.insert(0, str(failure_file))
    for hint in files_hint or []:
        h = str(hint).strip()
        if h and h not in found_paths:
            found_paths.append(h)

    cleaned: list[str] = []
    for path in found_paths:
        p = path.replace("\\", "/")
        if p.startswith("/"):
            try:
                rel = str(Path(p).resolve().relative_to(project_dir.expanduser().resolve())).replace("\\", "/")
                p = rel
            except Exception:
                pass
        if is_safe_repair_target(p, Path(project_dir)) and p not in cleaned:
            cleaned.append(p)

    if klass == "backend-pytest:module-not-found":
        targets = ["requirements.txt"]
        for path in cleaned:
            if path.endswith(".py") and "/tests/" not in f"/{path}" and not path.startswith("tests/"):
                targets.append(path)
                break
        return [t for t in list(dict.fromkeys(targets)) if is_safe_repair_target(t, Path(project_dir))]

    if klass == "backend-pytest:import":
        targets = []
        for path in cleaned:
            if path.endswith(".py") and "/tests/" not in f"/{path}" and not path.startswith("tests/"):
                targets.append(path)
        targets.append("requirements.txt")
        return [t for t in list(dict.fromkeys(targets)) if is_safe_repair_target(t, Path(project_dir))][:3]

    if klass in ("backend-pytest:assertion", "backend-pytest:api-response", "backend-pytest:other"):
        targets = []
        for path in cleaned:
            if path.endswith(".py") and "/tests/" not in f"/{path}" and not path.startswith("tests/"):
                targets.append(path)
        if not targets:
            targets = ["app/main.py"]
        return [t for t in list(dict.fromkeys(targets)) if is_safe_repair_target(t, Path(project_dir))][:3]

    if klass == "frontend-lint":
        targets = [p for p in cleaned if p.startswith("frontend/") and p.endswith((".ts", ".tsx", ".js", ".jsx"))]
        if not targets:
            targets = ["frontend/eslint.config.js"]
        else:
            targets.append("frontend/eslint.config.js")
        return [t for t in list(dict.fromkeys(targets)) if is_safe_repair_target(t, Path(project_dir))][:3]

    if klass == "frontend-typescript":
        targets = [p for p in cleaned if p.startswith("frontend/") and p.endswith((".ts", ".tsx"))]
        targets.extend(["frontend/tsconfig.json", "frontend/types.d.ts"])
        return [t for t in list(dict.fromkeys(targets)) if is_safe_repair_target(t, Path(project_dir))][:3]

    if klass == "frontend-build":
        targets = [p for p in cleaned if p.startswith("frontend/")]
        targets.extend(["frontend/next.config.js", "frontend/package.json"])
        return [t for t in list(dict.fromkeys(targets)) if is_safe_repair_target(t, Path(project_dir))][:3]

    if klass in ("frontend-dependency", "env-dependency"):
        targets = ["frontend/package.json", "requirements.txt", ".env.example"]
        return [t for t in list(dict.fromkeys(targets)) if is_safe_repair_target(t, Path(project_dir))][:3]

    return cleaned[:2] or ["inspect recent failure details"]


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
