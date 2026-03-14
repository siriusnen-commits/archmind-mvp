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
