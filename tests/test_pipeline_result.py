from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path


def _write_backend_project(tmp_path: Path, *, failing: bool) -> None:
    tmp_path.joinpath("pytest.ini").write_text("[pytest]\naddopts = -q\n", encoding="utf-8")
    if failing:
        tmp_path.joinpath("test_fail.py").write_text("def test_fail():\n    assert False\n", encoding="utf-8")
    else:
        tmp_path.joinpath("test_ok.py").write_text("def test_ok():\n    assert True\n", encoding="utf-8")


def _run_pipeline(path: Path) -> subprocess.CompletedProcess[str]:
    repo_root = Path(__file__).resolve().parents[1]
    return subprocess.run(
        [
            sys.executable,
            "-m",
            "archmind.cli",
            "pipeline",
            "--path",
            str(path),
            "--backend-only",
            "--max-iterations",
            "1",
            "--model",
            "none",
        ],
        cwd=repo_root,
        capture_output=True,
        text=True,
        timeout=120,
    )


def test_pipeline_writes_result_on_failure(tmp_path: Path) -> None:
    _write_backend_project(tmp_path, failing=True)

    result = _run_pipeline(tmp_path)
    assert result.returncode == 1

    result_path = tmp_path / ".archmind" / "result.json"
    assert result_path.exists()
    payload = json.loads(result_path.read_text(encoding="utf-8"))
    assert payload["status"] in {"FAIL", "PARTIAL"}


def test_pipeline_writes_result_on_success(tmp_path: Path) -> None:
    _write_backend_project(tmp_path, failing=False)

    result = _run_pipeline(tmp_path)
    assert result.returncode in (0, 1)

    result_path = tmp_path / ".archmind" / "result.json"
    assert result_path.exists()
