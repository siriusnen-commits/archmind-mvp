from __future__ import annotations

from pathlib import Path


def detect_fake_success_patterns(project_dir: Path) -> list[str]:
    issues: list[str] = []
    frontend_root = project_dir / "frontend" / "app"
    if not frontend_root.exists():
        return issues

    for page in frontend_root.rglob("page.tsx"):
        try:
            text = page.read_text(encoding="utf-8")
        except Exception:
            continue
        if 'setMessage("Created.")' not in text:
            continue
        has_fetch = "fetch(" in text
        has_error = "setError(" in text or "throw new Error(" in text
        has_refresh = "refreshList(" in text or "setItems(" in text or "router.refresh(" in text
        if has_fetch and has_error and not has_refresh:
            issues.append(f"{page}: fake create success pattern (no list reflection)")
    return issues
