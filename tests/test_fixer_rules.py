from __future__ import annotations

from pathlib import Path

from archmind.fixer import apply_plan, build_plan, build_diagnosis


def _write_project(tmp_path: Path) -> Path:
    app_dir = tmp_path / "app" / "api" / "routers"
    app_dir.mkdir(parents=True, exist_ok=True)
    target = app_dir / "defects.py"
    target.write_text(
        "from fastapi import APIRouter\n\n"
        "router = APIRouter()\n\n"
        "def list_defects(q: str = Query(None)):\n"
        "    return q\n",
        encoding="utf-8",
    )
    return target


def test_rule_adds_fastapi_query_import(tmp_path: Path) -> None:
    target = _write_project(tmp_path)

    summary = {
        "backend": {"status": "FAIL", "summary_lines": ["NameError: name 'Query' is not defined"]},
        "frontend": {"status": "SKIPPED", "summary_lines": []},
    }
    log_lines = [f"File \"{target}\", line 3", "NameError: name 'Query' is not defined"]

    diagnosis = build_diagnosis(summary, log_lines)
    plan = build_plan(diagnosis, scope="backend", iteration=1, project_dir=tmp_path)

    applied, _ = apply_plan(plan, tmp_path, apply_changes=True)
    assert applied

    updated = target.read_text(encoding="utf-8")
    assert "from fastapi import APIRouter, Query" in updated


def test_dry_run_does_not_modify_files(tmp_path: Path) -> None:
    target = _write_project(tmp_path)
    original = target.read_text(encoding="utf-8")

    plan = {
        "changes": [
            {
                "rule": "fastapi_imports",
                "names": ["Query"],
                "files_hint": [str(target)],
            }
        ]
    }
    applied, diffs = apply_plan(plan, tmp_path, apply_changes=False)
    assert applied
    assert diffs

    assert target.read_text(encoding="utf-8") == original
