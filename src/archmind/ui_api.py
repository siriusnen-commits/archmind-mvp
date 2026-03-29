from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, FastAPI, HTTPException
from fastapi.responses import JSONResponse

from archmind.command_executor import execute_command
from archmind.project_query import (
    add_project_entity,
    build_project_analysis,
    build_project_detail,
    build_project_logs,
    build_project_list_item,
    delete_project_all,
    delete_project_local,
    delete_project_repo,
    find_project_by_name,
    list_project_dirs,
    restart_project_runtime,
    run_project_all,
    run_project_backend,
    select_current_project,
    stop_project_runtime,
    update_project_provider_mode,
)
from archmind.deploy import get_local_runtime_status
from archmind.runtime_status import build_runtime_snapshot
from archmind.ui_models import (
    AddApiRequest,
    AddApiResponse,
    AddPageRequest,
    AddPageResponse,
    ImplementPageRequest,
    ImplementPageResponse,
    AddFieldRequest,
    AddFieldResponse,
    AddEntityRequest,
    AddEntityResponse,
    CurrentProjectResponse,
    DeleteActionResponse,
    ProjectListItem,
    ProjectDetailResponse,
    ProjectListResponse,
    ProviderModeResponse,
    RepositorySummary,
    ProviderUpdateRequest,
    ProjectAnalysisResponse,
    ProjectLogsResponse,
    RuntimeActionResponse,
    RunCommandRequest,
    RunCommandResponse,
)

router = APIRouter(prefix="/ui", tags=["ui"])
logger = logging.getLogger(__name__)


@router.get("/projects", response_model=ProjectListResponse)
def get_ui_projects() -> ProjectListResponse:
    try:
        items = []
        for project_dir in list_project_dirs():
            try:
                items.append(build_project_list_item(project_dir))
            except Exception as exc:
                logger.exception("Failed to build project list item for %s", project_dir)
                items.append(
                    ProjectListItem(
                        name=project_dir.name,
                        display_name=project_dir.name,
                        path=str(project_dir),
                        status="STOPPED",
                        runtime="STOPPED",
                        type="unknown",
                        template="unknown",
                        backend_url="",
                        frontend_url="",
                        repository=RepositorySummary(),
                        is_current=False,
                        warning=f"Failed to inspect project metadata: {exc}",
                    )
                )
        return ProjectListResponse(projects=items)
    except Exception as exc:
        logger.exception("Failed to load UI projects list")
        return JSONResponse(
            status_code=500,
            content={
                "detail": "Failed to load projects",
                "error": str(exc),
                "safe": True,
            },
        )


@router.get("/projects/{project_name}", response_model=ProjectDetailResponse)
def get_ui_project_detail(project_name: str) -> ProjectDetailResponse:
    try:
        project_dir = find_project_by_name(project_name)
        if project_dir is None:
            raise HTTPException(status_code=404, detail="Project not found")
        return build_project_detail(project_dir)
    except HTTPException:
        raise
    except Exception as exc:
        logger.exception("Failed to load UI project detail: %s", project_name)
        return JSONResponse(
            status_code=500,
            content={
                "detail": "Failed to load project detail",
                "error": str(exc),
                "project_name": project_name,
                "safe": True,
            },
        )


