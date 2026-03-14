from __future__ import annotations

from pathlib import Path

import pytest

from archmind.cli import main
import json
import subprocess
import sys


def _write_backend_project(tmp_path: Path) -> None:
    tmp_path.joinpath("pytest.ini").write_text("[pytest]\naddopts = -q\n", encoding="utf-8")
    tmp_path.joinpath("test_ok.py").write_text("def test_ok():\n    assert True\n", encoding="utf-8")


def _write_backend_fail_project(tmp_path: Path) -> None:
    tmp_path.joinpath("pytest.ini").write_text("[pytest]\naddopts = -q\n", encoding="utf-8")
    tmp_path.joinpath("test_fail.py").write_text("def test_fail():\n    assert False\n", encoding="utf-8")


def _fake_generate_project(idea: str, opt) -> Path:
    project_name = (opt.name or "archmind_project").strip() or "archmind_project"
    project_dir = Path(opt.out) / project_name
    project_dir.mkdir(parents=True, exist_ok=True)
    project_dir.joinpath("pytest.ini").write_text("[pytest]\naddopts = -q\n", encoding="utf-8")
    project_dir.joinpath("test_ok.py").write_text("def test_ok():\n    assert True\n", encoding="utf-8")
    return project_dir


def test_pipeline_help() -> None:
    with pytest.raises(SystemExit) as exc:
        main(["pipeline", "--help"])
    assert exc.value.code == 0


def test_pipeline_invalid_path_returns_error(capsys, tmp_path: Path) -> None:
    missing = tmp_path / "missing"
    exit_code = main(["pipeline", "--path", str(missing), "--max-iterations", "1"])
    captured = capsys.readouterr()

    assert exit_code != 0
    assert "path is not a directory" in captured.err.lower() or "error" in captured.err.lower()


def test_pipeline_dry_run_no_artifacts(tmp_path: Path) -> None:
    exit_code = main(["pipeline", "--path", str(tmp_path), "--dry-run"])
    assert exit_code == 0
    assert not (tmp_path / ".archmind").exists()


def test_pipeline_backend_only_smoke(tmp_path: Path) -> None:
    _write_backend_project(tmp_path)

    exit_code = main(
        [
            "pipeline",
            "--path",
            str(tmp_path),
            "--backend-only",
            "--max-iterations",
            "1",
            "--model",
            "none",
            "--scope",
            "backend",
        ]
    )
    assert exit_code in (0, 1)


def test_pipeline_invokes_environment_readiness_check(tmp_path: Path, monkeypatch) -> None:
    _write_backend_project(tmp_path)
    calls = {"n": 0}

    def fake_readiness(project_dir):  # type: ignore[no-untyped-def]
        assert project_dir == tmp_path.resolve()
        calls["n"] += 1
        return {"issue": "env-readiness-ok", "reason": "ok", "actions": []}

    monkeypatch.setattr("archmind.pipeline.ensure_environment_readiness", fake_readiness)
    exit_code = main(
        [
            "pipeline",
            "--path",
            str(tmp_path),
            "--backend-only",
            "--max-iterations",
            "1",
            "--model",
            "none",
        ]
    )
    assert exit_code in (0, 1)
    assert calls["n"] >= 1


