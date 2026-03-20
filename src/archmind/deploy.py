from __future__ import annotations

import json
import os
import re
import signal
import socket
import shutil
import subprocess
import sys
import time
from pathlib import Path
from typing import Any
from urllib import error, parse, request

from archmind.backend_runtime import (
    analyze_backend_failure,
    detect_backend_runtime_entry as detect_backend_runtime_entry_shared,
)
from archmind.state import ensure_state, load_state, update_after_deploy, update_runtime_state, write_state


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
        "backend_smoke_url": "",
        "backend_smoke_status": "SKIPPED",
        "backend_smoke_detail": "deploy failed before smoke check",
        "frontend_smoke_url": "",
        "frontend_smoke_status": "SKIPPED",
        "frontend_smoke_detail": "deploy failed before smoke check",
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
            (root / "app" / "main.py").exists(),
            (root / "backend" / "app").is_dir(),
            (root / "backend" / "app" / "main.py").exists(),
            (root / "requirements.txt").exists(),
            (root / "backend" / "requirements.txt").exists(),
            (root / "pytest.ini").exists(),
            (root / "backend" / "pytest.ini").exists(),
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


def verify_frontend_smoke(
    deploy_url: str,
    timeout_s: float = 10.0,
) -> dict[str, Any]:
    base = str(deploy_url or "").strip()
    if not base:
        return {
            "url": "",
            "status": "SKIPPED",
            "detail": "frontend deploy URL missing",
        }
    parsed = parse.urlparse(base)
    if parsed.scheme not in ("http", "https") or not parsed.netloc:
        return {
            "url": base,
            "status": "FAIL",
            "detail": "invalid frontend deploy URL",
        }
    req = request.Request(base, method="GET")
    try:
        with request.urlopen(req, timeout=timeout_s) as response:  # noqa: S310
            status_code = int(response.getcode() or 0)
    except error.URLError as exc:
        return {
            "url": base,
            "status": "FAIL",
            "detail": f"request failed: {exc.reason}",
        }
    except Exception as exc:
        return {
            "url": base,
            "status": "FAIL",
            "detail": f"request failed: {exc}",
        }

    if 200 <= status_code < 300:
        return {
            "url": base,
            "status": "SUCCESS",
            "detail": f"frontend URL returned HTTP {status_code}",
        }
    return {
        "url": base,
        "status": "FAIL",
        "detail": f"frontend URL returned HTTP {status_code}",
    }


def _service_result(status: str, url: str | None, detail: str) -> dict[str, Any]:
    return {
        "status": status,
        "url": url,
        "detail": detail,
    }


def find_free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def _detect_lan_ip() -> str:
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        sock.connect(("8.8.8.8", 80))
        return str(sock.getsockname()[0] or "").strip()
    except Exception:
        return ""
    finally:
        sock.close()


def _backend_env_file(root: Path) -> Path:
    return root / "backend" / ".env"


def _build_runtime_urls(backend_port: int | None, frontend_port: int | None) -> tuple[str, list[str]]:
    backend_base_url = f"http://127.0.0.1:{int(backend_port)}" if backend_port else ""
    origins: list[str] = []
    if frontend_port:
        p = int(frontend_port)
        origins.append(f"http://localhost:{p}")
        origins.append(f"http://127.0.0.1:{p}")
        external_frontend_url = os.getenv("ARCHMIND_EXTERNAL_FRONTEND_URL", "").strip()
        if external_frontend_url:
            origins.append(external_frontend_url)
        else:
            lan_ip = _detect_lan_ip()
            if lan_ip:
                origins.append(f"http://{lan_ip}:{p}")
    deduped: list[str] = []
    seen: set[str] = set()
    for item in origins:
        v = str(item).strip()
        if not v or v in seen:
            continue
        seen.add(v)
        deduped.append(v)
    return backend_base_url, deduped


def _write_runtime_env_files(
    root: Path,
    *,
    backend_port: int | None = None,
    frontend_port: int | None = None,
    backend_base_url: str | None = None,
) -> dict[str, str]:
    # Runtime is the single source of truth for backend/frontend connectivity.
    # Inject ports + URLs before process startup so templates can stay env-driven.
    backend_env_path = _backend_env_file(root)
    legacy_backend_env_path = root / ".env"
    frontend_dir = get_frontend_deploy_dir(root)
    if frontend_dir is None and (root / "frontend").is_dir():
        frontend_dir = root / "frontend"
    frontend_env_path = (frontend_dir / ".env.local") if frontend_dir is not None else None

    resolved_backend_url, cors_origins = _build_runtime_urls(backend_port, frontend_port)
    if backend_base_url is not None and str(backend_base_url).strip():
        resolved_backend_url = str(backend_base_url).strip()

    backend_lines = []
    if backend_port:
        backend_lines.append(f"APP_PORT={int(backend_port)}")
    if resolved_backend_url:
        backend_lines.append(f"BACKEND_BASE_URL={resolved_backend_url}")
    backend_lines.append(f"CORS_ALLOW_ORIGINS={','.join(cors_origins)}")
    backend_env_path.parent.mkdir(parents=True, exist_ok=True)
    backend_payload = "\n".join(backend_lines) + "\n"
    backend_env_path.write_text(backend_payload, encoding="utf-8")
    # Keep root .env for templates/projects that still read env_file=".env".
    legacy_backend_env_path.write_text(backend_payload, encoding="utf-8")

    if frontend_env_path is not None:
        frontend_lines = []
        if resolved_backend_url:
            frontend_lines.append(f"NEXT_PUBLIC_API_BASE_URL={resolved_backend_url}")
        if frontend_port:
            frontend_lines.append(f"NEXT_PUBLIC_FRONTEND_PORT={int(frontend_port)}")
        frontend_env_path.parent.mkdir(parents=True, exist_ok=True)
        frontend_env_path.write_text("\n".join(frontend_lines) + "\n", encoding="utf-8")

    return {
        "backend_env": str(backend_env_path),
        "frontend_env": str(frontend_env_path) if frontend_env_path is not None else "",
        "backend_base_url": resolved_backend_url,
        "cors_allow_origins": ",".join(cors_origins),
    }


def _read_env_key_values(path: Path) -> dict[str, str]:
    if not path.exists() or not path.is_file():
        return {}
    try:
        lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    except Exception:
        return {}
    out: dict[str, str] = {}
    for raw in lines:
        line = str(raw).strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        k = key.strip()
        if not k:
            continue
        out[k] = value.strip()
    return out


def _ensure_env_keys(path: Path, defaults: dict[str, str]) -> dict[str, Any]:
    existing_text = ""
    if path.exists() and path.is_file():
        try:
            existing_text = path.read_text(encoding="utf-8", errors="replace")
        except Exception:
            existing_text = ""
    lines = existing_text.splitlines() if existing_text else []
    keys = {line.split("=", 1)[0].strip() for line in lines if "=" in line and str(line).strip() and not str(line).strip().startswith("#")}
    added: list[str] = []
    for key, value in defaults.items():
        if key in keys:
            continue
        lines.append(f"{key}={value}")
        added.append(key)
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = "\n".join(lines).strip()
    if payload:
        payload += "\n"
    try:
        path.write_text(payload, encoding="utf-8")
    except Exception:
        return {"ok": False, "added_keys": added}
    return {"ok": True, "added_keys": added}


def ensure_runtime_env_defaults(
    project_dir: Path,
    *,
    backend_port: int | None = None,
    frontend_port: int | None = None,
) -> dict[str, Any]:
    root = project_dir.expanduser().resolve()
    resolved_backend_port = int(backend_port) if backend_port else 8000
    resolved_frontend_port = int(frontend_port) if frontend_port else 3000
    backend_base_url, cors_origins = _build_runtime_urls(resolved_backend_port, resolved_frontend_port)

    backend_defaults = {
        "APP_PORT": str(resolved_backend_port),
        "BACKEND_BASE_URL": backend_base_url,
        "CORS_ALLOW_ORIGINS": ",".join(cors_origins),
    }
    backend_dir_mode = (root / "backend").is_dir()
    backend_env_path = (root / "backend" / ".env") if backend_dir_mode else (root / ".env")
    backend_result = _ensure_env_keys(backend_env_path, backend_defaults)

    root_env_result: dict[str, Any] = {"ok": True, "added_keys": []}
    if backend_dir_mode:
        root_env_result = _ensure_env_keys(root / ".env", backend_defaults)

    frontend_env_path: Path | None = None
    frontend_result: dict[str, Any] = {"ok": True, "added_keys": []}
    frontend_dir = get_frontend_deploy_dir(root)
    if frontend_dir is None and (root / "frontend").is_dir():
        frontend_dir = root / "frontend"
    if frontend_dir is not None:
        frontend_env_path = frontend_dir / ".env.local"
        frontend_defaults = {
            "NEXT_PUBLIC_API_BASE_URL": backend_base_url,
            "NEXT_PUBLIC_FRONTEND_PORT": str(resolved_frontend_port),
        }
        frontend_result = _ensure_env_keys(frontend_env_path, frontend_defaults)

    ok = bool(backend_result.get("ok")) and bool(root_env_result.get("ok")) and bool(frontend_result.get("ok"))
    return {
        "ok": ok,
        "backend_env": str(backend_env_path),
        "root_env": str(root / ".env"),
        "frontend_env": str(frontend_env_path) if frontend_env_path is not None else "",
        "backend_added_keys": list(backend_result.get("added_keys") or []),
        "root_added_keys": list(root_env_result.get("added_keys") or []),
        "frontend_added_keys": list(frontend_result.get("added_keys") or []),
        "backend_base_url": backend_base_url,
    }


