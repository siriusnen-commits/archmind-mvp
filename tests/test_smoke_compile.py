from __future__ import annotations

import py_compile
from pathlib import Path


def test_tool_sources_compile() -> None:
    """
    Tool repo smoke test:
    - compile-only (no external deps required)
    - catches syntax errors (e.g., unterminated triple quotes)
    """
    root = Path(__file__).resolve().parents[1]
    targets = [
        root / "src" / "archmind" / "cli.py",
        root / "src" / "archmind" / "runner.py",
        root / "src" / "archmind" / "generator.py",
        root / "src" / "archmind" / "templates" / "fastapi.py",
        root / "src" / "archmind" / "templates" / "fastapi_ddd.py",
    ]
    for p in targets:
        assert p.exists(), f"Missing file: {p}"
        py_compile.compile(str(p), doraise=True)
