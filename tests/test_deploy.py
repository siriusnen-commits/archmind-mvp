from __future__ import annotations

from urllib.error import URLError
from pathlib import Path

from archmind.deploy import deploy_project, generate_deploy_slug, verify_deploy_health
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
    assert result["status"] == "SUCCESS"
    assert result["mode"] == "mock"
    assert str(result.get("url") or "").startswith("https://")


def test_update_after_deploy_persists_deploy_fields(tmp_path: Path) -> None:
    result = {
        "ok": True,
        "target": "railway",
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