@router.get("/projects/{project_name}/analysis", response_model=ProjectAnalysisResponse)
def get_ui_project_analysis(project_name: str) -> ProjectAnalysisResponse:
    try:
        project_dir = find_project_by_name(project_name)
        if project_dir is None:
            raise HTTPException(status_code=404, detail="Project not found")
        payload = build_project_analysis(project_dir)
        raw_next_candidates = payload.get("next_candidates") if isinstance(payload.get("next_candidates"), list) else []
        next_candidates = []
        for row in raw_next_candidates:
            if not isinstance(row, dict):
                continue
            command = str(row.get("command") or "").strip()
            if not command:
                continue
            next_candidates.append(
                {
                    "command": command,
                    "gap_type": str(row.get("gap_type") or "").strip(),
                    "priority": str(row.get("priority") or "").strip().lower(),
                    "reason": str(row.get("reason") or row.get("reason_summary") or "").strip(),
                    "reason_summary": str(row.get("reason_summary") or row.get("reason") or "").strip(),
                    "expected_effect": str(row.get("expected_effect") or "").strip(),
                }
            )
        return ProjectAnalysisResponse(
            project_name=str(payload.get("project_name") or project_name),
            entities=[str(x) for x in (payload.get("entities") or []) if str(x).strip()],
            fields_by_entity=payload.get("fields_by_entity") if isinstance(payload.get("fields_by_entity"), dict) else {},
            apis=[x for x in (payload.get("apis") or []) if isinstance(x, dict)],
            pages=[str(x) for x in (payload.get("pages") or []) if str(x).strip()],
            entity_graph=payload.get("entity_graph") if isinstance(payload.get("entity_graph"), dict) else {},
            api_map=payload.get("api_map") if isinstance(payload.get("api_map"), dict) else {},
            page_map=payload.get("page_map") if isinstance(payload.get("page_map"), dict) else {},
            visualization_gaps=[x for x in (payload.get("visualization_gaps") or []) if isinstance(x, dict)],
            entity_crud_status=payload.get("entity_crud_status")
            if isinstance(payload.get("entity_crud_status"), dict)
            else {},
            placeholder_pages=[str(x) for x in (payload.get("placeholder_pages") or []) if str(x).strip()],
            nav_visible_pages=[str(x) for x in (payload.get("nav_visible_pages") or []) if str(x).strip()],
            runtime_status=payload.get("runtime_status") if isinstance(payload.get("runtime_status"), dict) else {},
            suggestions=[x for x in (payload.get("suggestions") or []) if isinstance(x, dict)][:3],
            next_candidates=next_candidates[:3],
            next_action=payload.get("next_action") if isinstance(payload.get("next_action"), dict) else {},
            next_action_explanation=payload.get("next_action_explanation")
            if isinstance(payload.get("next_action_explanation"), dict)
            else {},
        )
    except HTTPException:
        raise
    except Exception as exc:
        logger.exception("Failed to load project analysis: %s", project_name)
        return JSONResponse(
            status_code=500,
            content={
                "detail": "Failed to load project analysis",
                "error": str(exc),
                "project_name": project_name,
                "safe": True,
            },
        )


@router.get("/projects/{project_name}/logs", response_model=ProjectLogsResponse)
def get_ui_project_logs(project_name: str) -> ProjectLogsResponse:
    try:
        project_dir = find_project_by_name(project_name)
        if project_dir is None:
            raise HTTPException(status_code=404, detail="Project not found")
        payload = build_project_logs(project_dir)
        return ProjectLogsResponse(
            project_name=project_name,
            default_source=str(payload.get("default_source") or "latest").strip() or "latest",
            max_lines=int(payload.get("max_lines") or 200),
            sources=[row for row in (payload.get("sources") or []) if isinstance(row, dict)],
        )
    except HTTPException:
        raise
    except Exception as exc:
        logger.exception("Failed to load project logs: %s", project_name)
        return JSONResponse(
            status_code=500,
            content={
                "detail": "Failed to load logs",
                "error": str(exc),
                "project_name": project_name,
                "safe": True,
            },
        )


@router.get("/projects/{project_name}/provider", response_model=ProviderModeResponse)
def get_ui_project_provider(project_name: str) -> ProviderModeResponse:
    try:
        project_dir = find_project_by_name(project_name)
        if project_dir is None:
            raise HTTPException(status_code=404, detail="Project not found")
        detail = build_project_detail(project_dir)
        return ProviderModeResponse(mode=detail.provider_mode)
    except HTTPException:
        raise
    except Exception as exc:
        logger.exception("Failed to load provider mode: %s", project_name)
        return JSONResponse(
            status_code=500,
            content={
                "detail": "Failed to load provider data",
                "error": str(exc),
                "project_name": project_name,
                "safe": True,
            },
        )