def _placeholder_backend_url(project_dir: Path) -> str:
    slug = generate_deploy_slug(project_dir.name or "archmind-app")
    return f"https://api-{slug}.up.railway.app"


def _placeholder_frontend_url(project_dir: Path) -> str:
    slug = generate_deploy_slug(project_dir.name or "archmind-app")
    return f"https://web-{slug}.up.railway.app"


def _slug_with_suffix(project_dir: Path, suffix: str) -> str:
    base = generate_deploy_slug(project_dir.name or "archmind-app")
    suffix_clean = re.sub(r"[^a-z0-9-]+", "-", str(suffix or "").strip().lower()).strip("-")
    if not suffix_clean:
        return base
    candidate = f"{base}-{suffix_clean}"[:40].strip("-")
    if not candidate:
        return base
    return candidate


def get_frontend_deploy_dir(project_dir: Path) -> Path | None:
    root = project_dir.expanduser().resolve()
    frontend_pkg = root / "frontend" / "package.json"
    root_pkg = root / "package.json"
    if frontend_pkg.exists():
        return frontend_pkg.parent
    if root_pkg.exists():
        return root
    return None


def deploy_frontend_to_railway_real(project_dir: Path) -> dict[str, Any]:
    root = project_dir.expanduser().resolve()
    frontend_dir = get_frontend_deploy_dir(root)
    if frontend_dir is None:
        return _service_result("FAIL", None, "frontend deploy directory not found")

    can_deploy, detail = can_deploy_to_railway()
    if not can_deploy:
        return _service_result("FAIL", None, detail)

    slug = _slug_with_suffix(root, "web")
    init_result = _run_railway(["railway", "init", "--name", slug], cwd=frontend_dir)
    if init_result.returncode != 0:
        init_text = f"{init_result.stdout}\n{init_result.stderr}".lower()
        already_exists = "already" in init_text and ("exist" in init_text or "linked" in init_text or "project" in init_text)
        if not already_exists:
            detail_text = (init_result.stderr or init_result.stdout or "").strip() or "railway init failed"
            return _service_result("FAIL", None, detail_text)

    up_result = _run_railway(["railway", "up", "--detach"], cwd=frontend_dir)
    if up_result.returncode != 0:
        detail_text = (up_result.stderr or up_result.stdout or "").strip() or "railway up failed"
        return _service_result("FAIL", None, detail_text)

    domain_result = _run_railway(["railway", "domain"], cwd=frontend_dir)
    domain_text = f"{domain_result.stdout}\n{domain_result.stderr}"
    domain_match = _RAILWAY_DOMAIN_RE.search(domain_text)
    frontend_url = domain_match.group(0) if domain_match else None
    return _service_result("SUCCESS", frontend_url, "real frontend deploy success")


def _run_local_process(cmd: list[str], *, cwd: Path) -> subprocess.Popen[str]:
    return subprocess.Popen(  # noqa: S603
        cmd,
        cwd=cwd,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        text=True,
        shell=False,
        start_new_session=True,
    )


def read_last_lines(path: Path, lines: int = 20) -> str | None:
    target = path.expanduser().resolve()
    if not target.exists() or not target.is_file():
        return None
    try:
        content = target.read_text(encoding="utf-8", errors="replace").splitlines()
    except Exception:
        return None
    if not content:
        return None
    take = max(1, int(lines))
    return "\n".join(content[-take:])


def _run_local_process_with_log(cmd: list[str], *, cwd: Path, log_path: Path) -> subprocess.Popen[str]:
    log_path.parent.mkdir(parents=True, exist_ok=True)
    handle = open(log_path, "a", encoding="utf-8")
    try:
        proc = subprocess.Popen(  # noqa: S603
            cmd,
            cwd=cwd,
            stdout=handle,
            stderr=subprocess.STDOUT,
            text=True,
            shell=False,
            start_new_session=True,
        )
    finally:
        handle.close()
    return proc


def detect_backend_runtime_entry(project_dir: Path, *, port: int) -> dict[str, Any]:
    out = dict(detect_backend_runtime_entry_shared(project_dir, port=port))
    out["launcher_mode_detected"] = str(out.get("backend_run_mode") or "").strip() == "launcher-python"
    return out


def _classify_backend_runtime_failure(detail: str) -> str:
    text = str(detail or "").lower()
    if not text:
        return "runtime-entrypoint-error"
    if any(
        token in text
        for token in (
            "no module named 'app'",
            'no module named "app"',
            'attribute "app" not found in module "main"',
            "attribute 'app' not found in module 'main'",
        )
    ):
        return "runtime-entrypoint-error"
    if any(
        token in text
        for token in (
            "python: command not found",
            "python3: command not found",
            "no module named pip",
        )
    ):
        return "environment-python"
    if any(
        token in text
        for token in (
            "no module named fastapi",
            "no module named uvicorn",
            "no module named pydantic",
            "no module named sqlmodel",
            "module not found: fastapi",
            "module not found: uvicorn",
            "modulenotfounderror",
            "importerror",
        )
    ):
        return "dependency-error"
    return "runtime-entrypoint-error"


def _compose_backend_runtime_failure_detail(
    failure_class: str,
    reason: str,
    *,
    detected_target: str,
    run_cwd: Path,
    run_command: list[str],
    backend_run_mode: str = "",
    log_path: Path | None = None,
    stderr_tail: str = "",
) -> str:
    lines = [
        f"{failure_class}: {reason}",
        f"Detected backend target: {detected_target or '(none)'}",
        f"Backend run mode: {backend_run_mode or '(none)'}",
        f"Run cwd: {run_cwd}",
        f"Run command: {' '.join(run_command) if run_command else '(none)'}",
    ]
    if log_path is not None:
        lines.append(f"Log path: {log_path}")
    tail = str(stderr_tail or "").strip()
    if tail:
        lines += ["stderr (last 20 lines):", tail]
    else:
        lines += ["stderr (last 20 lines):", "(no stderr captured)"]
    return "\n".join(lines)


def _backend_smoke_with_retry(base_url: str, attempts: int = 12, interval_s: float = 0.5) -> dict[str, Any]:
    latest = verify_deploy_health(base_url)
    if str(latest.get("healthcheck_status") or "").upper() == "SUCCESS":
        return latest
    for _ in range(max(0, attempts - 1)):
        time.sleep(interval_s)
        latest = verify_deploy_health(base_url)
        if str(latest.get("healthcheck_status") or "").upper() == "SUCCESS":
            return latest
    return latest


def _frontend_smoke_with_retry(base_url: str, attempts: int = 5, interval_s: float = 0.4) -> dict[str, Any]:
    latest = verify_frontend_smoke(base_url)
    if str(latest.get("status") or "").upper() == "SUCCESS":
        return latest
    for _ in range(max(0, attempts - 1)):
        time.sleep(interval_s)
        latest = verify_frontend_smoke(base_url)
        if str(latest.get("status") or "").upper() == "SUCCESS":
            return latest
    return latest


