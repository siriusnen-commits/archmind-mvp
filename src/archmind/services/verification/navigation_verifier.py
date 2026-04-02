from __future__ import annotations

from pathlib import Path


def verify_navigation_baseline(project_dir: Path) -> tuple[bool, list[str]]:
    issues: list[str] = []
    nav_path = project_dir / "frontend" / "app" / "_lib" / "navigation.ts"
    if not nav_path.exists():
        return False, ["navigation helper is missing"]

    try:
        text = nav_path.read_text(encoding="utf-8")
    except Exception as exc:
        return False, [f"navigation helper is unreadable: {exc}"]

    has_home = 'href: "/"' in text or 'href: ""' in text
    has_list = any(token in text for token in ["/tasks", "/notes", "/entries", "/bookmarks", "list"]) 
    has_create = '"/new"' in text or "/new\"" in text
    if not has_home:
        issues.append("Home navigation entry is missing")
    if not has_list:
        issues.append("List navigation entry is missing")
    if not has_create:
        issues.append("Create navigation entry is missing")

    app_nav_path = project_dir / "frontend" / "app" / "_lib" / "AppNav.tsx"
    if not app_nav_path.exists():
        issues.append("active-tab navigation component is missing")
    return len(issues) == 0, issues
