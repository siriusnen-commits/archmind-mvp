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
            "status": "SUCCESS",
            "url": "https://example.up.railway.app",
            "detail": "mock deploy success",
        },
    )
    exit_code = main(["deploy", "--path", str(tmp_path), "--target", "railway"])
    out = capsys.readouterr().out
    assert exit_code == 0
    assert "[DEPLOY] target=railway" in out
    assert "[DEPLOY] mode=mock" in out
    assert "[DEPLOY] status=SUCCESS" in out
    assert "[DEPLOY] url=https://example.up.railway.app" in out


def test_cli_deploy_failure_returns_nonzero(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr(
        "archmind.deploy.deploy_project",
        lambda *a, **k: {
            "ok": False,
            "target": "railway",
            "mode": "mock",
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
            "status": "SUCCESS",
            "url": "https://real-demo.up.railway.app",
            "detail": "railway deploy success",
        }

    monkeypatch.setattr("archmind.deploy.deploy_project", fake_deploy)
    exit_code = main(["deploy", "--path", str(tmp_path), "--target", "railway", "--allow-real-deploy"])
    out = capsys.readouterr().out

    assert exit_code == 0
    assert captured["allow_real_deploy"] is True
    assert "[DEPLOY] mode=real" in out
    assert "[DEPLOY] url=https://real-demo.up.railway.app" in out