def deploy_backend_local(project_dir: Path, *, port: int | None = None, frontend_port: int | None = None) -> dict[str, Any]:
    root = project_dir.expanduser().resolve()
    picked_port = int(port) if port else find_free_port()
    entry = detect_backend_runtime_entry(root, port=picked_port)
    run_cwd = entry.get("run_cwd")
    run_command = [str(x) for x in (entry.get("run_command") or [])]
    backend_entry = str(entry.get("backend_entry") or "")
    backend_run_mode = str(entry.get("backend_run_mode") or "")
    if not bool(entry.get("ok")):
        reason = str(entry.get("failure_reason") or "backend runtime entry detection failed")
        failure_class = str(entry.get("failure_class") or "generation-error")
        log_path = root / ".archmind" / "backend.log"
        return {
            "status": "FAIL",
            "url": None,
            "detail": _compose_backend_runtime_failure_detail(
                failure_class,
                reason,
                detected_target=backend_entry,
                run_cwd=Path(run_cwd) if isinstance(run_cwd, Path) else root,
                run_command=run_command,
                backend_run_mode=backend_run_mode,
                log_path=log_path,
            ),
            "failure_class": failure_class,
            "backend_entry": backend_entry,
            "backend_run_mode": backend_run_mode,
            "run_cwd": str(run_cwd or root),
            "run_command": " ".join(run_command),
            "backend_status": "FAIL",
            "backend_port": picked_port,
            "backend_log_path": str(log_path),
        }

    resolved_cwd = Path(run_cwd) if isinstance(run_cwd, Path) else root
    _write_runtime_env_files(root, backend_port=picked_port, frontend_port=frontend_port)
    log_path = root / ".archmind" / "backend.log"
    try:
        proc = _run_local_process_with_log(run_command, cwd=resolved_cwd, log_path=log_path)
    except Exception as exc:
        reason = f"local backend start failed: {exc}"
        failure_class = _classify_backend_runtime_failure(reason)
        return {
            "status": "FAIL",
            "url": None,
            "detail": _compose_backend_runtime_failure_detail(
                failure_class,
                reason,
                detected_target=backend_entry,
                run_cwd=resolved_cwd,
                run_command=run_command,
                backend_run_mode=backend_run_mode,
                log_path=log_path,
            ),
            "failure_class": failure_class,
            "backend_entry": backend_entry,
            "backend_run_mode": backend_run_mode,
            "run_cwd": str(resolved_cwd),
            "run_command": " ".join(run_command),
            "backend_status": "FAIL",
            "backend_port": picked_port,
            "backend_log_path": str(log_path),
        }
    time.sleep(0.35)
    exit_code = proc.poll()
    if exit_code is not None:
        stderr_tail = str(read_last_lines(log_path, lines=20) or "").strip()
        reason = f"backend process exited immediately (code={int(exit_code)})"
        failure_class = _classify_backend_runtime_failure(stderr_tail or reason)
        return {
            "status": "FAIL",
            "url": None,
            "detail": _compose_backend_runtime_failure_detail(
                failure_class,
                reason,
                detected_target=backend_entry,
                run_cwd=resolved_cwd,
                run_command=run_command,
                backend_run_mode=backend_run_mode,
                log_path=log_path,
                stderr_tail=stderr_tail,
            ),
            "failure_class": failure_class,
            "backend_entry": backend_entry,
            "backend_run_mode": backend_run_mode,
            "run_cwd": str(resolved_cwd),
            "run_command": " ".join(run_command),
            "backend_status": "FAIL",
            "backend_port": picked_port,
            "backend_log_path": str(log_path),
        }
    return {
        "status": "SUCCESS",
        "url": f"http://127.0.0.1:{picked_port}",
        "detail": "local backend started",
        "pid": int(proc.pid),
        "failure_class": "",
        "backend_entry": backend_entry,
        "backend_run_mode": backend_run_mode,
        "run_cwd": str(resolved_cwd),
        "run_command": " ".join(run_command),
        "backend_status": "RUNNING",
        "backend_port": picked_port,
        "backend_log_path": str(log_path),
    }


def _classify_runtime_execution_failure(log_text: str, reason: str) -> str:
    text = str(log_text or "").lower()
    if any(
        token in text
        for token in (
            "python: command not found",
            "python3: command not found",
            "modulenotfounderror",
            "importerror",
            "no module named",
            "traceback (most recent call last)",
        )
    ):
        return "environment-python"
    if "address already in use" in text:
        return "runtime-execution-error"
    if "command not found" in text:
        return "runtime-execution-error"
    if reason:
        return "runtime-execution-error"
    return "runtime-execution-error"


def _has_error_marker(log_text: str) -> bool:
    text = str(log_text or "")
    if not text.strip():
        return False
    return "ERROR" in text.upper()


def _stop_pid_safe(pid: Any) -> None:
    parsed = _to_pid(pid)
    if parsed is None:
        return
    try:
        os.kill(parsed, signal.SIGTERM)
    except Exception:
        return


def _init_db(project_dir: Path) -> tuple[bool, str]:
    root = project_dir.expanduser().resolve()
    candidates = [
        [sys.executable, "-m", "app.db.init_db"],
        [sys.executable, "-m", "app.db.init"],
        [sys.executable, "-m", "app.init_db"],
    ]
    for cmd in candidates:
        try:
            completed = subprocess.run(  # noqa: S603
                cmd,
                cwd=root,
                capture_output=True,
                text=True,
                timeout=20,
                shell=False,
                check=False,
            )
        except Exception as exc:
            return False, f"db init execution failed: {exc}"
        if completed.returncode == 0:
            return True, "database initialized"
    return False, "db init command not available"


def _apply_default_env(project_dir: Path, app_port: int | None) -> tuple[bool, str]:
    root = project_dir.expanduser().resolve()
    env_example = root / ".env.example"
    env_path = root / ".env"
    if env_example.exists() and not env_path.exists():
        try:
            shutil.copyfile(env_example, env_path)
        except Exception as exc:
            return False, f".env copy failed: {exc}"
    lines: list[str] = []
    if env_path.exists():
        try:
            lines = env_path.read_text(encoding="utf-8", errors="replace").splitlines()
        except Exception:
            lines = []
    keys = {line.split("=", 1)[0].strip() for line in lines if "=" in line and str(line).strip()}
    if "APP_PORT" not in keys:
        lines.append(f"APP_PORT={int(app_port)}" if app_port else "APP_PORT=8000")
    if "BACKEND_BASE_URL" not in keys and app_port:
        lines.append(f"BACKEND_BASE_URL=http://127.0.0.1:{int(app_port)}")
    if "CORS_ALLOW_ORIGINS" not in keys:
        lines.append("CORS_ALLOW_ORIGINS=http://localhost:3000,http://127.0.0.1:3000")
    try:
        env_path.write_text("\n".join(lines).strip() + "\n", encoding="utf-8")
    except Exception as exc:
        return False, f".env write failed: {exc}"
    return True, "runtime env defaults applied"


def apply_auto_fix(
    project_dir: Path,
    analysis_result: dict[str, Any],
    *,
    used_fix_types: set[str] | None = None,
    current_port: int | None = None,
) -> dict[str, Any]:
    root = project_dir.expanduser().resolve()
    used = used_fix_types if used_fix_types is not None else set()
    fix_type = str(analysis_result.get("type") or "unknown").strip().lower()
    package = str(analysis_result.get("package") or "").strip()
    if not fix_type or fix_type == "unknown":
        return {"applied": False, "fix_type": "unknown", "detail": "auto-fix skipped: unknown failure type", "new_port": None, "package": ""}
    if fix_type in used:
        return {"applied": False, "fix_type": fix_type, "detail": f"auto-fix skipped: {fix_type} already attempted", "new_port": None, "package": package}

    if fix_type == "missing_dependency":
        if not package:
            return {"applied": False, "fix_type": fix_type, "detail": "auto-fix skipped: missing package name", "new_port": None, "package": ""}
        try:
            completed = subprocess.run(  # noqa: S603
                [sys.executable, "-m", "pip", "install", package],
                cwd=root,
                capture_output=True,
                text=True,
                timeout=90,
                shell=False,
                check=False,
            )
        except Exception as exc:
            return {"applied": False, "fix_type": fix_type, "detail": f"pip install failed: {exc}", "new_port": None, "package": package}
        if completed.returncode != 0:
            detail = (completed.stderr or completed.stdout or "").strip() or f"pip install {package} failed"
            return {"applied": False, "fix_type": fix_type, "detail": detail, "new_port": None, "package": package}
        return {"applied": True, "fix_type": fix_type, "detail": f"missing_dependency -> {package} installed", "new_port": None, "package": package}

    if fix_type == "db_not_initialized":
        ok, detail = _init_db(root)
        return {"applied": ok, "fix_type": fix_type, "detail": detail, "new_port": None, "package": ""}

    if fix_type == "env_missing":
        ok, detail = _apply_default_env(root, current_port)
        return {"applied": ok, "fix_type": fix_type, "detail": detail, "new_port": None, "package": ""}

    if fix_type == "port_in_use":
        next_port = find_free_port()
        if current_port is not None:
            attempts = 0
            while next_port == int(current_port) and attempts < 5:
                next_port = find_free_port()
                attempts += 1
        return {"applied": True, "fix_type": fix_type, "detail": f"port_in_use -> switched port to {int(next_port)}", "new_port": int(next_port), "package": ""}

    return {"applied": False, "fix_type": "unknown", "detail": "auto-fix skipped: unsupported failure type", "new_port": None, "package": package}


def _auto_fix_meta(history: list[dict[str, Any]], status: str) -> dict[str, Any]:
    last = history[-1] if history else {}
    return {
        "attempts": len(history),
        "last_fix": str(last.get("fix_type") or ""),
        "last_detail": str(last.get("detail") or ""),
        "status": status,
    }


def _is_port_available(port: int) -> bool:
    if int(port) <= 0:
        return False
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        try:
            sock.bind(("127.0.0.1", int(port)))
        except OSError:
            return False
    return True


