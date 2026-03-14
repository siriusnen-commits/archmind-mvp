from __future__ import annotations

import json
import re
import shutil
import subprocess
from pathlib import Path
from typing import Any
from urllib import error, parse, request


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
        "kind": "backend",
        "status": "FAIL",
        "url": None,
        "detail": detail,
        "healthcheck_url": "",
        "healthcheck_status": "SKIPPED",
        "healthcheck_detail": "deploy failed before health check",
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


def detect_deploy_kind(project_dir: Path) -> str:
    root = project_dir.expanduser().resolve()
    has_backend = any(
        (
            (root / "app").is_dir(),
            (root / "requirements.txt").exists(),
            (root / "pytest.ini").exists(),
        )
    )
    has_frontend = any(
        (
            (root / "frontend").is_dir(),
            (root / "package.json").exists(),
            ((root / "next.config.mjs").exists() and (root / "app").is_dir()),
        )
    )
    if has_backend and has_frontend:
        return "fullstack"
    if has_frontend:
        return "frontend"
    return "backend"


def verify_deploy_health(
    deploy_url: str,
    path: str = "/health",
    timeout_s: float = 10.0,
) -> dict[str, Any]:
    base = str(deploy_url or "").strip()
    if not base:
        return {
            "healthcheck_url": "",
            "healthcheck_status": "SKIPPED",
            "healthcheck_detail": "deploy URL missing",
        }

    parsed = parse.urlparse(base)
    if parsed.scheme not in ("http", "https") or not parsed.netloc:
        return {
            "healthcheck_url": "",
            "healthcheck_status": "FAIL",
            "healthcheck_detail": "invalid deploy URL",
        }

    clean_path = "/" + str(path or "/health").lstrip("/")
    health_url = parse.urljoin(base.rstrip("/") + "/", clean_path.lstrip("/"))
    req = request.Request(health_url, method="GET")
    try:
        with request.urlopen(req, timeout=timeout_s) as response:  # noqa: S310
            status_code = int(response.getcode() or 0)
            body_text = response.read().decode("utf-8", errors="replace")
    except error.URLError as exc:
        return {
            "healthcheck_url": health_url,
            "healthcheck_status": "FAIL",
            "healthcheck_detail": f"health request failed: {exc.reason}",
        }
    except Exception as exc:
        return {
            "healthcheck_url": health_url,
            "healthcheck_status": "FAIL",
            "healthcheck_detail": f"health request failed: {exc}",
        }

    if status_code != 200:
        return {
            "healthcheck_url": health_url,
            "healthcheck_status": "FAIL",
            "healthcheck_detail": f"health endpoint returned HTTP {status_code}",
        }

    try:
        payload = json.loads(body_text)
    except Exception:
        payload = None
    if isinstance(payload, dict) and str(payload.get("status") or "").strip().lower() == "ok":
        return {
            "healthcheck_url": health_url,
            "healthcheck_status": "SUCCESS",
            "healthcheck_detail": "health endpoint returned status ok",
        }
    return {
        "healthcheck_url": health_url,
        "healthcheck_status": "FAIL",
        "healthcheck_detail": "unexpected response body",
    }


def _service_result(status: str, url: str | None, detail: str) -> dict[str, Any]:
    return {
        "status": status,
        "url": url,
        "detail": detail,
    }


def _placeholder_backend_url(project_dir: Path) -> str:
    slug = generate_deploy_slug(project_dir.name or "archmind-app")
    return f"https://api-{slug}.up.railway.app"


def _placeholder_frontend_url(project_dir: Path) -> str:
    slug = generate_deploy_slug(project_dir.name or "archmind-app")
    return f"https://web-{slug}.up.railway.app"


