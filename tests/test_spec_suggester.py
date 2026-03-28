from __future__ import annotations

from archmind.spec_suggester import suggest_project_spec


def test_suggest_project_spec_defects_domain() -> None:
    out = suggest_project_spec("defect tracker", {"domains": ["defects"], "frontend_needed": True})
    names = [entity["name"] for entity in out["entities"]]
    assert "Defect" in names
    assert "GET /defects" in out["api_endpoints"]


def test_suggest_project_spec_tasks_domain() -> None:
    out = suggest_project_spec("task tracker", {"domains": ["tasks"], "frontend_needed": True})
    names = [entity["name"] for entity in out["entities"]]
    assert "Task" in names


def test_suggest_project_spec_documents_domain() -> None:
    out = suggest_project_spec("document tool", {"domains": ["documents"], "frontend_needed": True})
    names = [entity["name"] for entity in out["entities"]]
    assert "Document" in names


def test_suggest_project_spec_expenses_domain() -> None:
    out = suggest_project_spec("expense app", {"domains": ["expenses"], "frontend_needed": True})
    names = [entity["name"] for entity in out["entities"]]
    assert "Expense" in names


def test_suggest_project_spec_inventory_domain() -> None:
    out = suggest_project_spec("inventory app", {"domains": ["inventory"], "frontend_needed": True})
    names = [entity["name"] for entity in out["entities"]]
    assert "Item" in names


def test_suggest_project_spec_backend_only_can_omit_pages() -> None:
    out = suggest_project_spec("backend api", {"domains": ["tasks"], "frontend_needed": False})
    assert out["frontend_pages"] == []


def test_suggest_project_spec_keyword_inference_for_qa_hardware() -> None:
    out = suggest_project_spec("tv hardware qa defect tracker", {"domains": [], "frontend_needed": True})
    names = [entity["name"] for entity in out["entities"]]
    assert "Device" in names
    assert "TestRun" in names
    assert "Defect" in names


def test_suggest_project_spec_keyword_inference_for_diary_entry_user() -> None:
    out = suggest_project_spec(
        "my diary app with entry pages and user login",
        {"domains": [], "frontend_needed": True},
    )
    names = [entity["name"] for entity in out["entities"]]
    assert "Entry" in names
    assert "User" in names
    assert "GET /entries" in out["api_endpoints"]
    assert "entries/list" in out["frontend_pages"]


def test_suggest_project_spec_diary_without_auth_does_not_inject_user_profile() -> None:
    out = suggest_project_spec("my diary app with entry pages", {"domains": [], "frontend_needed": True, "auth_needed": False})
    names = [entity["name"] for entity in out["entities"]]
    assert "Entry" in names
    assert "User" not in names
    assert "entries/list" in out["frontend_pages"]
    assert "entries/new" in out["frontend_pages"]


def test_suggest_project_spec_bookmark_infers_primary_resource_with_plural_convention() -> None:
    out = suggest_project_spec("bookmark manager web app", {"domains": [], "frontend_needed": True})
    names = [entity["name"] for entity in out["entities"]]
    assert "Bookmark" in names
    assert "GET /bookmarks" in out["api_endpoints"]
    assert "bookmarks/list" in out["frontend_pages"]
    assert "bookmarks/new" in out["frontend_pages"]
