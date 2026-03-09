from __future__ import annotations

from archmind.decision import decide_next_action


def test_decision_done() -> None:
    out = decide_next_action({"last_status": "NOT_DONE"}, {"status": "DONE"}, {"status": "SUCCESS"})
    assert out["action"] == "DONE"


def test_decision_stuck() -> None:
    out = decide_next_action({"stuck": True, "stuck_reason": "same failure repeated"}, {}, {})
    assert out["action"] == "STUCK"


def test_decision_fix_when_run_failed_not_stuck() -> None:
    out = decide_next_action({"fix_attempts": 0, "last_status": "FAIL"}, {"status": "NOT_DONE"}, {"status": "FAIL"})
    assert out["action"] == "FIX"


def test_decision_run_when_signature_changed_after_fix() -> None:
    out = decide_next_action(
        {
            "last_action": "archmind fix --path /tmp/p --apply",
            "last_failure_signature_before_fix": "backend-pytest:FAIL",
            "last_failure_signature_after_fix": "frontend-lint:FAIL",
            "last_status": "NOT_DONE",
            "fix_attempts": 1,
        },
        {"status": "NOT_DONE"},
        {},
    )
    assert out["action"] == "RUN"


def test_decision_retry_when_signature_unchanged_after_fix() -> None:
    out = decide_next_action(
        {
            "last_action": "archmind fix --path /tmp/p --apply",
            "last_failure_signature_before_fix": "backend-pytest:FAIL",
            "last_failure_signature_after_fix": "backend-pytest:FAIL",
            "last_status": "NOT_DONE",
            "fix_attempts": 2,
        },
        {"status": "NOT_DONE"},
        {},
    )
    assert out["action"] == "RETRY"


def test_decision_stop_when_ambiguous() -> None:
    out = decide_next_action({}, {}, {})
    assert out["action"] == "STOP"
