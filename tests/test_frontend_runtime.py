from __future__ import annotations

from pathlib import Path

from archmind.frontend_runtime import detect_frontend_runtime_entry


def test_detect_frontend_runtime_entry_next_command_has_single_port_flag(tmp_path: Path) -> None:
    frontend = tmp_path / "frontend"
    frontend.mkdir(parents=True, exist_ok=True)
    (frontend / "package.json").write_text(
        '{"name":"web","scripts":{"dev":"next dev -p 5173"},"dependencies":{"next":"14.0.0"}}',
        encoding="utf-8",
    )
    detected = detect_frontend_runtime_entry(tmp_path, port=3000)
    assert detected["ok"] is True
    cmd = [str(x) for x in detected.get("run_command") or []]
    assert cmd[:4] == ["npm", "exec", "--", "next"]
    assert cmd.count("--port") == 1
    assert "-p" not in cmd


def test_detect_frontend_runtime_entry_url_matches_selected_port(tmp_path: Path) -> None:
    frontend = tmp_path / "frontend"
    frontend.mkdir(parents=True, exist_ok=True)
    (frontend / "package.json").write_text(
        '{"name":"web","scripts":{"dev":"next dev"},"dependencies":{"next":"14.0.0"}}',
        encoding="utf-8",
    )
    detected = detect_frontend_runtime_entry(tmp_path, port=3111)
    assert detected["ok"] is True
    assert detected["frontend_port"] == 3111
    assert detected["frontend_url"] == "http://127.0.0.1:3111"


def test_detect_frontend_runtime_entry_generic_uses_host_flag_for_lan_bind(tmp_path: Path) -> None:
    frontend = tmp_path / "frontend"
    frontend.mkdir(parents=True, exist_ok=True)
    (frontend / "package.json").write_text(
        '{"name":"web","scripts":{"dev":"vite"},"dependencies":{"vite":"5.0.0"}}',
        encoding="utf-8",
    )
    detected = detect_frontend_runtime_entry(tmp_path, port=3232)
    assert detected["ok"] is True
    cmd = [str(x) for x in detected.get("run_command") or []]
    assert "--host" in cmd
    assert "0.0.0.0" in cmd
