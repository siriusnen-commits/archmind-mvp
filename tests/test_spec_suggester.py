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
    assert "PATCH /entries/{id}" in out["api_endpoints"]
    assert "entries/list" in out["frontend_pages"]


def test_suggest_project_spec_diary_without_auth_does_not_inject_user_profile() -> None:
    out = suggest_project_spec("my diary app with entry pages", {"domains": [], "frontend_needed": True, "auth_needed": False})
    names = [entity["name"] for entity in out["entities"]]
    assert "Entry" in names
    assert "User" not in names
    entry = next(entity for entity in out["entities"] if entity["name"] == "Entry")
    field_names = {str(field.get("name") or "") for field in entry.get("fields", []) if isinstance(field, dict)}
    assert {"title", "content", "created_at"}.issubset(field_names)
    assert "entries/list" in out["frontend_pages"]
    assert "entries/new" in out["frontend_pages"]
    assert "entries/detail" in out["frontend_pages"]


def test_suggest_project_spec_bookmark_infers_primary_resource_with_plural_convention() -> None:
    out = suggest_project_spec("bookmark manager web app", {"domains": [], "frontend_needed": True})
    entities = [entity for entity in out["entities"] if isinstance(entity, dict)]
    names = [str(entity.get("name") or "") for entity in entities]
    assert "Bookmark" in names
    bookmark = next(entity for entity in entities if str(entity.get("name") or "") == "Bookmark")
    field_names = {
        str(field.get("name") or "")
        for field in (bookmark.get("fields") if isinstance(bookmark.get("fields"), list) else [])
        if isinstance(field, dict)
    }
    assert {"title", "url", "note"}.issubset(field_names)
    assert "GET /bookmarks" in out["api_endpoints"]
    assert "PATCH /bookmarks/{id}" in out["api_endpoints"]
    assert "DELETE /bookmarks/{id}" in out["api_endpoints"]
    assert "bookmarks/list" in out["frontend_pages"]
    assert "bookmarks/new" in out["frontend_pages"]
    assert "bookmarks/detail" in out["frontend_pages"]


def test_suggest_project_spec_kanban_infers_board_and_card_with_relation_field() -> None:
    out = suggest_project_spec("kanban board app with boards and cards", {"domains": [], "frontend_needed": True})
    entities = out.get("entities") if isinstance(out.get("entities"), list) else []
    names = [str(entity.get("name") or "") for entity in entities if isinstance(entity, dict)]
    assert "Board" in names
    assert "Card" in names
    card = next(entity for entity in entities if isinstance(entity, dict) and str(entity.get("name") or "") == "Card")
    card_fields = card.get("fields") if isinstance(card.get("fields"), list) else []
    field_names = {str(field.get("name") or "") for field in card_fields if isinstance(field, dict)}
    assert "board_id" in field_names
    assert "GET /cards" in out["api_endpoints"]
    assert "cards/list" in out["frontend_pages"]


def test_suggest_project_spec_diary_tags_preserves_entry_and_tag() -> None:
    out = suggest_project_spec("diary app with entries and tags", {"domains": [], "frontend_needed": True})
    names = [entity["name"] for entity in out["entities"]]
    assert "Entry" in names
    assert "Tag" in names
    modules = [str(x).strip().lower() for x in (out.get("modules") or []) if str(x).strip()]
    assert "tagging" in modules
    assert "GET /entries" in out["api_endpoints"]
    assert "GET /tags" in out["api_endpoints"]
    assert "GET /entries/{id}/tags" in out["api_endpoints"]
    assert "tags/by_entry" in out["frontend_pages"]


def test_suggest_project_spec_bookmark_category_preserves_both_entities() -> None:
    out = suggest_project_spec("bookmark manager with categories", {"domains": [], "frontend_needed": True})
    entities = [entity for entity in out["entities"] if isinstance(entity, dict)]
    names = [str(entity.get("name") or "") for entity in entities]
    assert "Bookmark" in names
    assert "Category" in names
    bookmark = next(entity for entity in entities if str(entity.get("name") or "") == "Bookmark")
    bookmark_field_names = {
        str(field.get("name") or "")
        for field in (bookmark.get("fields") if isinstance(bookmark.get("fields"), list) else [])
        if isinstance(field, dict)
    }
    assert "category" in bookmark_field_names
    modules = [str(x).strip().lower() for x in (out.get("modules") or []) if str(x).strip()]
    assert "tagging" in modules
    category = next(entity for entity in entities if str(entity.get("name") or "") == "Category")
    field_names = {
        str(field.get("name") or "")
        for field in (category.get("fields") if isinstance(category.get("fields"), list) else [])
        if isinstance(field, dict)
    }
    assert {"name", "bookmark_id"}.issubset(field_names)
    assert "GET /bookmarks" in out["api_endpoints"]
    assert "GET /categories" in out["api_endpoints"]
    assert "GET /bookmarks/{id}/categories" in out["api_endpoints"]
    assert "categories/by_bookmark" in out["frontend_pages"]