def deploy_to_railway_mock(project_dir: Path, kind: str = "backend") -> dict[str, Any]:
    project_dir = project_dir.expanduser().resolve()
    if not project_dir.exists() or not project_dir.is_dir():
        return _deploy_fail("railway", f"path is not a directory: {project_dir}", mode="mock")

    can_deploy, detail = can_deploy_to_railway()
    if not can_deploy:
        return _deploy_fail("railway", detail, mode="mock")

    if kind == "fullstack":
        backend_url = _placeholder_backend_url(project_dir)
        frontend_url = _placeholder_frontend_url(project_dir)
        return {
            "ok": True,
            "target": "railway",
            "mode": "mock",
            "kind": "fullstack",
            "status": "SUCCESS",
            "url": frontend_url,
            "detail": "mock fullstack deploy success",
            "backend": _service_result("SUCCESS", backend_url, "mock backend deploy success"),
            "frontend": _service_result("SUCCESS", frontend_url, "mock frontend deploy success"),
            "healthcheck_url": "",
            "healthcheck_status": "SKIPPED",
            "healthcheck_detail": "mock deploy mode",
        }
    if kind == "frontend":
        frontend_url = _placeholder_frontend_url(project_dir)
        return {
            "ok": True,
            "target": "railway",
            "mode": "mock",
            "kind": "frontend",
            "status": "SUCCESS",
            "url": frontend_url,
            "detail": "mock frontend deploy success",
            "healthcheck_url": "",
            "healthcheck_status": "SKIPPED",
            "healthcheck_detail": "frontend health check not implemented",
        }

    return {
        "ok": True,
        "target": "railway",
        "mode": "mock",
        "kind": "backend",
        "status": "SUCCESS",
        "url": MOCK_RAILWAY_URL,
        "detail": "mock deploy success (real deploy disabled)",
        "healthcheck_url": "",
        "healthcheck_status": "SKIPPED",
        "healthcheck_detail": "mock deploy mode",
    }


def deploy_to_railway_real(project_dir: Path, kind: str = "backend") -> dict[str, Any]:
    if kind == "frontend":
        return {
            "ok": True,
            "target": "railway",
            "mode": "real",
            "kind": "frontend",
            "status": "SUCCESS",
            "url": None,
            "detail": "real frontend deploy not implemented yet",
            "healthcheck_url": "",
            "healthcheck_status": "SKIPPED",
            "healthcheck_detail": "frontend health check not implemented",
        }
    if kind == "fullstack":
        backend_result = deploy_to_railway_real(project_dir, kind="backend")
        frontend_result = _service_result("SKIPPED", None, "real frontend deploy not implemented yet")
        top_status = "SUCCESS" if bool(backend_result.get("ok")) else "FAIL"
        return {
            "ok": bool(backend_result.get("ok")),
            "target": "railway",
            "mode": "real",
            "kind": "fullstack",
            "status": top_status,
            "url": backend_result.get("url"),
            "detail": "fullstack deploy completed (frontend skipped)",
            "backend": _service_result(
                str(backend_result.get("status") or "FAIL"),
                backend_result.get("url"),
                str(backend_result.get("detail") or ""),
            ),
            "frontend": frontend_result,
            "healthcheck_url": str(backend_result.get("healthcheck_url") or ""),
            "healthcheck_status": str(backend_result.get("healthcheck_status") or "SKIPPED"),
            "healthcheck_detail": str(backend_result.get("healthcheck_detail") or ""),
        }

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

    result: dict[str, Any] = {
        "ok": True,
        "target": "railway",
        "mode": "real",
        "kind": "backend",
        "status": "SUCCESS",
        "url": deploy_url,
        "detail": "railway deploy success",
        "healthcheck_url": "",
        "healthcheck_status": "SKIPPED",
        "healthcheck_detail": "deploy URL missing",
    }
    if deploy_url:
        result.update(verify_deploy_health(deploy_url))
    return result


def deploy_to_railway(project_dir: Path, allow_real_deploy: bool = False, kind: str = "backend") -> dict[str, Any]:
    if allow_real_deploy:
        return deploy_to_railway_real(project_dir, kind=kind)
    return deploy_to_railway_mock(project_dir, kind=kind)


def deploy_project(
    project_dir: Path,
    target: str = "railway",
    allow_real_deploy: bool = False,
) -> dict[str, Any]:
    project_dir = project_dir.expanduser().resolve()
    resolved_target = (target or "").strip().lower()
    if not resolved_target:
        resolved_target = detect_deploy_target(project_dir)
    kind = detect_deploy_kind(project_dir)
    if resolved_target == "railway":
        return deploy_to_railway(project_dir, allow_real_deploy=allow_real_deploy, kind=kind)
    return _deploy_fail(
        resolved_target or "unknown",
        f"unsupported deploy target: {resolved_target or 'unknown'}",
        mode="real" if allow_real_deploy else "mock",
    )