def run_preflight_checks(project_dir: Path, *, requested_port: int | None = None) -> dict[str, Any]:
    root = project_dir.expanduser().resolve()
    issues_found: list[str] = []
    fixes_applied: list[str] = []
    used_fix_types: set[str] = set()
    selected_port = int(requested_port) if requested_port else 8000

    entry = detect_backend_runtime_entry(root, port=selected_port)
    if not bool(entry.get("ok")):
        issues_found.append(str(entry.get("failure_reason") or "backend entrypoint detection failed"))
        return {
            "ok": False,
            "fixed": False,
            "status": "FAILED",
            "fixes_applied": fixes_applied,
            "issues_found": issues_found,
            "selected_port": selected_port,
        }

    run_cwd = Path(entry.get("run_cwd") or root)
    req_candidates = [
        run_cwd / "requirements.txt",
        root / "requirements.txt",
        root / "backend" / "requirements.txt",
    ]
    req_path: Path | None = None
    for candidate in req_candidates:
        if candidate.exists() and candidate.is_file():
            req_path = candidate
            break
    if req_path is not None:
        completed = subprocess.run(  # noqa: S603
            [sys.executable, "-m", "pip", "install", "-r", str(req_path)],
            cwd=root,
            capture_output=True,
            text=True,
            timeout=120,
            shell=False,
            check=False,
        )
        if completed.returncode == 0:
            fixes_applied.append(f"installed requirements ({req_path.relative_to(root)})")
        else:
            detail = (completed.stderr or completed.stdout or "").strip() or "requirements install failed"
            issues_found.append(detail)

    env_ok, env_detail = _apply_default_env(root, selected_port)
    if env_ok:
        fixes_applied.append("created .env defaults")
    else:
        issues_found.append(env_detail)

    probe = subprocess.run(  # noqa: S603
        [sys.executable, "-c", "import app.main"],
        cwd=run_cwd,
        capture_output=True,
        text=True,
        timeout=20,
        shell=False,
        check=False,
    )
    if probe.returncode != 0:
        raw = (probe.stderr or probe.stdout or "").strip()
        issues_found.append(raw or "backend import probe failed")
        analysis = analyze_backend_failure(raw)
        fix = apply_auto_fix(root, analysis, used_fix_types=used_fix_types, current_port=selected_port)
        if bool(fix.get("applied")):
            used_fix_types.add(str(fix.get("fix_type") or ""))
            fixes_applied.append(str(fix.get("detail") or f"applied {fix.get('fix_type') or 'auto-fix'}"))
            if fix.get("new_port") is not None:
                selected_port = int(fix.get("new_port"))
            probe_retry = subprocess.run(  # noqa: S603
                [sys.executable, "-c", "import app.main"],
                cwd=run_cwd,
                capture_output=True,
                text=True,
                timeout=20,
                shell=False,
                check=False,
            )
            if probe_retry.returncode == 0 and issues_found:
                issues_found.pop()

    has_sqlite_db = any(root.glob("*.db")) or any((root / "backend").glob("*.db"))
    if not has_sqlite_db:
        fix = apply_auto_fix(
            root,
            {"type": "db_not_initialized", "package": "", "detail": "database file missing"},
            used_fix_types=used_fix_types,
            current_port=selected_port,
        )
        if bool(fix.get("applied")):
            used_fix_types.add(str(fix.get("fix_type") or ""))
            fixes_applied.append(str(fix.get("detail") or "database initialized"))
        else:
            db_detail = str(fix.get("detail") or "").strip()
            lowered = db_detail.lower()
            if "db init command not available" in lowered:
                fixes_applied.append("db init skipped (no explicit init command)")
            else:
                issues_found.append(db_detail or "database initialization failed")

    if not _is_port_available(selected_port):
        fix = apply_auto_fix(
            root,
            {"type": "port_in_use", "package": "", "detail": "address already in use"},
            used_fix_types=used_fix_types,
            current_port=selected_port,
        )
        if bool(fix.get("applied")) and fix.get("new_port") is not None:
            used_fix_types.add(str(fix.get("fix_type") or ""))
            selected_port = int(fix.get("new_port"))
            fixes_applied.append(str(fix.get("detail") or f"switched port to {selected_port}"))
        else:
            issues_found.append("port allocation failed")

    ok = len(issues_found) == 0
    fixed = len(fixes_applied) > 0
    status = "OK" if ok and not fixed else ("FIXED" if ok and fixed else "FAILED")
    return {
        "ok": ok,
        "fixed": fixed,
        "status": status,
        "fixes_applied": fixes_applied,
        "issues_found": issues_found,
        "selected_port": selected_port,
    }


