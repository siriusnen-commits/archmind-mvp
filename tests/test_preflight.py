from __future__ import annotations

from pathlib import Path

from archmind.deploy import run_backend_local_with_health, run_preflight_checks


def _write_app_main(root: Path) -> None:
    (root / "app").mkdir(parents=True, exist_ok=True)
    (root / "app" / "main.py").write_text("from fastapi import FastAPI\napp = FastAPI()\n", encoding="utf-8")
    (root / "requirements.txt").write_text("fastapi\nuvicorn\n", encoding="utf-8")


def test_preflight_requirements_install_ok(monkeypatch, tmp_path: Path) -> None:
    _write_app_main(tmp_path)
    (tmp_path / "runtime.db").write_text("", encoding="utf-8")

    monkeypatch.setattr(
        "archmind.deploy.detect_backend_runtime_entry",
        lambda *_a, **_k: {"ok": True, "run_cwd": tmp_path, "failure_reason": ""},
    )

    class Completed:
        def __init__(self, code: int = 0) -> None:
            self.returncode = code
            self.stderr = ""
            self.stdout = ""

    monkeypatch.setattr("archmind.deploy.subprocess.run", lambda *_a, **_k: Completed(0))
    monkeypatch.setattr("archmind.deploy._apply_default_env", lambda *_a, **_k: (True, "runtime env defaults applied"))
    monkeypatch.setattr("archmind.deploy._is_port_available", lambda _p: True)
    monkeypatch.setattr("archmind.deploy.apply_auto_fix", lambda *_a, **_k: {"applied": False, "fix_type": "unknown", "detail": "", "new_port": None})

    result = run_preflight_checks(tmp_path)
    assert result["ok"] is True
    assert result["status"] in {"OK", "FIXED"}
    assert any("installed requirements" in item for item in result["fixes_applied"])


def test_preflight_import_failure_fixed(monkeypatch, tmp_path: Path) -> None:
    _write_app_main(tmp_path)
    (tmp_path / "runtime.db").write_text("", encoding="utf-8")

    monkeypatch.setattr(
        "archmind.deploy.detect_backend_runtime_entry",
        lambda *_a, **_k: {"ok": True, "run_cwd": tmp_path, "failure_reason": ""},
    )

    class Completed:
        def __init__(self, code: int = 0, stderr: str = "", stdout: str = "") -> None:
            self.returncode = code
            self.stderr = stderr
            self.stdout = stdout

    calls = {"n": 0}

    def fake_run(cmd, **_kwargs):  # type: ignore[no-untyped-def]
        if len(cmd) >= 3 and cmd[1] == "-m" and cmd[2] == "pip":
            return Completed(0)
        if len(cmd) >= 2 and cmd[1] == "-c":
            calls["n"] += 1
            if calls["n"] == 1:
                return Completed(1, stderr="ModuleNotFoundError: No module named 'sqlmodel'")
            return Completed(0)
        return Completed(0)

    monkeypatch.setattr("archmind.deploy.subprocess.run", fake_run)
    monkeypatch.setattr("archmind.deploy._apply_default_env", lambda *_a, **_k: (True, "runtime env defaults applied"))
    monkeypatch.setattr("archmind.deploy._is_port_available", lambda _p: True)
    monkeypatch.setattr(
        "archmind.deploy.apply_auto_fix",
        lambda *_a, **_k: {"applied": True, "fix_type": "missing_dependency", "detail": "missing_dependency -> sqlmodel installed", "new_port": None},
    )

    result = run_preflight_checks(tmp_path)
    assert result["ok"] is True
    assert result["status"] == "FIXED"
    assert any("sqlmodel installed" in item for item in result["fixes_applied"])


def test_preflight_db_init_when_missing(monkeypatch, tmp_path: Path) -> None:
    _write_app_main(tmp_path)
    monkeypatch.setattr(
        "archmind.deploy.detect_backend_runtime_entry",
        lambda *_a, **_k: {"ok": True, "run_cwd": tmp_path, "failure_reason": ""},
    )

    class Completed:
        returncode = 0
        stderr = ""
        stdout = ""

    monkeypatch.setattr("archmind.deploy.subprocess.run", lambda *_a, **_k: Completed())
    monkeypatch.setattr("archmind.deploy._apply_default_env", lambda *_a, **_k: (True, "runtime env defaults applied"))
    monkeypatch.setattr("archmind.deploy._is_port_available", lambda _p: True)
    monkeypatch.setattr(
        "archmind.deploy.apply_auto_fix",
        lambda _p, analysis, **_k: (
            {"applied": True, "fix_type": "db_not_initialized", "detail": "database initialized", "new_port": None}
            if str(analysis.get("type") or "") == "db_not_initialized"
            else {"applied": False, "fix_type": "unknown", "detail": "", "new_port": None}
        ),
    )

    result = run_preflight_checks(tmp_path)
    assert result["ok"] is True
    assert any("database initialized" in item for item in result["fixes_applied"])


def test_preflight_db_init_command_unavailable_is_non_blocking(monkeypatch, tmp_path: Path) -> None:
    _write_app_main(tmp_path)
    monkeypatch.setattr(
        "archmind.deploy.detect_backend_runtime_entry",
        lambda *_a, **_k: {"ok": True, "run_cwd": tmp_path, "failure_reason": ""},
    )

    class Completed:
        returncode = 0
        stderr = ""
        stdout = ""

    monkeypatch.setattr("archmind.deploy.subprocess.run", lambda *_a, **_k: Completed())
    monkeypatch.setattr("archmind.deploy._apply_default_env", lambda *_a, **_k: (True, "runtime env defaults applied"))
    monkeypatch.setattr("archmind.deploy._is_port_available", lambda _p: True)
    monkeypatch.setattr(
        "archmind.deploy.apply_auto_fix",
        lambda _p, analysis, **_k: (
            {"applied": False, "fix_type": "db_not_initialized", "detail": "db init command not available", "new_port": None}
            if str(analysis.get("type") or "") == "db_not_initialized"
            else {"applied": False, "fix_type": "unknown", "detail": "", "new_port": None}
        ),
    )

    result = run_preflight_checks(tmp_path)
    assert result["ok"] is True
    assert any("db init skipped" in item for item in result["fixes_applied"])
    assert not any("db init command not available" in str(item) for item in result["issues_found"])


