from __future__ import annotations

import pytest

from archmind.brain import reason_architecture_from_idea
from tests.brain_cases import BRAIN_CASES


@pytest.mark.parametrize("case", BRAIN_CASES, ids=[case["idea"] for case in BRAIN_CASES])
def test_reason_architecture_cases(case: dict[str, object]) -> None:
    idea = str(case["idea"])
    expected_shape = str(case["expected_shape"])
    expected_template = str(case["expected_template"])
    expected_domains = [str(x) for x in (case.get("expected_domains") or [])]

    out = reason_architecture_from_idea(idea)

    assert out["app_shape"] == expected_shape, (
        f"idea={idea}\nexpected_shape={expected_shape}\nactual_shape={out.get('app_shape')}"
    )
    assert out["recommended_template"] == expected_template, (
        f"idea={idea}\nexpected_template={expected_template}\nactual_template={out.get('recommended_template')}"
    )
    if expected_domains:
        actual_domains = [str(x) for x in out.get("domains", [])]
        assert any(domain in actual_domains for domain in expected_domains), (
            f"idea={idea}\nexpected_domains(any)={expected_domains}\nactual_domains={actual_domains}"
        )


def test_reason_architecture_realtime_signal() -> None:
    out = reason_architecture_from_idea("realtime multiplayer web game")
    assert out["realtime_needed"] is True


def test_reason_architecture_unknown_fallback_defaults() -> None:
    out = reason_architecture_from_idea("hello")
    assert out["app_shape"] == "unknown"
    assert out["recommended_template"] == "fastapi"