def run_backend_local_with_health(project_dir: Path, *, port: int | None = None) -> dict[str, Any]:
    root = project_dir.expanduser().resolve()
    max_retries = 2
    current_port = int(port) if port else None
    preflight = run_preflight_checks(root, requested_port=current_port)
    selected = preflight.get("selected_port")
    if selected is not None and str(selected).isdigit():
        current_port = int(selected)
    if not bool(preflight.get("ok")):
        issue_lines = [str(item).strip() for item in (preflight.get("issues_found") or []) if str(item).strip()]
        detail = "preflight failed before backend execution"
        if issue_lines:
            detail = f"{detail}\n" + "\n".join(issue_lines[:5])
        return {
            "ok": False,
            "target": "local",
            "mode": "real",
            "kind": "backend",
            "status": "FAIL",
            "url": "",
            "detail": detail,
            "failure_class": "runtime-execution-error",
            "backend_status": "FAIL",
            "healthcheck_url": "",
            "healthcheck_status": "SKIPPED",
            "healthcheck_detail": "preflight failed",
            "backend_smoke_url": "",
            "backend_smoke_status": "SKIPPED",
            "backend_smoke_detail": "preflight failed",
            "frontend_smoke_url": "",
            "frontend_smoke_status": "SKIPPED",
            "frontend_smoke_detail": "frontend not deployed",
            "auto_fix": _auto_fix_meta([], "SKIPPED"),
            "preflight": preflight,
        }

    used_fix_types: set[str] = set()
    auto_fix_history: list[dict[str, Any]] = []

    for attempt in range(max_retries + 1):
        backend = deploy_backend_local(root, port=current_port)
        backend_ok = str(backend.get("status") or "").upper() == "SUCCESS"
        backend_url = str(backend.get("url") or "").strip()
        backend_port = int(backend.get("backend_port") or 0) if str(backend.get("backend_port") or "").isdigit() else current_port
        backend_log_path = str(backend.get("backend_log_path") or (root / ".archmind" / "backend.log"))
        log_tail_100 = str(read_last_lines(Path(backend_log_path), lines=100) or "").strip()

        if not backend_ok:
            failure_class = str(backend.get("failure_class") or "runtime-execution-error")
            if failure_class == "generation-error":
                return {
                    "ok": False,
                    "target": "local",
                    "mode": "real",
                    "kind": "backend",
                    "status": "FAIL",
                    "url": "",
                    "detail": str(backend.get("detail") or "backend start failed"),
                    "failure_class": failure_class,
                    "backend_entry": str(backend.get("backend_entry") or ""),
                    "backend_run_mode": str(backend.get("backend_run_mode") or ""),
                    "run_cwd": str(backend.get("run_cwd") or ""),
                    "run_command": str(backend.get("run_command") or ""),
                    "backend_pid": backend.get("pid"),
                    "backend_port": backend_port,
                    "backend_log_path": backend_log_path,
                    "backend_status": "FAIL",
                    "healthcheck_url": "",
                    "healthcheck_status": "SKIPPED",
                    "healthcheck_detail": "backend deploy failed",
                    "backend_smoke_url": "",
                    "backend_smoke_status": "SKIPPED",
                    "backend_smoke_detail": "backend deploy failed",
                    "frontend_smoke_url": "",
                    "frontend_smoke_status": "SKIPPED",
                    "frontend_smoke_detail": "frontend not deployed",
                    "auto_fix": _auto_fix_meta(auto_fix_history, "FAILED"),
                    "preflight": preflight,
                }

            if attempt < max_retries:
                analysis = analyze_backend_failure(f"{str(backend.get('detail') or '')}\n{log_tail_100}")
                fix = apply_auto_fix(root, analysis, used_fix_types=used_fix_types, current_port=backend_port)
                if bool(fix.get("applied")):
                    used_fix_types.add(str(fix.get("fix_type") or ""))
                    auto_fix_history.append(
                        {
                            "attempt": attempt + 1,
                            "fix_type": str(fix.get("fix_type") or ""),
                            "detail": str(fix.get("detail") or ""),
                            "analysis_type": str(analysis.get("type") or ""),
                        }
                    )
                    if fix.get("new_port") is not None:
                        current_port = int(fix.get("new_port"))
                    continue

            return {
                "ok": False,
                "target": "local",
                "mode": "real",
                "kind": "backend",
                "status": "FAIL",
                "url": "",
                "detail": str(backend.get("detail") or "backend start failed"),
                "failure_class": failure_class,
                "backend_entry": str(backend.get("backend_entry") or ""),
                "backend_run_mode": str(backend.get("backend_run_mode") or ""),
                "run_cwd": str(backend.get("run_cwd") or ""),
                "run_command": str(backend.get("run_command") or ""),
                "backend_pid": backend.get("pid"),
                "backend_port": backend_port,
                "backend_log_path": backend_log_path,
                "backend_status": "FAIL",
                "healthcheck_url": "",
                "healthcheck_status": "SKIPPED",
                "healthcheck_detail": "backend deploy failed",
                "backend_smoke_url": "",
                "backend_smoke_status": "SKIPPED",
                "backend_smoke_detail": "backend deploy failed",
                "frontend_smoke_url": "",
                "frontend_smoke_status": "SKIPPED",
                "frontend_smoke_detail": "frontend not deployed",
                "auto_fix": _auto_fix_meta(auto_fix_history, "FAILED"),
                "preflight": preflight,
            }

        backend_smoke = _backend_smoke_with_retry(backend_url)
        smoke_ok = str(backend_smoke.get("healthcheck_status") or "").upper() == "SUCCESS"
        has_error = _has_error_marker(log_tail_100)
        if smoke_ok and not has_error:
            detail_text = str(backend.get("detail") or "local backend started")
            auto_fix_meta = _auto_fix_meta(auto_fix_history, "SUCCESS" if auto_fix_history else "SKIPPED")
            if auto_fix_history:
                detail_text = f"{detail_text}\nAuto-fix applied: {auto_fix_meta.get('last_detail') or auto_fix_meta.get('last_fix')}"
            return {
                "ok": True,
                "target": "local",
                "mode": "real",
                "kind": "backend",
                "status": "SUCCESS",
                "url": backend_url,
                "detail": detail_text,
                "failure_class": "",
                "backend_entry": str(backend.get("backend_entry") or ""),
                "backend_run_mode": str(backend.get("backend_run_mode") or ""),
                "run_cwd": str(backend.get("run_cwd") or ""),
                "run_command": str(backend.get("run_command") or ""),
                "backend_pid": backend.get("pid"),
                "backend_port": backend_port,
                "backend_log_path": backend_log_path,
                "backend_status": "RUNNING",
                "healthcheck_url": str(backend_smoke.get("healthcheck_url") or ""),
                "healthcheck_status": "SUCCESS",
                "healthcheck_detail": str(backend_smoke.get("healthcheck_detail") or "health endpoint returned status ok"),
                "backend_smoke_url": str(backend_smoke.get("healthcheck_url") or ""),
                "backend_smoke_status": "SUCCESS",
                "backend_smoke_detail": str(backend_smoke.get("healthcheck_detail") or "health endpoint returned status ok"),
                "frontend_smoke_url": "",
                "frontend_smoke_status": "SKIPPED",
                "frontend_smoke_detail": "frontend not deployed",
                "auto_fix": auto_fix_meta,
                "preflight": preflight,
            }

        failure_reason = "backend log contains ERROR marker" if has_error else str(backend_smoke.get("healthcheck_detail") or "backend health check failed").strip()
        analysis = analyze_backend_failure(f"{failure_reason}\n{log_tail_100}")
        _stop_pid_safe(backend.get("pid"))

        if attempt < max_retries:
            fix = apply_auto_fix(root, analysis, used_fix_types=used_fix_types, current_port=backend_port)
            if bool(fix.get("applied")):
                used_fix_types.add(str(fix.get("fix_type") or ""))
                auto_fix_history.append(
                    {
                        "attempt": attempt + 1,
                        "fix_type": str(fix.get("fix_type") or ""),
                        "detail": str(fix.get("detail") or ""),
                        "analysis_type": str(analysis.get("type") or ""),
                    }
                )
                if fix.get("new_port") is not None:
                    current_port = int(fix.get("new_port"))
                continue

        stderr_tail = str(read_last_lines(Path(backend_log_path), lines=20) or "").strip()
        failure_class = _classify_runtime_execution_failure(stderr_tail, failure_reason)
        return {
            "ok": False,
            "target": "local",
            "mode": "real",
            "kind": "backend",
            "status": "FAIL",
            "url": backend_url,
            "detail": _compose_backend_runtime_failure_detail(
                failure_class,
                failure_reason,
                detected_target=str(backend.get("backend_entry") or ""),
                run_cwd=Path(str(backend.get("run_cwd") or root)),
                run_command=[x for x in str(backend.get("run_command") or "").split(" ") if x],
                backend_run_mode=str(backend.get("backend_run_mode") or ""),
                log_path=Path(backend_log_path),
                stderr_tail=stderr_tail,
            ),
            "failure_class": failure_class,
            "backend_entry": str(backend.get("backend_entry") or ""),
            "backend_run_mode": str(backend.get("backend_run_mode") or ""),
            "run_cwd": str(backend.get("run_cwd") or ""),
            "run_command": str(backend.get("run_command") or ""),
            "backend_pid": backend.get("pid"),
            "backend_port": backend_port,
            "backend_log_path": backend_log_path,
            "backend_status": "FAIL",
            "healthcheck_url": str(backend_smoke.get("healthcheck_url") or ""),
            "healthcheck_status": str(backend_smoke.get("healthcheck_status") or "FAIL"),
            "healthcheck_detail": failure_reason,
            "backend_smoke_url": str(backend_smoke.get("healthcheck_url") or ""),
            "backend_smoke_status": str(backend_smoke.get("healthcheck_status") or "FAIL"),
            "backend_smoke_detail": failure_reason,
            "frontend_smoke_url": "",
            "frontend_smoke_status": "SKIPPED",
            "frontend_smoke_detail": "frontend not deployed",
            "auto_fix": _auto_fix_meta(auto_fix_history, "FAILED"),
            "preflight": preflight,
        }

    return {
        "ok": False,
        "target": "local",
        "mode": "real",
        "kind": "backend",
        "status": "FAIL",
        "url": "",
        "detail": "runtime retry limit exceeded",
        "failure_class": "runtime-execution-error",
        "backend_status": "FAIL",
        "auto_fix": _auto_fix_meta(auto_fix_history, "FAILED"),
        "preflight": preflight,
    }


def deploy_frontend_local(
    project_dir: Path,
    *,
    port: int | None = None,
    backend_base_url: str | None = None,
) -> dict[str, Any]:
    root = project_dir.expanduser().resolve()
    frontend_dir = get_frontend_deploy_dir(root)
    if frontend_dir is None:
        return _service_result("FAIL", None, "frontend deploy directory not found")
    picked_port = int(port) if port else find_free_port()
    _write_runtime_env_files(root, frontend_port=picked_port, backend_base_url=backend_base_url)
    cmd = ["npm", "run", "dev", "--", "--hostname", "0.0.0.0", "--port", str(picked_port)]
    try:
        proc = _run_local_process_with_log(cmd, cwd=frontend_dir, log_path=(root / ".archmind" / "frontend.log"))
    except Exception as exc:
        return _service_result("FAIL", None, f"local frontend start failed: {exc}")
    return {
        "status": "SUCCESS",
        "url": f"http://127.0.0.1:{picked_port}",
        "detail": "local frontend started",
        "pid": int(proc.pid),
    }


def deploy_fullstack_local(project_dir: Path) -> dict[str, Any]:
    backend_port = find_free_port()
    frontend_port = find_free_port()
    while frontend_port == backend_port:
        frontend_port = find_free_port()
    _write_runtime_env_files(project_dir.expanduser().resolve(), backend_port=backend_port, frontend_port=frontend_port)
    backend = deploy_backend_local(project_dir, port=backend_port, frontend_port=frontend_port)
    backend_url = str(backend.get("url") or "")
    frontend = deploy_frontend_local(project_dir, port=frontend_port, backend_base_url=backend_url)
    backend_ok = str(backend.get("status") or "").upper() == "SUCCESS"
    frontend_ok = str(frontend.get("status") or "").upper() == "SUCCESS"
    backend_smoke = (
        _backend_smoke_with_retry(str(backend.get("url") or ""))
        if backend_ok
        else {"healthcheck_url": "", "healthcheck_status": "SKIPPED", "healthcheck_detail": "backend deploy failed"}
    )
    frontend_smoke = (
        _frontend_smoke_with_retry(str(frontend.get("url") or ""))
        if frontend_ok
        else {"url": "", "status": "SKIPPED", "detail": "frontend deploy failed"}
    )
    runtime_failure_class = str(backend.get("failure_class") or "").strip() if not backend_ok else ""
    return {
        "ok": backend_ok or frontend_ok,
        "target": "local",
        "mode": "real",
        "kind": "fullstack",
        "status": "SUCCESS" if (backend_ok and frontend_ok) else "FAIL",
        "url": frontend.get("url") or backend.get("url"),
        "detail": "local fullstack deploy completed",
        "backend": _service_result(str(backend.get("status") or "FAIL"), backend.get("url"), str(backend.get("detail") or "")),
        "frontend": _service_result(str(frontend.get("status") or "FAIL"), frontend.get("url"), str(frontend.get("detail") or "")),
        "failure_class": runtime_failure_class,
        "backend_entry": str(backend.get("backend_entry") or ""),
        "backend_run_mode": str(backend.get("backend_run_mode") or ""),
        "run_cwd": str(backend.get("run_cwd") or ""),
        "run_command": str(backend.get("run_command") or ""),
        "backend_pid": backend.get("pid"),
        "frontend_pid": frontend.get("pid"),
        "healthcheck_url": str(backend_smoke.get("healthcheck_url") or ""),
        "healthcheck_status": str(backend_smoke.get("healthcheck_status") or "SKIPPED"),
        "healthcheck_detail": str(backend_smoke.get("healthcheck_detail") or ""),
        "backend_smoke_url": str(backend_smoke.get("healthcheck_url") or ""),
        "backend_smoke_status": str(backend_smoke.get("healthcheck_status") or "SKIPPED"),
        "backend_smoke_detail": str(backend_smoke.get("healthcheck_detail") or ""),
        "frontend_smoke_url": str(frontend_smoke.get("url") or ""),
        "frontend_smoke_status": str(frontend_smoke.get("status") or "SKIPPED"),
        "frontend_smoke_detail": str(frontend_smoke.get("detail") or ""),
    }


