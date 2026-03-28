from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, Optional

from archmind.state import update_environment_readiness

ENV_ISSUES = (
    "backend-dependency-missing",
    "frontend-eslint-bootstrap-needed",
    "frontend-config-missing",
    "env-readiness-ok",
    "unknown-environment-issue",
)

_NEXT_ESLINT_PROMPT_MARKERS = (
    "how would you like to configure eslint",
    "strict (recommended)",
    "base",
    "cancel",
    "if you set up eslint yourself",
)

_MODULE_MISSING_RE = re.compile(r"modulenotfounderror:\s*no module named ['\"]([^'\"]+)['\"]", re.IGNORECASE)


def _load_json(path: Path) -> Optional[dict[str, Any]]:
    if not path.exists():
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None
    return payload if isinstance(payload, dict) else None


def _has_eslint_config(frontend_dir: Path) -> bool:
    candidates = (
        ".eslintrc",
        ".eslintrc.json",
        ".eslintrc.js",
        ".eslintrc.cjs",
        ".eslintrc.yaml",
        ".eslintrc.yml",
        "eslint.config.js",
        "eslint.config.cjs",
        "eslint.config.mjs",
    )
    return any((frontend_dir / name).exists() for name in candidates)


def _has_next_lint_script(package_payload: dict[str, Any]) -> bool:
    scripts = package_payload.get("scripts")
    if not isinstance(scripts, dict):
        return False
    lint_cmd = str(scripts.get("lint") or "").lower()
    return "next lint" in lint_cmd


def _collect_log_text(project_dir: Path) -> str:
    archmind = project_dir / ".archmind"
    chunks: list[str] = []
    state_payload = _load_json(archmind / "state.json") or {}
    result_payload = _load_json(archmind / "result.json") or {}
    failures = state_payload.get("recent_failures")
    if isinstance(failures, list):
        chunks.extend(str(x) for x in failures)
    summary = result_payload.get("failure_summary")
    if isinstance(summary, list):
        chunks.extend(str(x) for x in summary)
    run_logs = archmind / "run_logs"
    if run_logs.exists():
        summaries = sorted(run_logs.glob("run_*.summary.txt"), key=lambda p: p.stat().st_mtime, reverse=True)
        if summaries:
            chunks.extend(summaries[0].read_text(encoding="utf-8", errors="replace").splitlines()[-80:])
    return "\n".join(chunks)


def _looks_like_third_party_missing(project_dir: Path, module_name: str) -> bool:
    name = (module_name or "").strip()
    if not name:
        return False
    root_name = name.split(".", 1)[0]
    if (project_dir / root_name).exists() or (project_dir / f"{root_name}.py").exists():
        return False
    return True


def detect_environment_issue(
    project_dir: Path,
    state: Optional[dict[str, Any]],
    result: Optional[dict[str, Any]],
    logs: str,
) -> dict[str, str]:
    project_dir = project_dir.expanduser().resolve()
    state_payload = state or {}
    result_payload = result or {}
    text = (logs or "").lower()

    match = _MODULE_MISSING_RE.search(logs or "")
    if match:
        module_name = match.group(1).strip()
        if (project_dir / "requirements.txt").exists() and _looks_like_third_party_missing(project_dir, module_name):
            return {
                "issue": "backend-dependency-missing",
                "reason": f"missing dependency module detected: {module_name}",
            }

    frontend_dir = project_dir / "frontend"
    package_path = frontend_dir / "package.json"
    package_payload = _load_json(package_path) if package_path.exists() else None
    has_eslint_config = _has_eslint_config(frontend_dir)
    has_next_lint = _has_next_lint_script(package_payload or {}) if isinstance(package_payload, dict) else False

    if has_next_lint and not has_eslint_config:
        if any(marker in text for marker in _NEXT_ESLINT_PROMPT_MARKERS):
            return {
                "issue": "frontend-eslint-bootstrap-needed",
                "reason": "next lint triggered interactive eslint setup prompt",
            }
        return {
            "issue": "frontend-config-missing",
            "reason": "frontend lint script exists but eslint config is missing",
        }

    # fall back to last known issue if still unresolved and logs mention environment-like failures
    previous_issue = str(state_payload.get("environment_issue") or "").strip()
    if previous_issue and previous_issue in ENV_ISSUES and previous_issue != "env-readiness-ok":
        if "module not found" in text or "eslint" in text or "config" in text:
            return {
                "issue": previous_issue,
                "reason": str(state_payload.get("environment_issue_reason") or "environment issue persists").strip(),
            }

    if any(token in text for token in ("modulenotfounderror", "how would you like to configure eslint", "eslint")):
        return {"issue": "unknown-environment-issue", "reason": "environment-related signal detected but not confidently classified"}

    return {"issue": "env-readiness-ok", "reason": "no environment readiness issue detected"}


def _bootstrap_frontend_eslint(project_dir: Path) -> list[str]:
    frontend_dir = project_dir / "frontend"
    if not frontend_dir.exists():
        return []
    target = frontend_dir / ".eslintrc.json"
    if target.exists():
        return []
    payload = {"extends": ["next/core-web-vitals"]}
    target.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    return ["created frontend/.eslintrc.json"]


def apply_safe_bootstrap(project_dir: Path, issue: str) -> list[str]:
    project_dir = project_dir.expanduser().resolve()
    if issue == "frontend-eslint-bootstrap-needed":
        return _bootstrap_frontend_eslint(project_dir)
    if issue == "frontend-config-missing":
        return _bootstrap_frontend_eslint(project_dir)
    return []


def ensure_environment_readiness(
    project_dir: Path,
    *,
    state: Optional[dict[str, Any]] = None,
    result: Optional[dict[str, Any]] = None,
    logs: Optional[str] = None,
) -> dict[str, Any]:
    project_dir = project_dir.expanduser().resolve()
    log_text = logs if logs is not None else _collect_log_text(project_dir)
    decision = detect_environment_issue(project_dir, state or {}, result or {}, log_text)
    issue = str(decision.get("issue") or "unknown-environment-issue")
    reason = str(decision.get("reason") or "")
    actions = apply_safe_bootstrap(project_dir, issue)
    update_environment_readiness(project_dir, issue=issue, reason=reason, bootstrap_actions=actions)
    return {"issue": issue, "reason": reason, "actions": actions}
