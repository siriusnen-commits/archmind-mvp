from __future__ import annotations

import json
import shlex
import sys
from pathlib import Path

from archmind.cli import main
from archmind.runner import CommandResult


def _read_result_payload(project_dir: Path) -> dict[str, object]:
    result_path = project_dir / ".archmind" / "result.json"
    assert result_path.exists()
    return json.loads(result_path.read_text(encoding="utf-8"))


def _assert_result_artifacts(project_dir: Path) -> None:
    assert (project_dir / ".archmind" / "result.json").exists()
    assert (project_dir / ".archmind" / "result.txt").exists()


def test_e2e_python_pytest_profile(tmp_path: Path) -> None:
    tests_dir = tmp_path / "tests"
    tests_dir.mkdir(parents=True, exist_ok=True)
    tests_dir.joinpath("test_ok.py").write_text("def test_ok():\n    assert True\n", encoding="utf-8")

    exit_code = main(["run", "--path", str(tmp_path), "--profile", "python-pytest"])
    assert exit_code == 0

    _assert_result_artifacts(tmp_path)
    payload = _read_result_payload(tmp_path)
    assert payload["status"] == "SUCCESS"
    assert payload["profile"] == "python-pytest"


def test_e2e_node_vite_missing_npm_skips(tmp_path: Path, monkeypatch) -> None:
    tmp_path.joinpath("package.json").write_text(
        '{"name": "demo", "private": true, "scripts": {"lint": "echo lint"}}',
        encoding="utf-8",
    )

    monkeypatch.setattr("archmind.runner.shutil.which", lambda _: None)

    exit_code = main(["run", "--path", str(tmp_path), "--profile", "node-vite"])
    assert exit_code == 0

    _assert_result_artifacts(tmp_path)
    payload = _read_result_payload(tmp_path)
    assert payload["status"] == "SKIP"
    assert payload["profile"] == "node-vite"

    steps = payload.get("steps") or []
    assert any(step.get("status") == "SKIP" for step in steps)


def test_e2e_node_vite_install_failure_marks_skip(tmp_path: Path, monkeypatch) -> None:
    tmp_path.joinpath("package.json").write_text(
        '{\"name\": \"demo\", \"private\": true, \"scripts\": {\"lint\": \"echo lint\"}}',
        encoding="utf-8",
    )

    monkeypatch.setattr("archmind.runner.shutil.which", lambda _: "/usr/bin/fake")

    def fake_run_shell_capture(command: str, cwd: Path, timeout_s: int) -> CommandResult:
        cmd = ["sh", "-c", command]
        if command in ("npm ci", "npm install"):
            return CommandResult(
                cmd=cmd,
                cwd=cwd,
                exit_code=1,
                duration_s=0.01,
                stdout="",
                stderr="offline",
            )
        return CommandResult(cmd=cmd, cwd=cwd, exit_code=0, duration_s=0.01, stdout="", stderr="")

    monkeypatch.setattr("archmind.runner.run_shell_capture", fake_run_shell_capture)

    exit_code = main(["run", "--path", str(tmp_path), "--profile", "node-vite"])
    assert exit_code == 0

    _assert_result_artifacts(tmp_path)
    payload = _read_result_payload(tmp_path)
    assert payload["status"] == "SKIP"
    assert payload["profile"] == "node-vite"
    assert payload.get("reason")


def test_e2e_generic_shell_failure_summary(tmp_path: Path) -> None:
    py = shlex.quote(sys.executable)
    cmd_ok = f'{py} -c "from pathlib import Path; Path(\\"ok.txt\\").write_text(\\"ok\\")"'
    cmd_fail = f'{py} -c "import sys; print(\\"boom\\"); sys.exit(1)"'

    exit_code = main(
        [
            "run",
            "--path",
            str(tmp_path),
            "--profile",
            "generic",
            "--cmd",
            cmd_ok,
            "--cmd",
            cmd_fail,
        ]
    )
    assert exit_code == 1

    _assert_result_artifacts(tmp_path)
    payload = _read_result_payload(tmp_path)
    assert payload["status"] == "FAIL"
    assert payload["profile"] == "generic-shell"
    failure_summary = payload.get("failure_summary") or []
    assert len(failure_summary) > 0
