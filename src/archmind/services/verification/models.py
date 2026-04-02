from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal

VerificationOverallStatus = Literal["VERIFIED", "PARTIAL", "FAILED"]


@dataclass
class VerificationStep:
    name: str
    status: str
    ok: bool
    detail: str = ""

    def as_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "status": self.status,
            "ok": bool(self.ok),
            "detail": str(self.detail or "").strip(),
        }


@dataclass
class MutationVerification:
    overall_status: VerificationOverallStatus = "PARTIAL"
    steps: list[VerificationStep] = field(default_factory=list)
    issues: list[str] = field(default_factory=list)
    runtime_reflection: str = "unknown"
    drift_summary: str = ""

    def as_dict(self) -> dict[str, Any]:
        return {
            "overall_status": str(self.overall_status),
            "steps": [step.as_dict() for step in self.steps],
            "issues": [str(item) for item in self.issues if str(item).strip()],
            "runtime_reflection": str(self.runtime_reflection or "unknown"),
            "drift_summary": str(self.drift_summary or "").strip(),
        }


def fold_overall_status(*, critical_fail: bool, issues: list[str]) -> VerificationOverallStatus:
    if critical_fail:
        return "FAILED"
    if issues:
        return "PARTIAL"
    return "VERIFIED"
