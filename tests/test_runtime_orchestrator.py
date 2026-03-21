from __future__ import annotations

from pathlib import Path

from archmind.runtime_orchestrator import run_all_local_services


def test_run_all_local_services_avoids_shared_frontend_port_collision(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr("archmind.runtime_orchestrator.detect_deploy_kind", lambda _root: "fullstack")
    monkeypatch.setattr(
        "archmind.runtime_orchestrator.get_local_runtime_status",
        lambda _root: {
            "backend": {"status": "NOT RUNNING", "url": "", "pid": None},
            "frontend": {"status": "NOT RUNNING", "url": "", "pid": None},
        },
    )
    monkeypatch.setattr(
        "archmind.runtime_orchestrator.run_backend_local_with_health",
        lambda _root: {
            "status": "SUCCESS",
            "url": "http://127.0.0.1:61080",
            "backend_pid": 20001,
            "backend_port": 61080,
            "backend_log_path": str(tmp_path / ".archmind" / "backend.log"),
            "detail": "backend started",
            "backend_smoke_status": "SUCCESS",
            "backend_smoke_detail": "ok",
        },
    )
    monkeypatch.setattr(
        "archmind.runtime_orchestrator.detect_frontend_runtime_entry",
        lambda _root: {"ok": True, "frontend_port": 5173, "framework": "nextjs"},
    )
    monkeypatch.setattr("archmind.runtime_orchestrator._is_port_available", lambda port: int(port) not in {5173, 61080})
    free_ports = iter([5173, 5200])
    monkeypatch.setattr("archmind.runtime_orchestrator.find_free_port", lambda: next(free_ports))
    captured: dict[str, int] = {}

    def fake_deploy_frontend(_root, *, port=None, backend_base_url=None):  # type: ignore[no-untyped-def]
        captured["port"] = int(port)
        return {
            "status": "SUCCESS",
            "url": f"http://127.0.0.1:{int(port)}",
            "pid": 30001,
            "detail": "frontend started",
            "framework": "nextjs",
        }

    monkeypatch.setattr("archmind.runtime_orchestrator.deploy_frontend_local", fake_deploy_frontend)
    monkeypatch.setattr(
        "archmind.runtime_orchestrator.verify_frontend_smoke",
        lambda url: {"status": "SUCCESS", "url": url, "detail": "ok"},
    )

    result = run_all_local_services(tmp_path)
    assert result["ok"] is True
    assert result["frontend_port"] == 5200
    assert result["frontend_url"] == "http://127.0.0.1:5200"
    assert captured["port"] == 5200


def test_run_all_local_services_reuses_project_frontend_port_when_available(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr("archmind.runtime_orchestrator.detect_deploy_kind", lambda _root: "fullstack")
    monkeypatch.setattr(
        "archmind.runtime_orchestrator.get_local_runtime_status",
        lambda _root: {
            "backend": {"status": "NOT RUNNING", "url": "", "pid": None},
            "frontend": {"status": "NOT RUNNING", "url": "http://127.0.0.1:5301", "pid": None, "port": 5301},
        },
    )
    monkeypatch.setattr(
        "archmind.runtime_orchestrator.run_backend_local_with_health",
        lambda _root: {
            "status": "SUCCESS",
            "url": "http://127.0.0.1:62080",
            "backend_pid": 21001,
            "backend_port": 62080,
            "backend_log_path": str(tmp_path / ".archmind" / "backend.log"),
            "detail": "backend started",
            "backend_smoke_status": "SUCCESS",
            "backend_smoke_detail": "ok",
        },
    )
    monkeypatch.setattr(
        "archmind.runtime_orchestrator.detect_frontend_runtime_entry",
        lambda _root: {"ok": True, "frontend_port": 5173, "framework": "nextjs"},
    )
    monkeypatch.setattr("archmind.runtime_orchestrator._is_port_available", lambda _port: True)
    captured: dict[str, int] = {}

    def fake_deploy_frontend(_root, *, port=None, backend_base_url=None):  # type: ignore[no-untyped-def]
        captured["port"] = int(port)
        return {
            "status": "SUCCESS",
            "url": f"http://127.0.0.1:{int(port)}",
            "pid": 31001,
            "detail": "frontend started",
            "framework": "nextjs",
        }

    monkeypatch.setattr("archmind.runtime_orchestrator.deploy_frontend_local", fake_deploy_frontend)
    monkeypatch.setattr(
        "archmind.runtime_orchestrator.verify_frontend_smoke",
        lambda url: {"status": "SUCCESS", "url": url, "detail": "ok"},
    )

    result = run_all_local_services(tmp_path)
    assert result["ok"] is True
    assert result["frontend_port"] == 5301
    assert captured["port"] == 5301
