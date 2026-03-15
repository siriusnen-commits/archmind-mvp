from __future__ import annotations

import json
from pathlib import Path

from archmind.cli import main
from archmind.failure_memory import append_failure_memory, get_failure_hints
from archmind.idea_normalizer import normalize_idea


def test_normalize_idea_korean() -> None:
    out = normalize_idea("협업용 작업 관리 대시보드")
    assert out["language"] == "ko"
    assert "task" in str(out["normalized"]).lower()
    assert "dashboard" in str(out["normalized"]).lower()


def test_normalize_idea_japanese() -> None:
    out = normalize_idea("文書アップロード管理ツール")
    assert out["language"] == "ja"
    assert "document" in str(out["normalized"]).lower()
    assert "upload" in str(out["normalized"]).lower()


def test_pipeline_generation_failure_records_failure_memory(tmp_path: Path, monkeypatch) -> None:
    def _raise_generate(*args, **kwargs):  # type: ignore[no-untyped-def]
        raise RuntimeError("generator mock failure")

    monkeypatch.setattr("archmind.pipeline._resolve_generator_entry", lambda: _raise_generate)
    exit_code = main(
        [
            "pipeline",
            "--idea",
            "background batch processing api",
            "--out",
            str(tmp_path),
            "--name",
            "fail_memory_demo",
            "--backend-only",
            "--max-iterations",
            "1",
            "--model",
            "none",
        ]
    )
    assert exit_code != 0

    failure_path = tmp_path / ".archmind" / "failure_memory.json"
    assert failure_path.exists()
    payload = json.loads(failure_path.read_text(encoding="utf-8"))
    assert isinstance(payload, list) and payload
    latest = payload[-1]
    assert "background batch processing api" in str(latest.get("idea") or "")
    assert latest.get("error")
    assert latest.get("hint")


def test_get_failure_hints_for_similar_idea(tmp_path: Path) -> None:
    failure_path = tmp_path / ".archmind" / "failure_memory.json"
    append_failure_memory(
        failure_path,
        idea="background batch processing api",
        template="fastapi",
        modules=["worker"],
        error="mock failure",
        hint="similar idea may require worker module",
    )
    hints = get_failure_hints("api for worker batch jobs", failure_path)
    assert any("worker" in item.lower() for item in hints)
