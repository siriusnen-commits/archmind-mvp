from __future__ import annotations

from pathlib import Path

from archmind.cli import main


def test_cli_deploy_success_outputs_summary(monkeypatch, tmp_path: Path, capsys) -> None:
    monkeypatch.setattr(
        "archmind.deploy.deploy_project",
        lambda *a, **k: {
            "ok": True,
            "target": "railway",
            "mode": "mock",
            "kind": "backend",
            "status": "SUCCESS",
            "url": "https://example.up.railway.app",
            "detail": "mock deploy success",
            "healthcheck_url": "",
            "healthcheck_status": "SKIPPED",
            "healthcheck_detail": "mock deploy mode",
            "backend_smoke_url": "",
            "backend_smoke_status": "SKIPPED",
            "backend_smoke_detail": "mock deploy mode",
            "frontend_smoke_url": "",
            "frontend_smoke_status": "SKIPPED",
            "frontend_smoke_detail": "frontend not deployed",
        },
    )
    exit_code = main(["deploy", "--path", str(tmp_path), "--target", "railway"])
    out = capsys.readouterr().out
    assert exit_code == 0
    assert "[DEPLOY] target=railway" in out
    assert "[DEPLOY] mode=mock" in out
    assert "[DEPLOY] kind=backend" in out
    assert "[DEPLOY] status=SUCCESS" in out
    assert "[DEPLOY] url=https://example.up.railway.app" in out
    assert "[HEALTH] status=SKIPPED" in out
    assert "[BACKEND-SMOKE] status=SKIPPED" in out