@router.post("/projects/{project_name}/provider", response_model=ProviderModeResponse)
def set_ui_project_provider(project_name: str, body: ProviderUpdateRequest) -> ProviderModeResponse:
    try:
        project_dir = find_project_by_name(project_name)
        if project_dir is None:
            raise HTTPException(status_code=404, detail="Project not found")
        mode = update_project_provider_mode(project_dir, body.mode)
        return ProviderModeResponse(mode=mode)  # type: ignore[arg-type]
    except HTTPException:
        raise
    except Exception as exc:
        logger.exception("Failed to set provider mode: %s", project_name)
        return JSONResponse(
            status_code=500,
            content={
                "detail": "Failed to update provider",
                "error": str(exc),
                "project_name": project_name,
                "safe": True,
            },
        )


@router.post("/projects/{project_name}/select", response_model=CurrentProjectResponse)
def post_ui_project_select(project_name: str) -> CurrentProjectResponse:
    try:
        project_dir = find_project_by_name(project_name)
        if project_dir is None:
            return CurrentProjectResponse(
                ok=False,
                project_name=project_name,
                is_current=False,
                detail="Project not found",
                error="Project not found",
            )
        result = select_current_project(project_dir)
        return CurrentProjectResponse(
            ok=bool(result.get("ok")),
            project_name=str(result.get("project_name") or project_name),
            is_current=bool(result.get("is_current")),
            detail=str(result.get("detail") or ""),
            error=str(result.get("error") or ""),
        )
    except Exception as exc:
        logger.exception("Failed to select current project: %s", project_name)
        return CurrentProjectResponse(
            ok=False,
            project_name=project_name,
            is_current=False,
            detail="Failed to set current project",
            error=str(exc),
        )


@router.post("/projects/{project_name}/entities", response_model=AddEntityResponse)
def post_ui_project_add_entity(project_name: str, body: AddEntityRequest) -> AddEntityResponse:
    try:
        project_dir = find_project_by_name(project_name)
        if project_dir is None:
            return AddEntityResponse(
                ok=False,
                project_name=project_name,
                entity_name=str(body.entity_name or ""),
                detail="Project not found",
                error="Project not found",
            )
        result = add_project_entity(project_dir, str(body.entity_name or ""))
        return AddEntityResponse(
            ok=bool(result.get("ok")),
            project_name=str(result.get("project_name") or project_name),
            entity_name=str(result.get("entity_name") or ""),
            detail=str(result.get("detail") or ""),
            error=str(result.get("error") or ""),
            spec_summary=result.get("spec_summary") if isinstance(result.get("spec_summary"), dict) else {},
            recent_evolution=[str(x) for x in (result.get("recent_evolution") or []) if str(x).strip()],
        )
    except Exception as exc:
        logger.exception("Failed to add entity: %s", project_name)
        return AddEntityResponse(
            ok=False,
            project_name=project_name,
            entity_name=str(body.entity_name or ""),
            detail="Failed to add entity",
            error=str(exc),
        )


@router.post("/projects/{project_name}/fields", response_model=AddFieldResponse)
def post_ui_project_add_field(project_name: str, body: AddFieldRequest) -> AddFieldResponse:
    try:
        entity_name = str(body.entity_name or "").strip()
        field_name = str(body.field_name or "").strip()
        field_type = str(body.field_type or "").strip()
        if not entity_name or not field_name or not field_type:
            return AddFieldResponse(
                ok=False,
                project_name=project_name,
                entity_name=entity_name,
                field_name=field_name,
                field_type=field_type,
                detail="Invalid field input: entity_name, field_name, and field_type are required",
                error="invalid field input",
            )
        command = f"/add_field {entity_name} {field_name}:{field_type}"
        result = execute_command(command, project_name, source="ui-next-run")
        detail = str(result.get("detail") or result.get("message") or result.get("error") or "")
        return AddFieldResponse(
            ok=bool(result.get("ok")),
            project_name=str(result.get("project_name") or project_name),
            entity_name=str(result.get("entity_name") or entity_name),
            field_name=str(result.get("field_name") or field_name),
            field_type=str(result.get("field_type") or field_type),
            detail=detail,
            error=str(result.get("error") or ""),
            spec_summary=result.get("spec_summary") if isinstance(result.get("spec_summary"), dict) else {},
            recent_evolution=[str(x) for x in (result.get("recent_evolution") or []) if str(x).strip()],
        )
    except Exception as exc:
        logger.exception("Failed to add field: %s", project_name)
        return AddFieldResponse(
            ok=False,
            project_name=project_name,
            entity_name=str(body.entity_name or ""),
            field_name=str(body.field_name or ""),
            field_type=str(body.field_type or ""),
            detail="Failed to add field",
            error=str(exc),
        )


