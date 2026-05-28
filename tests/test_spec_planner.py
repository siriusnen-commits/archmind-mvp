from __future__ import annotations

from archmind.spec_planner import plan_project_spec_from_idea


def _entity_names(spec: dict) -> list[str]:
    return [str(entity.get("name") or "") for entity in spec.get("entities", []) if isinstance(entity, dict)]


def _relationships(spec: dict) -> list[tuple[str, str, str]]:
    return [
        (str(rel.get("from_entity") or ""), str(rel.get("field") or ""), str(rel.get("to_entity") or ""))
        for rel in spec.get("relationships", [])
        if isinstance(rel, dict)
    ]


def test_plan_project_spec_support_ticket_manager() -> None:
    spec = plan_project_spec_from_idea("support ticket manager")

    assert _entity_names(spec) == ["Ticket", "Customer", "Agent", "Comment"]
    assert ("Ticket", "customer_id", "Customer") in _relationships(spec)
    assert ("Ticket", "agent_id", "Agent") in _relationships(spec)
    assert ("Comment", "ticket_id", "Ticket") in _relationships(spec)
    assert "tickets" in spec["resources"]
    assert "GET /comments" in spec["api_endpoints"]
    assert "comments/list" in spec["frontend_pages"]
    assert any(row.get("type") == "workflow_status" for row in spec.get("patterns", []))
    assert any(row.get("type") == "workflow_tracking" for row in spec.get("composed_patterns", []))
    assert "show_status_filters" in spec.get("ui_hints", [])


def test_plan_project_spec_employee_onboarding_management_system_diagnostics() -> None:
    spec = plan_project_spec_from_idea("employee_onboarding_management_system")

    names = _entity_names(spec)
    assert len(names) >= 3
    assert {"Employee", "Training", "Department"}.issubset(set(names))
    assert names != ["Task"]
    assert ("Employee", "department_id", "Department") in _relationships(spec)
    assert ("Training", "employee_id", "Employee") in _relationships(spec)
    assert "GET /employees" in spec["api_endpoints"]
    assert "GET /trainings" in spec["api_endpoints"]
    assert "GET /departments" in spec["api_endpoints"]
    assert "employees/list" in spec["frontend_pages"]
    assert "trainings/list" in spec["frontend_pages"]
    assert "departments/list" in spec["frontend_pages"]

    diagnostics = [row for row in spec.get("planning_diagnostics", []) if isinstance(row, dict)]
    stages = {str(row.get("stage") or "") for row in diagnostics}
    assert {"planning_engine", "pattern_inference", "composition_engine"}.issubset(stages)
    for row in diagnostics:
        for key in ("entities", "patterns", "composed_patterns", "ui_hints", "generated_pages", "generated_apis"):
            assert isinstance(row.get(key), list)


def test_plan_project_spec_project_asset_crm_and_habit_domains() -> None:
    project = plan_project_spec_from_idea("project management tool")
    assert _entity_names(project) == ["Project", "Task", "Member"]
    assert ("Task", "project_id", "Project") in _relationships(project)

    asset = plan_project_spec_from_idea("asset tracker")
    assert _entity_names(asset) == ["Asset", "Category", "Location"]
    assert ("Asset", "category_id", "Category") in _relationships(asset)

    crm = plan_project_spec_from_idea("CRM app")
    assert _entity_names(crm) == ["Customer", "Deal", "Contact", "Activity"]
    assert ("Deal", "customer_id", "Customer") in _relationships(crm)

    habit = plan_project_spec_from_idea("habit tracker")
    assert _entity_names(habit) == ["Habit", "HabitLog", "Goal"]
    assert ("HabitLog", "habit_id", "Habit") in _relationships(habit)


def test_plan_project_spec_preserves_simple_ideas() -> None:
    base = {"entities": [{"name": "Entry", "fields": [{"name": "title", "type": "string"}]}]}

    spec = plan_project_spec_from_idea("simple diary app", base)

    assert spec == base