def test_cli_deploy_failure_returns_nonzero(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr(
        "archmind.deploy.deploy_project",
        lambda *a, **k: {
            "ok": False,
            "target": "railway",
            "mode": "mock",
            "kind": "backend",
            "status": "FAIL",
            "url": None,
            "detail": "railway CLI not installed",
        },
    )
    exit_code = main(["deploy", "--path", str(tmp_path), "--target", "railway"])
    assert exit_code == 1


def test_cli_deploy_real_flag_is_forwarded(monkeypatch, tmp_path: Path, capsys) -> None:
    captured: dict[str, object] = {}

    def fake_deploy(project_dir, target="railway", allow_real_deploy=False):  # type: ignore[no-untyped-def]
        captured["project_dir"] = project_dir
        captured["target"] = target
        captured["allow_real_deploy"] = allow_real_deploy
        return {
            "ok": True,
            "target": "railway",
            "mode": "real",
            "kind": "backend",
            "status": "SUCCESS",
            "url": "https://real-demo.up.railway.app",
            "detail": "railway deploy success",
            "healthcheck_url": "https://real-demo.up.railway.app/health",
            "healthcheck_status": "SUCCESS",
            "healthcheck_detail": "health endpoint returned status ok",
            "backend_smoke_url": "https://real-demo.up.railway.app/health",
            "backend_smoke_status": "SUCCESS",
            "backend_smoke_detail": "health endpoint returned status ok",
            "frontend_smoke_url": "",
            "frontend_smoke_status": "SKIPPED",
            "frontend_smoke_detail": "frontend not deployed",
        }

    monkeypatch.setattr("archmind.deploy.deploy_project", fake_deploy)
    exit_code = main(["deploy", "--path", str(tmp_path), "--target", "railway", "--allow-real-deploy"])
    out = capsys.readouterr().out

    assert exit_code == 0
    assert captured["allow_real_deploy"] is True
    assert "[DEPLOY] mode=real" in out
    assert "[DEPLOY] url=https://real-demo.up.railway.app" in out
    assert "[HEALTH] url=https://real-demo.up.railway.app/health" in out
    assert "[HEALTH] status=SUCCESS" in out
    assert "[HEALTH] detail=health endpoint returned status ok" in out
    assert "[BACKEND-SMOKE] status=SUCCESS" in out


def test_cli_deploy_fullstack_prints_backend_frontend_sections(monkeypatch, tmp_path: Path, capsys) -> None:
    monkeypatch.setattr(
        "archmind.deploy.deploy_project",
        lambda *a, **k: {
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
            "backend_smoke_url": "",
            "backend_smoke_status": "SKIPPED",
            "backend_smoke_detail": "mock deploy mode",
            "frontend_smoke_url": "",
            "frontend_smoke_status": "SKIPPED",
            "frontend_smoke_detail": "mock deploy mode",
        },
    )
    exit_code = main(["deploy", "--path", str(tmp_path), "--target", "railway"])
    out = capsys.readouterr().out
    assert exit_code == 0
    assert "[DEPLOY] kind=fullstack" in out
    assert "[BACKEND] status=SUCCESS" in out
    assert "[BACKEND] url=https://api-example.up.railway.app" in out
    assert "[BACKEND-SMOKE] status=SKIPPED" in out
    assert "[FRONTEND] status=SUCCESS" in out
    assert "[FRONTEND] url=https://web-example.up.railway.app" in out
    assert "[FRONTEND-SMOKE] status=SKIPPED" in out


def test_cli_real_fullstack_shows_real_frontend_deploy_result(monkeypatch, tmp_path: Path, capsys) -> None:
    monkeypatch.setattr(
        "archmind.deploy.deploy_project",
        lambda *a, **k: {
            "ok": True,
            "target": "railway",
            "mode": "real",
            "kind": "fullstack",
            "status": "SUCCESS",
            "url": "https://web-real.up.railway.app",
            "detail": "fullstack deploy completed",
            "backend": {
                "status": "SUCCESS",
                "url": "https://api-real.up.railway.app",
                "detail": "railway deploy success",
            },
            "frontend": {
                "status": "SUCCESS",
                "url": "https://web-real.up.railway.app",
                "detail": "real frontend deploy success",
            },
            "healthcheck_url": "https://api-real.up.railway.app/health",
            "healthcheck_status": "SUCCESS",
            "healthcheck_detail": "health endpoint returned status ok",
            "backend_smoke_url": "https://api-real.up.railway.app/health",
            "backend_smoke_status": "SUCCESS",
            "backend_smoke_detail": "health endpoint returned status ok",
            "frontend_smoke_url": "https://web-real.up.railway.app",
            "frontend_smoke_status": "SUCCESS",
            "frontend_smoke_detail": "frontend URL returned HTTP 200",
        },
    )
    exit_code = main(["deploy", "--path", str(tmp_path), "--target", "railway", "--allow-real-deploy"])
    out = capsys.readouterr().out
    assert exit_code == 0
    assert "[DEPLOY] mode=real" in out
    assert "[DEPLOY] kind=fullstack" in out
    assert "[FRONTEND] status=SUCCESS" in out
    assert "[FRONTEND] url=https://web-real.up.railway.app" in out
    assert "[BACKEND-SMOKE] status=SUCCESS" in out
    assert "[FRONTEND-SMOKE] status=SUCCESS" in out


def test_cli_local_output_includes_localhost_urls(monkeypatch, tmp_path: Path, capsys) -> None:
    monkeypatch.setattr(
        "archmind.deploy.deploy_project",
        lambda *a, **k: {
            "ok": True,
            "target": "local",
            "mode": "real",
            "kind": "fullstack",
            "status": "SUCCESS",
            "url": "http://127.0.0.1:3011",
            "detail": "local fullstack deploy completed",
            "backend": {
                "status": "SUCCESS",
                "url": "http://127.0.0.1:8011",
                "detail": "local backend started",
            },
            "frontend": {
                "status": "SUCCESS",
                "url": "http://127.0.0.1:3011",
                "detail": "local frontend started",
            },
            "backend_smoke_url": "http://127.0.0.1:8011/health",
            "backend_smoke_status": "SUCCESS",
            "backend_smoke_detail": "health endpoint returned status ok",
            "frontend_smoke_url": "http://127.0.0.1:3011",
            "frontend_smoke_status": "SUCCESS",
            "frontend_smoke_detail": "frontend URL returned HTTP 200",
        },
    )
    exit_code = main(["deploy", "--path", str(tmp_path), "--target", "local"])
    out = capsys.readouterr().out
    assert exit_code == 0
    assert "[DEPLOY] target=local" in out
    assert "[BACKEND] url=http://127.0.0.1:8011" in out
    assert "[FRONTEND] url=http://127.0.0.1:3011" in out
    assert "[BACKEND-SMOKE] url=http://127.0.0.1:8011/health" in out
    assert "[FRONTEND-SMOKE] url=http://127.0.0.1:3011" in out


def test_cli_default_target_is_railway(monkeypatch, tmp_path: Path) -> None:
    captured: dict[str, object] = {}

    def fake_deploy(project_dir, target="railway", allow_real_deploy=False):  # type: ignore[no-untyped-def]
        captured["target"] = target
        captured["allow_real_deploy"] = allow_real_deploy
        return {
            "ok": True,
            "target": target,
            "mode": "mock",
            "kind": "backend",
            "status": "SUCCESS",
            "url": "https://example.up.railway.app",
            "detail": "mock deploy success",
        }

    monkeypatch.setattr("archmind.deploy.deploy_project", fake_deploy)
    exit_code = main(["deploy", "--path", str(tmp_path)])
    assert exit_code == 0
    assert captured["target"] == "railway"


def test_cli_stop_outputs_stopped(monkeypatch, tmp_path: Path, capsys) -> None:
    monkeypatch.setattr(
        "archmind.deploy.stop_local_services",
        lambda _p: {
            "ok": True,
            "target": "local",
            "backend": {"status": "STOPPED", "pid": 1111, "detail": ""},
            "frontend": {"status": "STOPPED", "pid": 2222, "detail": ""},
        },
    )
    exit_code = main(["stop", "--path", str(tmp_path)])
    out = capsys.readouterr().out
    assert exit_code == 0
    assert "[STOP] backend stopped" in out
    assert "[STOP] frontend stopped" in out


def test_cli_stop_outputs_not_running(monkeypatch, tmp_path: Path, capsys) -> None:
    monkeypatch.setattr(
        "archmind.deploy.stop_local_services",
        lambda _p: {
            "ok": True,
            "target": "local",
            "backend": {"status": "NOT RUNNING", "pid": None, "detail": ""},
            "frontend": {"status": "NOT RUNNING", "pid": None, "detail": ""},
        },
    )
    exit_code = main(["stop", "--path", str(tmp_path)])
    out = capsys.readouterr().out
    assert exit_code == 0
    assert "[STOP] backend not running" in out
    assert "[STOP] frontend not running" in out


def test_cli_running_prints_running_projects(monkeypatch, tmp_path: Path, capsys) -> None:
    monkeypatch.setattr(
        "archmind.deploy.list_running_local_projects",
        lambda _root: [
            {
                "project_name": "proj_a",
                "backend": {"status": "RUNNING", "pid": 12345, "url": "http://127.0.0.1:8011"},
                "frontend": {"status": "RUNNING", "pid": 12346, "url": "http://127.0.0.1:3011"},
            }
        ],
    )
    exit_code = main(["running", "--projects-dir", str(tmp_path)])
    out = capsys.readouterr().out
    assert exit_code == 0
    assert "[RUNNING] proj_a" in out
    assert "backend: RUNNING pid=12345 url=http://127.0.0.1:8011" in out
    assert "frontend: RUNNING pid=12346 url=http://127.0.0.1:3011" in out


def test_cli_running_prints_no_services_when_empty(monkeypatch, tmp_path: Path, capsys) -> None:
    monkeypatch.setattr("archmind.deploy.list_running_local_projects", lambda _root: [])
    exit_code = main(["running", "--projects-dir", str(tmp_path)])
    out = capsys.readouterr().out
    assert exit_code == 0
    assert "No local services running." in out


def test_cli_logs_local_prints_backend_and_frontend(monkeypatch, tmp_path: Path, capsys) -> None:
    monkeypatch.setattr(
        "archmind.deploy.read_last_lines",
        lambda path, lines=20: "backend line" if str(path).endswith("backend.log") else "frontend line",
    )
    exit_code = main(["logs", "--path", str(tmp_path), "--local"])
    out = capsys.readouterr().out
    assert exit_code == 0
    assert "[BACKEND LOGS]" in out
    assert "backend line" in out
    assert "[FRONTEND LOGS]" in out
    assert "frontend line" in out


def test_cli_logs_local_backend_only(monkeypatch, tmp_path: Path, capsys) -> None:
    monkeypatch.setattr("archmind.deploy.read_last_lines", lambda *_a, **_k: "backend only line")
    exit_code = main(["logs", "--path", str(tmp_path), "--local", "--backend"])
    out = capsys.readouterr().out
    assert exit_code == 0
    assert "[BACKEND LOGS]" in out
    assert "backend only line" in out
    assert "[FRONTEND LOGS]" not in out


def test_cli_logs_local_no_logs(monkeypatch, tmp_path: Path, capsys) -> None:
    monkeypatch.setattr("archmind.deploy.read_last_lines", lambda *_a, **_k: None)
    exit_code = main(["logs", "--path", str(tmp_path), "--local"])
    out = capsys.readouterr().out
    assert exit_code == 0
    assert "No logs available." in out


def test_cli_restart_outputs_restarted(monkeypatch, tmp_path: Path, capsys) -> None:
    monkeypatch.setattr(
        "archmind.deploy.restart_local_services",
        lambda _p: {
            "ok": True,
            "target": "local",
            "backend": {"status": "RESTARTED", "url": "http://127.0.0.1:8011", "detail": ""},
            "frontend": {"status": "RESTARTED", "url": "http://127.0.0.1:3011", "detail": ""},
        },
    )
    exit_code = main(["restart", "--path", str(tmp_path)])
    out = capsys.readouterr().out
    assert exit_code == 0
    assert "[RESTART] backend restarted" in out
    assert "[RESTART] frontend restarted" in out


def test_cli_restart_outputs_not_running(monkeypatch, tmp_path: Path, capsys) -> None:
    monkeypatch.setattr(
        "archmind.deploy.restart_local_services",
        lambda _p: {
            "ok": True,
            "target": "local",
            "backend": {"status": "NOT RUNNING", "url": "", "detail": ""},
            "frontend": {"status": "NOT RUNNING", "url": "", "detail": ""},
        },
    )
    exit_code = main(["restart", "--path", str(tmp_path)])
    out = capsys.readouterr().out
    assert exit_code == 0
    assert "[RESTART] backend not running" in out
    assert "[RESTART] frontend not running" in out