def deploy_to_local(project_dir: Path, kind: str = "backend") -> dict[str, Any]:
    root = project_dir.expanduser().resolve()
    if not root.exists() or not root.is_dir():
        return _deploy_fail("local", f"path is not a directory: {root}", mode="real")

    if kind == "fullstack":
        return deploy_fullstack_local(root)
    if kind == "frontend":
        state = load_state(root) or {}
        backend_url = str(state.get("backend_deploy_url") or state.get("deploy_url") or "").strip()
        frontend = deploy_frontend_local(root, backend_base_url=backend_url or None)
        ok = str(frontend.get("status") or "").upper() == "SUCCESS"
        frontend_smoke = (
            _frontend_smoke_with_retry(str(frontend.get("url") or ""))
            if ok
            else {"url": "", "status": "SKIPPED", "detail": "frontend deploy failed"}
        )
        return {
            "ok": ok,
            "target": "local",
            "mode": "real",
            "kind": "frontend",
            "status": "SUCCESS" if ok else "FAIL",
            "url": frontend.get("url"),
            "detail": str(frontend.get("detail") or ""),
            "frontend_pid": frontend.get("pid"),
            "healthcheck_url": "",
            "healthcheck_status": "SKIPPED",
            "healthcheck_detail": "backend not deployed",
            "backend_smoke_url": "",
            "backend_smoke_status": "SKIPPED",
            "backend_smoke_detail": "backend not deployed",
            "frontend_smoke_url": str(frontend_smoke.get("url") or ""),
            "frontend_smoke_status": str(frontend_smoke.get("status") or "SKIPPED"),
            "frontend_smoke_detail": str(frontend_smoke.get("detail") or ""),
        }

    state = load_state(root) or {}
    frontend_url = str(state.get("frontend_deploy_url") or "").strip()
    frontend_port = None
    match = re.match(r"^https?://[^:/]+:(\d+)", frontend_url)
    if match:
        frontend_port = int(match.group(1))
    backend = deploy_backend_local(root, frontend_port=frontend_port)
    ok = str(backend.get("status") or "").upper() == "SUCCESS"
    runtime_failure_class = str(backend.get("failure_class") or "").strip() if not ok else ""
    backend_smoke = (
        _backend_smoke_with_retry(str(backend.get("url") or ""))
        if ok
        else {"healthcheck_url": "", "healthcheck_status": "SKIPPED", "healthcheck_detail": "backend deploy failed"}
    )
    return {
        "ok": ok,
        "target": "local",
        "mode": "real",
        "kind": "backend",
        "status": "SUCCESS" if ok else "FAIL",
        "url": backend.get("url"),
        "detail": str(backend.get("detail") or ""),
        "failure_class": runtime_failure_class,
        "backend_entry": str(backend.get("backend_entry") or ""),
        "backend_run_mode": str(backend.get("backend_run_mode") or ""),
        "run_cwd": str(backend.get("run_cwd") or ""),
        "run_command": str(backend.get("run_command") or ""),
        "backend_pid": backend.get("pid"),
        "healthcheck_url": str(backend_smoke.get("healthcheck_url") or ""),
        "healthcheck_status": str(backend_smoke.get("healthcheck_status") or "SKIPPED"),
        "healthcheck_detail": str(backend_smoke.get("healthcheck_detail") or ""),
        "backend_smoke_url": str(backend_smoke.get("healthcheck_url") or ""),
        "backend_smoke_status": str(backend_smoke.get("healthcheck_status") or "SKIPPED"),
        "backend_smoke_detail": str(backend_smoke.get("healthcheck_detail") or ""),
        "frontend_smoke_url": "",
        "frontend_smoke_status": "SKIPPED",
        "frontend_smoke_detail": "frontend not deployed",
    }


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
            "backend_smoke_url": "",
            "backend_smoke_status": "SKIPPED",
            "backend_smoke_detail": "mock deploy mode",
            "frontend_smoke_url": "",
            "frontend_smoke_status": "SKIPPED",
            "frontend_smoke_detail": "mock deploy mode",
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
            "backend_smoke_url": "",
            "backend_smoke_status": "SKIPPED",
            "backend_smoke_detail": "backend not deployed",
            "frontend_smoke_url": "",
            "frontend_smoke_status": "SKIPPED",
            "frontend_smoke_detail": "mock deploy mode",
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
        "backend_smoke_url": "",
        "backend_smoke_status": "SKIPPED",
        "backend_smoke_detail": "mock deploy mode",
        "frontend_smoke_url": "",
        "frontend_smoke_status": "SKIPPED",
        "frontend_smoke_detail": "frontend not deployed",
    }


def deploy_to_railway_real(project_dir: Path, kind: str = "backend") -> dict[str, Any]:
    if kind == "frontend":
        frontend_result = deploy_frontend_to_railway_real(project_dir)
        frontend_ok = str(frontend_result.get("status") or "").upper() == "SUCCESS"
        frontend_smoke = verify_frontend_smoke(str(frontend_result.get("url") or "")) if frontend_ok else {
            "url": str(frontend_result.get("url") or ""),
            "status": "SKIPPED",
            "detail": "frontend deploy failed",
        }
        return {
            "ok": frontend_ok,
            "target": "railway",
            "mode": "real",
            "kind": "frontend",
            "status": "SUCCESS" if frontend_ok else "FAIL",
            "url": frontend_result.get("url"),
            "detail": str(frontend_result.get("detail") or ""),
            "healthcheck_url": "",
            "healthcheck_status": "SKIPPED",
            "healthcheck_detail": "frontend health check not implemented",
            "backend_smoke_url": "",
            "backend_smoke_status": "SKIPPED",
            "backend_smoke_detail": "backend not deployed",
            "frontend_smoke_url": str(frontend_smoke.get("url") or ""),
            "frontend_smoke_status": str(frontend_smoke.get("status") or "SKIPPED"),
            "frontend_smoke_detail": str(frontend_smoke.get("detail") or ""),
        }
    if kind == "fullstack":
        backend_result = deploy_to_railway_real(project_dir, kind="backend")
        frontend_result = deploy_frontend_to_railway_real(project_dir)
        backend_ok = bool(backend_result.get("ok"))
        frontend_ok = str(frontend_result.get("status") or "").upper() == "SUCCESS"
        top_status = "SUCCESS" if (backend_ok and frontend_ok) else "FAIL"
        frontend_smoke = verify_frontend_smoke(str(frontend_result.get("url") or "")) if frontend_ok else {
            "url": str(frontend_result.get("url") or ""),
            "status": "SKIPPED",
            "detail": "frontend deploy failed",
        }
        return {
            "ok": backend_ok or frontend_ok,
            "target": "railway",
            "mode": "real",
            "kind": "fullstack",
            "status": top_status,
            "url": frontend_result.get("url") or backend_result.get("url"),
            "detail": "fullstack deploy completed",
            "backend": _service_result(
                str(backend_result.get("status") or "FAIL"),
                backend_result.get("url"),
                str(backend_result.get("detail") or ""),
            ),
            "frontend": frontend_result,
            "healthcheck_url": str(backend_result.get("healthcheck_url") or ""),
            "healthcheck_status": str(backend_result.get("healthcheck_status") or "SKIPPED"),
            "healthcheck_detail": str(backend_result.get("healthcheck_detail") or ""),
            "backend_smoke_url": str(backend_result.get("backend_smoke_url") or ""),
            "backend_smoke_status": str(backend_result.get("backend_smoke_status") or "SKIPPED"),
            "backend_smoke_detail": str(backend_result.get("backend_smoke_detail") or ""),
            "frontend_smoke_url": str(frontend_smoke.get("url") or ""),
            "frontend_smoke_status": str(frontend_smoke.get("status") or "SKIPPED"),
            "frontend_smoke_detail": str(frontend_smoke.get("detail") or ""),
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
        "backend_smoke_url": "",
        "backend_smoke_status": "SKIPPED",
        "backend_smoke_detail": "backend deploy URL missing",
        "frontend_smoke_url": "",
        "frontend_smoke_status": "SKIPPED",
        "frontend_smoke_detail": "frontend not deployed",
    }
    if deploy_url:
        health = verify_deploy_health(deploy_url)
        result.update(health)
        result["backend_smoke_url"] = str(health.get("healthcheck_url") or "")
        result["backend_smoke_status"] = str(health.get("healthcheck_status") or "FAIL")
        result["backend_smoke_detail"] = str(health.get("healthcheck_detail") or "")
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
    if resolved_target == "local":
        return deploy_to_local(project_dir, kind=kind)
    return _deploy_fail(
        resolved_target or "unknown",
        f"unsupported deploy target: {resolved_target or 'unknown'}",
        mode="real" if allow_real_deploy else "mock",
    )


