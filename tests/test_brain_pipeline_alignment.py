from __future__ import annotations

import json
from pathlib import Path

import pytest

from archmind.cli import main
from tests.brain_cases import BRAIN_CASES


ALIGNMENT_CASES = [
    BRAIN_CASES[0],   # backend
    BRAIN_CASES[1],   # fullstack
    BRAIN_CASES[2],   # frontend
    BRAIN_CASES[7],   # realtime -> frontend
    BRAIN_CASES[9],   # backend with inventory domain
]


def _fake_generate_project(idea: str, opt) -> Path:  # type: ignore[no-untyped-def]
    del idea
    project_name = (opt.name or "archmind_project").strip() or "archmind_project"
    project_dir = Path(opt.out) / project_name
    project_dir.mkdir(parents=True, exist_ok=True)

    template = str(getattr(opt, "template", "") or "").strip().lower()
    project_dir.joinpath("pytest.ini").write_text("[pytest]\naddopts = -q\n", encoding="utf-8")
    project_dir.joinpath("test_ok.py").write_text("def test_ok():\n    assert True\n", encoding="utf-8")

    if template in ("fastapi", "fastapi-ddd", "worker-api", "internal-tool", "data-tool"):
        backend_root = project_dir
        (backend_root / "app").mkdir(parents=True, exist_ok=True)
        (backend_root / "app" / "__init__.py").write_text("", encoding="utf-8")
        (backend_root / "app" / "main.py").write_text(
            "from fastapi import FastAPI\napp = FastAPI()\n@app.get('/health')\ndef health(): return {'status':'ok'}\n",
            encoding="utf-8",
        )
        (backend_root / "requirements.txt").write_text("fastapi\nuvicorn\n", encoding="utf-8")
    if template == "fullstack-ddd":
        backend_root = project_dir / "backend"
        (backend_root / "app").mkdir(parents=True, exist_ok=True)
        (backend_root / "app" / "__init__.py").write_text("", encoding="utf-8")
        (backend_root / "app" / "main.py").write_text(
            "from fastapi import FastAPI\napp = FastAPI()\n@app.get('/health')\ndef health(): return {'status':'ok'}\n",
            encoding="utf-8",
        )
        (backend_root / "requirements.txt").write_text("fastapi\nuvicorn\n", encoding="utf-8")

    if template in ("nextjs", "fullstack-ddd", "internal-tool", "data-tool"):
        frontend_dir = project_dir / "frontend" if template == "fullstack-ddd" else project_dir
        if template in ("internal-tool", "data-tool"):
            frontend_dir = project_dir / "frontend"
        frontend_dir.mkdir(parents=True, exist_ok=True)
        (frontend_dir / "package.json").write_text(
            json.dumps({"name": "demo", "scripts": {"dev": "next dev", "start": "next start"}}),
            encoding="utf-8",
        )
        (frontend_dir / "next.config.mjs").write_text("export default {};\n", encoding="utf-8")

    return project_dir


def _detect_project_shape(project_dir: Path) -> str:
    has_backend = (
        (project_dir / "app").is_dir()
        or (project_dir / "requirements.txt").exists()
        or (project_dir / "backend" / "app").is_dir()
        or (project_dir / "backend" / "requirements.txt").exists()
    )
    has_frontend = (
        (project_dir / "frontend" / "package.json").exists()
        or (project_dir / "package.json").exists()
        or (project_dir / "next.config.mjs").exists()
    )
    if has_backend and has_frontend:
        return "fullstack"
    if has_backend:
        return "backend"
    if has_frontend:
        return "frontend"
    return "unknown"


@pytest.mark.parametrize("case", ALIGNMENT_CASES, ids=[case["idea"] for case in ALIGNMENT_CASES])
def test_pipeline_reasoning_alignment(case: dict[str, object], monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr("archmind.pipeline._resolve_generator_entry", lambda: _fake_generate_project)

    idea = str(case["idea"])
    name = f"brain_align_{ALIGNMENT_CASES.index(case)}"
    exit_code = main(
        [
            "pipeline",
            "--idea",
            idea,
            "--out",
            str(tmp_path),
            "--name",
            name,
            "--backend-only",
            "--max-iterations",
            "1",
            "--model",
            "none",
        ]
    )
    assert exit_code == 0, f"pipeline failed for idea={idea}"

    project_dir = tmp_path / name
    reasoning_path = project_dir / ".archmind" / "architecture_reasoning.json"
    assert reasoning_path.exists(), f"architecture_reasoning.json missing for idea={idea}"

    reasoning = json.loads(reasoning_path.read_text(encoding="utf-8"))
    recommended_template = str(reasoning.get("recommended_template") or "").strip()
    assert recommended_template, f"recommended_template missing for idea={idea}"

    result_payload = json.loads((project_dir / ".archmind" / "result.json").read_text(encoding="utf-8"))
    selected_template = str(result_payload.get("selected_template") or "").strip()
    assert selected_template == recommended_template, (
        f"idea={idea}\nrecommended_template={recommended_template}\nselected_template={selected_template}"
    )

    reasoning_shape = str(reasoning.get("app_shape") or "unknown")
    actual_shape = _detect_project_shape(project_dir)
    if reasoning_shape == "fullstack":
        assert actual_shape == "fullstack", f"idea={idea}\nreasoning_shape={reasoning_shape}\nactual_shape={actual_shape}"
    elif reasoning_shape == "backend":
        assert actual_shape in ("backend", "fullstack"), (
            f"idea={idea}\nreasoning_shape={reasoning_shape}\nactual_shape={actual_shape}"
        )
    elif reasoning_shape == "frontend":
        assert actual_shape in ("frontend", "fullstack"), (
            f"idea={idea}\nreasoning_shape={reasoning_shape}\nactual_shape={actual_shape}"
        )
