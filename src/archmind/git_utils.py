from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Any

RUNTIME_LOCAL_PREFIXES = (
    ".archmind/",
    "logs/",
    "tmp/",
    ".pytest_cache/",
)
RUNTIME_LOCAL_FILES = {
    ".archmind/state.json",
    ".archmind/result.json",
    ".archmind/evaluation.json",
    ".archmind/plan.md",
    ".archmind/plan.json",
}
RUNTIME_LOCAL_SUFFIXES = (".log", ".pid", ".tmp")


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


def _remote_name(project_dir: Path) -> str:
    try:
        result = _run_git(project_dir, ["remote"])
    except Exception:
        return ""
    if result.returncode != 0:
        return ""
    remotes = [str(line).strip() for line in str(result.stdout or "").splitlines() if str(line).strip()]
    if not remotes:
        return ""
    if "origin" in remotes:
        return "origin"
    return remotes[0]


def _remote_url(project_dir: Path) -> str:
    name = _remote_name(project_dir)
    if not name:
        return ""
    try:
        result = _run_git(project_dir, ["remote", "get-url", name])
    except Exception:
        return ""
    if result.returncode != 0:
        return ""
    return str(result.stdout or "").strip()


def _remote_type(remote_url: str) -> str:
    url = str(remote_url or "").strip().lower()
    if not url:
        return ""
    if url.startswith("git@") or url.startswith("ssh://"):
        return "ssh"
    if url.startswith("http://") or url.startswith("https://"):
        return "https"
    return "other"


def _status_lines(project_dir: Path) -> list[str]:
    if not _is_git_repo(project_dir):
        return []
    try:
        result = _run_git(project_dir, ["status", "--porcelain"])
    except Exception:
        return []
    if result.returncode != 0:
        return []
    return [str(line).rstrip("\n") for line in str(result.stdout or "").splitlines() if str(line).strip()]


def _dirty_paths(project_dir: Path) -> list[str]:
    paths: list[str] = []
    for line in _status_lines(project_dir):
        raw = line[3:] if len(line) >= 4 else ""
        path = str(raw).strip()
        if " -> " in path:
            path = path.split(" -> ", 1)[1].strip()
        if path.startswith('"') and path.endswith('"') and len(path) >= 2:
            path = path[1:-1]
        if path:
            paths.append(path)
    deduped: list[str] = []
    seen: set[str] = set()
    for item in paths:
        if item in seen:
            continue
        seen.add(item)
        deduped.append(item)
    return deduped


def _is_runtime_local_path(path: str) -> bool:
    normalized = str(path or "").strip().lstrip("./")
    if not normalized:
        return False
    if normalized in RUNTIME_LOCAL_FILES:
        return True
    if any(normalized.startswith(prefix) for prefix in RUNTIME_LOCAL_PREFIXES):
        return True
    return any(normalized.endswith(suffix) for suffix in RUNTIME_LOCAL_SUFFIXES)


