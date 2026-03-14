from __future__ import annotations

import subprocess
import shutil
from pathlib import Path
from typing import Any


MOCK_RAILWAY_URL = "https://example.up.railway.app"


def detect_deploy_target(project_dir: Path) -> str:
    del project_dir
    return "railway"


def can_deploy_to_railway() -> tuple[bool, str]:
    if shutil.which("railway") is None:
        return False, "railway CLI not installed"
    try:
        completed = subprocess.run(  # noqa: S603
            ["railway", "--version"],
            capture_output=True,
            text=True,
            timeout=15,
            shell=False,
            check=False,
        )
    except Exception as exc:
        return False, f"railway CLI check failed: {exc}"
    if completed.returncode != 0:
        detail = (completed.stderr or completed.stdout or "").strip() or "railway CLI not usable"
        return False, detail
    return True, "railway CLI available"


def _deploy_fail(target: str, detail: str) -> dict[str, Any]:
    return {
        "ok": False,
        "target": target,
        "mode": "mock",
        "status": "FAIL",
        "url": None,
        "detail": detail,
    }


def deploy_to_railway(project_dir: Path, allow_real_deploy: bool = False) -> dict[str, Any]:
    project_dir = project_dir.expanduser().resolve()
    if not project_dir.exists() or not project_dir.is_dir():
        return _deploy_fail("railway", f"path is not a directory: {project_dir}")

    can_deploy, detail = can_deploy_to_railway()
    if not can_deploy:
        return _deploy_fail("railway", detail)

    if not allow_real_deploy:
        return {
            "ok": True,
            "target": "railway",
            "mode": "mock",
            "status": "SUCCESS",
            "url": MOCK_RAILWAY_URL,
            "detail": "mock deploy success (real deploy disabled)",
        }

    return {
        "ok": True,
        "target": "railway",
        "mode": "check-only",
        "status": "SUCCESS",
        "url": None,
        "detail": "real deploy placeholder: verified railway CLI only",
    }


def deploy_project(
    project_dir: Path,
    target: str = "railway",
    allow_real_deploy: bool = False,
) -> dict[str, Any]:
    project_dir = project_dir.expanduser().resolve()
    resolved_target = (target or "").strip().lower()
    if not resolved_target:
        resolved_target = detect_deploy_target(project_dir)
    if resolved_target == "railway":
        return deploy_to_railway(project_dir, allow_real_deploy=allow_real_deploy)
    return _deploy_fail(resolved_target or "unknown", f"unsupported deploy target: {resolved_target or 'unknown'}")