def test_starter_pack_bookmark_with_folder_signal_includes_category_field() -> None:
    out = suggest_project_spec("link saver app with folder groups", {"domains": [], "frontend_needed": True})
    entities = [entity for entity in out["entities"] if isinstance(entity, dict)]
    bookmark = next(entity for entity in entities if str(entity.get("name") or "") == "Bookmark")
    field_names = {
        str(field.get("name") or "")
        for field in (bookmark.get("fields") if isinstance(bookmark.get("fields"), list) else [])
        if isinstance(field, dict)
    }
    assert "category" in field_names


def test_starter_pack_bookmark_with_search_applies_search_module_expectations() -> None:
    out = suggest_project_spec("bookmark app with search", {"domains": [], "frontend_needed": True})
    entities = [entity for entity in out["entities"] if isinstance(entity, dict)]
    names = [str(entity.get("name") or "") for entity in entities]
    assert "Bookmark" in names
    modules = [str(x).strip().lower() for x in (out.get("modules") or []) if str(x).strip()]
    assert "search" in modules
    expectations = [str(x).strip().lower() for x in (out.get("frontend_expectations") or []) if str(x).strip()]
    assert "list_search_input" in expectations
    assert "search_empty_state" in expectations


def test_starter_pack_bookmark_with_history_includes_created_at() -> None:
    out = suggest_project_spec("reading list app with recent saved date history", {"domains": [], "frontend_needed": True})
    entities = [entity for entity in out["entities"] if isinstance(entity, dict)]
    bookmark = next(entity for entity in entities if str(entity.get("name") or "") == "Bookmark")
    field_names = {
        str(field.get("name") or "")
        for field in (bookmark.get("fields") if isinstance(bookmark.get("fields"), list) else [])
        if isinstance(field, dict)
    }
    assert "created_at" in field_names


def test_starter_pack_bookmark_with_tags_preserves_tagging_path_without_entity_duplication() -> None:
    out = suggest_project_spec("bookmark app with tags", {"domains": [], "frontend_needed": True})
    entities = [entity for entity in out["entities"] if isinstance(entity, dict)]
    names = [str(entity.get("name") or "") for entity in entities]
    assert names.count("Category") <= 1
    modules = [str(x).strip().lower() for x in (out.get("modules") or []) if str(x).strip()]
    assert "tagging" in modules
    assert "GET /categories" in out["api_endpoints"]
    assert "GET /bookmarks/{id}/categories" in out["api_endpoints"]


def test_bookmark_signal_does_not_misclassify_unrelated_dashboard_idea() -> None:
    out = suggest_project_spec("analytics dashboard for sales", {"domains": [], "frontend_needed": True})
    names = [str(entity.get("name") or "") for entity in out["entities"] if isinstance(entity, dict)]
    assert "Bookmark" not in names


def test_starter_pack_memo_notes_routes_to_note_with_useful_defaults() -> None:
    out = suggest_project_spec("quick personal notes app", {"domains": [], "frontend_needed": True})
    entities = [entity for entity in out["entities"] if isinstance(entity, dict)]
    names = [str(entity.get("name") or "") for entity in entities]
    assert "Note" in names
    note = next(entity for entity in entities if str(entity.get("name") or "") == "Note")
    field_names = {
        str(field.get("name") or "")
        for field in (note.get("fields") if isinstance(note.get("fields"), list) else [])
        if isinstance(field, dict)
    }
    assert {"title", "content"}.issubset(field_names)
    assert "notes/list" in out["frontend_pages"]
    assert "notes/new" in out["frontend_pages"]
    assert "notes/detail" in out["frontend_pages"]


def test_starter_pack_todo_tasks_routes_to_task_with_status_and_crud() -> None:
    out = suggest_project_spec("simple todo app for task management", {"domains": [], "frontend_needed": True})
    entities = [entity for entity in out["entities"] if isinstance(entity, dict)]
    names = [str(entity.get("name") or "") for entity in entities]
    assert "Task" in names
    task = next(entity for entity in entities if str(entity.get("name") or "") == "Task")
    field_names = {
        str(field.get("name") or "")
        for field in (task.get("fields") if isinstance(task.get("fields"), list) else [])
        if isinstance(field, dict)
    }
    assert {"title", "status"}.issubset(field_names)
    assert "GET /tasks" in out["api_endpoints"]
    assert "POST /tasks" in out["api_endpoints"]
    assert "GET /tasks/{id}" in out["api_endpoints"]
    assert "PATCH /tasks/{id}" in out["api_endpoints"]
    assert "DELETE /tasks/{id}" in out["api_endpoints"]
    assert "tasks/list" in out["frontend_pages"]
    assert "tasks/new" in out["frontend_pages"]
    assert "tasks/detail" in out["frontend_pages"]