@router.post("/projects/{project_name}/apis", response_model=AddApiResponse)
def post_ui_project_add_api(project_name: str, body: AddApiRequest) -> AddApiResponse:
    try:
        method = str(body.method or "").strip().upper()
        path = str(body.path or "").strip()
        if not method or not path:
            return AddApiResponse(
                ok=False,
                project_name=project_name,
                method=method,
                path=path,
                detail="Invalid API input: method and path are required",
                error="invalid api input",
            )
        command = f"/add_api {method} {path}"
        result = execute_command(command, project_name, source="ui-next-run")
        detail = str(result.get("detail") or result.get("message") or result.get("error") or "")
        return AddApiResponse(
            ok=bool(result.get("ok")),
            project_name=str(result.get("project_name") or project_name),
            method=str(result.get("method") or method),
            path=str(result.get("path") or path),
            detail=detail,
            error=str(result.get("error") or ""),
            spec_summary=result.get("spec_summary") if isinstance(result.get("spec_summary"), dict) else {},
            recent_evolution=[str(x) for x in (result.get("recent_evolution") or []) if str(x).strip()],
        )
    except Exception as exc:
        logger.exception("Failed to add API: %s", project_name)
        return AddApiResponse(
            ok=False,
            project_name=project_name,
            method=str(body.method or ""),
            path=str(body.path or ""),
            detail="Failed to add API",
            error=str(exc),
        )


@router.post("/projects/{project_name}/pages", response_model=AddPageResponse)
def post_ui_project_add_page(project_name: str, body: AddPageRequest) -> AddPageResponse:
    try:
        page_path = str(body.page_path or "").strip()
        if not page_path:
            return AddPageResponse(
                ok=False,
                project_name=project_name,
                page_path=page_path,
                detail="Invalid page path",
                error="invalid page path",
            )
        command = f"/add_page {page_path}"
        result = execute_command(command, project_name, source="ui-next-run")
        detail = str(result.get("detail") or result.get("message") or result.get("error") or "")
        return AddPageResponse(
            ok=bool(result.get("ok")),
            project_name=str(result.get("project_name") or project_name),
            page_path=str(result.get("page_path") or page_path),
            detail=detail,
            error=str(result.get("error") or ""),
            spec_summary=result.get("spec_summary") if isinstance(result.get("spec_summary"), dict) else {},
            recent_evolution=[str(x) for x in (result.get("recent_evolution") or []) if str(x).strip()],
        )
    except Exception as exc:
        logger.exception("Failed to add page: %s", project_name)
        return AddPageResponse(
            ok=False,
            project_name=project_name,
            page_path=str(body.page_path or ""),
            detail="Failed to add page",
            error=str(exc),
        )


