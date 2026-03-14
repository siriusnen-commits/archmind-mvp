from __future__ import annotations

from urllib.error import URLError
from pathlib import Path

from archmind.deploy import (
    delete_github_repo,
    delete_local_project,
    delete_project,
    deploy_backend_local,
    deploy_frontend_local,
    deploy_frontend_to_railway_real,
    deploy_fullstack_local,
    deploy_project,
    detect_deploy_kind,
    generate_deploy_slug,
    get_frontend_deploy_dir,
    get_local_runtime_status,
    is_pid_running,
    list_running_local_projects,
    read_last_lines,
    restart_local_services,
    stop_local_services,
    verify_frontend_smoke,
    verify_deploy_health,
)
from archmind.state import load_state, update_after_deploy, write_state


def test_deploy_project_returns_fail_when_railway_cli_missing(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr("archmind.deploy.shutil.which", lambda _name: None)
    result = deploy_project(tmp_path, target="railway", allow_real_deploy=False)
    assert result["ok"] is False
    assert result["target"] == "railway"
    assert result["status"] == "FAIL"
    assert result["url"] is None
    assert "railway CLI not installed" in str(result.get("detail") or "")


def test_deploy_project_dispatches_to_railway(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr("archmind.deploy.detect_deploy_kind", lambda _p: "backend")
    monkeypatch.setattr(
        "archmind.deploy.deploy_to_railway",
        lambda *_a, **_k: {"ok": True, "target": "railway", "mode": "mock", "kind": "backend", "status": "SUCCESS", "url": "x", "detail": "ok"},
    )
    result = deploy_project(tmp_path, target="railway", allow_real_deploy=False)
    assert result["target"] == "railway"


def test_deploy_project_dispatches_to_local(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr("archmind.deploy.detect_deploy_kind", lambda _p: "backend")
    monkeypatch.setattr(
        "archmind.deploy.deploy_to_local",
        lambda *_a, **_k: {"ok": True, "target": "local", "mode": "real", "kind": "backend", "status": "SUCCESS", "url": "http://127.0.0.1:8001", "detail": "ok"},
    )
    result = deploy_project(tmp_path, target="local", allow_real_deploy=False)
    assert result["target"] == "local"


def test_deploy_project_returns_success_mock_when_provider_available(tmp_path: Path, monkeypatch) -> None:
    class DummyCompleted:
        returncode = 0
        stdout = "railway 3.0.0"
        stderr = ""

    monkeypatch.setattr("archmind.deploy.shutil.which", lambda _name: "/usr/local/bin/railway")
    monkeypatch.setattr("archmind.deploy.subprocess.run", lambda *a, **k: DummyCompleted())

    result = deploy_project(tmp_path, target="railway", allow_real_deploy=False)
    assert result["ok"] is True
    assert result["target"] == "railway"
    assert result["kind"] == "backend"
    assert result["status"] == "SUCCESS"
    assert result["mode"] == "mock"
    assert str(result.get("url") or "").startswith("https://")


def test_update_after_deploy_persists_deploy_fields(tmp_path: Path) -> None:
    result = {
        "ok": True,
        "target": "railway",
        "kind": "backend",
        "status": "SUCCESS",
        "url": "https://example.up.railway.app",
        "detail": "mock deploy success",
        "healthcheck_url": "https://example.up.railway.app/health",
        "healthcheck_status": "SUCCESS",
        "healthcheck_detail": "health endpoint returned status ok",
    }
    update_after_deploy(tmp_path, result, action="archmind deploy --path x --target railway")
    state = load_state(tmp_path)
    assert state is not None
    assert state.get("deploy_target") == "railway"
    assert state.get("last_deploy_status") == "SUCCESS"
    assert state.get("deploy_url") == "https://example.up.railway.app"
    assert state.get("last_deploy_detail") == "mock deploy success"
    assert state.get("healthcheck_url") == "https://example.up.railway.app/health"
    assert state.get("healthcheck_status") == "SUCCESS"
    assert state.get("healthcheck_detail") == "health endpoint returned status ok"
    assert state.get("deploy_kind") == "backend"
    assert state.get("backend_deploy_status") == "SUCCESS"


def test_detect_deploy_kind_backend(tmp_path: Path) -> None:
    (tmp_path / "app").mkdir(parents=True, exist_ok=True)
    (tmp_path / "requirements.txt").write_text("fastapi\n", encoding="utf-8")
    assert detect_deploy_kind(tmp_path) == "backend"


def test_detect_deploy_kind_frontend(tmp_path: Path) -> None:
    (tmp_path / "package.json").write_text('{"name":"web"}', encoding="utf-8")
    assert detect_deploy_kind(tmp_path) == "frontend"


def test_detect_deploy_kind_fullstack(tmp_path: Path) -> None:
    (tmp_path / "app").mkdir(parents=True, exist_ok=True)
    (tmp_path / "frontend").mkdir(parents=True, exist_ok=True)
    (tmp_path / "frontend" / "package.json").write_text('{"name":"web"}', encoding="utf-8")
    assert detect_deploy_kind(tmp_path) == "fullstack"


def test_get_frontend_deploy_dir_prefers_frontend_subdir(tmp_path: Path) -> None:
    (tmp_path / "frontend").mkdir(parents=True, exist_ok=True)
    (tmp_path / "frontend" / "package.json").write_text('{"name":"web"}', encoding="utf-8")
    (tmp_path / "package.json").write_text('{"name":"root-web"}', encoding="utf-8")
    assert get_frontend_deploy_dir(tmp_path) == (tmp_path / "frontend")


def test_get_frontend_deploy_dir_uses_root_package_json(tmp_path: Path) -> None:
    (tmp_path / "package.json").write_text('{"name":"root-web"}', encoding="utf-8")
    assert get_frontend_deploy_dir(tmp_path) == tmp_path


def test_local_backend_deploy_returns_localhost_url(monkeypatch, tmp_path: Path) -> None:
    (tmp_path / "app").mkdir(parents=True, exist_ok=True)

    class DummyProc:
        pid = 12001

    monkeypatch.setattr("archmind.deploy.find_free_port", lambda: 8011)
    monkeypatch.setattr("archmind.deploy._run_local_process_with_log", lambda *a, **k: DummyProc())
    result = deploy_backend_local(tmp_path)
    assert result["status"] == "SUCCESS"
    assert result["url"] == "http://127.0.0.1:8011"
    assert result["pid"] == 12001


def test_local_frontend_deploy_returns_localhost_url(monkeypatch, tmp_path: Path) -> None:
    (tmp_path / "frontend").mkdir(parents=True, exist_ok=True)
    (tmp_path / "frontend" / "package.json").write_text('{"name":"web"}', encoding="utf-8")

    class DummyProc:
        pid = 13001

    monkeypatch.setattr("archmind.deploy.find_free_port", lambda: 3011)
    monkeypatch.setattr("archmind.deploy._run_local_process_with_log", lambda *a, **k: DummyProc())
    result = deploy_frontend_local(tmp_path)
    assert result["status"] == "SUCCESS"
    assert result["url"] == "http://127.0.0.1:3011"
    assert result["pid"] == 13001


def test_local_deploy_process_uses_archmind_log_files(monkeypatch, tmp_path: Path) -> None:
    (tmp_path / "app").mkdir(parents=True, exist_ok=True)
    (tmp_path / "frontend").mkdir(parents=True, exist_ok=True)
    (tmp_path / "frontend" / "package.json").write_text('{"name":"web"}', encoding="utf-8")
    captured: list[str] = []

    class DummyProc:
        def __init__(self, pid: int) -> None:
            self.pid = pid

    def fake_popen(cmd, **kwargs):  # type: ignore[no-untyped-def]
        out = kwargs.get("stdout")
        name = str(getattr(out, "name", ""))
        captured.append(name)
        if "uvicorn" in " ".join(str(x) for x in cmd):
            return DummyProc(14001)
        return DummyProc(14002)

    monkeypatch.setattr("archmind.deploy.subprocess.Popen", fake_popen)
    monkeypatch.setattr("archmind.deploy.find_free_port", lambda: 8011)
    backend = deploy_backend_local(tmp_path)
    monkeypatch.setattr("archmind.deploy.find_free_port", lambda: 3011)
    frontend = deploy_frontend_local(tmp_path)

    assert backend["status"] == "SUCCESS"
    assert frontend["status"] == "SUCCESS"
    assert any(path.endswith(".archmind/backend.log") for path in captured)
    assert any(path.endswith(".archmind/frontend.log") for path in captured)


def test_local_fullstack_deploy_returns_both_urls(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr(
        "archmind.deploy.deploy_backend_local",
        lambda _p: {"status": "SUCCESS", "url": "http://127.0.0.1:8011", "detail": "local backend started", "pid": 1001},
    )
    monkeypatch.setattr(
        "archmind.deploy.deploy_frontend_local",
        lambda _p: {"status": "SUCCESS", "url": "http://127.0.0.1:3011", "detail": "local frontend started", "pid": 1002},
    )
    monkeypatch.setattr(
        "archmind.deploy._backend_smoke_with_retry",
        lambda _url: {"healthcheck_url": "http://127.0.0.1:8011/health", "healthcheck_status": "SUCCESS", "healthcheck_detail": "health endpoint returned status ok"},
    )
    monkeypatch.setattr(
        "archmind.deploy._frontend_smoke_with_retry",
        lambda _url: {"url": "http://127.0.0.1:3011", "status": "SUCCESS", "detail": "frontend URL returned HTTP 200"},
    )
    result = deploy_fullstack_local(tmp_path)
    assert result["kind"] == "fullstack"
    assert result["backend"]["url"] == "http://127.0.0.1:8011"
    assert result["frontend"]["url"] == "http://127.0.0.1:3011"
    assert result["backend_smoke_status"] == "SUCCESS"
    assert result["frontend_smoke_status"] == "SUCCESS"


def test_generate_deploy_slug_from_timestamped_name() -> None:
    slug = generate_deploy_slug("20260314_201330_simple_note_taking_api_with_fast")
    assert slug == "simple-note-api"


def test_generate_deploy_slug_fallback_and_constraints() -> None:
    slug = generate_deploy_slug("20260314___%%%")
    assert slug.startswith("a")
    assert len(slug) <= 40


def test_deploy_project_real_path_calls_railway_commands(monkeypatch, tmp_path: Path) -> None:
    calls: list[tuple[list[str], Path | None]] = []

    class DummyCompleted:
        def __init__(self, returncode: int = 0, stdout: str = "", stderr: str = "") -> None:
            self.returncode = returncode
            self.stdout = stdout
            self.stderr = stderr

    def fake_run(cmd, **kwargs):  # type: ignore[no-untyped-def]
        cwd = kwargs.get("cwd")
        calls.append((list(cmd), cwd))
        if cmd == ["railway", "--version"]:
            return DummyCompleted(returncode=0, stdout="railway 3.0.0")
        if cmd[:2] == ["railway", "init"]:
            return DummyCompleted(returncode=0, stdout="initialized")
        if cmd == ["railway", "up", "--detach"]:
            return DummyCompleted(returncode=0, stdout="deployed")
        if cmd == ["railway", "domain"]:
            return DummyCompleted(returncode=0, stdout="https://real-demo.up.railway.app")
        return DummyCompleted(returncode=0)

    monkeypatch.setattr("archmind.deploy.shutil.which", lambda _name: "/usr/local/bin/railway")
    monkeypatch.setattr("archmind.deploy.subprocess.run", fake_run)
    monkeypatch.setattr(
        "archmind.deploy.verify_deploy_health",
        lambda *_a, **_k: {
            "healthcheck_url": "https://real-demo.up.railway.app/health",
            "healthcheck_status": "SUCCESS",
            "healthcheck_detail": "health endpoint returned status ok",
        },
    )

    result = deploy_project(tmp_path, target="railway", allow_real_deploy=True)
    assert result["ok"] is True
    assert result["mode"] == "real"
    assert result["status"] == "SUCCESS"
    assert result["url"] == "https://real-demo.up.railway.app"
    assert result["backend_smoke_status"] == "SUCCESS"
    assert result["backend_smoke_url"] == "https://real-demo.up.railway.app/health"

    commands = [cmd for cmd, _cwd in calls]
    assert ["railway", "--version"] in commands
    assert any(cmd[:2] == ["railway", "init"] for cmd in commands)
    assert ["railway", "up", "--detach"] in commands
    assert ["railway", "domain"] in commands


def test_fullstack_mock_deploy_returns_backend_frontend_entries(monkeypatch, tmp_path: Path) -> None:
    (tmp_path / "app").mkdir(parents=True, exist_ok=True)
    (tmp_path / "frontend").mkdir(parents=True, exist_ok=True)
    (tmp_path / "frontend" / "package.json").write_text('{"name":"web"}', encoding="utf-8")

    class DummyCompleted:
        returncode = 0
        stdout = "railway 3.0.0"
        stderr = ""

    monkeypatch.setattr("archmind.deploy.shutil.which", lambda _name: "/usr/local/bin/railway")
    monkeypatch.setattr("archmind.deploy.subprocess.run", lambda *a, **k: DummyCompleted())

    result = deploy_project(tmp_path, target="railway", allow_real_deploy=False)
    assert result["ok"] is True
    assert result["kind"] == "fullstack"
    assert isinstance(result.get("backend"), dict)
    assert isinstance(result.get("frontend"), dict)
    assert result["backend"]["status"] == "SUCCESS"
    assert result["frontend"]["status"] == "SUCCESS"


def test_fullstack_state_stores_backend_frontend_fields(tmp_path: Path) -> None:
    result = {
        "ok": True,
        "target": "railway",
        "mode": "mock",
        "kind": "fullstack",
        "status": "SUCCESS",
        "url": "https://web-example.up.railway.app",
        "detail": "mock fullstack deploy success",
        "backend": {
            "status": "SUCCESS",
            "url": "https://api-example.up.railway.app",
            "detail": "mock backend deploy success",
        },
        "frontend": {
            "status": "SUCCESS",
            "url": "https://web-example.up.railway.app",
            "detail": "mock frontend deploy success",
        },
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
    update_after_deploy(tmp_path, result, action="archmind deploy --path x --target railway")
    state = load_state(tmp_path)
    assert state is not None
    assert state.get("deploy_kind") == "fullstack"
    assert state.get("backend_deploy_status") == "SUCCESS"
    assert state.get("backend_deploy_url") == "https://api-example.up.railway.app"
    assert state.get("frontend_deploy_status") == "SUCCESS"
    assert state.get("frontend_deploy_url") == "https://web-example.up.railway.app"
    assert state.get("backend_smoke_status") == "SKIPPED"
    assert state.get("frontend_smoke_status") == "SKIPPED"


def test_local_fullstack_state_stores_smoke_fields(tmp_path: Path) -> None:
    result = {
        "ok": True,
        "target": "local",
        "mode": "real",
        "kind": "fullstack",
        "status": "SUCCESS",
        "url": "http://127.0.0.1:3011",
        "detail": "local fullstack deploy completed",
        "backend": {"status": "SUCCESS", "url": "http://127.0.0.1:8011", "detail": "local backend started"},
        "frontend": {"status": "SUCCESS", "url": "http://127.0.0.1:3011", "detail": "local frontend started"},
        "backend_smoke_url": "http://127.0.0.1:8011/health",
        "backend_smoke_status": "SUCCESS",
        "backend_smoke_detail": "health endpoint returned status ok",
        "frontend_smoke_url": "http://127.0.0.1:3011",
        "frontend_smoke_status": "SUCCESS",
        "frontend_smoke_detail": "frontend URL returned HTTP 200",
        "backend_pid": 1001,
        "frontend_pid": 1002,
    }
    update_after_deploy(tmp_path, result, action="archmind deploy --path x --target local")
    state = load_state(tmp_path)
    assert state is not None
    assert state.get("deploy_target") == "local"
    assert state.get("deploy_mode") == "real"
    assert state.get("backend_smoke_status") == "SUCCESS"
    assert state.get("frontend_smoke_status") == "SUCCESS"
    assert int(state.get("backend_pid") or 0) == 1001
    assert int(state.get("frontend_pid") or 0) == 1002


def test_frontend_real_deploy_returns_fail_when_railway_missing(monkeypatch, tmp_path: Path) -> None:
    (tmp_path / "frontend").mkdir(parents=True, exist_ok=True)
    (tmp_path / "frontend" / "package.json").write_text('{"name":"web"}', encoding="utf-8")
    monkeypatch.setattr("archmind.deploy.shutil.which", lambda _name: None)
    result = deploy_frontend_to_railway_real(tmp_path)
    assert result["status"] == "FAIL"
    assert result["url"] is None
    assert "railway CLI not installed" in str(result.get("detail") or "")


def test_frontend_real_deploy_returns_success_when_commands_succeed(monkeypatch, tmp_path: Path) -> None:
    (tmp_path / "frontend").mkdir(parents=True, exist_ok=True)
    (tmp_path / "frontend" / "package.json").write_text('{"name":"web"}', encoding="utf-8")

    class DummyCompleted:
        def __init__(self, returncode: int = 0, stdout: str = "", stderr: str = "") -> None:
            self.returncode = returncode
            self.stdout = stdout
            self.stderr = stderr

    def fake_run(cmd, **kwargs):  # type: ignore[no-untyped-def]
        if cmd == ["railway", "--version"]:
            return DummyCompleted(returncode=0, stdout="railway 3.0.0")
        if cmd[:2] == ["railway", "init"]:
            return DummyCompleted(returncode=0, stdout="initialized")
        if cmd == ["railway", "up", "--detach"]:
            return DummyCompleted(returncode=0, stdout="deployed")
        if cmd == ["railway", "domain"]:
            return DummyCompleted(returncode=0, stdout="https://web-real.up.railway.app")
        return DummyCompleted(returncode=0)

    monkeypatch.setattr("archmind.deploy.shutil.which", lambda _name: "/usr/local/bin/railway")
    monkeypatch.setattr("archmind.deploy.subprocess.run", fake_run)
    result = deploy_frontend_to_railway_real(tmp_path)
    assert result["status"] == "SUCCESS"
    assert result["url"] == "https://web-real.up.railway.app"
    assert result["detail"] == "real frontend deploy success"


def test_fullstack_real_deploy_stores_frontend_real_url(monkeypatch, tmp_path: Path) -> None:
    (tmp_path / "app").mkdir(parents=True, exist_ok=True)
    (tmp_path / "frontend").mkdir(parents=True, exist_ok=True)
    (tmp_path / "frontend" / "package.json").write_text('{"name":"web"}', encoding="utf-8")

    class DummyCompleted:
        def __init__(self, returncode: int = 0, stdout: str = "", stderr: str = "") -> None:
            self.returncode = returncode
            self.stdout = stdout
            self.stderr = stderr

    def fake_run(cmd, **kwargs):  # type: ignore[no-untyped-def]
        cwd = kwargs.get("cwd")
        if cmd == ["railway", "--version"]:
            return DummyCompleted(returncode=0, stdout="railway 3.0.0")
        if cmd[:2] == ["railway", "init"]:
            return DummyCompleted(returncode=0, stdout="initialized")
        if cmd == ["railway", "up", "--detach"]:
            return DummyCompleted(returncode=0, stdout="deployed")
        if cmd == ["railway", "domain"] and cwd == tmp_path:
            return DummyCompleted(returncode=0, stdout="https://api-real.up.railway.app")
        if cmd == ["railway", "domain"] and cwd == (tmp_path / "frontend"):
            return DummyCompleted(returncode=0, stdout="https://web-real.up.railway.app")
        return DummyCompleted(returncode=0)

    monkeypatch.setattr("archmind.deploy.shutil.which", lambda _name: "/usr/local/bin/railway")
    monkeypatch.setattr("archmind.deploy.subprocess.run", fake_run)
    monkeypatch.setattr(
        "archmind.deploy.verify_deploy_health",
        lambda *_a, **_k: {
            "healthcheck_url": "https://api-real.up.railway.app/health",
            "healthcheck_status": "SUCCESS",
            "healthcheck_detail": "health endpoint returned status ok",
        },
    )
    monkeypatch.setattr(
        "archmind.deploy.verify_frontend_smoke",
        lambda *_a, **_k: {
            "url": "https://web-real.up.railway.app",
            "status": "SUCCESS",
            "detail": "frontend URL returned HTTP 200",
        },
    )

    result = deploy_project(tmp_path, target="railway", allow_real_deploy=True)
    assert result["kind"] == "fullstack"
    assert result["backend"]["status"] == "SUCCESS"
    assert result["frontend"]["status"] == "SUCCESS"
    assert result["frontend"]["url"] == "https://web-real.up.railway.app"
    assert result["backend_smoke_status"] == "SUCCESS"


def test_stop_local_services_calls_kill_and_clears_pids(monkeypatch, tmp_path: Path) -> None:
    write_state(
        tmp_path,
        {
            "backend_pid": 1234,
            "frontend_pid": 2345,
        },
    )
    killed: list[tuple[int, int]] = []

    def fake_kill(pid: int, sig: int) -> None:
        killed.append((pid, sig))

    monkeypatch.setattr("archmind.deploy.os.kill", fake_kill)
    result = stop_local_services(tmp_path)
    assert result["backend"]["status"] == "STOPPED"
    assert result["frontend"]["status"] == "STOPPED"
    assert [pid for pid, _sig in killed] == [1234, 2345]

    state = load_state(tmp_path)
    assert state is not None
    assert state.get("backend_pid") is None
    assert state.get("frontend_pid") is None


def test_stop_local_services_handles_missing_pids(tmp_path: Path) -> None:
    result = stop_local_services(tmp_path)
    assert result["backend"]["status"] == "NOT RUNNING"
    assert result["frontend"]["status"] == "NOT RUNNING"

    state = load_state(tmp_path)
    assert state is not None
    assert state.get("backend_pid") is None
    assert state.get("frontend_pid") is None


def test_restart_local_services_calls_stop_then_deploy(monkeypatch, tmp_path: Path) -> None:
    calls: list[str] = []
    monkeypatch.setattr(
        "archmind.deploy.get_local_runtime_status",
        lambda _p: {
            "backend": {"status": "RUNNING"},
            "frontend": {"status": "RUNNING"},
        },
    )
    monkeypatch.setattr(
        "archmind.deploy.stop_local_services",
        lambda _p: calls.append("stop") or {"ok": True, "backend": {"status": "STOPPED"}, "frontend": {"status": "STOPPED"}},
    )
    monkeypatch.setattr(
        "archmind.deploy.deploy_to_local",
        lambda _p, kind="backend": calls.append(f"deploy:{kind}")
        or {
            "ok": True,
            "target": "local",
            "mode": "real",
            "kind": "fullstack",
            "status": "SUCCESS",
            "url": "http://127.0.0.1:3011",
            "detail": "local fullstack deploy completed",
            "backend": {"status": "SUCCESS", "url": "http://127.0.0.1:8011", "detail": "local backend started"},
            "frontend": {"status": "SUCCESS", "url": "http://127.0.0.1:3011", "detail": "local frontend started"},
            "backend_pid": 9001,
            "frontend_pid": 9002,
            "backend_smoke_url": "http://127.0.0.1:8011/health",
            "backend_smoke_status": "SUCCESS",
            "backend_smoke_detail": "health endpoint returned status ok",
            "frontend_smoke_url": "http://127.0.0.1:3011",
            "frontend_smoke_status": "SUCCESS",
            "frontend_smoke_detail": "frontend URL returned HTTP 200",
            "healthcheck_url": "http://127.0.0.1:8011/health",
            "healthcheck_status": "SUCCESS",
            "healthcheck_detail": "health endpoint returned status ok",
        },
    )
    monkeypatch.setattr("archmind.deploy.update_after_deploy", lambda *_a, **_k: {})

    result = restart_local_services(tmp_path)
    assert calls == ["stop", "deploy:fullstack"]
    assert result["backend"]["status"] == "RESTARTED"
    assert result["frontend"]["status"] == "RESTARTED"


def test_restart_local_services_updates_pids_in_state(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr(
        "archmind.deploy.get_local_runtime_status",
        lambda _p: {
            "backend": {"status": "RUNNING"},
            "frontend": {"status": "NOT RUNNING"},
        },
    )
    monkeypatch.setattr(
        "archmind.deploy.stop_local_services",
        lambda _p: {"ok": True, "backend": {"status": "STOPPED"}, "frontend": {"status": "NOT RUNNING"}},
    )
    monkeypatch.setattr(
        "archmind.deploy.deploy_to_local",
        lambda _p, kind="backend": {
            "ok": True,
            "target": "local",
            "mode": "real",
            "kind": "backend",
            "status": "SUCCESS",
            "url": "http://127.0.0.1:8055",
            "detail": "local backend started",
            "backend_pid": 8055,
            "backend_smoke_url": "http://127.0.0.1:8055/health",
            "backend_smoke_status": "SUCCESS",
            "backend_smoke_detail": "health endpoint returned status ok",
            "frontend_smoke_url": "",
            "frontend_smoke_status": "SKIPPED",
            "frontend_smoke_detail": "frontend not deployed",
            "healthcheck_url": "http://127.0.0.1:8055/health",
            "healthcheck_status": "SUCCESS",
            "healthcheck_detail": "health endpoint returned status ok",
        },
    )

    result = restart_local_services(tmp_path)
    assert result["backend"]["status"] == "RESTARTED"
    assert result["frontend"]["status"] == "NOT RUNNING"
    state = load_state(tmp_path)
    assert state is not None
    assert int(state.get("backend_pid") or 0) == 8055


def test_restart_local_services_when_not_running(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr(
        "archmind.deploy.get_local_runtime_status",
        lambda _p: {
            "backend": {"status": "NOT RUNNING"},
            "frontend": {"status": "NOT RUNNING"},
        },
    )
    called = {"deploy": 0}
    monkeypatch.setattr("archmind.deploy.stop_local_services", lambda _p: {"ok": True})
    monkeypatch.setattr(
        "archmind.deploy.deploy_to_local",
        lambda _p, kind="backend": called.__setitem__("deploy", called["deploy"] + 1) or {"ok": True},
    )
    result = restart_local_services(tmp_path)
    assert called["deploy"] == 0
    assert result["backend"]["status"] == "NOT RUNNING"
    assert result["frontend"]["status"] == "NOT RUNNING"


def test_is_pid_running_true_when_kill_zero_succeeds(monkeypatch) -> None:
    monkeypatch.setattr("archmind.deploy.os.kill", lambda *_a, **_k: None)
    assert is_pid_running(12345) is True


def test_is_pid_running_false_when_process_missing(monkeypatch) -> None:
    def fake_kill(_pid: int, _sig: int) -> None:
        raise ProcessLookupError

    monkeypatch.setattr("archmind.deploy.os.kill", fake_kill)
    assert is_pid_running(12345) is False


def test_list_running_local_projects_includes_backend_only_running(monkeypatch, tmp_path: Path) -> None:
    root = tmp_path / "projects"
    project = root / "backend_only"
    (project / ".archmind").mkdir(parents=True, exist_ok=True)
    write_state(
        project,
        {
            "deploy_target": "local",
            "backend_pid": 11111,
            "frontend_pid": None,
            "backend_deploy_url": "http://127.0.0.1:8011",
            "frontend_deploy_url": "",
        },
    )

    monkeypatch.setattr("archmind.deploy.is_pid_running", lambda pid: int(pid or 0) == 11111)
    rows = list_running_local_projects(root)
    assert len(rows) == 1
    assert rows[0]["project_name"] == "backend_only"
    assert rows[0]["backend"]["status"] == "RUNNING"
    assert rows[0]["frontend"]["status"] == "NOT RUNNING"


def test_list_running_local_projects_excludes_dead_pids(monkeypatch, tmp_path: Path) -> None:
    root = tmp_path / "projects"
    project = root / "dead_service"
    (project / ".archmind").mkdir(parents=True, exist_ok=True)
    write_state(
        project,
        {
            "deploy_target": "local",
            "backend_pid": 22222,
            "frontend_pid": 33333,
        },
    )

    monkeypatch.setattr("archmind.deploy.is_pid_running", lambda _pid: False)
    rows = list_running_local_projects(root)
    assert rows == []


def test_get_local_runtime_status_uses_urls_and_pid_status(monkeypatch, tmp_path: Path) -> None:
    write_state(
        tmp_path,
        {
            "deploy_target": "local",
            "backend_pid": 44444,
            "frontend_pid": 55555,
            "backend_deploy_url": "http://127.0.0.1:8044",
            "frontend_deploy_url": "http://127.0.0.1:3044",
        },
    )
    monkeypatch.setattr("archmind.deploy.is_pid_running", lambda pid: int(pid or 0) == 44444)
    status = get_local_runtime_status(tmp_path)
    assert status["backend"]["status"] == "RUNNING"
    assert status["backend"]["url"] == "http://127.0.0.1:8044"
    assert status["frontend"]["status"] == "NOT RUNNING"
    assert status["frontend"]["url"] == "http://127.0.0.1:3044"


def test_read_last_lines_returns_none_when_missing(tmp_path: Path) -> None:
    assert read_last_lines(tmp_path / "missing.log", lines=20) is None


def test_read_last_lines_returns_tail_content(tmp_path: Path) -> None:
    path = tmp_path / "service.log"
    path.write_text("l1\nl2\nl3\n", encoding="utf-8")
    assert read_last_lines(path, lines=2) == "l2\nl3"


def test_delete_local_project_calls_stop_and_rmtree(monkeypatch, tmp_path: Path) -> None:
    project = tmp_path / "to_delete"
    project.mkdir(parents=True, exist_ok=True)
    called = {"stop": 0, "rmtree": 0}

    def fake_stop(_p: Path):  # type: ignore[no-untyped-def]
        called["stop"] += 1
        return {"ok": True}

    def fake_rmtree(path: Path):  # type: ignore[no-untyped-def]
        called["rmtree"] += 1
        assert path == project

    monkeypatch.setattr("archmind.deploy.stop_local_services", fake_stop)
    monkeypatch.setattr("archmind.deploy.shutil.rmtree", fake_rmtree)
    result = delete_local_project(project)
    assert called["stop"] == 1
    assert called["rmtree"] == 1
    assert result["local_status"] == "DELETED"


def test_delete_github_repo_skips_when_url_missing(tmp_path: Path) -> None:
    result = delete_github_repo(tmp_path)
    assert result["ok"] is False
    assert result["repo_status"] == "SKIPPED"
    assert "not found" in str(result["repo_detail"]).lower()


def test_delete_github_repo_uses_gh_delete(monkeypatch, tmp_path: Path) -> None:
    write_state(tmp_path, {"github_repo_url": "https://github.com/siriusnen-commits/demo-repo"})

    class DummyCompleted:
        returncode = 0
        stdout = "deleted"
        stderr = ""

    captured: dict[str, object] = {}

    def fake_run(cmd, **kwargs):  # type: ignore[no-untyped-def]
        captured["cmd"] = cmd
        return DummyCompleted()

    monkeypatch.setattr("archmind.deploy.subprocess.run", fake_run)
    result = delete_github_repo(tmp_path)
    assert result["ok"] is True
    assert result["repo_status"] == "DELETED"
    assert captured["cmd"] == ["gh", "repo", "delete", "siriusnen-commits/demo-repo", "--yes"]


def test_delete_project_all_runs_repo_then_local(monkeypatch, tmp_path: Path) -> None:
    calls: list[str] = []
    monkeypatch.setattr(
        "archmind.deploy.delete_github_repo",
        lambda _p: calls.append("repo")
        or {"ok": True, "repo_status": "DELETED", "repo_detail": "", "repo_slug": "owner/name"},
    )
    monkeypatch.setattr(
        "archmind.deploy.delete_local_project",
        lambda _p: calls.append("local") or {"ok": True, "local_status": "DELETED", "local_detail": ""},
    )
    result = delete_project(tmp_path, mode="all")
    assert calls == ["repo", "local"]
    assert result["ok"] is True
    assert result["repo_status"] == "DELETED"
    assert result["local_status"] == "DELETED"


def test_verify_deploy_health_success(monkeypatch) -> None:
    class DummyResponse:
        def __enter__(self):  # type: ignore[no-untyped-def]
            return self

        def __exit__(self, exc_type, exc, tb):  # type: ignore[no-untyped-def]
            return False

        def getcode(self) -> int:
            return 200

        def read(self) -> bytes:
            return b'{"status":"ok"}'

    monkeypatch.setattr("archmind.deploy.request.urlopen", lambda *_a, **_k: DummyResponse())
    result = verify_deploy_health("https://demo.up.railway.app")
    assert result["healthcheck_status"] == "SUCCESS"
    assert result["healthcheck_url"] == "https://demo.up.railway.app/health"


def test_verify_deploy_health_fail_on_non_200(monkeypatch) -> None:
    class DummyResponse:
        def __enter__(self):  # type: ignore[no-untyped-def]
            return self

        def __exit__(self, exc_type, exc, tb):  # type: ignore[no-untyped-def]
            return False

        def getcode(self) -> int:
            return 503

        def read(self) -> bytes:
            return b"unavailable"

    monkeypatch.setattr("archmind.deploy.request.urlopen", lambda *_a, **_k: DummyResponse())
    result = verify_deploy_health("https://demo.up.railway.app")
    assert result["healthcheck_status"] == "FAIL"
    assert "HTTP 503" in result["healthcheck_detail"]


def test_verify_deploy_health_fail_on_invalid_body(monkeypatch) -> None:
    class DummyResponse:
        def __enter__(self):  # type: ignore[no-untyped-def]
            return self

        def __exit__(self, exc_type, exc, tb):  # type: ignore[no-untyped-def]
            return False

        def getcode(self) -> int:
            return 200

        def read(self) -> bytes:
            return b'{"message":"alive"}'

    monkeypatch.setattr("archmind.deploy.request.urlopen", lambda *_a, **_k: DummyResponse())
    result = verify_deploy_health("https://demo.up.railway.app")
    assert result["healthcheck_status"] == "FAIL"
    assert result["healthcheck_detail"] == "unexpected response body"


def test_verify_deploy_health_fail_on_request_exception(monkeypatch) -> None:
    def fake_urlopen(*_a, **_k):  # type: ignore[no-untyped-def]
        raise URLError("timed out")

    monkeypatch.setattr("archmind.deploy.request.urlopen", fake_urlopen)
    result = verify_deploy_health("https://demo.up.railway.app")
    assert result["healthcheck_status"] == "FAIL"
    assert "health request failed" in result["healthcheck_detail"]


def test_verify_frontend_smoke_success_on_http_200(monkeypatch) -> None:
    class DummyResponse:
        def __enter__(self):  # type: ignore[no-untyped-def]
            return self

        def __exit__(self, exc_type, exc, tb):  # type: ignore[no-untyped-def]
            return False

        def getcode(self) -> int:
            return 200

    monkeypatch.setattr("archmind.deploy.request.urlopen", lambda *_a, **_k: DummyResponse())
    result = verify_frontend_smoke("https://web-demo.up.railway.app")
    assert result["status"] == "SUCCESS"
    assert result["url"] == "https://web-demo.up.railway.app"


def test_verify_frontend_smoke_fail_on_non_200(monkeypatch) -> None:
    class DummyResponse:
        def __enter__(self):  # type: ignore[no-untyped-def]
            return self

        def __exit__(self, exc_type, exc, tb):  # type: ignore[no-untyped-def]
            return False

        def getcode(self) -> int:
            return 503

    monkeypatch.setattr("archmind.deploy.request.urlopen", lambda *_a, **_k: DummyResponse())
    result = verify_frontend_smoke("https://web-demo.up.railway.app")
    assert result["status"] == "FAIL"
    assert "HTTP 503" in result["detail"]


def test_verify_frontend_smoke_fail_on_request_exception(monkeypatch) -> None:
    def fake_urlopen(*_a, **_k):  # type: ignore[no-untyped-def]
        raise URLError("request timeout")

    monkeypatch.setattr("archmind.deploy.request.urlopen", fake_urlopen)
    result = verify_frontend_smoke("https://web-demo.up.railway.app")
    assert result["status"] == "FAIL"
    assert "request failed" in result["detail"]