def test_starter_pack_todo_includes_due_date_when_due_signal_exists() -> None:
    out = suggest_project_spec("todo app with due date and deadlines", {"domains": [], "frontend_needed": True})
    entities = [entity for entity in out["entities"] if isinstance(entity, dict)]
    task = next(entity for entity in entities if str(entity.get("name") or "") == "Task")
    field_names = {
        str(field.get("name") or "")
        for field in (task.get("fields") if isinstance(task.get("fields"), list) else [])
        if isinstance(field, dict)
    }
    assert "due_date" in field_names


def test_starter_pack_task_tracker_with_details_includes_description() -> None:
    out = suggest_project_spec("task tracker with details", {"domains": [], "frontend_needed": True})
    entities = [entity for entity in out["entities"] if isinstance(entity, dict)]
    task = next(entity for entity in entities if str(entity.get("name") or "") == "Task")
    field_names = {
        str(field.get("name") or "")
        for field in (task.get("fields") if isinstance(task.get("fields"), list) else [])
        if isinstance(field, dict)
    }
    assert "description" in field_names


def test_starter_pack_board_kanban_routes_to_board_card_with_relation_defaults() -> None:
    out = suggest_project_spec("project kanban board app", {"domains": [], "frontend_needed": True})
    entities = [entity for entity in out["entities"] if isinstance(entity, dict)]
    names = [str(entity.get("name") or "") for entity in entities]
    assert "Board" in names
    assert "Card" in names
    card = next(entity for entity in entities if str(entity.get("name") or "") == "Card")
    card_fields = card.get("fields") if isinstance(card.get("fields"), list) else []
    card_field_names = {str(field.get("name") or "") for field in card_fields if isinstance(field, dict)}
    assert "board_id" in card_field_names
    assert "status" in card_field_names
    assert "GET /boards" in out["api_endpoints"]
    assert "GET /cards" in out["api_endpoints"]
    assert "GET /boards/{id}" in out["api_endpoints"]
    assert "GET /cards/{id}" in out["api_endpoints"]
    assert "PATCH /boards/{id}" in out["api_endpoints"]
    assert "PATCH /cards/{id}" in out["api_endpoints"]
    assert "DELETE /boards/{id}" in out["api_endpoints"]
    assert "DELETE /cards/{id}" in out["api_endpoints"]
    assert "GET /boards/{id}/cards" in out["api_endpoints"]
    assert "boards/list" in out["frontend_pages"]
    assert "boards/new" in out["frontend_pages"]
    assert "boards/detail" in out["frontend_pages"]
    assert "cards/list" in out["frontend_pages"]
    assert "cards/new" in out["frontend_pages"]
    assert "cards/detail" in out["frontend_pages"]
    assert "cards/by_board" in out["frontend_pages"]


def test_starter_pack_unrelated_idea_is_not_misclassified() -> None:
    out = suggest_project_spec("expense dashboard app", {"domains": ["expenses"], "frontend_needed": True})
    names = [str(entity.get("name") or "") for entity in out["entities"] if isinstance(entity, dict)]
    assert "Expense" in names
    assert "Task" not in names
    assert "Note" not in names
    assert "Board" not in names


def test_starter_pack_journal_routes_to_diary_v2_defaults() -> None:
    out = suggest_project_spec("personal journal app", {"domains": [], "frontend_needed": True})
    entities = [entity for entity in out["entities"] if isinstance(entity, dict)]
    names = [str(entity.get("name") or "") for entity in entities]
    assert "Entry" in names
    entry = next(entity for entity in entities if str(entity.get("name") or "") == "Entry")
    field_names = {
        str(field.get("name") or "")
        for field in (entry.get("fields") if isinstance(entry.get("fields"), list) else [])
        if isinstance(field, dict)
    }
    assert {"title", "content", "created_at"}.issubset(field_names)
    assert "GET /entries" in out["api_endpoints"]
    assert "PATCH /entries/{id}" in out["api_endpoints"]
    assert "DELETE /entries/{id}" in out["api_endpoints"]
    assert "entries/list" in out["frontend_pages"]
    assert "entries/new" in out["frontend_pages"]
    assert "entries/detail" in out["frontend_pages"]