def _classify_dirty_paths(paths: list[str]) -> dict[str, Any]:
    runtime_only: list[str] = []
    unexpected: list[str] = []
    for path in paths:
        if _is_runtime_local_path(path):
            runtime_only.append(path)
        else:
            unexpected.append(path)
    if not paths:
        summary = "clean"
    elif unexpected:
        summary = f"dirty ({len(unexpected)} unexpected files)"
    else:
        summary = "dirty (runtime artifacts only)"
    top = unexpected[:3] if unexpected else runtime_only[:3]
    detail = ", ".join(top)
    if len(paths) > len(top) and top:
        detail += ", ..."
    return {
        "runtime_only_paths": runtime_only,
        "unexpected_paths": unexpected,
        "summary": summary,
        "detail": detail,
    }


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
    remote_url = _remote_url(project_dir)
    return {
        "is_git_repo": _is_git_repo(project_dir),
        "has_remote": _has_remote(project_dir),
        "remote_url": remote_url,
        "remote_type": _remote_type(remote_url),
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
            "dirty_detail": "",
            "remote_url": str(snapshot.get("remote_url") or ""),
            "remote_type": str(snapshot.get("remote_type") or ""),
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
            "dirty_detail": "",
            "remote_url": str(snapshot.get("remote_url") or ""),
            "remote_type": str(snapshot.get("remote_type") or ""),
        }

    dirty_before = _dirty_paths(root)
    status_before = "dirty" if dirty_before else _working_tree_state(root)
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
            "dirty_detail": "",
            "remote_url": str(snapshot.get("remote_url") or ""),
            "remote_type": str(snapshot.get("remote_type") or ""),
        }

    add_result = _run_git(root, ["add", "."])
    classification_before = _classify_dirty_paths(dirty_before)
    runtime_paths = [str(path).strip() for path in classification_before.get("runtime_only_paths") or [] if str(path).strip()]
    if add_result.returncode == 0 and runtime_paths:
        _run_git(root, ["reset", "-q", "HEAD", "--", *runtime_paths])
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
            "dirty_detail": str(classification_before.get("detail") or ""),
            "remote_url": str(snapshot.get("remote_url") or ""),
            "remote_type": str(snapshot.get("remote_type") or ""),
        }

    commit_result = _run_git(root, ["commit", "-m", str(commit_message or "archmind: update").strip()])
    commit_stdout = str(commit_result.stdout or "")
    commit_stderr = str(commit_result.stderr or "")
    if commit_result.returncode != 0:
        combined = f"{commit_stdout}\n{commit_stderr}".strip().lower()
        if "nothing to commit" in combined or "no changes added to commit" in combined:
            post_paths = _dirty_paths(root)
            post_classification = _classify_dirty_paths(post_paths)
            if post_paths:
                return {
                    "attempted": True,
                    "status": "DIRTY",
                    "reason": str(post_classification.get("summary") or "dirty working tree"),
                    "last_commit_hash": _last_commit_hash(root),
                    "working_tree_state": "dirty",
                    "committed": False,
                    "pushed": False,
                    "hint": "",
                    "dirty_detail": str(post_classification.get("detail") or ""),
                    "remote_url": str(snapshot.get("remote_url") or ""),
                    "remote_type": str(snapshot.get("remote_type") or ""),
                }
            return {
                "attempted": True,
                "status": "SYNCED",
                "reason": "no changes",
                "last_commit_hash": _last_commit_hash(root),
                "working_tree_state": _working_tree_state(root),
                "committed": False,
                "pushed": False,
                "hint": "",
                "dirty_detail": "",
                "remote_url": str(snapshot.get("remote_url") or ""),
                "remote_type": str(snapshot.get("remote_type") or ""),
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
            "dirty_detail": str(_classify_dirty_paths(_dirty_paths(root)).get("detail") or ""),
            "remote_url": str(snapshot.get("remote_url") or ""),
            "remote_type": str(snapshot.get("remote_type") or ""),
        }

    push_result = _run_git(root, ["push"])
    if push_result.returncode != 0:
        normalized_reason, hint = _normalize_push_failure_reason(str(push_result.stderr or ""), str(push_result.stdout or ""))
        post_paths = _dirty_paths(root)
        post_classification = _classify_dirty_paths(post_paths)
        return {
            "attempted": True,
            "status": "COMMIT_ONLY",
            "reason": normalized_reason,
            "last_commit_hash": _last_commit_hash(root),
            "working_tree_state": "dirty" if post_paths else "clean",
            "committed": True,
            "pushed": False,
            "hint": hint,
            "dirty_detail": str(post_classification.get("detail") or ""),
            "remote_url": str(snapshot.get("remote_url") or ""),
            "remote_type": str(snapshot.get("remote_type") or ""),
        }
    post_paths = _dirty_paths(root)
    post_classification = _classify_dirty_paths(post_paths)
    return {
        "attempted": True,
        "status": "DIRTY" if post_paths else "SYNCED",
        "reason": str(post_classification.get("summary") or "") if post_paths else "",
        "last_commit_hash": _last_commit_hash(root),
        "working_tree_state": "dirty" if post_paths else "clean",
        "committed": True,
        "pushed": True,
        "hint": "",
        "dirty_detail": str(post_classification.get("detail") or ""),
        "remote_url": str(snapshot.get("remote_url") or ""),
        "remote_type": str(snapshot.get("remote_type") or ""),
    }
