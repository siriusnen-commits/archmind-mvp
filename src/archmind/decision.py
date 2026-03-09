from __future__ import annotations

from typing import Any

NEXT_ACTIONS = ("DONE", "FIX", "RUN", "RETRY", "STUCK", "STOP")


def _norm(value: Any) -> str:
    return str(value or "").strip().upper()


def _latest_run_failed(state: dict[str, Any], evaluation: dict[str, Any], result: dict[str, Any]) -> bool:
    checks = evaluation.get("checks")
    if isinstance(checks, dict) and _norm(checks.get("run_status")) == "FAIL":
        return True
    if _norm(result.get("status")) in ("FAIL", "PARTIAL"):
        return True
    return _norm(state.get("last_status")) == "FAIL"


def decide_next_action(state: dict[str, Any], evaluation: dict[str, Any], result: dict[str, Any]) -> dict[str, str]:
    state = state or {}
    evaluation = evaluation or {}
    result = result or {}

    eval_status = _norm(evaluation.get("status"))
    state_status = _norm(state.get("last_status"))
    stuck = bool(state.get("stuck")) or eval_status == "STUCK"
    fix_attempts = int(state.get("fix_attempts") or 0)
    iterations = int(state.get("iterations") or 0)
    last_action = str(state.get("last_action") or "").lower()
    before = str(state.get("last_failure_signature_before_fix") or "").strip()
    after = str(state.get("last_failure_signature_after_fix") or "").strip()

    if eval_status == "DONE":
        return {"action": "DONE", "reason": "evaluation marked project complete", "confidence": "high"}
    if state_status == "DONE":
        return {"action": "DONE", "reason": "state marked project complete", "confidence": "medium"}
    if stuck:
        reason = str(state.get("stuck_reason") or "").strip() or "stuck state detected"
        return {"action": "STUCK", "reason": reason, "confidence": "high"}
    if eval_status == "BLOCKED":
        return {"action": "STOP", "reason": "project is blocked", "confidence": "high"}

    if before and after and before != after:
        return {"action": "RUN", "reason": "failure signature changed after fix", "confidence": "high"}
    if before and after and before == after and "fix" in last_action:
        if fix_attempts >= 3 or iterations >= 3:
            return {"action": "RETRY", "reason": "fix did not change failure signature", "confidence": "high"}
        return {"action": "RETRY", "reason": "fix completed but failure signature is unchanged", "confidence": "medium"}

    if _latest_run_failed(state, evaluation, result):
        if fix_attempts == 0:
            return {"action": "FIX", "reason": "latest run failed and no fix attempt yet", "confidence": "high"}
        if "fix" in last_action:
            return {"action": "RETRY", "reason": "fix attempted; another fix+run loop may help", "confidence": "medium"}
        return {"action": "FIX", "reason": "latest run failed", "confidence": "high"}

    if eval_status == "NOT_DONE":
        if state_status in ("SUCCESS", "SKIP") and "fix" in last_action:
            return {"action": "RUN", "reason": "fix completed and project needs rerun", "confidence": "medium"}
        if fix_attempts > 0:
            return {"action": "RETRY", "reason": "project still not done after prior attempts", "confidence": "medium"}
        return {"action": "RUN", "reason": "project not done; run/evaluate cycle needed", "confidence": "low"}

    if state_status == "NOT_DONE":
        if "fix" in last_action:
            return {"action": "RUN", "reason": "fix completed; rerun to validate changes", "confidence": "medium"}
        if fix_attempts > 0:
            return {"action": "RETRY", "reason": "project still not done after fix attempts", "confidence": "medium"}
        return {"action": "FIX", "reason": "project is not done and needs a fix attempt", "confidence": "medium"}

    return {"action": "STOP", "reason": "insufficient signal for automatic next step", "confidence": "low"}


def next_action_suggestions(action: str) -> list[str]:
    normalized = _norm(action)
    if normalized == "DONE":
        return ["review project artifacts"]
    if normalized == "STUCK":
        return ["run /logs backend", "inspect backend failure details", "then run /fix or /continue"]
    if normalized == "FIX":
        return ["run /logs backend", "run /fix"]
    if normalized == "RUN":
        return ["run /continue"]
    if normalized == "RETRY":
        return ["run /retry"]
    if normalized == "STOP":
        return ["inspect /state and logs before proceeding"]
    return ["run /state"]
