from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from archmind.services.verification.crud_verifier import detect_fake_success_patterns
from archmind.services.verification.models import MutationVerification, VerificationStep, fold_overall_status
from archmind.services.verification.navigation_verifier import verify_navigation_baseline
from archmind.services.verification.runtime_verifier import verify_runtime_restart

TARGET_COMMAND_PREFIXES = ("/add_field", "/add_api", "/add_page", "/auto")


def _entity_to_resource(entity_name: str) -> str:
    token = str(entity_name or "").strip()
    if not token:
        return ""
    snake = re.sub(r"(?<!^)(?=[A-Z])", "_", token).strip("_").lower()
    if not snake:
        return ""
    if snake.endswith("s"):
        return snake
    if snake.endswith("y") and len(snake) > 1 and snake[-2] not in "aeiou":
        return snake[:-1] + "ies"
    if snake.endswith(("ch", "sh", "x", "z")):
        return snake + "es"
    return snake + "s"


@dataclass
class MutationContext:
    command: str
    project_dir: Path
    spec_before: dict[str, Any]
    spec_after: dict[str, Any]
    result: dict[str, Any]


def _read_spec(project_dir: Path) -> dict[str, Any]:
    spec_path = project_dir / ".archmind" / "project_spec.json"
    if not spec_path.exists():
        return {}
    try:
        payload = json.loads(spec_path.read_text(encoding="utf-8"))
    except Exception:
        return {}
    return payload if isinstance(payload, dict) else {}


def snapshot_mutation_state(project_dir: Path) -> dict[str, Any]:
    return {"spec": _read_spec(project_dir)}


def _contains_expected_spec_change(command: str, spec_after: dict[str, Any]) -> bool:
    text = str(command or "").strip()
    if text.startswith("/add_field"):
        parts = text.split()
        if len(parts) < 3:
            return False
        entity = parts[1].strip().lower()
        field_pair = parts[2].strip()
        field_name = field_pair.split(":", 1)[0].strip().lower()
        for item in (spec_after.get("entities") or []):
            if not isinstance(item, dict):
                continue
            if str(item.get("name") or "").strip().lower() != entity:
                continue
            for field in (item.get("fields") or []):
                if not isinstance(field, dict):
                    continue
                if str(field.get("name") or "").strip().lower() == field_name:
                    return True
        return False
    if text.startswith("/add_api"):
        normalized = " ".join(text.split()[1:]).strip().upper()
        endpoints = [str(x).strip().upper() for x in (spec_after.get("api_endpoints") or [])]
        return normalized in endpoints
    if text.startswith("/add_page"):
        rel = " ".join(text.split()[1:]).strip().lower().strip("/")
        pages = [str(x).strip().lower().strip("/") for x in (spec_after.get("frontend_pages") or [])]
        return rel in pages
    return True


def _code_patch_detected(project_dir: Path, command: str, result: dict[str, Any]) -> tuple[bool, str]:
    changed = [str(x).strip() for x in (result.get("generated_files") or []) if str(x).strip()]
    changed += [str(x).strip() for x in (result.get("changed_files") or []) if str(x).strip()]
    if changed:
        return True, "generated/changed files reported by mutation runner"

    text = str(command or "").strip()
    if text.startswith("/add_field"):
        parts = text.split()
        if len(parts) >= 3:
            field_name = parts[2].split(":", 1)[0].strip()
            backend_hits = list(project_dir.rglob("*.py"))
            for path in backend_hits:
                try:
                    body = path.read_text(encoding="utf-8")
                except Exception:
                    continue
                if field_name in body:
                    return True, f"field name detected in backend code ({path.name})"
    if text.startswith("/add_api"):
        api_part = " ".join(text.split()[1:]).strip()
        for path in project_dir.rglob("*.py"):
            try:
                body = path.read_text(encoding="utf-8")
            except Exception:
                continue
            if api_part and api_part.split(" ", 1)[-1] in body:
                return True, f"api path detected in backend code ({path.name})"
    if text.startswith("/add_page"):
        rel = " ".join(text.split()[1:]).strip().strip("/")
        target = project_dir / "frontend" / "app" / rel / "page.tsx"
        if target.exists():
            return True, f"frontend page exists ({target})"

    return False, "no concrete code patch signal found"


