from __future__ import annotations

from fastapi import APIRouter, FastAPI, HTTPException

from archmind.project_query import (
    build_project_detail,
    build_project_list_item,
    find_project_by_name,
    list_project_dirs,
    update_project_provider_mode,
)
from archmind.ui_models import ProjectDetailResponse, ProjectListResponse, ProviderModeResponse, ProviderUpdateRequest

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


def create_ui_app() -> FastAPI:
    app = FastAPI(title="ArchMind UI API")
    app.include_router(router)
    return app
