from __future__ import annotations

import re
import subprocess
from pathlib import Path
from typing import Optional


def _run(cmd: list[str], cwd: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(  # noqa: S603
        cmd,
        cwd=cwd,
        capture_output=True,
        text=True,
        timeout=60,
        shell=False,
        check=False,
    )


def _extract_repo_url(*texts: str) -> Optional[str]:
    for text in texts:
        if not text:
            continue
        match = re.search(r"https://github\.com/[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", text)
        if match:
            return match.group(0)
    return None


def build_github_ssh_remote(owner: str, repo: str) -> str:
    owner_text = str(owner or "").strip()
    repo_text = str(repo or "").strip()
    if not owner_text or not repo_text:
        return ""
    return f"git@github.com:{owner_text}/{repo_text}.git"


def _extract_owner_repo_from_url(repo_url: str) -> tuple[str, str]:
    text = str(repo_url or "").strip()
    if not text:
        return "", ""
    matched = re.search(r"github\.com[:/]+([A-Za-z0-9_.-]+)/([A-Za-z0-9_.-]+?)(?:\.git)?$", text)
    if not matched:
        return "", ""
    owner = str(matched.group(1) or "").strip()
    repo = str(matched.group(2) or "").strip()
    return owner, repo


def _resolve_owner_repo(project_dir: Path, repo_slug: str, repo_url: str) -> tuple[str, str]:
    owner, repo = _extract_owner_repo_from_url(repo_url)
    if owner and repo:
        return owner, repo
    view_result = _run(
        ["gh", "repo", "view", repo_slug, "--json", "name,owner", "-q", ".owner.login + \"/\" + .name"],
        cwd=project_dir,
    )
    if view_result.returncode != 0:
        return "", ""
    pair = str(view_result.stdout or "").strip()
    if "/" not in pair:
        return "", ""
    owner_text, repo_text = pair.split("/", 1)
    return str(owner_text).strip(), str(repo_text).strip()


def _ensure_origin_remote_ssh(project_dir: Path, ssh_remote: str) -> tuple[bool, str]:
    if not ssh_remote:
        return False, "empty ssh remote"
    current = _run(["git", "remote", "get-url", "origin"], cwd=project_dir)
    if current.returncode == 0 and str(current.stdout or "").strip() == ssh_remote:
        return True, ""

    set_result = _run(["git", "remote", "set-url", "origin", ssh_remote], cwd=project_dir)
    if set_result.returncode == 0:
        return True, ""

    add_result = _run(["git", "remote", "add", "origin", ssh_remote], cwd=project_dir)
    if add_result.returncode == 0:
        return True, ""

    reason = (set_result.stderr or set_result.stdout or add_result.stderr or add_result.stdout or "git remote set-url failed").strip()
    return False, reason


def _split_display_name(project_dir: Path) -> tuple[str, str]:
    display_name = project_dir.name
    matched = re.match(r"^(\d{8}_\d{6})(?:[_-]+(.*))?$", display_name)
    if not matched:
        return "", display_name
    project_id = str(matched.group(1) or "").strip()
    tail = str(matched.group(2) or "").strip()
    return project_id, tail


def _sanitize_english_slug(value: str, max_len: int = 24) -> str:
    text = str(value or "").strip().lower()
    text = text.replace("_", " ").replace("-", " ")
    text = re.sub(r"[^a-z0-9\s]", " ", text)
    text = re.sub(r"\s+", "-", text).strip("-")
    if not text:
        return "project"
    return text[:max_len].strip("-") or "project"


def _build_repo_slug(project_dir: Path) -> str:
    project_id, raw_tail = _split_display_name(project_dir)
    short_english_slug = _sanitize_english_slug(raw_tail or project_dir.name)
    if project_id:
        return f"{project_id}_{short_english_slug}"
    return short_english_slug


def create_github_repo_with_status(project_dir: Path, *, enabled: bool = True) -> dict[str, object]:
    project_dir = project_dir.expanduser().resolve()
    repo_slug = _build_repo_slug(project_dir)
    payload: dict[str, object] = {
        "status": "SKIPPED",
        "url": "",
        "name": repo_slug,
        "reason": "",
        "attempted": False,
    }
    if not enabled:
        payload["reason"] = "repository creation disabled"
        return payload
    if not project_dir.exists() or not project_dir.is_dir():
        payload["reason"] = "generation failed before scaffold completed"
        return payload

    payload["attempted"] = True
    git_dir = project_dir / ".git"
    if not git_dir.exists():
        init_result = _run(["git", "init"], cwd=project_dir)
        if init_result.returncode != 0:
            payload["status"] = "FAILED"
            payload["reason"] = (init_result.stderr or init_result.stdout or "git init failed").strip()
            return payload

    add_result = _run(["git", "add", "."], cwd=project_dir)
    if add_result.returncode != 0:
        payload["status"] = "FAILED"
        payload["reason"] = (add_result.stderr or add_result.stdout or "git add failed").strip()
        return payload

    commit_result = _run(
        ["git", "commit", "-m", "Initial commit (generated by ArchMind)"],
        cwd=project_dir,
    )
    if commit_result.returncode != 0:
        combined = f"{commit_result.stdout}\n{commit_result.stderr}".lower()
        if "nothing to commit" not in combined and "working tree clean" not in combined:
            payload["status"] = "FAILED"
            payload["reason"] = (commit_result.stderr or commit_result.stdout or "git commit failed").strip()
            return payload

    create_result = _run(
        [
            "gh",
            "repo",
            "create",
            repo_slug,
            "--private",
            "--source",
            str(project_dir),
            "--push",
        ],
        cwd=project_dir,
    )
    if create_result.returncode != 0:
        payload["status"] = "FAILED"
        payload["reason"] = (create_result.stderr or create_result.stdout or "gh repo create failed").strip()
        return payload

    repo_url = _extract_repo_url(create_result.stdout, create_result.stderr)
    if not repo_url:
        view_result = _run(["gh", "repo", "view", repo_slug, "--json", "url", "-q", ".url"], cwd=project_dir)
        if view_result.returncode != 0:
            payload["status"] = "FAILED"
            payload["reason"] = (view_result.stderr or view_result.stdout or "gh repo view failed").strip()
            return payload
        repo_url = (view_result.stdout or "").strip()
    if not repo_url:
        payload["status"] = "FAILED"
        payload["reason"] = "repository URL not returned"
        return payload

    payload["status"] = "CREATED"
    payload["url"] = repo_url
    payload["reason"] = ""
    owner, repo = _resolve_owner_repo(project_dir, repo_slug, repo_url)
    ssh_remote = build_github_ssh_remote(owner, repo)
    ok, reason = _ensure_origin_remote_ssh(project_dir, ssh_remote)
    if ok and ssh_remote:
        payload["remote_url"] = ssh_remote
    elif not ok and reason:
        payload["reason"] = f"repository created but failed to set SSH origin: {reason}"
    return payload


def create_github_repo(project_dir: Path) -> Optional[str]:
    result = create_github_repo_with_status(project_dir, enabled=True)
    if str(result.get("status") or "").upper() != "CREATED":
        return None
    value = str(result.get("url") or "").strip()
    return value or None
