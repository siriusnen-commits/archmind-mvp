from __future__ import annotations

import ast
import re
from pathlib import Path
from typing import Any


def has_fastapi_app_declaration(main_file: Path) -> bool:
    if not main_file.exists() or not main_file.is_file():
        return False
    try:
        text = main_file.read_text(encoding="utf-8", errors="replace")
    except Exception:
        return False
    try:
        tree = ast.parse(text)
    except SyntaxError:
        return "app = FastAPI(" in text

    def _is_fastapi_call(node: ast.AST) -> bool:
        if not isinstance(node, ast.Call):
            return False
        fn = node.func
        if isinstance(fn, ast.Name):
            return fn.id == "FastAPI"
        if isinstance(fn, ast.Attribute):
            return fn.attr == "FastAPI"
        return False

    for node in ast.walk(tree):
        if isinstance(node, ast.Assign):
            if not _is_fastapi_call(node.value):
                continue
            for target in node.targets:
                if isinstance(target, ast.Name) and target.id == "app":
                    return True
        if isinstance(node, ast.AnnAssign):
            if isinstance(node.target, ast.Name) and node.target.id == "app" and _is_fastapi_call(node.value):
                return True
    return False


def inspect_backend_layout(project_dir: Path, layout: str) -> dict[str, Any]:
    root = project_dir.expanduser().resolve()
    key = str(layout or "").strip().lower()
    if key == "fullstack":
        main_py = root / "backend" / "app" / "main.py"
        requirements = root / "backend" / "requirements.txt"
        run_cwd = root / "backend"
    else:
        key = "flat"
        main_py = root / "app" / "main.py"
        requirements = root / "requirements.txt"
        run_cwd = root
    main_exists = main_py.exists()
    requirements_exists = requirements.exists()
    app_decl_ok = has_fastapi_app_declaration(main_py) if main_exists else False
    return {
        "layout": key,
        "main_py": main_py,
        "requirements": requirements,
        "run_cwd": run_cwd,
        "main_exists": main_exists,
        "requirements_exists": requirements_exists,
        "app_decl_ok": app_decl_ok,
    }


def detect_backend_asgi_entry(
    project_dir: Path,
    *,
    allowed_layouts: tuple[str, ...] = ("fullstack", "flat"),
    prefer_layout: str = "fullstack",
    port: int | None = None,
) -> dict[str, Any]:
    root = project_dir.expanduser().resolve()
    normalized_allowed: list[str] = []
    for item in allowed_layouts:
        key = str(item or "").strip().lower()
        if key not in {"fullstack", "flat"}:
            continue
        if key not in normalized_allowed:
            normalized_allowed.append(key)
    if not normalized_allowed:
        normalized_allowed = ["fullstack", "flat"]
    preferred = str(prefer_layout or "").strip().lower()
    ordered = [preferred] if preferred in normalized_allowed else []
    ordered += [item for item in normalized_allowed if item != preferred]

    inspected = {layout: inspect_backend_layout(root, layout) for layout in ordered}
    for layout in ordered:
        entry = inspected[layout]
        if bool(entry.get("main_exists")) and bool(entry.get("requirements_exists")) and bool(entry.get("app_decl_ok")):
            target = "app.main:app"
            run_command = ["uvicorn", target, "--host", "0.0.0.0"]
            if port is not None:
                run_command += ["--port", str(int(port))]
            return {
                "ok": True,
                "layout": layout,
                "backend_entry": target,
                "backend_run_mode": "asgi-direct",
                "run_cwd": entry["run_cwd"],
                "run_command": run_command,
                "failure_reason": "",
            }

    reasons: list[str] = []
    for layout in ordered:
        entry = inspected[layout]
        main_rel = entry["main_py"].relative_to(root).as_posix()
        req_rel = entry["requirements"].relative_to(root).as_posix()
        if not bool(entry.get("main_exists")):
            reasons.append(f"missing backend entrypoint: {main_rel}")
        if not bool(entry.get("requirements_exists")):
            reasons.append(f"missing requirements: {req_rel}")
        if bool(entry.get("main_exists")) and not bool(entry.get("app_decl_ok")):
            reasons.append(f"invalid FastAPI app declaration in: {main_rel}")

    reason = "; ".join(reasons) if reasons else "backend entrypoint not found"
    return {
        "ok": False,
        "layout": "",
        "backend_entry": "",
        "backend_run_mode": "",
        "run_cwd": root,
        "run_command": [],
        "failure_reason": reason,
    }


def _contains_launcher_target(main_file: Path, target: str = "app.main:app") -> bool:
    if not main_file.exists() or not main_file.is_file():
        return False
    try:
        text = main_file.read_text(encoding="utf-8", errors="replace")
    except Exception:
        return False
    pattern = re.compile(rf"uvicorn\.run\(\s*['\"]{re.escape(target)}['\"]")
    return bool(pattern.search(text))


def detect_backend_runtime_entry(project_dir: Path, *, port: int) -> dict[str, Any]:
    root = project_dir.expanduser().resolve()
    asgi = detect_backend_asgi_entry(
        root,
        allowed_layouts=("fullstack", "flat"),
        prefer_layout="fullstack",
        port=port,
    )
    if bool(asgi.get("ok")):
        return {
            "ok": True,
            "failure_class": "",
            "failure_reason": "",
            "backend_entry": str(asgi.get("backend_entry") or "app.main:app"),
            "backend_run_mode": str(asgi.get("backend_run_mode") or "asgi-direct"),
            "run_cwd": asgi.get("run_cwd") or root,
            "run_command": [str(item) for item in (asgi.get("run_command") or [])],
        }

    if _contains_launcher_target(root / "main.py", "app.main:app"):
        return {
            "ok": True,
            "failure_class": "",
            "failure_reason": "",
            "backend_entry": "app.main:app",
            "backend_run_mode": "launcher-python",
            "run_cwd": root,
            "run_command": ["python", "main.py"],
        }

    return {
        "ok": False,
        "failure_class": "generation-error",
        "failure_reason": str(asgi.get("failure_reason") or "backend entrypoint not found"),
        "backend_entry": "",
        "backend_run_mode": "",
        "run_cwd": root,
        "run_command": [],
    }


def analyze_backend_failure(log_text: str) -> dict[str, Any]:
    text = str(log_text or "")
    lower = text.lower()

    if "address already in use" in lower:
        return {
            "type": "port_in_use",
            "package": "",
            "detail": "address already in use",
        }

    missing_match = re.search(r"No module named ['\"]([^'\"]+)['\"]", text)
    if missing_match:
        pkg = str(missing_match.group(1) or "").strip().split(".")[0]
        return {
            "type": "missing_dependency",
            "package": pkg,
            "detail": f"missing dependency: {pkg}" if pkg else "missing dependency",
        }
    if "modulenotfounderror" in lower or "importerror" in lower:
        return {
            "type": "missing_dependency",
            "package": "",
            "detail": "python import failed",
        }

    if "sqlite3.operationalerror" in lower or "no such table" in lower:
        return {
            "type": "db_not_initialized",
            "package": "",
            "detail": "database is not initialized",
        }

    if "environment variable" in lower or "settings" in lower:
        return {
            "type": "env_missing",
            "package": "",
            "detail": "runtime env configuration is missing",
        }

    return {
        "type": "unknown",
        "package": "",
        "detail": "unknown runtime failure",
    }