def _runtime_reflection_check(project_dir: Path, command: str) -> tuple[bool, str]:
    text = str(command or "").strip()
    if text.startswith("/add_field"):
        parts = text.split()
        if len(parts) < 3:
            return False, "malformed add_field command"
        entity_name = parts[1].strip()
        field_name = parts[2].split(":", 1)[0].strip()
        entity_resource = _entity_to_resource(entity_name)
        target_page = project_dir / "frontend" / "app" / entity_resource / "new" / "page.tsx"
        if target_page.exists():
            try:
                body = target_page.read_text(encoding="utf-8")
            except Exception:
                body = ""
            if field_name in body:
                return True, f"frontend create form reflects field ({field_name})"
            return False, f"frontend create form does not reflect field ({field_name})"
        create_pages = list((project_dir / "frontend" / "app").rglob("new/page.tsx")) if (project_dir / "frontend" / "app").exists() else []
        for page in create_pages:
            try:
                body = page.read_text(encoding="utf-8")
            except Exception:
                continue
            if field_name in body:
                return True, f"frontend create form reflects field ({field_name})"
        return False, f"frontend create form does not reflect field ({field_name})"

    if text.startswith("/add_api"):
        api_path = " ".join(text.split()[2:]).strip()
        for path in project_dir.rglob("*.py"):
            try:
                body = path.read_text(encoding="utf-8")
            except Exception:
                continue
            if api_path and api_path in body:
                return True, "backend route patch includes target path"
        return False, "target API path not found in generated backend code"

    if text.startswith("/add_page"):
        rel = " ".join(text.split()[1:]).strip().strip("/")
        target = project_dir / "frontend" / "app" / rel / "page.tsx"
        return target.exists(), ("frontend page exists" if target.exists() else "frontend page file not found")

    return True, "auto verification relies on per-step records"


def verify_mutation(command: str, project_dir: Path, before: dict[str, Any], result: dict[str, Any]) -> dict[str, Any]:
    after = snapshot_mutation_state(project_dir)
    spec_before = before.get("spec") if isinstance(before.get("spec"), dict) else {}
    spec_after = after.get("spec") if isinstance(after.get("spec"), dict) else {}

    issues: list[str] = []
    steps: list[VerificationStep] = []

    spec_changed = spec_before != spec_after and _contains_expected_spec_change(command, spec_after)
    if not spec_changed:
        issues.append("spec mutation is missing or incomplete")
    steps.append(
        VerificationStep(
            name="spec",
            status="SPEC_UPDATED" if spec_changed else "FAILED",
            ok=spec_changed,
            detail="spec reflects requested mutation" if spec_changed else "spec does not reflect requested mutation",
        )
    )

    code_ok, code_detail = _code_patch_detected(project_dir, command, result if isinstance(result, dict) else {})
    if not code_ok:
        issues.append(code_detail)
    steps.append(VerificationStep(name="code", status="CODE_PATCHED" if code_ok else "FAILED", ok=code_ok, detail=code_detail))

    runtime_ok, runtime_detail, runtime_reflection = verify_runtime_restart(
        project_dir,
        result.get("runtime_recovery") if isinstance(result, dict) else None,
    )
    if not runtime_ok:
        issues.append(runtime_detail)
    steps.append(
        VerificationStep(
            name="runtime",
            status="RUNTIME_RESTARTED" if runtime_ok else "FAILED",
            ok=runtime_ok,
            detail=runtime_detail,
        )
    )

    reflect_ok, reflect_detail = _runtime_reflection_check(project_dir, command)
    if not reflect_ok:
        issues.append(reflect_detail)
    steps.append(VerificationStep(name="reflection", status="VERIFIED" if reflect_ok else "FAILED", ok=reflect_ok, detail=reflect_detail))

    crud_issues = detect_fake_success_patterns(project_dir)
    if crud_issues:
        issues.extend(crud_issues)

    nav_ok, nav_issues = verify_navigation_baseline(project_dir)
    if not nav_ok:
        issues.extend(nav_issues)

    critical_fail = not spec_changed or not code_ok
    overall = fold_overall_status(critical_fail=critical_fail, issues=issues)
    drift_summary = "runtime and generated code are aligned" if overall == "VERIFIED" else "; ".join(issues[:3])

    verification = MutationVerification(
        overall_status=overall,
        steps=steps,
        issues=issues,
        runtime_reflection=runtime_reflection,
        drift_summary=drift_summary,
    )
    return verification.as_dict()


def should_verify_command(command: str) -> bool:
    text = str(command or "").strip().lower()
    return any(text.startswith(prefix) for prefix in TARGET_COMMAND_PREFIXES)
