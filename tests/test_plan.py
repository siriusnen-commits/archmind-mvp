from __future__ import annotations

import json
from pathlib import Path

from archmind.cli import main
from archmind.planner import read_plan_summary, write_project_plan


def test_write_project_plan_creates_required_files(tmp_path: Path) -> None:
    artifacts = write_project_plan(tmp_path, "devin-style planning for project")
    assert artifacts.plan_md_path.exists()
    assert artifacts.plan_json_path.exists()

    plan_md_lines = artifacts.plan_md_path.read_text(encoding="utf-8").splitlines()
    assert 20 <= len(plan_md_lines) <= 60
    plan_md_text = "\n".join(plan_md_lines)
    assert "목표/범위" in plan_md_text
    assert "작업 단계" in plan_md_text
    assert "테스트 전략" in plan_md_text
    assert "Done 정의" in plan_md_text

    payload = json.loads(artifacts.plan_json_path.read_text(encoding="utf-8"))
    assert isinstance(payload.get("steps"), list)
    assert isinstance(payload.get("risks"), list)
    assert isinstance(payload.get("acceptance"), list)
    assert payload["steps"]
    assert payload["risks"]
    assert payload["acceptance"]


def test_plan_cli_writes_artifacts(tmp_path: Path) -> None:
    exit_code = main(["plan", "--idea", "stabilize bugfix workflow", "--path", str(tmp_path)])
    assert exit_code == 0
    assert (tmp_path / ".archmind" / "plan.md").exists()
    assert (tmp_path / ".archmind" / "plan.json").exists()


def test_read_plan_summary_truncates_to_200_lines(tmp_path: Path) -> None:
    plan_path = tmp_path / ".archmind" / "plan.md"
    plan_path.parent.mkdir(parents=True, exist_ok=True)
    plan_path.write_text("\n".join(f"line {i}" for i in range(250)), encoding="utf-8")

    summary = read_plan_summary(tmp_path, max_lines=200)
    assert len(summary) == 200
    assert summary[0] == "line 0"
    assert summary[-1] == "line 199"