def _to_pid(value: Any) -> int | None:
    try:
        pid = int(value)
    except Exception:
        return None
    return pid if pid > 0 else None


def is_pid_running(pid: int | None) -> bool:
    if pid is None:
        return False
    try:
        os.kill(pid, 0)
        return True
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    except Exception:
        return False


def get_local_runtime_status(project_dir: Path) -> dict[str, Any]:
    root = project_dir.expanduser().resolve()
    state = load_state(root) or {}
    runtime = state.get("runtime") if isinstance(state.get("runtime"), dict) else {}
    deploy = state.get("deploy") if isinstance(state.get("deploy"), dict) else {}
    backend_pid = _to_pid(runtime.get("backend_pid") if isinstance(runtime, dict) else state.get("backend_pid"))
    frontend_pid = _to_pid(state.get("frontend_pid"))
    backend_running = is_pid_running(backend_pid)
    frontend_running = is_pid_running(frontend_pid)
    deploy_target = str((deploy.get("target") if isinstance(deploy, dict) else "") or state.get("deploy_target") or "").strip().lower()
    backend_url = str(
        (runtime.get("backend_url") if isinstance(runtime, dict) else "")
        or (deploy.get("backend_url") if isinstance(deploy, dict) else "")
        or state.get("backend_deploy_url")
        or state.get("deploy_url")
        or ""
    ).strip()
    frontend_url = str((deploy.get("frontend_url") if isinstance(deploy, dict) else "") or state.get("frontend_deploy_url") or "").strip()
    backend_state_status = str((runtime.get("backend_status") if isinstance(runtime, dict) else "") or state.get("backend_status") or "").strip().upper()
    if backend_running:
        backend_status = "RUNNING"
    elif backend_state_status in {"FAIL", "WARNING"}:
        backend_status = backend_state_status
    else:
        backend_status = "NOT RUNNING"

    return {
        "project_dir": root,
        "project_name": root.name,
        "deploy_target": deploy_target,
        "backend": {
            "status": backend_status,
            "pid": backend_pid,
            "url": backend_url,
        },
        "frontend": {
            "status": "RUNNING" if frontend_running else "NOT RUNNING",
            "pid": frontend_pid,
            "url": frontend_url,
        },
        "running": backend_running or frontend_running,
        "mtime": (root / ".archmind" / "state.json").stat().st_mtime if (root / ".archmind" / "state.json").exists() else 0.0,
    }


def list_running_local_projects(projects_root: Path) -> list[dict[str, Any]]:
    root = projects_root.expanduser().resolve()
    if not root.exists() or not root.is_dir():
        return []

    rows: list[dict[str, Any]] = []
    for project_dir in root.iterdir():
        if not project_dir.is_dir():
            continue
        state_path = project_dir / ".archmind" / "state.json"
        if not state_path.exists():
            continue
        status = get_local_runtime_status(project_dir)
        backend_pid = status.get("backend", {}).get("pid") if isinstance(status.get("backend"), dict) else None
        frontend_pid = status.get("frontend", {}).get("pid") if isinstance(status.get("frontend"), dict) else None
        deploy_target = str(status.get("deploy_target") or "").strip().lower()
        candidate = deploy_target == "local" or backend_pid is not None or frontend_pid is not None
        if not candidate:
            continue
        if not bool(status.get("running")):
            continue
        rows.append(status)

    rows.sort(key=lambda item: float(item.get("mtime") or 0.0), reverse=True)
    return rows


def _stop_pid(pid: int | None) -> tuple[str, str]:
    if pid is None:
        return "NOT RUNNING", ""
    try:
        os.kill(pid, signal.SIGTERM)
        time.sleep(0.6)
        if not is_pid_running(pid):
            return "STOPPED", ""
        os.kill(pid, signal.SIGKILL)
        time.sleep(0.2)
        if not is_pid_running(pid):
            return "STOPPED", ""
        return "WARNING", "process still running after SIGKILL"
    except ProcessLookupError:
        return "NOT RUNNING", ""
    except Exception as exc:
        return "WARNING", str(exc)


def _is_local_service_responsive(url: str) -> bool:
    text = str(url or "").strip()
    if not text:
        return False
    try:
        parsed = parse.urlparse(text)
    except Exception:
        return False
    if parsed.scheme not in {"http", "https"}:
        return False
    if parsed.hostname not in {"127.0.0.1", "localhost"}:
        return False
    targets = [text]
    if parsed.path in {"", "/"}:
        targets.append(text.rstrip("/") + "/health")
    for target in targets:
        try:
            with request.urlopen(target, timeout=0.5) as response:  # noqa: S310
                code = int(getattr(response, "status", 0) or 0)
                if 200 <= code < 500:
                    return True
        except Exception:
            continue
    return False


def stop_local_services(project_dir: Path) -> dict[str, Any]:
    root = project_dir.expanduser().resolve()
    payload = load_state(root) or ensure_state(root)
    runtime_block = payload.get("runtime") if isinstance(payload.get("runtime"), dict) else {}
    deploy_block = payload.get("deploy") if isinstance(payload.get("deploy"), dict) else {}
    backend_pid = _to_pid(payload.get("backend_pid") or runtime_block.get("backend_pid"))
    frontend_pid = _to_pid(payload.get("frontend_pid") or runtime_block.get("frontend_pid"))
    backend_url = str(
        runtime_block.get("backend_url")
        or payload.get("backend_deploy_url")
        or deploy_block.get("backend_url")
        or payload.get("deploy_url")
        or ""
    ).strip()
    frontend_url = str(
        deploy_block.get("frontend_url")
        or payload.get("frontend_deploy_url")
        or runtime_block.get("frontend_url")
        or ""
    ).strip()

    backend_status, backend_detail = _stop_pid(backend_pid)
    frontend_status, frontend_detail = _stop_pid(frontend_pid)
    if backend_status == "WARNING" and backend_detail == "process still running after SIGKILL" and not _is_local_service_responsive(backend_url):
        backend_status, backend_detail = "STOPPED", "process lingering but backend service is down"
    if frontend_status == "WARNING" and frontend_detail == "process still running after SIGKILL" and not _is_local_service_responsive(frontend_url):
        frontend_status, frontend_detail = "STOPPED", "process lingering but frontend service is down"

    payload["backend_pid"] = None
    payload["frontend_pid"] = None
    runtime_block["backend_pid"] = None
    runtime_block["frontend_pid"] = None
    runtime_block["backend_status"] = "STOPPED" if backend_status == "STOPPED" else "NOT RUNNING"
    runtime_block["frontend_status"] = "STOPPED" if frontend_status == "STOPPED" else "NOT RUNNING"
    runtime_block["failure_class"] = ""
    runtime_block["healthcheck_status"] = ""
    runtime_block["healthcheck_detail"] = ""
    payload["runtime"] = runtime_block
    write_state(root, payload)

    return {
        "ok": backend_status != "WARNING" and frontend_status != "WARNING",
        "target": "local",
        "backend": {
            "status": backend_status,
            "pid": backend_pid,
            "detail": backend_detail,
        },
        "frontend": {
            "status": frontend_status,
            "pid": frontend_pid,
            "detail": frontend_detail,
        },
    }


def stop_all_local_services(projects_root: Path) -> dict[str, Any]:
    rows = list_running_local_projects(projects_root)
    stopped: list[dict[str, Any]] = []
    already_stopped: list[dict[str, Any]] = []
    failed: list[dict[str, Any]] = []

    for row in rows:
        project_dir = row.get("project_dir")
        if not isinstance(project_dir, Path):
            continue
        project_name = str(row.get("project_name") or project_dir.name)
        result = stop_local_services(project_dir)
        backend = result.get("backend") if isinstance(result.get("backend"), dict) else {}
        frontend = result.get("frontend") if isinstance(result.get("frontend"), dict) else {}
        backend_status = str(backend.get("status") or "NOT RUNNING").strip().upper()
        frontend_status = str(frontend.get("status") or "NOT RUNNING").strip().upper()
        backend_pid = backend.get("pid")
        frontend_pid = frontend.get("pid")
        backend_detail = str(backend.get("detail") or "").strip()
        frontend_detail = str(frontend.get("detail") or "").strip()
        item = {
            "project_name": project_name,
            "project_dir": project_dir,
            "backend_status": backend_status,
            "frontend_status": frontend_status,
            "backend_pid": backend_pid,
            "frontend_pid": frontend_pid,
            "backend_detail": backend_detail,
            "frontend_detail": frontend_detail,
        }
        if backend_status == "WARNING" or frontend_status == "WARNING":
            failed.append(item)
        elif backend_status == "STOPPED" or frontend_status == "STOPPED":
            stopped.append(item)
        else:
            already_stopped.append(item)

    return {
        "ok": len(failed) == 0,
        "target": "local",
        "stopped": stopped,
        "already_stopped": already_stopped,
        "failed": failed,
        "counts": {
            "stopped": len(stopped),
            "already_stopped": len(already_stopped),
            "failed": len(failed),
            "projects": len(rows),
        },
    }