@router.post("/projects/{project_name}/implement-page", response_model=ImplementPageResponse)
def post_ui_project_implement_page(project_name: str, body: ImplementPageRequest) -> ImplementPageResponse:
    try:
        page_path = str(body.page_path or "").strip()
        if not page_path:
            return ImplementPageResponse(
                ok=False,
                project_name=project_name,
                page_path=page_path,
                detail="Invalid page path",
                error="invalid page path",
            )
        command = f"/implement_page {page_path}"
        result = execute_command(command, project_name, source="ui-next-run")
        detail = str(result.get("detail") or result.get("message") or result.get("error") or "")
        return ImplementPageResponse(
            ok=bool(result.get("ok")),
            project_name=str(result.get("project_name") or project_name),
            page_path=str(result.get("page_path") or page_path),
            detail=detail,
            error=str(result.get("error") or ""),
            spec_summary=result.get("spec_summary") if isinstance(result.get("spec_summary"), dict) else {},
            recent_evolution=[str(x) for x in (result.get("recent_evolution") or []) if str(x).strip()],
        )
    except Exception as exc:
        logger.exception("Failed to implement page: %s", project_name)
        return ImplementPageResponse(
            ok=False,
            project_name=project_name,
            page_path=str(body.page_path or ""),
            detail="Failed to implement page",
            error=str(exc),
        )


@router.post("/projects/{project_name}/commands", response_model=RunCommandResponse)
def post_ui_project_run_command(project_name: str, body: RunCommandRequest) -> RunCommandResponse:
    try:
        command = str(body.command or "").strip()
        strategy = str(body.strategy or "").strip().lower()
        result = execute_command(command, project_name, source="ui-next-run", auto_strategy=strategy)
        detail = str(result.get("detail") or result.get("message") or result.get("error") or "")
        return RunCommandResponse(
            ok=bool(result.get("ok")),
            project_name=str(result.get("project_name") or project_name),
            command=str(result.get("command") or command),
            detail=detail,
            error=str(result.get("error") or ""),
            auto_result=result.get("auto_result") if isinstance(result.get("auto_result"), dict) else {},
            spec_summary=result.get("spec_summary") if isinstance(result.get("spec_summary"), dict) else {},
            recent_evolution=[str(x) for x in (result.get("recent_evolution") or []) if str(x).strip()],
        )
    except Exception as exc:
        logger.exception("Failed to run command: %s", project_name)
        return RunCommandResponse(
            ok=False,
            project_name=project_name,
            command=str(body.command or ""),
            detail="Failed to run command",
            error=str(exc),
        )


def _runtime_action_response(project_dir, action: str, result: dict) -> RuntimeActionResponse:
    runtime = get_local_runtime_status(project_dir)
    snapshot = build_runtime_snapshot(runtime if isinstance(runtime, dict) else {}, {})
    backend = snapshot.get("backend") if isinstance(snapshot.get("backend"), dict) else {}
    frontend = snapshot.get("frontend") if isinstance(snapshot.get("frontend"), dict) else {}
    ok = bool(result.get("ok"))
    detail = str(result.get("detail") or "").strip()
    error = "" if ok else _extract_runtime_action_error(result)
    if not detail and not ok and error:
        detail = error
    return RuntimeActionResponse(
        ok=ok,
        action=action,
        status=str(result.get("status") or ("SUCCESS" if ok else "FAIL")),
        detail=detail,
        error=error,
        backend_status=str(backend.get("status") or "NOT RUNNING").strip().upper() or "NOT RUNNING",
        frontend_status=str(frontend.get("status") or "NOT RUNNING").strip().upper() or "NOT RUNNING",
        backend_url=str(backend.get("url") or ""),
        frontend_url=str(frontend.get("url") or ""),
    )


def _extract_runtime_action_error(result: dict[str, Any]) -> str:
    candidates: list[Any] = [
        result.get("error"),
        result.get("failure_class"),
        result.get("detail"),
    ]
    backend = result.get("backend")
    if isinstance(backend, dict):
        candidates.extend([backend.get("error"), backend.get("detail")])
    frontend = result.get("frontend")
    if isinstance(frontend, dict):
        candidates.extend([frontend.get("error"), frontend.get("detail")])
    services = result.get("services")
    if isinstance(services, dict):
        backend_service = services.get("backend")
        if isinstance(backend_service, dict):
            candidates.extend([backend_service.get("error"), backend_service.get("detail")])
        frontend_service = services.get("frontend")
        if isinstance(frontend_service, dict):
            candidates.extend([frontend_service.get("error"), frontend_service.get("detail")])
    for item in candidates:
        text = str(item or "").strip()
        if text:
            return text
    return ""


