from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, FastAPI, HTTPException
from fastapi.responses import JSONResponse

from archmind.project_query import (
    add_project_entity,
    build_project_detail,
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
from archmind.ui_models import (
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
    RuntimeActionResponse,
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


def _runtime_action_response(project_dir, action: str, result: dict) -> RuntimeActionResponse:
    runtime = get_local_runtime_status(project_dir)
    backend = runtime.get("backend") if isinstance(runtime.get("backend"), dict) else {}
    frontend = runtime.get("frontend") if isinstance(runtime.get("frontend"), dict) else {}
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
        backend_status=str(backend.get("status") or "STOPPED").strip().upper() or "STOPPED",
        frontend_status=str(frontend.get("status") or "STOPPED").strip().upper() or "STOPPED",
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
