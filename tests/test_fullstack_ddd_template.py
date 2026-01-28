from __future__ import annotations

import importlib
import os
import sys
from pathlib import Path

from archmind.generator import GenerateOptions, generate_project


def _generate_fullstack(tmp_path: Path, name: str = "fullstack_demo") -> Path:
    opt = GenerateOptions(out=tmp_path, force=False, name=name, template="fullstack-ddd")
    project_dir = generate_project("defect tracker", opt)
    return Path(project_dir)


def _import_app(project_dir: Path, db_url: str):
    prev = os.environ.get("DB_URL")
    os.environ["DB_URL"] = db_url
    db_path = db_url.replace("sqlite:///", "", 1)
    if db_path:
        Path(db_path).parent.mkdir(parents=True, exist_ok=True)
    sys.path.insert(0, str(project_dir))
    try:
        for mod in list(sys.modules):
            if mod == "app" or mod.startswith("app."):
                del sys.modules[mod]
        module = importlib.import_module("app.main")
        from app.db.session import init_db

        init_db()
        return module.app
    finally:
        if str(project_dir) in sys.path:
            sys.path.remove(str(project_dir))
        if prev is None:
            os.environ.pop("DB_URL", None)
        else:
            os.environ["DB_URL"] = prev


def test_fullstack_ddd_template_pytest_passes(tmp_path: Path) -> None:
    import subprocess

    project_dir = _generate_fullstack(tmp_path)
    result = subprocess.run(
        [sys.executable, "-m", "pytest", "-q"],
        cwd=project_dir,
        capture_output=True,
        text=True,
        timeout=120,
    )
    assert result.returncode == 0, result.stderr


def test_defects_query_sort_pagination(tmp_path: Path) -> None:
    project_dir = _generate_fullstack(tmp_path)
    db_path = project_dir / "data" / "test.db"
    db_url = f"sqlite:///{db_path}"
    app = _import_app(project_dir, db_url)

    from fastapi.testclient import TestClient

    client = TestClient(app)
    for dtype in ["HDMI_CEC", "HDMI_ARC", "USB_POWER"]:
        r = client.post("/defects", json={"defect_type": dtype, "note": f"note {dtype}"})
        assert r.status_code == 200

    r = client.get("/defects", params={"defect_type": "HDMI"})
    assert r.status_code == 200
    data = r.json()
    assert data["total"] == 2

    r = client.get("/defects", params={"q": "USB"})
    assert r.status_code == 200
    assert r.json()["total"] == 1

    r = client.get("/defects", params={"page": 1, "page_size": 2})
    assert r.status_code == 200
    assert len(r.json()["items"]) == 2

    r = client.get("/defects", params={"sort": "id", "order": "asc"})
    assert r.status_code == 200
    ids = [item["id"] for item in r.json()["items"]]
    assert ids == sorted(ids)


def test_pipeline_generate_and_run_backend_only(tmp_path: Path) -> None:
    from archmind.cli import main

    exit_code = main(
        [
            "pipeline",
            "--idea",
            "defect tracker",
            "--template",
            "fullstack-ddd",
            "--out",
            str(tmp_path),
            "--name",
            "fs_pipeline",
            "--backend-only",
            "--max-iterations",
            "1",
            "--model",
            "none",
        ]
    )
    assert exit_code == 0

    project_dir = tmp_path / "fs_pipeline"
    log_dir = project_dir / ".archmind" / "run_logs"
    assert log_dir.exists()
    assert list(log_dir.glob("run_*.summary.txt"))