def test_preflight_db_init_execution_failure_is_blocking(monkeypatch, tmp_path: Path) -> None:
    _write_app_main(tmp_path)
    monkeypatch.setattr(
        "archmind.deploy.detect_backend_runtime_entry",
        lambda *_a, **_k: {"ok": True, "run_cwd": tmp_path, "failure_reason": ""},
    )

    class Completed:
        returncode = 0
        stderr = ""
        stdout = ""

    monkeypatch.setattr("archmind.deploy.subprocess.run", lambda *_a, **_k: Completed())
    monkeypatch.setattr("archmind.deploy._apply_default_env", lambda *_a, **_k: (True, "runtime env defaults applied"))
    monkeypatch.setattr("archmind.deploy._is_port_available", lambda _p: True)
    monkeypatch.setattr(
        "archmind.deploy.apply_auto_fix",
        lambda _p, analysis, **_k: (
            {"applied": False, "fix_type": "db_not_initialized", "detail": "db init execution failed: permission denied", "new_port": None}
            if str(analysis.get("type") or "") == "db_not_initialized"
            else {"applied": False, "fix_type": "unknown", "detail": "", "new_port": None}
        ),
    )

    result = run_preflight_checks(tmp_path)
    assert result["ok"] is False
    assert result["status"] == "FAILED"
    assert any("db init execution failed" in str(item) for item in result["issues_found"])


def test_preflight_creates_env_when_missing(monkeypatch, tmp_path: Path) -> None:
    _write_app_main(tmp_path)
    (tmp_path / "runtime.db").write_text("", encoding="utf-8")
    monkeypatch.setattr(
        "archmind.deploy.detect_backend_runtime_entry",
        lambda *_a, **_k: {"ok": True, "run_cwd": tmp_path, "failure_reason": ""},
    )

    class Completed:
        returncode = 0
        stderr = ""
        stdout = ""

    monkeypatch.setattr("archmind.deploy.subprocess.run", lambda *_a, **_k: Completed())
    monkeypatch.setattr("archmind.deploy._apply_default_env", lambda *_a, **_k: (True, "runtime env defaults applied"))
    monkeypatch.setattr("archmind.deploy._is_port_available", lambda _p: True)
    monkeypatch.setattr("archmind.deploy.apply_auto_fix", lambda *_a, **_k: {"applied": False, "fix_type": "unknown", "detail": "", "new_port": None})

    result = run_preflight_checks(tmp_path)
    assert result["ok"] is True
    assert any("created .env" in item for item in result["fixes_applied"])


def test_preflight_switches_port_when_conflict(monkeypatch, tmp_path: Path) -> None:
    _write_app_main(tmp_path)
    (tmp_path / "runtime.db").write_text("", encoding="utf-8")
    monkeypatch.setattr(
        "archmind.deploy.detect_backend_runtime_entry",
        lambda *_a, **_k: {"ok": True, "run_cwd": tmp_path, "failure_reason": ""},
    )

    class Completed:
        returncode = 0
        stderr = ""
        stdout = ""

    monkeypatch.setattr("archmind.deploy.subprocess.run", lambda *_a, **_k: Completed())
    monkeypatch.setattr("archmind.deploy._apply_default_env", lambda *_a, **_k: (True, "runtime env defaults applied"))
    monkeypatch.setattr("archmind.deploy._is_port_available", lambda _p: False)
    monkeypatch.setattr("archmind.deploy.find_free_port", lambda: 9555)
    monkeypatch.setattr(
        "archmind.deploy.apply_auto_fix",
        lambda *_a, **_k: {"applied": True, "fix_type": "port_in_use", "detail": "port_in_use -> switched port to 9555", "new_port": 9555},
    )

    result = run_preflight_checks(tmp_path, requested_port=8000)
    assert result["ok"] is True
    assert result["selected_port"] == 9555


def test_preflight_then_run_success(monkeypatch, tmp_path: Path) -> None:
    _write_app_main(tmp_path)
    monkeypatch.setattr(
        "archmind.deploy.run_preflight_checks",
        lambda *_a, **_k: {
            "ok": True,
            "fixed": True,
            "status": "FIXED",
            "fixes_applied": ["installed requirements", "created .env defaults"],
            "issues_found": [],
            "selected_port": 8120,
        },
    )

    class DummyProc:
        pid = 32123

        def poll(self) -> int | None:
            return None

    monkeypatch.setattr("archmind.deploy._run_local_process_with_log", lambda *_a, **_k: DummyProc())
    monkeypatch.setattr("archmind.deploy.time.sleep", lambda _s: None)
    monkeypatch.setattr(
        "archmind.deploy._backend_smoke_with_retry",
        lambda _url: {
            "healthcheck_url": "http://127.0.0.1:8120/health",
            "healthcheck_status": "SUCCESS",
            "healthcheck_detail": "health endpoint returned status ok",
        },
    )
    monkeypatch.setattr("archmind.deploy.read_last_lines", lambda *_a, **_k: "")

    result = run_backend_local_with_health(tmp_path)
    assert result["ok"] is True
    preflight = result.get("preflight") if isinstance(result.get("preflight"), dict) else {}
    assert preflight.get("status") == "FIXED"
