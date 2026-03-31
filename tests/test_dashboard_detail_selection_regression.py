from pathlib import Path


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[1]


def test_project_list_keeps_detail_link_and_separate_set_current_action() -> None:
    source = (_repo_root() / "frontend" / "components" / "ProjectList.tsx").read_text(encoding="utf-8")

    assert 'href={name ? `/projects/${encodeURIComponent(name)}` : "/dashboard"}' in source
    assert 'onClick={() => void handleSetCurrent(name)}' in source
    assert 'import { UI_API_BASE } from "@/components/uiApi";' in source
    assert 'fetch(`${UI_API_BASE}/projects/${encodeURIComponent(target)}/select`' in source
    assert '"Set current"' in source
    assert 'settingCurrentName === name ? "Setting..." : "Set current"' in source


def test_project_detail_page_keeps_detail_only_cards_reachable() -> None:
    source = (_repo_root() / "frontend" / "app" / "projects" / "[project]" / "page.tsx").read_text(
        encoding="utf-8"
    )

    assert 'import AddEntityCard from "@/components/AddEntityCard";' in source
    assert 'import AddFieldCard from "@/components/AddFieldCard";' in source
    assert 'import AddApiCard from "@/components/AddApiCard";' in source
    assert 'import AddPageCard from "@/components/AddPageCard";' in source
    assert 'import DangerZoneCard from "@/components/DangerZoneCard";' in source
    assert '<AddEntityCard projectName={detail.name} />' in source
    assert '<AddFieldCard projectName={detail.name} entities={detail.entities} />' in source
    assert '<AddApiCard projectName={detail.name} />' in source
    assert '<AddPageCard projectName={detail.name} />' in source
    assert '<DangerZoneCard projectName={detail.name} repositoryUrl={detail.repository?.url} />' in source
