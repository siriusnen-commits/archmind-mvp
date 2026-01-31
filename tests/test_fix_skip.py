from __future__ import annotations

from pathlib import Path

from archmind.cli import main


def _write_frontend_project(root: Path) -> None:
    frontend = root / "frontend"
    frontend.mkdir(parents=True, exist_ok=True)
    frontend.joinpath("package.json").write_text(
        '{"name": "demo", "private": true, "scripts": {"lint": "echo lint"}}',
        encoding="utf-8",
    )


def test_fix_frontend_skip_exits_zero(tmp_path: Path, monkeypatch) -> None:
    _write_frontend_project(tmp_path)
    monkeypatch.setattr("archmind.runner.shutil.which", lambda _: None)

    exit_code = main(["fix", "--path", str(tmp_path), "--scope", "frontend"])
    assert exit_code == 0

    log_dir = tmp_path / ".archmind" / "run_logs"
    prompts = sorted(log_dir.glob("fix_*.prompt.md"))
    assert prompts, "Expected skip prompt to be created"
    prompt_text = prompts[-1].read_text(encoding="utf-8")
    assert "환경 문제로 SKIP" in prompt_text
