from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any


def _read_package_json(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}
    return payload if isinstance(payload, dict) else {}


def _detect_frontend_dir(project_dir: Path) -> Path | None:
    root = project_dir.expanduser().resolve()
    frontend_pkg = root / "frontend" / "package.json"
    if frontend_pkg.exists():
        return frontend_pkg.parent
    root_pkg = root / "package.json"
    if root_pkg.exists():
        return root
    return None


def _parse_port_from_text(text: str) -> int | None:
    raw = str(text or "").strip()
    if not raw:
        return None
    match = re.search(r":(\d+)(?:/|$)", raw)
    if not match:
        return None
    try:
        value = int(match.group(1))
    except Exception:
        return None
    return value if value > 0 else None


def _parse_port_from_script(script: str) -> int | None:
    text = str(script or "").strip()
    if not text:
        return None
    match = re.search(r"(?:--port|-p)\s*(?:=|\s)\s*(\d+)", text)
    if not match:
        return None
    try:
        value = int(match.group(1))
    except Exception:
        return None
    return value if value > 0 else None


def detect_frontend_runtime_entry(
    project_dir: Path,
    *,
    port: int | None = None,
    backend_base_url: str | None = None,
) -> dict[str, Any]:
    root = project_dir.expanduser().resolve()
    frontend_dir = _detect_frontend_dir(root)
    if frontend_dir is None:
        return {
            "ok": False,
            "frontend_present": False,
            "failure_class": "generation-error",
            "failure_reason": "frontend package.json not found",
            "run_cwd": "",
            "run_command": [],
            "frontend_run_mode": "",
            "frontend_port": None,
            "frontend_url": "",
            "backend_base_url": str(backend_base_url or "").strip(),
        }

    package_json_path = frontend_dir / "package.json"
    package_json = _read_package_json(package_json_path)
    scripts = package_json.get("scripts") if isinstance(package_json.get("scripts"), dict) else {}
    dev_script = str(scripts.get("dev") or "").strip()
    deps = package_json.get("dependencies") if isinstance(package_json.get("dependencies"), dict) else {}
    dev_deps = package_json.get("devDependencies") if isinstance(package_json.get("devDependencies"), dict) else {}
    has_next_dependency = "next" in deps or "next" in dev_deps
    # Backward-compatible default for simple frontend scaffolds that omit scripts/dev.
    if not dev_script and not has_next_dependency:
        dev_script = "npm run dev"

    script_port = _parse_port_from_script(dev_script)
    selected_port = int(port) if port else (script_port or 3000)
    uses_next = "next" in dev_script.lower() or has_next_dependency
    if uses_next:
        # Use package-script execution from the detected frontend directory.
        # This keeps Next.js package resolution pinned to the project-local dependency.
        run_command = [
            "npm",
            "run",
            "dev",
            "--",
            "--hostname",
            "0.0.0.0",
            "--port",
            str(selected_port),
        ]
        frontend_run_mode = "next-dev"
        framework = "nextjs"
    else:
        # Generic dev servers (e.g. Vite) typically use `--host` for non-local binding.
        run_command = [
            "npm",
            "run",
            "dev",
            "--",
            "--host",
            "0.0.0.0",
            "--port",
            str(selected_port),
        ]
        frontend_run_mode = "npm-dev"
        framework = "generic"
    return {
        "ok": True,
        "frontend_present": True,
        "failure_class": "",
        "failure_reason": "",
        "run_cwd": str(frontend_dir),
        "run_command": run_command,
        "frontend_run_mode": frontend_run_mode,
        "frontend_port": selected_port,
        "frontend_url": f"http://127.0.0.1:{selected_port}",
        "backend_base_url": str(backend_base_url or "").strip(),
        "dev_script": dev_script,
        "uses_next": uses_next,
        "framework": framework,
        "script_port": script_port,
    }


def frontend_runtime_port_hint(url: str) -> int | None:
    return _parse_port_from_text(url)
