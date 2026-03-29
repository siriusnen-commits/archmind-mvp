from __future__ import annotations

import subprocess
from pathlib import Path

from archmind.git_utils import repository_sync_snapshot, sync_repository_changes


def test_sync_repository_changes_commit_only_when_github_auth_not_configured(monkeypatch, tmp_path: Path) -> None:
    project_dir = tmp_path / "repo_auth_missing"
    project_dir.mkdir(parents=True, exist_ok=True)

    monkeypatch.setattr("archmind.git_utils._is_git_repo", lambda _p: True)
    monkeypatch.setattr("archmind.git_utils._has_remote", lambda _p: True)
    monkeypatch.setattr("archmind.git_utils._working_tree_state", lambda _p: "dirty")
    monkeypatch.setattr("archmind.git_utils._last_commit_hash", lambda _p: "abc1234")

    def fake_run_git(_project_dir: Path, args: list[str], timeout: int = 30):  # type: ignore[no-untyped-def]
        del timeout
        if args == ["add", "."]:
            return subprocess.CompletedProcess(["git", *args], 0, stdout="", stderr="")
        if args[:2] == ["commit", "-m"]:
            return subprocess.CompletedProcess(["git", *args], 0, stdout="[main abc1234] commit", stderr="")
        if args == ["push"]:
            return subprocess.CompletedProcess(
                ["git", *args],
                128,
                stdout="",
                stderr="fatal: could not read Username for 'https://github.com': Device not configured",
            )
        raise AssertionError(f"unexpected git args: {args}")

    monkeypatch.setattr("archmind.git_utils._run_git", fake_run_git)

    out = sync_repository_changes(project_dir, commit_message="archmind: test")
    assert out["status"] == "COMMIT_ONLY"
    assert out["committed"] is True
    assert out["pushed"] is False
    assert out["last_commit_hash"] == "abc1234"
    assert "github authentication not configured" in str(out["reason"])
    assert "configure git credentials or token" in str(out["hint"])


def test_sync_repository_changes_commit_only_when_remote_rejects_push(monkeypatch, tmp_path: Path) -> None:
    project_dir = tmp_path / "repo_remote_reject"
    project_dir.mkdir(parents=True, exist_ok=True)

    monkeypatch.setattr("archmind.git_utils._is_git_repo", lambda _p: True)
    monkeypatch.setattr("archmind.git_utils._has_remote", lambda _p: True)
    monkeypatch.setattr("archmind.git_utils._working_tree_state", lambda _p: "dirty")
    monkeypatch.setattr("archmind.git_utils._last_commit_hash", lambda _p: "def5678")

    def fake_run_git(_project_dir: Path, args: list[str], timeout: int = 30):  # type: ignore[no-untyped-def]
        del timeout
        if args == ["add", "."]:
            return subprocess.CompletedProcess(["git", *args], 0, stdout="", stderr="")
        if args[:2] == ["commit", "-m"]:
            return subprocess.CompletedProcess(["git", *args], 0, stdout="[main def5678] commit", stderr="")
        if args == ["push"]:
            return subprocess.CompletedProcess(
                ["git", *args],
                1,
                stdout="",
                stderr="remote: error: GH006: Protected branch update failed\n[remote rejected] main -> main (protected branch hook declined)",
            )
        raise AssertionError(f"unexpected git args: {args}")

    monkeypatch.setattr("archmind.git_utils._run_git", fake_run_git)

    out = sync_repository_changes(project_dir, commit_message="archmind: test")
    assert out["status"] == "COMMIT_ONLY"
    assert out["committed"] is True
    assert out["pushed"] is False
    assert out["last_commit_hash"] == "def5678"
    assert "remote push rejected" in str(out["reason"])


def test_repository_sync_snapshot_reports_ssh_remote_type(monkeypatch, tmp_path: Path) -> None:
    project_dir = tmp_path / "repo_snapshot_ssh"
    project_dir.mkdir(parents=True, exist_ok=True)

    monkeypatch.setattr("archmind.git_utils._is_git_repo", lambda _p: True)
    monkeypatch.setattr("archmind.git_utils._has_remote", lambda _p: True)
    monkeypatch.setattr("archmind.git_utils._last_commit_hash", lambda _p: "abc1234")
    monkeypatch.setattr("archmind.git_utils._working_tree_state", lambda _p: "clean")

    def fake_run_git(_project_dir: Path, args: list[str], timeout: int = 30):  # type: ignore[no-untyped-def]
        del timeout
        if args == ["remote"]:
            return subprocess.CompletedProcess(["git", *args], 0, stdout="origin\n", stderr="")
        if args == ["remote", "get-url", "origin"]:
            return subprocess.CompletedProcess(
                ["git", *args],
                0,
                stdout="git@github.com:siriusnen-commits/generated_repo.git\n",
                stderr="",
            )
        raise AssertionError(f"unexpected git args: {args}")

    monkeypatch.setattr("archmind.git_utils._run_git", fake_run_git)

    snapshot = repository_sync_snapshot(project_dir)
    assert snapshot["remote_type"] == "ssh"
    assert snapshot["remote_url"] == "git@github.com:siriusnen-commits/generated_repo.git"


def test_sync_repository_changes_with_ssh_remote_uses_non_https_failure_reason(monkeypatch, tmp_path: Path) -> None:
    project_dir = tmp_path / "repo_ssh_push_fail"
    project_dir.mkdir(parents=True, exist_ok=True)

    monkeypatch.setattr("archmind.git_utils._is_git_repo", lambda _p: True)
    monkeypatch.setattr("archmind.git_utils._has_remote", lambda _p: True)
    monkeypatch.setattr("archmind.git_utils._working_tree_state", lambda _p: "dirty")
    monkeypatch.setattr("archmind.git_utils._last_commit_hash", lambda _p: "def9999")

    def fake_run_git(_project_dir: Path, args: list[str], timeout: int = 30):  # type: ignore[no-untyped-def]
        del timeout
        if args == ["remote"]:
            return subprocess.CompletedProcess(["git", *args], 0, stdout="origin\n", stderr="")
        if args == ["remote", "get-url", "origin"]:
            return subprocess.CompletedProcess(
                ["git", *args],
                0,
                stdout="git@github.com:siriusnen-commits/generated_repo.git\n",
                stderr="",
            )
        if args == ["add", "."]:
            return subprocess.CompletedProcess(["git", *args], 0, stdout="", stderr="")
        if args[:2] == ["commit", "-m"]:
            return subprocess.CompletedProcess(["git", *args], 0, stdout="[main def9999] commit", stderr="")
        if args == ["push"]:
            return subprocess.CompletedProcess(
                ["git", *args],
                128,
                stdout="",
                stderr="git@github.com: Permission denied (publickey).",
            )
        raise AssertionError(f"unexpected git args: {args}")

    monkeypatch.setattr("archmind.git_utils._run_git", fake_run_git)

    out = sync_repository_changes(project_dir, commit_message="archmind: ssh-test")
    assert out["status"] == "COMMIT_ONLY"
    assert out["remote_type"] == "ssh"
    assert "could not read Username for 'https://github.com'" not in str(out["reason"])
    assert "repository access failed" in str(out["reason"])
