from __future__ import annotations

from urllib.error import URLError
from pathlib import Path

from archmind.deploy import (
    deploy_frontend_to_railway_real,
    deploy_project,
    detect_deploy_kind,
    generate_deploy_slug,
    get_frontend_deploy_dir,
    verify_deploy_health,
)
from archmind.state import load_state, update_after_deploy


def test_deploy_project_returns_fail_when_railway_cli_missing(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr("archmind.deploy.shutil.which", lambda _name: None)
    result = deploy_project(tmp_path, target="railway", allow_real_deploy=False)
    assert result["ok"] is False
    assert result["target"] == "railway"
    assert result["status"] == "FAIL"
    assert result["url"] is None
    assert "railway CLI not installed" in str(result.get("detail") or "")


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
    }
    update_after_deploy(tmp_path, result, action="archmind deploy --path x --target railway")
    state = load_state(tmp_path)
    assert state is not None
    assert state.get("deploy_kind") == "fullstack"
    assert state.get("backend_deploy_status") == "SUCCESS"
    assert state.get("backend_deploy_url") == "https://api-example.up.railway.app"
    assert state.get("frontend_deploy_status") == "SUCCESS"
    assert state.get("frontend_deploy_url") == "https://web-example.up.railway.app"


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

    result = deploy_project(tmp_path, target="railway", allow_real_deploy=True)
    assert result["kind"] == "fullstack"
    assert result["backend"]["status"] == "SUCCESS"
    assert result["frontend"]["status"] == "SUCCESS"
    assert result["frontend"]["url"] == "https://web-real.up.railway.app"


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