def test_notes_only_does_not_accidentally_route_to_diary() -> None:
    out = suggest_project_spec("simple notes app", {"domains": [], "frontend_needed": True})
    names = [str(entity.get("name") or "") for entity in out["entities"] if isinstance(entity, dict)]
    assert "Note" in names
    assert "Entry" not in names


def test_diary_with_categories_routes_tagging_module_path() -> None:
    out = suggest_project_spec("diary app with categories", {"domains": [], "frontend_needed": True})
    entities = [entity for entity in out["entities"] if isinstance(entity, dict)]
    names = [str(entity.get("name") or "") for entity in entities]
    assert "Entry" in names
    assert "Tag" in names
    tag = next(entity for entity in entities if str(entity.get("name") or "") == "Tag")
    field_names = {
        str(field.get("name") or "")
        for field in (tag.get("fields") if isinstance(tag.get("fields"), list) else [])
        if isinstance(field, dict)
    }
    assert {"name", "entry_id"}.issubset(field_names)
    modules = [str(x).strip().lower() for x in (out.get("modules") or []) if str(x).strip()]
    assert "tagging" in modules
    assert "GET /entries/{id}/tags" in out["api_endpoints"]


def test_diary_with_search_routes_search_module_path() -> None:
    out = suggest_project_spec("personal diary app with search", {"domains": [], "frontend_needed": True})
    names = [str(entity.get("name") or "") for entity in out["entities"] if isinstance(entity, dict)]
    assert "Entry" in names
    modules = [str(x).strip().lower() for x in (out.get("modules") or []) if str(x).strip()]
    assert "search" in modules
    expectations = [str(x).strip().lower() for x in (out.get("frontend_expectations") or []) if str(x).strip()]
    assert "list_search_input" in expectations
    assert "entries/list" in out["frontend_pages"]


def test_diary_with_tags_and_search_applies_both_modules_without_duplication() -> None:
    out = suggest_project_spec("journal app with tags and search", {"domains": [], "frontend_needed": True})
    names = [str(entity.get("name") or "") for entity in out["entities"] if isinstance(entity, dict)]
    assert names.count("Tag") == 1
    modules = [str(x).strip().lower() for x in (out.get("modules") or []) if str(x).strip()]
    assert "tagging" in modules
    assert "search" in modules
    expectations = [str(x).strip().lower() for x in (out.get("frontend_expectations") or []) if str(x).strip()]
    assert "list_search_input" in expectations


def test_notes_with_search_applies_search_module_without_overwriting_basics() -> None:
    out = suggest_project_spec("simple notes app with keyword search", {"domains": [], "frontend_needed": True})
    names = [str(entity.get("name") or "") for entity in out["entities"] if isinstance(entity, dict)]
    assert "Note" in names
    modules = [str(x).strip().lower() for x in (out.get("modules") or []) if str(x).strip()]
    assert "search" in modules
    expectations = [str(x).strip().lower() for x in (out.get("frontend_expectations") or []) if str(x).strip()]
    assert "list_search_input" in expectations


def test_unrelated_app_does_not_overtrigger_modules() -> None:
    out = suggest_project_spec("internal analytics dashboard", {"domains": ["expenses"], "frontend_needed": True})
    modules = [str(x).strip().lower() for x in (out.get("modules") or []) if str(x).strip()]
    assert "tagging" not in modules
    assert "search" not in modules


def test_starter_pack_kanban_due_signal_includes_card_due_date() -> None:
    out = suggest_project_spec("kanban board app with card due dates", {"domains": [], "frontend_needed": True})
    entities = [entity for entity in out["entities"] if isinstance(entity, dict)]
    card = next(entity for entity in entities if str(entity.get("name") or "") == "Card")
    field_names = {
        str(field.get("name") or "")
        for field in (card.get("fields") if isinstance(card.get("fields"), list) else [])
        if isinstance(field, dict)
    }
    assert "due_date" in field_names


def test_starter_pack_kanban_assignee_signal_includes_card_assignee() -> None:
    out = suggest_project_spec("project board with assignee", {"domains": [], "frontend_needed": True})
    entities = [entity for entity in out["entities"] if isinstance(entity, dict)]
    card = next(entity for entity in entities if str(entity.get("name") or "") == "Card")
    field_names = {
        str(field.get("name") or "")
        for field in (card.get("fields") if isinstance(card.get("fields"), list) else [])
        if isinstance(field, dict)
    }
    assert "assignee" in field_names


def test_dashboard_only_does_not_accidentally_route_to_board_card() -> None:
    out = suggest_project_spec("analytics dashboard app", {"domains": ["expenses"], "frontend_needed": True})
    names = [str(entity.get("name") or "") for entity in out["entities"] if isinstance(entity, dict)]
    assert "Board" not in names
    assert "Card" not in names
