from __future__ import annotations

import json
from pathlib import Path

from archmind.cli import main
from archmind.github_repo import build_github_ssh_remote, create_github_repo


class _DummyCompleted:
    def __init__(self, returncode: int = 0, stdout: str = "", stderr: str = "") -> None:
        self.returncode = returncode
        self.stdout = stdout
        self.stderr = stderr


def test_create_github_repo_returns_url_when_gh_succeeds(monkeypatch, tmp_path: Path) -> None:
    (tmp_path / "README.md").write_text("# demo\n", encoding="utf-8")
    calls: list[list[str]] = []

    def fake_run(cmd, **kwargs):  # type: ignore[no-untyped-def]
        calls.append(list(cmd))
        if cmd[:3] == ["gh", "repo", "create"]:
            return _DummyCompleted(
                returncode=0,
                stdout="https://github.com/siriusnen-commits/demo_repo\n",
                stderr="",
            )
        if cmd[:4] == ["git", "remote", "get-url", "origin"]:
            return _DummyCompleted(returncode=0, stdout="https://github.com/siriusnen-commits/demo_repo.git\n", stderr="")
        if cmd[:4] == ["git", "remote", "set-url", "origin"]:
            return _DummyCompleted(returncode=0, stdout="", stderr="")
        return _DummyCompleted(returncode=0, stdout="", stderr="")

    monkeypatch.setattr("archmind.github_repo.subprocess.run", fake_run)
    url = create_github_repo(tmp_path)
    assert url == "https://github.com/siriusnen-commits/demo_repo"
    assert [
        "git",
        "remote",
        "set-url",
        "origin",
        "git@github.com:siriusnen-commits/demo_repo.git",
    ] in calls


def test_create_github_repo_handles_gh_failure_gracefully(monkeypatch, tmp_path: Path) -> None:
    (tmp_path / "README.md").write_text("# demo\n", encoding="utf-8")

    def fake_run(cmd, **kwargs):  # type: ignore[no-untyped-def]
        if cmd[:3] == ["gh", "repo", "create"]:
            return _DummyCompleted(returncode=1, stdout="", stderr="gh failed")
        return _DummyCompleted(returncode=0, stdout="", stderr="")

    monkeypatch.setattr("archmind.github_repo.subprocess.run", fake_run)
    url = create_github_repo(tmp_path)
    assert url is None


def test_create_github_repo_uses_project_id_and_english_slug_for_korean_name(monkeypatch, tmp_path: Path) -> None:
    project_dir = tmp_path / "20260318_171959_일기 웹앱!!!"
    project_dir.mkdir(parents=True, exist_ok=True)
    (project_dir / "README.md").write_text("# demo\n", encoding="utf-8")
    captured_create_cmd: list[str] = []

    def fake_run(cmd, **kwargs):  # type: ignore[no-untyped-def]
        nonlocal captured_create_cmd
        if cmd[:3] == ["gh", "repo", "create"]:
            captured_create_cmd = list(cmd)
            return _DummyCompleted(
                returncode=0,
                stdout="https://github.com/siriusnen-commits/20260318_171959_project\n",
                stderr="",
            )
        if cmd[:4] == ["git", "remote", "set-url", "origin"]:
            return _DummyCompleted(returncode=0, stdout="", stderr="")
        return _DummyCompleted(returncode=0, stdout="", stderr="")

    monkeypatch.setattr("archmind.github_repo.subprocess.run", fake_run)
    url = create_github_repo(project_dir)
    assert captured_create_cmd[:4] == ["gh", "repo", "create", "20260318_171959_project"]
    assert url == "https://github.com/siriusnen-commits/20260318_171959_project"


def test_build_github_ssh_remote_formats_canonical_remote() -> None:
    assert build_github_ssh_remote("siriusnen-commits", "demo_repo") == "git@github.com:siriusnen-commits/demo_repo.git"


def test_create_github_repo_keeps_existing_ssh_origin_without_unnecessary_set_url(monkeypatch, tmp_path: Path) -> None:
    (tmp_path / "README.md").write_text("# demo\n", encoding="utf-8")
    calls: list[list[str]] = []

    def fake_run(cmd, **kwargs):  # type: ignore[no-untyped-def]
        calls.append(list(cmd))
        if cmd[:3] == ["gh", "repo", "create"]:
            return _DummyCompleted(
                returncode=0,
                stdout="https://github.com/siriusnen-commits/ssh_repo\n",
                stderr="",
            )
        if cmd[:4] == ["git", "remote", "get-url", "origin"]:
            return _DummyCompleted(returncode=0, stdout="git@github.com:siriusnen-commits/ssh_repo.git\n", stderr="")
        if cmd[:4] == ["git", "remote", "set-url", "origin"]:
            return _DummyCompleted(returncode=0, stdout="", stderr="")
        return _DummyCompleted(returncode=0, stdout="", stderr="")

    monkeypatch.setattr("archmind.github_repo.subprocess.run", fake_run)
    url = create_github_repo(tmp_path)
    assert url == "https://github.com/siriusnen-commits/ssh_repo"
    assert ["git", "remote", "set-url", "origin", "git@github.com:siriusnen-commits/ssh_repo.git"] not in calls


def test_pipeline_stores_github_repo_url_in_state(monkeypatch, tmp_path: Path) -> None:
    def fake_generate_project(idea: str, opt) -> Path:  # type: ignore[no-untyped-def]
        project_name = (opt.name or "archmind_project").strip() or "archmind_project"
        project_dir = Path(opt.out) / project_name
        project_dir.mkdir(parents=True, exist_ok=True)
        project_dir.joinpath("pytest.ini").write_text("[pytest]\naddopts = -q\n", encoding="utf-8")
        project_dir.joinpath("test_ok.py").write_text("def test_ok():\n    assert True\n", encoding="utf-8")
        return project_dir

    monkeypatch.setattr("archmind.pipeline._resolve_generator_entry", lambda: fake_generate_project)
    monkeypatch.setattr(
        "archmind.pipeline.create_github_repo_with_status",
        lambda _project_dir, enabled=True: {  # noqa: ARG001
            "status": "CREATED",
            "url": "https://github.com/siriusnen-commits/idea_repo",
            "name": "idea_repo",
            "reason": "",
            "attempted": True,
        },
    )

    exit_code = main(
        [
            "pipeline",
            "--idea",
            "simple fastapi notes api",
            "--out",
            str(tmp_path),
            "--name",
            "idea_repo",
            "--backend-only",
            "--max-iterations",
            "1",
            "--model",
            "none",
        ]
    )
    assert exit_code == 0

    state_payload = json.loads((tmp_path / "idea_repo" / ".archmind" / "state.json").read_text(encoding="utf-8"))
    result_payload = json.loads((tmp_path / "idea_repo" / ".archmind" / "result.json").read_text(encoding="utf-8"))
    assert state_payload.get("github_repo_url") == "https://github.com/siriusnen-commits/idea_repo"
    assert result_payload.get("github_repo_url") == "https://github.com/siriusnen-commits/idea_repo"
    assert (state_payload.get("repository") or {}).get("status") == "CREATED"
