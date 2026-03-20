from __future__ import annotations

from pathlib import Path

from archmind.backend_runtime import analyze_backend_failure
from archmind.deploy import run_backend_local_with_health


def test_analyze_backend_failure_missing_dependency() -> None:
    result = analyze_backend_failure("ModuleNotFoundError: No module named 'sqlmodel'")
    assert result["type"] == "missing_dependency"
    assert result["package"] == "sqlmodel"


def test_auto_fix_missing_dependency_then_success(monkeypatch, tmp_path: Path) -> None:
    calls = {"deploy": 0, "pip": 0}

    def fake_deploy(_p: Path, port=None):  # type: ignore[no-untyped-def]
        calls["deploy"] += 1
        if calls["deploy"] == 1:
            return {
                "status": "FAIL",
                "url": None,
                "detail": "ModuleNotFoundError: No module named 'sqlmodel'",
                "failure_class": "runtime-execution-error",
                "backend_entry": "app.main:app",
                "backend_run_mode": "asgi-direct",
                "run_cwd": str(tmp_path),
                "run_command": "uvicorn app.main:app --port 8121",
                "backend_port": 8121,
                "backend_log_path": str(tmp_path / ".archmind" / "backend.log"),
            }
        return {
            "status": "SUCCESS",
            "url": "http://127.0.0.1:8121",
            "detail": "local backend started",
            "pid": 9911,
            "backend_entry": "app.main:app",
            "backend_run_mode": "asgi-direct",
            "run_cwd": str(tmp_path),
            "run_command": "uvicorn app.main:app --port 8121",
            "backend_port": 8121,
            "backend_log_path": str(tmp_path / ".archmind" / "backend.log"),
        }

    class DummyCompleted:
        returncode = 0
        stdout = "installed"
        stderr = ""

    def fake_run(cmd, **_kwargs):  # type: ignore[no-untyped-def]
        if cmd[:4] == ["/Users/inkyun/.pyenv/versions/3.11.7/bin/python", "-m", "pip", "install"] or cmd[1:4] == ["-m", "pip", "install"]:
            calls["pip"] += 1
        return DummyCompleted()

    monkeypatch.setattr("archmind.deploy.deploy_backend_local", fake_deploy)
    monkeypatch.setattr("archmind.deploy.subprocess.run", fake_run)
    monkeypatch.setattr(
        "archmind.deploy._backend_smoke_with_retry",
        lambda _url: {"healthcheck_url": "http://127.0.0.1:8121/health", "healthcheck_status": "SUCCESS", "healthcheck_detail": "ok"},
    )
    monkeypatch.setattr("archmind.deploy.read_last_lines", lambda *_a, **_k: "")

    result = run_backend_local_with_health(tmp_path)
    assert result["ok"] is True
    assert result["status"] == "SUCCESS"
    assert result["auto_fix"]["attempts"] == 1
    assert result["auto_fix"]["last_fix"] == "missing_dependency"
    assert result["auto_fix"]["status"] == "SUCCESS"
    assert "sqlmodel installed" in str(result["auto_fix"]["last_detail"])
    assert calls["pip"] == 1


def test_auto_fix_db_init_then_success(monkeypatch, tmp_path: Path) -> None:
    calls = {"deploy": 0}

    def fake_deploy(_p: Path, port=None):  # type: ignore[no-untyped-def]
        calls["deploy"] += 1
        return {
            "status": "SUCCESS",
            "url": "http://127.0.0.1:8122",
            "detail": "local backend started",
            "pid": 9912,
            "backend_entry": "app.main:app",
            "backend_run_mode": "asgi-direct",
            "run_cwd": str(tmp_path),
            "run_command": "uvicorn app.main:app --port 8122",
            "backend_port": 8122,
            "backend_log_path": str(tmp_path / ".archmind" / "backend.log"),
        }

    smoke_calls = {"n": 0}

    def fake_smoke(_url: str):  # type: ignore[no-untyped-def]
        smoke_calls["n"] += 1
        if smoke_calls["n"] == 1:
            return {"healthcheck_url": "http://127.0.0.1:8122/health", "healthcheck_status": "FAIL", "healthcheck_detail": "health request failed"}
        return {"healthcheck_url": "http://127.0.0.1:8122/health", "healthcheck_status": "SUCCESS", "healthcheck_detail": "ok"}

    monkeypatch.setattr("archmind.deploy.deploy_backend_local", fake_deploy)
    monkeypatch.setattr("archmind.deploy._backend_smoke_with_retry", fake_smoke)
    log_calls = {"n": 0}

    def fake_read_last_lines(*_a, **_k):  # type: ignore[no-untyped-def]
        log_calls["n"] += 1
        if log_calls["n"] == 1:
            return "sqlite3.OperationalError: no such table: users"
        return ""

    monkeypatch.setattr("archmind.deploy.read_last_lines", fake_read_last_lines)
    monkeypatch.setattr("archmind.deploy._stop_pid_safe", lambda *_a, **_k: None)
    monkeypatch.setattr("archmind.deploy._init_db", lambda *_a, **_k: (True, "database initialized"))

    result = run_backend_local_with_health(tmp_path)
    assert result["ok"] is True
    assert result["auto_fix"]["attempts"] == 1
    assert result["auto_fix"]["last_fix"] == "db_not_initialized"
    assert result["auto_fix"]["status"] == "SUCCESS"


