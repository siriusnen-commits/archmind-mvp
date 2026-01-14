from __future__ import annotations

from pathlib import Path

from archmind.cli import main
from archmind.runner import CommandResult


def _write_pytest_pass_project(root: Path) -> None:
    root.joinpath("pytest.ini").write_text("[pytest]\naddopts = -q\n", encoding="utf-8")
    root.joinpath("test_ok.py").write_text(
        "def test_ok():\n    assert True\n",
        encoding="utf-8",
    )


def _write_pytest_fail_project(root: Path) -> None:
    root.joinpath("pytest.ini").write_text("[pytest]\naddopts = -q\n", encoding="utf-8")
    root.joinpath("test_fail.py").write_text(
        "def test_fail():\n    assert False\n",
        encoding="utf-8",
    )


def _write_frontend_package(root: Path) -> None:
    frontend = root / "frontend"
    frontend.mkdir(parents=True, exist_ok=True)
    frontend.joinpath("package.json").write_text(
        """{
  "name": "demo",
  "private": true,
  "scripts": {
    "lint": "echo lint",
    "test": "echo test",
    "build": "echo build"
  }
}
""",
        encoding="utf-8",
    )


def _find_summary(root: Path) -> Path:
    log_dir = root / ".archmind" / "run_logs"
    summaries = sorted(log_dir.glob("run_*.summary.txt"))
    assert summaries, "Expected summary.txt to be created"
    return summaries[-1]


def _find_prompt(root: Path) -> Path:
    log_dir = root / ".archmind" / "run_logs"
    prompts = sorted(log_dir.glob("*.prompt.md"))
    assert prompts, "Expected prompt.md to be created"
    return prompts[-1]


def test_run_missing_path_returns_64(capsys, tmp_path: Path) -> None:
    missing = tmp_path / "missing_project"
    exit_code = main(["run", "--path", str(missing)])
    captured = capsys.readouterr()

    assert exit_code == 64
    assert "path not found" in captured.err.lower()


def test_backend_only_pass_creates_logs(tmp_path: Path) -> None:
    _write_pytest_pass_project(tmp_path)

    exit_code = main(["run", "--path", str(tmp_path), "--backend-only"])
    assert exit_code == 0

    summary_path = _find_summary(tmp_path)
    assert "Backend:" in summary_path.read_text(encoding="utf-8")


def test_backend_fail_returns_1_and_summary(tmp_path: Path) -> None:
    _write_pytest_fail_project(tmp_path)

    exit_code = main(["run", "--path", str(tmp_path), "--backend-only"])
    assert exit_code == 1

    summary_text = _find_summary(tmp_path).read_text(encoding="utf-8")
    assert "Failure summary:" in summary_text
    assert "FAILED" in summary_text or "Traceback" in summary_text

    prompt_text = _find_prompt(tmp_path).read_text(encoding="utf-8")
    assert "archmind run --path" in prompt_text
    assert "python -m pytest -q" in prompt_text


def test_backend_uses_project_venv_python(tmp_path: Path, monkeypatch) -> None:
    _write_pytest_pass_project(tmp_path)
    venv_python = tmp_path / ".venv" / "bin" / "python"
    venv_python.parent.mkdir(parents=True, exist_ok=True)
    venv_python.write_text("#!/usr/bin/env python\n", encoding="utf-8")

    captured: dict[str, list[str]] = {}

    def fake_run_cmd_capture(cmd: list[str], cwd: Path, timeout_s: int) -> CommandResult:
        captured["cmd"] = cmd
        return CommandResult(cmd=cmd, cwd=cwd, exit_code=0, duration_s=0.01, stdout="", stderr="")

    monkeypatch.setattr("archmind.runner.run_cmd_capture", fake_run_cmd_capture)

    exit_code = main(["run", "--path", str(tmp_path), "--backend-only"])
    assert exit_code == 0
    assert captured["cmd"][0] == str(venv_python)
    assert captured["cmd"][1:3] == ["-m", "pytest"]
    assert "-c" in captured["cmd"]
    assert "./pytest.ini" in captured["cmd"]
    assert "-q" in captured["cmd"]


def test_frontend_absent_keeps_backend_result(tmp_path: Path) -> None:
    _write_pytest_pass_project(tmp_path)

    exit_code = main(["run", "--path", str(tmp_path), "--all"])
    assert exit_code == 0

    summary_text = _find_summary(tmp_path).read_text(encoding="utf-8")
    assert "Frontend:" in summary_text
    assert "status: ABSENT" in summary_text


def test_frontend_node_missing_is_skipped(tmp_path: Path, monkeypatch) -> None:
    _write_pytest_pass_project(tmp_path)
    _write_frontend_package(tmp_path)

    monkeypatch.setattr("archmind.runner.shutil.which", lambda _: None)

    exit_code = main(["run", "--path", str(tmp_path), "--all"])
    assert exit_code == 0

    summary_text = _find_summary(tmp_path).read_text(encoding="utf-8")
    assert "status: SKIPPED" in summary_text


def test_frontend_fail_sets_exit_2(tmp_path: Path, monkeypatch) -> None:
    _write_pytest_pass_project(tmp_path)
    _write_frontend_package(tmp_path)

    monkeypatch.setattr("archmind.runner.shutil.which", lambda _: "/usr/bin/fake")

    calls: list[str] = []

    def fake_run_cmd_capture(cmd: list[str], cwd: Path, timeout_s: int) -> CommandResult:
        calls.append(" ".join(cmd))
        if "pytest" in cmd:
            return CommandResult(cmd=cmd, cwd=cwd, exit_code=0, duration_s=0.01, stdout="", stderr="")
        if cmd[:2] == ["npm", "ci"]:
            return CommandResult(cmd=cmd, cwd=cwd, exit_code=0, duration_s=0.01, stdout="ci ok", stderr="")
        if cmd[:2] == ["npm", "install"]:
            return CommandResult(cmd=cmd, cwd=cwd, exit_code=0, duration_s=0.01, stdout="install ok", stderr="")
        if cmd[:3] == ["npm", "run", "lint"]:
            return CommandResult(cmd=cmd, cwd=cwd, exit_code=0, duration_s=0.01, stdout="lint ok", stderr="")
        if cmd[:3] == ["npm", "run", "test"]:
            return CommandResult(cmd=cmd, cwd=cwd, exit_code=1, duration_s=0.01, stdout="test fail", stderr="Traceback")
        if cmd[:3] == ["npm", "run", "build"]:
            return CommandResult(cmd=cmd, cwd=cwd, exit_code=0, duration_s=0.01, stdout="build ok", stderr="")
        return CommandResult(cmd=cmd, cwd=cwd, exit_code=0, duration_s=0.01, stdout="", stderr="")

    monkeypatch.setattr("archmind.runner.run_cmd_capture", fake_run_cmd_capture)

    exit_code = main(["run", "--path", str(tmp_path), "--all"])
    assert exit_code == 2

    assert not any("npm run build" in c for c in calls)
