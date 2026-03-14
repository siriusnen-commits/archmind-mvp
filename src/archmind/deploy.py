from __future__ import annotations

import re
import shutil
import subprocess
from pathlib import Path
from typing import Any


MOCK_RAILWAY_URL = "https://example.up.railway.app"
_RAILWAY_DOMAIN_RE = re.compile(r"https://[a-z0-9-]+\.up\.railway\.app")


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


def _deploy_fail(target: str, detail: str, *, mode: str = "mock") -> dict[str, Any]:
    return {
        "ok": False,
        "target": target,
        "mode": mode,
        "status": "FAIL",
        "url": None,
        "detail": detail,
    }


def generate_deploy_slug(project_name: str) -> str:
    raw = str(project_name or "").strip().lower().replace("_", "-")
    raw = re.sub(r"[^a-z0-9-]+", "-", raw)
    raw = re.sub(r"-+", "-", raw).strip("-")
    tokens = [t for t in raw.split("-") if t]
    stopwords = {"the", "and", "with", "for", "to", "from", "on", "in", "of", "by", "at", "a", "an"}
    filtered = [t for t in tokens if not t.isdigit() and t not in stopwords]
    if not filtered:
        filtered = ["archmind", "app"]

    selected: list[str]
    if "api" in filtered:
        api_idx = len(filtered) - 1 - filtered[::-1].index("api")
        before = [t for t in filtered[:api_idx] if t not in {"service", "backend", "project"}]
        selected = []
        if before:
            selected.append(before[0])
        if len(before) > 1:
            selected.append(before[1])
        selected.append("api")
    elif "app" in filtered:
        app_idx = len(filtered) - 1 - filtered[::-1].index("app")
        before = [t for t in filtered[:app_idx] if t not in {"service", "project"}]
        selected = []
        if before:
            selected.append(before[0])
        if len(before) > 1:
            selected.append(before[1])
        selected.append("app")
    else:
        selected = filtered[-3:]

    if not selected:
        selected = ["archmind", "app"]

    slug = re.sub(r"[^a-z0-9-]+", "-", "-".join(selected))
    slug = re.sub(r"-+", "-", slug).strip("-")
    if not slug:
        slug = "archmind-app"
    if not slug[0].isalpha():
        slug = f"archmind-{slug}"
    slug = slug[:40].strip("-")
    if not slug:
        slug = "archmind-app"
    if not slug[0].isalpha():
        slug = f"archmind-{slug}"
    return slug[:40].strip("-")


def _run_railway(cmd: list[str], *, cwd: Path | None = None) -> subprocess.CompletedProcess[str]:
    return subprocess.run(  # noqa: S603
        cmd,
        cwd=cwd,
        capture_output=True,
        text=True,
        timeout=60,
        shell=False,
        check=False,
    )


def deploy_to_railway_mock(project_dir: Path) -> dict[str, Any]:
    project_dir = project_dir.expanduser().resolve()
    if not project_dir.exists() or not project_dir.is_dir():
        return _deploy_fail("railway", f"path is not a directory: {project_dir}", mode="mock")

    can_deploy, detail = can_deploy_to_railway()
    if not can_deploy:
        return _deploy_fail("railway", detail, mode="mock")

    return {
        "ok": True,
        "target": "railway",
        "mode": "mock",
        "status": "SUCCESS",
        "url": MOCK_RAILWAY_URL,
        "detail": "mock deploy success (real deploy disabled)",
    }


def deploy_to_railway_real(project_dir: Path) -> dict[str, Any]:
    project_dir = project_dir.expanduser().resolve()
    if not project_dir.exists() or not project_dir.is_dir():
        return _deploy_fail("railway", f"path is not a directory: {project_dir}", mode="real")

    slug = generate_deploy_slug(project_dir.name)
    can_deploy, detail = can_deploy_to_railway()
    if not can_deploy:
        return _deploy_fail("railway", detail, mode="real")

    init_result = _run_railway(["railway", "init", "--name", slug], cwd=project_dir)
    if init_result.returncode != 0:
        init_text = f"{init_result.stdout}\n{init_result.stderr}".lower()
        already_exists = "already" in init_text and ("exist" in init_text or "linked" in init_text or "project" in init_text)
        if not already_exists:
            detail_text = (init_result.stderr or init_result.stdout or "").strip() or "railway init failed"
            return _deploy_fail("railway", detail_text, mode="real")

    up_result = _run_railway(["railway", "up", "--detach"], cwd=project_dir)
    if up_result.returncode != 0:
        detail_text = (up_result.stderr or up_result.stdout or "").strip() or "railway deploy failed"
        return _deploy_fail("railway", detail_text, mode="real")

    domain_result = _run_railway(["railway", "domain"], cwd=project_dir)
    domain_text = f"{domain_result.stdout}\n{domain_result.stderr}"
    domain_match = _RAILWAY_DOMAIN_RE.search(domain_text)
    deploy_url = domain_match.group(0) if domain_match else None

    return {
        "ok": True,
        "target": "railway",
        "mode": "real",
        "status": "SUCCESS",
        "url": deploy_url,
        "detail": "railway deploy success",
    }


def deploy_to_railway(project_dir: Path, allow_real_deploy: bool = False) -> dict[str, Any]:
    if allow_real_deploy:
        return deploy_to_railway_real(project_dir)
    return deploy_to_railway_mock(project_dir)


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
        if allow_real_deploy:
            return deploy_to_railway_real(project_dir)
        return deploy_to_railway_mock(project_dir)
    return _deploy_fail(
        resolved_target or "unknown",
        f"unsupported deploy target: {resolved_target or 'unknown'}",
        mode="real" if allow_real_deploy else "mock",
    )