def _is_runtime_stopped(stop_payload: Any) -> bool:
    if not isinstance(stop_payload, dict):
        return False
    backend = stop_payload.get("backend") if isinstance(stop_payload.get("backend"), dict) else {}
    frontend = stop_payload.get("frontend") if isinstance(stop_payload.get("frontend"), dict) else {}
    backend_status = str(backend.get("status") or "").strip().upper()
    frontend_status = str(frontend.get("status") or "").strip().upper()
    stopped_states = {"STOPPED", "NOT RUNNING", "ABSENT"}
    return (not backend_status or backend_status in stopped_states) and (not frontend_status or frontend_status in stopped_states)


def _delete_action_response(project_name: str, action: str, result: dict[str, Any]) -> DeleteActionResponse:
    local_status = str(result.get("local_status") or "").strip().upper()
    repo_status = str(result.get("repo_status") or "").strip().upper()
    stop_payload = result.get("stop")
    local_deleted = local_status == "DELETED"
    github_deleted = repo_status in {"DELETED", "ALREADY_DELETED"}
    ok = bool(result.get("ok"))
    detail_candidates = [
        result.get("detail"),
        result.get("local_detail"),
        result.get("repo_detail"),
    ]
    detail = ""
    for item in detail_candidates:
        text = str(item or "").strip()
        if text:
            detail = text
            break
    if not detail:
        detail = "Delete action completed" if ok else "Delete action failed"

    error = ""
    if not ok:
        local_detail = str(result.get("local_detail") or "").strip()
        repo_detail = str(result.get("repo_detail") or "").strip()
        if local_detail and repo_detail and local_detail != repo_detail:
            error = f"{local_detail}; {repo_detail}"
        else:
            error = local_detail or repo_detail or str(result.get("error") or "").strip() or "delete failed"

    return DeleteActionResponse(
        ok=ok,
        action=action,
        project_name=project_name,
        local_deleted=local_deleted,
        github_deleted=github_deleted,
        runtime_stopped=_is_runtime_stopped(stop_payload),
        detail=detail,
        error=error,
    )


@router.post("/projects/{project_name}/run-backend", response_model=RuntimeActionResponse)
def post_ui_project_run_backend(project_name: str) -> RuntimeActionResponse:
    try:
        project_dir = find_project_by_name(project_name)
        if project_dir is None:
            raise HTTPException(status_code=404, detail="Project not found")
        result = run_project_backend(project_dir)
        return _runtime_action_response(project_dir, "run-backend", result)
    except HTTPException:
        raise
    except Exception as exc:
        logger.exception("Runtime action failed: run-backend (%s)", project_name)
        return RuntimeActionResponse(
            ok=False,
            action="run-backend",
            status="FAIL",
            detail="Failed to run action",
            error=str(exc),
            backend_status="STOPPED",
            frontend_status="STOPPED",
            backend_url="",
            frontend_url="",
        )


@router.post("/projects/{project_name}/run-all", response_model=RuntimeActionResponse)
def post_ui_project_run_all(project_name: str) -> RuntimeActionResponse:
    try:
        project_dir = find_project_by_name(project_name)
        if project_dir is None:
            raise HTTPException(status_code=404, detail="Project not found")
        result = run_project_all(project_dir)
        return _runtime_action_response(project_dir, "run-all", result)
    except HTTPException:
        raise
    except Exception as exc:
        logger.exception("Runtime action failed: run-all (%s)", project_name)
        return RuntimeActionResponse(
            ok=False,
            action="run-all",
            status="FAIL",
            detail="Failed to run action",
            error=str(exc),
            backend_status="STOPPED",
            frontend_status="STOPPED",
            backend_url="",
            frontend_url="",
        )