def test_pipeline_idea_generates_and_runs(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr("archmind.pipeline._resolve_generator_entry", lambda: _fake_generate_project)

    exit_code = main(
        [
            "pipeline",
            "--idea",
            "demo",
            "--template",
            "fullstack-ddd",
            "--out",
            str(tmp_path),
            "--name",
            "demo_proj",
            "--backend-only",
            "--max-iterations",
            "1",
            "--model",
            "none",
        ]
    )
    assert exit_code == 0

    project_dir = tmp_path / "demo_proj"
    assert project_dir.exists()
    assert (project_dir / ".archmind" / "plan.md").exists()
    assert (project_dir / ".archmind" / "plan.json").exists()
    log_dir = project_dir / ".archmind" / "run_logs"
    assert log_dir.exists()
    assert list(log_dir.glob("run_*.summary.txt"))
    state_payload = json.loads((project_dir / ".archmind" / "state.json").read_text(encoding="utf-8"))
    assert state_payload.get("agent_state") in {"DONE", "NOT_DONE", "STUCK", "BLOCKED"}
    history = state_payload.get("history") or []
    assert any("pipeline planning" in str(item.get("action") or "") for item in history if isinstance(item, dict))
    assert any("pipeline run" in str(item.get("action") or "") for item in history if isinstance(item, dict))
    assert state_payload.get("current_step_key") == "finished"
    assert state_payload.get("current_step_label") == "Finished"
    assert state_payload.get("last_progress_at")


def test_pipeline_idea_generator_receives_effective_template_for_frontend_web(tmp_path: Path, monkeypatch) -> None:
    captured: dict[str, str] = {}

    def fake_generate_project(idea: str, opt) -> Path:  # type: ignore[no-untyped-def]
        captured["idea"] = idea
        captured["template"] = str(getattr(opt, "template", ""))
        project_name = (opt.name or "archmind_project").strip() or "archmind_project"
        project_dir = Path(opt.out) / project_name
        project_dir.mkdir(parents=True, exist_ok=True)
        project_dir.joinpath("pytest.ini").write_text("[pytest]\naddopts = -q\n", encoding="utf-8")
        project_dir.joinpath("test_ok.py").write_text("def test_ok():\n    assert True\n", encoding="utf-8")
        return project_dir

    monkeypatch.setattr("archmind.pipeline._resolve_generator_entry", lambda: fake_generate_project)

    exit_code = main(
        [
            "pipeline",
            "--idea",
            "simple nextjs counter dashboard",
            "--out",
            str(tmp_path),
            "--name",
            "idea_frontend_route",
            "--backend-only",
            "--max-iterations",
            "1",
            "--model",
            "none",
        ]
    )
    assert exit_code == 0
    assert captured.get("idea") == "simple nextjs counter dashboard"
    assert captured.get("template") == "nextjs"

    result_payload = json.loads((tmp_path / "idea_frontend_route" / ".archmind" / "result.json").read_text(encoding="utf-8"))
    assert result_payload.get("selected_template") == "nextjs"
    assert result_payload.get("effective_template") == "nextjs"
    assert result_payload.get("template_fallback_reason") in ("", None)


def test_pipeline_frontend_web_routes_to_nextjs_without_fallback(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr("archmind.pipeline._resolve_generator_entry", lambda: _fake_generate_project)

    exit_code = main(
        [
            "pipeline",
            "--idea",
            "simple nextjs counter dashboard",
            "--out",
            str(tmp_path),
            "--name",
            "frontend_routing_demo",
            "--backend-only",
            "--max-iterations",
            "1",
            "--model",
            "none",
        ]
    )
    assert exit_code == 0

    project_dir = tmp_path / "frontend_routing_demo"
    result_payload = json.loads((project_dir / ".archmind" / "result.json").read_text(encoding="utf-8"))
    assert result_payload.get("project_type") == "frontend-web"
    assert result_payload.get("selected_template") == "nextjs"
    assert result_payload.get("effective_template") == "nextjs"
    assert result_payload.get("template_fallback_reason") in ("", None)

    state_payload = json.loads((project_dir / ".archmind" / "state.json").read_text(encoding="utf-8"))
    assert state_payload.get("effective_template") == "nextjs"
    assert state_payload.get("template_fallback_reason") in ("", None)


def test_pipeline_cli_type_keeps_fallback_metadata(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr("archmind.pipeline._resolve_generator_entry", lambda: _fake_generate_project)

    exit_code = main(
        [
            "pipeline",
            "--idea",
            "python cli tool for csv merge",
            "--out",
            str(tmp_path),
            "--name",
            "cli_routing_demo",
            "--backend-only",
            "--max-iterations",
            "1",
            "--model",
            "none",
        ]
    )
    assert exit_code == 0

    project_dir = tmp_path / "cli_routing_demo"
    result_payload = json.loads((project_dir / ".archmind" / "result.json").read_text(encoding="utf-8"))
    assert result_payload.get("project_type") == "cli-tool"
    assert result_payload.get("selected_template") == "cli"
    assert result_payload.get("effective_template") == "fastapi"
    assert "template not supported" in str(result_payload.get("template_fallback_reason") or "")


def test_pipeline_path_runs_backend_only(tmp_path: Path) -> None:
    _write_backend_project(tmp_path)

    exit_code = main(
        [
            "pipeline",
            "--path",
            str(tmp_path),
            "--backend-only",
            "--max-iterations",
            "1",
            "--model",
            "none",
        ]
    )
    assert exit_code == 0

    log_dir = tmp_path / ".archmind" / "run_logs"
    assert (tmp_path / ".archmind" / "plan.md").exists()
    assert (tmp_path / ".archmind" / "plan.json").exists()
    assert (tmp_path / ".archmind" / "tasks.json").exists()
    result_payload = json.loads((tmp_path / ".archmind" / "result.json").read_text(encoding="utf-8"))
    assert "current_task" in result_payload
    assert list(log_dir.glob("run_*.summary.txt"))


def test_pipeline_failure_creates_prompt_and_summary(tmp_path: Path) -> None:
    _write_backend_fail_project(tmp_path)

    exit_code = main(
        [
            "pipeline",
            "--path",
            str(tmp_path),
            "--backend-only",
            "--max-iterations",
            "1",
            "--model",
            "none",
        ]
    )
    assert exit_code != 0

    log_dir = tmp_path / ".archmind" / "run_logs"
    assert list(log_dir.glob("run_*.summary.txt"))
    prompts = list(log_dir.glob("fix_*.prompt.md"))
    assert prompts
    prompt_text = prompts[-1].read_text(encoding="utf-8")
    assert "Plan 요약" in prompt_text


def test_pipeline_frontend_only_skips_backend(tmp_path: Path) -> None:
    tmp_path.joinpath("pytest.ini").write_text("[pytest]\naddopts = -q\n", encoding="utf-8")

    exit_code = main(
        [
            "pipeline",
            "--path",
            str(tmp_path),
            "--frontend-only",
            "--max-iterations",
            "1",
            "--model",
            "none",
        ]
    )
    assert exit_code == 0

    log_dir = tmp_path / ".archmind" / "run_logs"
    summaries = sorted(log_dir.glob("run_*.summary.txt"))
    assert summaries, "Expected run summary to be created"
    summary_text = summaries[-1].read_text(encoding="utf-8")
    assert "Backend:" in summary_text
    assert "backend not requested" in summary_text


def test_pipeline_backend_only_skips_frontend_in_subprocess(tmp_path: Path) -> None:
    _write_backend_project(tmp_path)
    repo_root = Path(__file__).resolve().parents[1]

    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "archmind.cli",
            "pipeline",
            "--path",
            str(tmp_path),
            "--backend-only",
            "--max-iterations",
            "1",
            "--model",
            "none",
        ],
        cwd=repo_root,
        capture_output=True,
        text=True,
        timeout=120,
    )
    assert result.returncode == 0, result.stderr

    log_dir = tmp_path / ".archmind" / "run_logs"
    summaries = sorted(log_dir.glob("run_*.summary.txt"))
    assert summaries, "Expected run summary to be created"
    summary_text = summaries[-1].read_text(encoding="utf-8")
    assert "Frontend:" in summary_text
    assert "frontend not requested" in summary_text


def test_pipeline_auto_deploy_local_calls_deploy(monkeypatch, tmp_path: Path) -> None:
    _write_backend_project(tmp_path)
    captured: dict[str, object] = {}

    def fake_deploy(project_dir, target="railway", allow_real_deploy=False):  # type: ignore[no-untyped-def]
        captured["project_dir"] = project_dir
        captured["target"] = target
        captured["allow_real_deploy"] = allow_real_deploy
        return {
            "ok": True,
            "target": "local",
            "mode": "real",
            "kind": "backend",
            "status": "SUCCESS",
            "url": "http://127.0.0.1:8011",
            "detail": "local backend started",
            "backend_smoke_url": "http://127.0.0.1:8011/health",
            "backend_smoke_status": "SUCCESS",
            "backend_smoke_detail": "health endpoint returned status ok",
            "frontend_smoke_url": "",
            "frontend_smoke_status": "SKIPPED",
            "frontend_smoke_detail": "frontend not deployed",
        }

    monkeypatch.setattr("archmind.pipeline.deploy_project", fake_deploy)

    exit_code = main(
        [
            "pipeline",
            "--path",
            str(tmp_path),
            "--backend-only",
            "--max-iterations",
            "1",
            "--model",
            "none",
            "--auto-deploy",
            "--deploy-target",
            "local",
        ]
    )
    assert exit_code == 0
    assert captured["project_dir"] == tmp_path.resolve()
    assert captured["target"] == "local"
    assert captured["allow_real_deploy"] is True

    result_payload = json.loads((tmp_path / ".archmind" / "result.json").read_text(encoding="utf-8"))
    assert result_payload.get("auto_deploy_enabled") is True
    assert result_payload.get("auto_deploy_target") == "local"
    assert result_payload.get("auto_deploy_status") == "SUCCESS"


def test_pipeline_auto_deploy_fail_does_not_fail_pipeline(monkeypatch, tmp_path: Path) -> None:
    _write_backend_project(tmp_path)

    monkeypatch.setattr(
        "archmind.pipeline.deploy_project",
        lambda *a, **k: {
            "ok": False,
            "target": "local",
            "mode": "real",
            "kind": "backend",
            "status": "FAIL",
            "url": None,
            "detail": "local backend start failed",
            "backend_smoke_url": "",
            "backend_smoke_status": "SKIPPED",
            "backend_smoke_detail": "deploy failed before smoke check",
            "frontend_smoke_url": "",
            "frontend_smoke_status": "SKIPPED",
            "frontend_smoke_detail": "frontend not deployed",
        },
    )

    exit_code = main(
        [
            "pipeline",
            "--path",
            str(tmp_path),
            "--backend-only",
            "--max-iterations",
            "1",
            "--model",
            "none",
            "--auto-deploy",
        ]
    )
    assert exit_code == 0

    result_payload = json.loads((tmp_path / ".archmind" / "result.json").read_text(encoding="utf-8"))
    assert result_payload.get("status") == "SUCCESS"
    assert result_payload.get("auto_deploy_status") == "FAIL"