def test_auto_fix_port_in_use_switches_port(monkeypatch, tmp_path: Path) -> None:
    seen_ports: list[int | None] = []

    def fake_deploy(_p: Path, port=None):  # type: ignore[no-untyped-def]
        seen_ports.append(port)
        if len(seen_ports) == 1:
            return {
                "status": "FAIL",
                "url": None,
                "detail": "address already in use",
                "failure_class": "runtime-execution-error",
                "backend_entry": "app.main:app",
                "backend_run_mode": "asgi-direct",
                "run_cwd": str(tmp_path),
                "run_command": "uvicorn app.main:app --port 8123",
                "backend_port": 8123,
                "backend_log_path": str(tmp_path / ".archmind" / "backend.log"),
            }
        return {
            "status": "SUCCESS",
            "url": "http://127.0.0.1:9233",
            "detail": "local backend started",
            "pid": 9913,
            "backend_entry": "app.main:app",
            "backend_run_mode": "asgi-direct",
            "run_cwd": str(tmp_path),
            "run_command": "uvicorn app.main:app --port 9233",
            "backend_port": 9233,
            "backend_log_path": str(tmp_path / ".archmind" / "backend.log"),
        }

    monkeypatch.setattr("archmind.deploy.deploy_backend_local", fake_deploy)
    monkeypatch.setattr("archmind.deploy.find_free_port", lambda: 9233)
    monkeypatch.setattr(
        "archmind.deploy._backend_smoke_with_retry",
        lambda _url: {"healthcheck_url": "http://127.0.0.1:9233/health", "healthcheck_status": "SUCCESS", "healthcheck_detail": "ok"},
    )
    monkeypatch.setattr("archmind.deploy.read_last_lines", lambda *_a, **_k: "")

    result = run_backend_local_with_health(tmp_path)
    assert result["ok"] is True
    assert result["backend_port"] == 9233
    assert result["auto_fix"]["last_fix"] == "port_in_use"
    assert len(seen_ports) == 2
    assert seen_ports[1] == 9233


def test_auto_fix_unknown_skips_and_keeps_fail(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr(
        "archmind.deploy.deploy_backend_local",
        lambda *_a, **_k: {
            "status": "FAIL",
            "url": None,
            "detail": "unexpected startup crash",
            "failure_class": "runtime-execution-error",
            "backend_entry": "app.main:app",
            "backend_run_mode": "asgi-direct",
            "run_cwd": str(tmp_path),
            "run_command": "uvicorn app.main:app --port 8124",
            "backend_port": 8124,
            "backend_log_path": str(tmp_path / ".archmind" / "backend.log"),
        },
    )
    monkeypatch.setattr("archmind.deploy.read_last_lines", lambda *_a, **_k: "random failure without known marker")

    result = run_backend_local_with_health(tmp_path)
    assert result["ok"] is False
    assert result["status"] == "FAIL"
    assert result["auto_fix"]["attempts"] == 0
    assert result["auto_fix"]["status"] == "FAILED"


def test_auto_fix_retry_limited_to_two_attempts(monkeypatch, tmp_path: Path) -> None:
    deploy_calls = {"n": 0}

    def fake_deploy(*_a, **_k):  # type: ignore[no-untyped-def]
        deploy_calls["n"] += 1
        detail = "address already in use" if deploy_calls["n"] == 1 else ("settings validation error" if deploy_calls["n"] == 2 else "random unknown failure")
        return {
            "status": "FAIL",
            "url": None,
            "detail": detail,
            "failure_class": "runtime-execution-error",
            "backend_entry": "app.main:app",
            "backend_run_mode": "asgi-direct",
            "run_cwd": str(tmp_path),
            "run_command": "uvicorn app.main:app --port 8125",
            "backend_port": 8125,
            "backend_log_path": str(tmp_path / ".archmind" / "backend.log"),
        }

    monkeypatch.setattr(
        "archmind.deploy.deploy_backend_local",
        fake_deploy,
    )
    log_lines = iter(
        [
            "address already in use",
            "settings validation error",
            "random unknown failure",
        ]
    )
    monkeypatch.setattr("archmind.deploy.read_last_lines", lambda *_a, **_k: next(log_lines, "random unknown failure"))
    monkeypatch.setattr("archmind.deploy.find_free_port", lambda: 9333)
    monkeypatch.setattr("archmind.deploy._apply_default_env", lambda *_a, **_k: (True, "runtime env defaults applied"))

    result = run_backend_local_with_health(tmp_path)
    assert result["ok"] is False
    assert result["status"] == "FAIL"
    assert result["auto_fix"]["attempts"] == 2
    assert result["auto_fix"]["status"] == "FAILED"