def restart_local_services(project_dir: Path) -> dict[str, Any]:
    root = project_dir.expanduser().resolve()
    before = get_local_runtime_status(root)
    backend_was_running = str(before.get("backend", {}).get("status") or "") == "RUNNING"
    frontend_was_running = str(before.get("frontend", {}).get("status") or "") == "RUNNING"

    stop_result = stop_local_services(root)
    if not backend_was_running and not frontend_was_running:
        deploy_result = run_backend_local_with_health(root)
        update_runtime_state(root, deploy_result, action="archmind restart --path <project>")
        backend_ok = str(deploy_result.get("status") or "").upper() == "SUCCESS"
        return {
            "ok": backend_ok,
            "target": "local",
            "backend": {
                "status": "RESTARTED" if backend_ok else "FAIL",
                "url": str(deploy_result.get("url") or "").strip(),
                "detail": str(deploy_result.get("detail") or "").strip(),
            },
            "frontend": {"status": "NOT RUNNING", "url": "", "detail": ""},
            "stop": stop_result,
            "deploy": deploy_result,
        }

    restart_kind = "fullstack" if (backend_was_running and frontend_was_running) else ("backend" if backend_was_running else "frontend")
    deploy_result = deploy_to_local(root, kind=restart_kind)
    if restart_kind in {"backend", "fullstack"}:
        update_runtime_state(root, deploy_result, action="archmind restart --path <project>")

    backend_status = "NOT RUNNING"
    backend_url = ""
    backend_detail = ""
    if backend_was_running:
        backend_source = deploy_result
        if restart_kind == "fullstack":
            backend_source = deploy_result.get("backend") if isinstance(deploy_result.get("backend"), dict) else {}
        backend_ok = str(backend_source.get("status") or "").upper() == "SUCCESS"
        backend_status = "RESTARTED" if backend_ok else "FAIL"
        backend_url = str(backend_source.get("url") or "").strip()
        backend_detail = str(backend_source.get("detail") or "").strip()

    frontend_status = "NOT RUNNING"
    frontend_url = ""
    frontend_detail = ""
    if frontend_was_running:
        frontend_source = deploy_result
        if restart_kind == "fullstack":
            frontend_source = deploy_result.get("frontend") if isinstance(deploy_result.get("frontend"), dict) else {}
        frontend_ok = str(frontend_source.get("status") or "").upper() == "SUCCESS"
        frontend_status = "RESTARTED" if frontend_ok else "FAIL"
        frontend_url = str(frontend_source.get("url") or "").strip()
        frontend_detail = str(frontend_source.get("detail") or "").strip()

    ok = backend_status != "FAIL" and frontend_status != "FAIL"
    return {
        "ok": ok,
        "target": "local",
        "backend": {"status": backend_status, "url": backend_url, "detail": backend_detail},
        "frontend": {"status": frontend_status, "url": frontend_url, "detail": frontend_detail},
        "stop": stop_result,
        "deploy": deploy_result,
    }


def _parse_github_repo_slug(raw_url: str) -> str | None:
    text = str(raw_url or "").strip()
    if not text:
        return None
    http_match = re.search(r"github\.com[:/]+([A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+?)(?:\.git)?$", text)
    if http_match:
        return http_match.group(1)
    ssh_match = re.search(r"git@github\.com:([A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+?)(?:\.git)?$", text)
    if ssh_match:
        return ssh_match.group(1)
    return None


def _github_repo_slug_from_state_or_result(project_dir: Path) -> str | None:
    root = project_dir.expanduser().resolve()
    state = load_state(root) or {}
    state_url = str(state.get("github_repo_url") or "").strip()
    slug = _parse_github_repo_slug(state_url)
    if slug:
        return slug

    result_path = root / ".archmind" / "result.json"
    if result_path.exists():
        try:
            result = json.loads(result_path.read_text(encoding="utf-8"))
        except Exception:
            result = {}
        if isinstance(result, dict):
            result_url = str(result.get("github_repo_url") or "").strip()
            slug = _parse_github_repo_slug(result_url)
            if slug:
                return slug
    return None


def _github_repo_slug_from_git_remote(project_dir: Path) -> str | None:
    root = project_dir.expanduser().resolve()
    try:
        completed = subprocess.run(  # noqa: S603
            ["git", "-C", str(root), "remote", "get-url", "origin"],
            capture_output=True,
            text=True,
            timeout=10,
            shell=False,
            check=False,
        )
    except Exception:
        return None
    if completed.returncode != 0:
        return None
    return _parse_github_repo_slug(str(completed.stdout or "").strip())


def _resolve_github_repo_slug(project_dir: Path) -> str | None:
    slug = _github_repo_slug_from_state_or_result(project_dir)
    if slug:
        return slug
    return _github_repo_slug_from_git_remote(project_dir)


def delete_local_project(project_dir: Path) -> dict[str, Any]:
    root = project_dir.expanduser().resolve()
    stop_result = stop_local_services(root)
    if not root.exists():
        return {
            "ok": True,
            "mode": "local",
            "local_status": "SKIPPED",
            "local_detail": "project directory not found",
            "repo_status": "UNCHANGED",
            "repo_detail": "",
            "stop": stop_result,
        }
    try:
        shutil.rmtree(root)
    except Exception as exc:
        return {
            "ok": False,
            "mode": "local",
            "local_status": "FAIL",
            "local_detail": f"local delete failed: {exc}",
            "repo_status": "UNCHANGED",
            "repo_detail": "",
            "stop": stop_result,
        }
    return {
        "ok": True,
        "mode": "local",
        "local_status": "DELETED",
        "local_detail": "local project directory deleted",
        "repo_status": "UNCHANGED",
        "repo_detail": "",
        "stop": stop_result,
    }


def delete_github_repo(project_dir: Path) -> dict[str, Any]:
    root = project_dir.expanduser().resolve()
    slug = _resolve_github_repo_slug(root)
    if not slug:
        return {
            "ok": False,
            "mode": "repo",
            "repo_status": "SKIPPED",
            "repo_detail": "github repo url not found",
            "repo_slug": "",
        }
    try:
        completed = subprocess.run(  # noqa: S603
            ["gh", "repo", "delete", slug, "--yes"],
            capture_output=True,
            text=True,
            timeout=30,
            shell=False,
            check=False,
        )
    except Exception as exc:
        return {
            "ok": False,
            "mode": "repo",
            "repo_status": "FAIL",
            "repo_detail": f"github repo delete failed: {exc}",
            "repo_slug": slug,
        }
    if completed.returncode != 0:
        detail = (completed.stderr or completed.stdout or "").strip() or "github repo delete failed"
        return {
            "ok": False,
            "mode": "repo",
            "repo_status": "FAIL",
            "repo_detail": detail,
            "repo_slug": slug,
        }
    payload = load_state(root) or {}
    if payload:
        payload["github_repo_url"] = ""
        try:
            write_state(root, payload)
        except Exception:
            pass
    return {
        "ok": True,
        "mode": "repo",
        "repo_status": "DELETED",
        "repo_detail": "github repository deleted",
        "repo_slug": slug,
    }


def delete_project(project_dir: Path, mode: str = "local") -> dict[str, Any]:
    root = project_dir.expanduser().resolve()
    selected_mode = str(mode or "").strip().lower() or "local"
    if selected_mode not in ("local", "repo", "all"):
        return {
            "ok": False,
            "mode": selected_mode,
            "local_status": "UNCHANGED",
            "local_detail": "",
            "repo_status": "UNCHANGED",
            "repo_detail": f"unsupported delete mode: {selected_mode}",
        }

    if selected_mode == "local":
        return delete_local_project(root)
    if selected_mode == "repo":
        repo = delete_github_repo(root)
        return {
            "ok": bool(repo.get("ok")),
            "mode": "repo",
            "local_status": "UNCHANGED",
            "local_detail": "",
            "repo_status": str(repo.get("repo_status") or "UNCHANGED"),
            "repo_detail": str(repo.get("repo_detail") or ""),
            "repo_slug": str(repo.get("repo_slug") or ""),
        }

    repo = delete_github_repo(root)
    local = delete_local_project(root)
    return {
        "ok": bool(repo.get("ok")) and bool(local.get("ok")),
        "mode": "all",
        "local_status": str(local.get("local_status") or "UNCHANGED"),
        "local_detail": str(local.get("local_detail") or ""),
        "repo_status": str(repo.get("repo_status") or "UNCHANGED"),
        "repo_detail": str(repo.get("repo_detail") or ""),
        "repo_slug": str(repo.get("repo_slug") or ""),
    }