@router.post("/projects/{project_name}/restart", response_model=RuntimeActionResponse)
def post_ui_project_restart(project_name: str) -> RuntimeActionResponse:
    try:
        project_dir = find_project_by_name(project_name)
        if project_dir is None:
            raise HTTPException(status_code=404, detail="Project not found")
        result = restart_project_runtime(project_dir)
        return _runtime_action_response(project_dir, "restart", result)
    except HTTPException:
        raise
    except Exception as exc:
        logger.exception("Runtime action failed: restart (%s)", project_name)
        return RuntimeActionResponse(
            ok=False,
            action="restart",
            status="FAIL",
            detail="Failed to run action",
            error=str(exc),
            backend_status="STOPPED",
            frontend_status="STOPPED",
            backend_url="",
            frontend_url="",
        )


@router.post("/projects/{project_name}/stop", response_model=RuntimeActionResponse)
def post_ui_project_stop(project_name: str) -> RuntimeActionResponse:
    try:
        project_dir = find_project_by_name(project_name)
        if project_dir is None:
            raise HTTPException(status_code=404, detail="Project not found")
        result = stop_project_runtime(project_dir)
        return _runtime_action_response(project_dir, "stop", result)
    except HTTPException:
        raise
    except Exception as exc:
        logger.exception("Runtime action failed: stop (%s)", project_name)
        return RuntimeActionResponse(
            ok=False,
            action="stop",
            status="FAIL",
            detail="Failed to run action",
            error=str(exc),
            backend_status="STOPPED",
            frontend_status="STOPPED",
            backend_url="",
            frontend_url="",
        )


@router.post("/projects/{project_name}/delete-local", response_model=DeleteActionResponse)
def post_ui_project_delete_local(project_name: str) -> DeleteActionResponse:
    try:
        project_dir = find_project_by_name(project_name)
        if project_dir is None:
            raise HTTPException(status_code=404, detail="Project not found")
        result = delete_project_local(project_dir)
        return _delete_action_response(project_name, "delete-local", result)
    except HTTPException:
        raise
    except Exception as exc:
        logger.exception("Delete action failed: delete-local (%s)", project_name)
        return DeleteActionResponse(
            ok=False,
            action="delete-local",
            project_name=project_name,
            local_deleted=False,
            github_deleted=False,
            runtime_stopped=False,
            detail="Failed to delete local project",
            error=str(exc),
        )


@router.post("/projects/{project_name}/delete-repo", response_model=DeleteActionResponse)
def post_ui_project_delete_repo(project_name: str) -> DeleteActionResponse:
    try:
        project_dir = find_project_by_name(project_name)
        if project_dir is None:
            raise HTTPException(status_code=404, detail="Project not found")
        result = delete_project_repo(project_dir)
        return _delete_action_response(project_name, "delete-repo", result)
    except HTTPException:
        raise
    except Exception as exc:
        logger.exception("Delete action failed: delete-repo (%s)", project_name)
        return DeleteActionResponse(
            ok=False,
            action="delete-repo",
            project_name=project_name,
            local_deleted=False,
            github_deleted=False,
            runtime_stopped=False,
            detail="Failed to delete GitHub repo",
            error=str(exc),
        )


@router.post("/projects/{project_name}/delete-all", response_model=DeleteActionResponse)
def post_ui_project_delete_all(project_name: str) -> DeleteActionResponse:
    try:
        project_dir = find_project_by_name(project_name)
        if project_dir is None:
            raise HTTPException(status_code=404, detail="Project not found")
        result = delete_project_all(project_dir)
        return _delete_action_response(project_name, "delete-all", result)
    except HTTPException:
        raise
    except Exception as exc:
        logger.exception("Delete action failed: delete-all (%s)", project_name)
        return DeleteActionResponse(
            ok=False,
            action="delete-all",
            project_name=project_name,
            local_deleted=False,
            github_deleted=False,
            runtime_stopped=False,
            detail="Failed to delete project and GitHub repo",
            error=str(exc),
        )


def create_ui_app() -> FastAPI:
    app = FastAPI(title="ArchMind UI API")
    app.include_router(router)
    return app
