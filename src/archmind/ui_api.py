from __future__ import annotations

from typing import Any

from fastapi import APIRouter, FastAPI, HTTPException

from archmind.project_query import (
    build_project_detail,
    build_project_list_item,
    find_project_by_name,
    list_project_dirs,
    restart_project_runtime,
    run_project_all,
    run_project_backend,
    stop_project_runtime,
    update_project_provider_mode,
)
from archmind.deploy import get_local_runtime_status
from archmind.ui_models import (
    ProjectDetailResponse,
    ProjectListResponse,
    ProviderModeResponse,
    ProviderUpdateRequest,
    RuntimeActionResponse,
)

router = APIRouter(prefix="/ui", tags=["ui"])


@router.get("/projects", response_model=ProjectListResponse)
def get_ui_projects() -> ProjectListResponse:
    items = [build_project_list_item(project_dir) for project_dir in list_project_dirs()]
    return ProjectListResponse(projects=items)


@router.get("/projects/{project_name}", response_model=ProjectDetailResponse)
def get_ui_project_detail(project_name: str) -> ProjectDetailResponse:
    project_dir = find_project_by_name(project_name)
    if project_dir is None:
        raise HTTPException(status_code=404, detail="Project not found")
    return build_project_detail(project_dir)


@router.get("/projects/{project_name}/provider", response_model=ProviderModeResponse)
def get_ui_project_provider(project_name: str) -> ProviderModeResponse:
    project_dir = find_project_by_name(project_name)
    if project_dir is None:
        raise HTTPException(status_code=404, detail="Project not found")
    detail = build_project_detail(project_dir)
    return ProviderModeResponse(mode=detail.provider_mode)


@router.post("/projects/{project_name}/provider", response_model=ProviderModeResponse)
def set_ui_project_provider(project_name: str, body: ProviderUpdateRequest) -> ProviderModeResponse:
    project_dir = find_project_by_name(project_name)
    if project_dir is None:
        raise HTTPException(status_code=404, detail="Project not found")
    mode = update_project_provider_mode(project_dir, body.mode)
    return ProviderModeResponse(mode=mode)  # type: ignore[arg-type]


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


@router.post("/projects/{project_name}/run-backend", response_model=RuntimeActionResponse)
def post_ui_project_run_backend(project_name: str) -> RuntimeActionResponse:
    project_dir = find_project_by_name(project_name)
    if project_dir is None:
        raise HTTPException(status_code=404, detail="Project not found")
    result = run_project_backend(project_dir)
    return _runtime_action_response(project_dir, "run-backend", result)


@router.post("/projects/{project_name}/run-all", response_model=RuntimeActionResponse)
def post_ui_project_run_all(project_name: str) -> RuntimeActionResponse:
    project_dir = find_project_by_name(project_name)
    if project_dir is None:
        raise HTTPException(status_code=404, detail="Project not found")
    result = run_project_all(project_dir)
    return _runtime_action_response(project_dir, "run-all", result)


@router.post("/projects/{project_name}/restart", response_model=RuntimeActionResponse)
def post_ui_project_restart(project_name: str) -> RuntimeActionResponse:
    project_dir = find_project_by_name(project_name)
    if project_dir is None:
        raise HTTPException(status_code=404, detail="Project not found")
    result = restart_project_runtime(project_dir)
    return _runtime_action_response(project_dir, "restart", result)


@router.post("/projects/{project_name}/stop", response_model=RuntimeActionResponse)
def post_ui_project_stop(project_name: str) -> RuntimeActionResponse:
    project_dir = find_project_by_name(project_name)
    if project_dir is None:
        raise HTTPException(status_code=404, detail="Project not found")
    result = stop_project_runtime(project_dir)
    return _runtime_action_response(project_dir, "stop", result)


def create_ui_app() -> FastAPI:
    app = FastAPI(title="ArchMind UI API")
    app.include_router(router)
    return app
