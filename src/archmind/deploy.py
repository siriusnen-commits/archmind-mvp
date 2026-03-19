from __future__ import annotations

import json
import os
import re
import signal
import socket
import shutil
import subprocess
import time
from pathlib import Path
from typing import Any
from urllib import error, parse, request

from archmind.state import ensure_state, load_state, update_after_deploy, write_state


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
    app_main_root = root / "app" / "main.py"
    app_main_backend = root / "backend" / "app" / "main.py"
    launcher_main = root / "main.py"
    launcher_mode = _contains_launcher_target(launcher_main, "app.main:app")

    if app_main_root.exists():
        target = "app.main:app"
        run_cwd = root
        return {
            "ok": True,
            "failure_class": "",
            "failure_reason": "",
            "backend_entry": target,
            "backend_run_mode": "asgi-direct",
            "run_cwd": run_cwd,
            "run_command": ["uvicorn", target, "--host", "0.0.0.0", "--port", str(int(port))],
            "launcher_mode_detected": launcher_mode,
        }
    if app_main_backend.exists():
        target = "app.main:app"
        run_cwd = root / "backend"
        return {
            "ok": True,
            "failure_class": "",
            "failure_reason": "",
            "backend_entry": target,
            "backend_run_mode": "asgi-direct",
            "run_cwd": run_cwd,
            "run_command": ["uvicorn", target, "--host", "0.0.0.0", "--port", str(int(port))],
            "launcher_mode_detected": launcher_mode,
        }

    if launcher_mode:
        return {
            "ok": True,
            "failure_class": "",
            "failure_reason": "",
            "backend_entry": "app.main:app",
            "backend_run_mode": "launcher-python",
            "run_cwd": root,
            "run_command": ["python", "main.py"],
            "launcher_mode_detected": True,
        }

    reason = "backend entrypoint not found"
    return {
        "ok": False,
        "failure_class": "generation-error",
        "failure_reason": reason,
        "backend_entry": "",
        "backend_run_mode": "",
        "run_cwd": root,
        "run_command": [],
        "launcher_mode_detected": False,
    }


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
            "virtualenv",
            "venv",
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


def _backend_smoke_with_retry(base_url: str, attempts: int = 5, interval_s: float = 0.4) -> dict[str, Any]:
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
            ),
            "failure_class": failure_class,
            "backend_entry": backend_entry,
            "backend_run_mode": backend_run_mode,
            "run_cwd": str(run_cwd or root),
            "run_command": " ".join(run_command),
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
        "failure_class": str(backend.get("failure_class") or ""),
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
        "failure_class": str(backend.get("failure_class") or ""),
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
    backend_pid = _to_pid(state.get("backend_pid"))
    frontend_pid = _to_pid(state.get("frontend_pid"))
    backend_running = is_pid_running(backend_pid)
    frontend_running = is_pid_running(frontend_pid)
    deploy_target = str(state.get("deploy_target") or "").strip().lower()
    backend_url = str(state.get("backend_deploy_url") or state.get("deploy_url") or "").strip()
    frontend_url = str(state.get("frontend_deploy_url") or "").strip()

    return {
        "project_dir": root,
        "project_name": root.name,
        "deploy_target": deploy_target,
        "backend": {
            "status": "RUNNING" if backend_running else "NOT RUNNING",
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
        return "STOPPED", ""
    except ProcessLookupError:
        return "NOT RUNNING", ""
    except Exception as exc:
        return "WARNING", str(exc)


def stop_local_services(project_dir: Path) -> dict[str, Any]:
    root = project_dir.expanduser().resolve()
    payload = load_state(root) or ensure_state(root)
    backend_pid = _to_pid(payload.get("backend_pid"))
    frontend_pid = _to_pid(payload.get("frontend_pid"))

    backend_status, backend_detail = _stop_pid(backend_pid)
    frontend_status, frontend_detail = _stop_pid(frontend_pid)

    payload["backend_pid"] = None
    payload["frontend_pid"] = None
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


def restart_local_services(project_dir: Path) -> dict[str, Any]:
    root = project_dir.expanduser().resolve()
    before = get_local_runtime_status(root)
    backend_was_running = str(before.get("backend", {}).get("status") or "") == "RUNNING"
    frontend_was_running = str(before.get("frontend", {}).get("status") or "") == "RUNNING"

    stop_result = stop_local_services(root)
    if not backend_was_running and not frontend_was_running:
        return {
            "ok": True,
            "target": "local",
            "backend": {"status": "NOT RUNNING", "url": "", "detail": ""},
            "frontend": {"status": "NOT RUNNING", "url": "", "detail": ""},
            "stop": stop_result,
        }

    restart_kind = "fullstack" if (backend_was_running and frontend_was_running) else ("backend" if backend_was_running else "frontend")
    deploy_result = deploy_to_local(root, kind=restart_kind)
    update_after_deploy(root, deploy_result, action="archmind restart --path <project>")

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
