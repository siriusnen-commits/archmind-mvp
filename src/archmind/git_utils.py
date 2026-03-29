from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Any


def _run_git(project_dir: Path, args: list[str], timeout: int = 30) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", *args],
        cwd=project_dir.expanduser().resolve(),
        capture_output=True,
        text=True,
        timeout=timeout,
        shell=False,
        check=False,
    )


def _short_reason(text: str) -> str:
    line = str(text or "").strip().splitlines()
    if not line:
        return ""
    return line[0][:220]


def _normalize_push_failure_reason(stderr: str, stdout: str) -> tuple[str, str]:
    combined = "\n".join(part for part in [str(stderr or "").strip(), str(stdout or "").strip()] if part).strip()
    lowered = combined.lower()
    detail = _short_reason(combined)

    if "could not read username for 'https://github.com'" in lowered:
        reason = "github authentication not configured"
        if detail:
            reason = f"{reason} ({detail})"
        return reason, "configure git credentials or token for GitHub push from this environment"
    if "authentication failed" in lowered or "invalid username or password" in lowered:
        reason = "github authentication failed"
        if detail:
            reason = f"{reason} ({detail})"
        return reason, "check GitHub credentials/token permissions for this environment"
    if "permission denied" in lowered:
        reason = "repository access failed"
        if detail:
            reason = f"{reason} ({detail})"
        return reason, "check repository write permission for the configured GitHub credentials"
    if "repository not found" in lowered:
        reason = "repository access failed"
        if detail:
            reason = f"{reason} ({detail})"
        return reason, "verify remote repository URL and access permission"
    if "remote rejected" in lowered or "[remote rejected]" in lowered:
        reason = "remote push rejected"
        if detail:
            reason = f"{reason} ({detail})"
        return reason, "check branch protection or remote policy for this repository"

    reason = "git push failed"
    if detail:
        reason = f"{reason} ({detail})"
    return reason, ""


def _is_git_repo(project_dir: Path) -> bool:
    try:
        result = _run_git(project_dir, ["rev-parse", "--is-inside-work-tree"])
    except Exception:
        return False
    return result.returncode == 0 and str(result.stdout or "").strip().lower() == "true"


def _has_remote(project_dir: Path) -> bool:
    try:
        result = _run_git(project_dir, ["remote"])
    except Exception:
        return False
    if result.returncode != 0:
        return False
    return bool([line for line in str(result.stdout or "").splitlines() if str(line).strip()])


def _working_tree_state(project_dir: Path) -> str:
    if not _is_git_repo(project_dir):
        return "unknown"
    try:
        result = _run_git(project_dir, ["status", "--porcelain"])
    except Exception:
        return "unknown"
    if result.returncode != 0:
        return "unknown"
    return "dirty" if str(result.stdout or "").strip() else "clean"


def _last_commit_hash(project_dir: Path) -> str:
    if not _is_git_repo(project_dir):
        return ""
    try:
        result = _run_git(project_dir, ["rev-parse", "--short", "HEAD"])
    except Exception:
        return ""
    if result.returncode != 0:
        return ""
    return str(result.stdout or "").strip()


def repository_sync_snapshot(project_dir: Path) -> dict[str, Any]:
    return {
        "is_git_repo": _is_git_repo(project_dir),
        "has_remote": _has_remote(project_dir),
        "last_commit_hash": _last_commit_hash(project_dir),
        "working_tree_state": _working_tree_state(project_dir),
    }


def sync_repository_changes(project_dir: Path, *, commit_message: str) -> dict[str, Any]:
    root = project_dir.expanduser().resolve()
    snapshot = repository_sync_snapshot(root)
    if not snapshot.get("is_git_repo"):
        return {
            "attempted": False,
            "status": "NOT_ATTEMPTED",
            "reason": "git repository not initialized",
            "last_commit_hash": str(snapshot.get("last_commit_hash") or ""),
            "working_tree_state": str(snapshot.get("working_tree_state") or "unknown"),
            "committed": False,
            "pushed": False,
            "hint": "",
        }
    if not snapshot.get("has_remote"):
        return {
            "attempted": False,
            "status": "NOT_ATTEMPTED",
            "reason": "git remote not configured",
            "last_commit_hash": str(snapshot.get("last_commit_hash") or ""),
            "working_tree_state": str(snapshot.get("working_tree_state") or "unknown"),
            "committed": False,
            "pushed": False,
            "hint": "",
        }

    status_before = _working_tree_state(root)
    if status_before != "dirty":
        return {
            "attempted": False,
            "status": "SYNCED",
            "reason": "no changes",
            "last_commit_hash": _last_commit_hash(root),
            "working_tree_state": status_before,
            "committed": False,
            "pushed": False,
            "hint": "",
        }

    add_result = _run_git(root, ["add", "."])
    if add_result.returncode != 0:
        return {
            "attempted": True,
            "status": "DIRTY",
            "reason": _short_reason(add_result.stderr or add_result.stdout or "git add failed"),
            "last_commit_hash": _last_commit_hash(root),
            "working_tree_state": _working_tree_state(root),
            "committed": False,
            "pushed": False,
            "hint": "",
        }

    commit_result = _run_git(root, ["commit", "-m", str(commit_message or "archmind: update").strip()])
    commit_stdout = str(commit_result.stdout or "")
    commit_stderr = str(commit_result.stderr or "")
    if commit_result.returncode != 0:
        combined = f"{commit_stdout}\n{commit_stderr}".strip().lower()
        if "nothing to commit" in combined or "no changes added to commit" in combined:
            return {
                "attempted": True,
                "status": "SYNCED",
                "reason": "no changes",
                "last_commit_hash": _last_commit_hash(root),
                "working_tree_state": _working_tree_state(root),
                "committed": False,
                "pushed": False,
                "hint": "",
            }
        return {
            "attempted": True,
            "status": "DIRTY",
            "reason": _short_reason(commit_stderr or commit_stdout or "git commit failed"),
            "last_commit_hash": _last_commit_hash(root),
            "working_tree_state": _working_tree_state(root),
            "committed": False,
            "pushed": False,
            "hint": "",
        }

    push_result = _run_git(root, ["push"])
    if push_result.returncode != 0:
        normalized_reason, hint = _normalize_push_failure_reason(str(push_result.stderr or ""), str(push_result.stdout or ""))
        return {
            "attempted": True,
            "status": "COMMIT_ONLY",
            "reason": normalized_reason,
            "last_commit_hash": _last_commit_hash(root),
            "working_tree_state": _working_tree_state(root),
            "committed": True,
            "pushed": False,
            "hint": hint,
        }
    return {
        "attempted": True,
        "status": "SYNCED",
        "reason": "",
        "last_commit_hash": _last_commit_hash(root),
        "working_tree_state": _working_tree_state(root),
        "committed": True,
        "pushed": True,
        "hint": "",
    }
