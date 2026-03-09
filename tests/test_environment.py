from __future__ import annotations

import json
from pathlib import Path

from archmind.environment import apply_safe_bootstrap, detect_environment_issue, ensure_environment_readiness


def test_detect_frontend_eslint_bootstrap_needed_from_interactive_prompt(tmp_path: Path) -> None:
    frontend = tmp_path / "frontend"
    frontend.mkdir(parents=True, exist_ok=True)
    (frontend / "package.json").write_text(
        json.dumps({"scripts": {"lint": "next lint"}}),
        encoding="utf-8",
    )
    logs = "\n".join(
        [
            "How would you like to configure ESLint?",
            "Strict (recommended)",
            "Base",
            "Cancel",
        ]
    )
    out = detect_environment_issue(tmp_path, {}, {}, logs)
    assert out["issue"] == "frontend-eslint-bootstrap-needed"


def test_bootstrap_creates_eslintrc_json(tmp_path: Path) -> None:
    frontend = tmp_path / "frontend"
    frontend.mkdir(parents=True, exist_ok=True)
    actions = apply_safe_bootstrap(tmp_path, "frontend-eslint-bootstrap-needed")
    target = frontend / ".eslintrc.json"
    assert target.exists()
    payload = json.loads(target.read_text(encoding="utf-8"))
    assert payload["extends"] == ["next/core-web-vitals", "next/typescript"]
    assert "created frontend/.eslintrc.json" in actions


def test_bootstrap_does_not_overwrite_existing_eslintrc(tmp_path: Path) -> None:
    frontend = tmp_path / "frontend"
    frontend.mkdir(parents=True, exist_ok=True)
    target = frontend / ".eslintrc.json"
    target.write_text(json.dumps({"extends": ["custom"]}), encoding="utf-8")
    actions = apply_safe_bootstrap(tmp_path, "frontend-eslint-bootstrap-needed")
    payload = json.loads(target.read_text(encoding="utf-8"))
    assert payload["extends"] == ["custom"]
    assert actions == []


def test_detect_backend_dependency_missing_fastapi(tmp_path: Path) -> None:
    (tmp_path / "requirements.txt").write_text("pytest==8.0.0\n", encoding="utf-8")
    logs = "E ModuleNotFoundError: No module named 'fastapi'"
    out = detect_environment_issue(tmp_path, {}, {}, logs)
    assert out["issue"] == "backend-dependency-missing"


def test_ensure_environment_readiness_records_state(tmp_path: Path) -> None:
    archmind = tmp_path / ".archmind"
    archmind.mkdir(parents=True, exist_ok=True)
    frontend = tmp_path / "frontend"
    frontend.mkdir(parents=True, exist_ok=True)
    (frontend / "package.json").write_text(json.dumps({"scripts": {"lint": "next lint"}}), encoding="utf-8")
    outcome = ensure_environment_readiness(
        tmp_path,
        logs="How would you like to configure ESLint?\nStrict (recommended)\nBase\nCancel\n",
    )
    assert outcome["issue"] == "frontend-eslint-bootstrap-needed"
    state_payload = json.loads((archmind / "state.json").read_text(encoding="utf-8"))
    assert state_payload["environment_issue"] == "frontend-eslint-bootstrap-needed"
    assert "last_bootstrap_actions" in state_payload
