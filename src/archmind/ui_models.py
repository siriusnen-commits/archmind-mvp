from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field

ProviderMode = Literal["local", "cloud", "auto"]


class ProviderUpdateRequest(BaseModel):
    mode: ProviderMode


class RuntimeSummary(BaseModel):
    backend_status: str = "STOPPED"
    frontend_status: str = "STOPPED"
    backend_url: str = ""
    frontend_url: str = ""
    backend_urls: list[str] = Field(default_factory=list)
    frontend_urls: list[str] = Field(default_factory=list)


class SpecSummary(BaseModel):
    stage: str = "Stage 0"
    entities: int = 0
    apis: int = 0
    pages: int = 0
    history_count: int = 0


class RepositorySummary(BaseModel):
    status: str = "SKIPPED"
    url: str = ""


class ProjectListItem(BaseModel):
    name: str
    display_name: str = ""
    path: str
    status: str
    runtime: str
    type: str = "unknown"
    template: str = "unknown"
    backend_url: str = ""
    frontend_url: str = ""
    repository: RepositorySummary = Field(default_factory=RepositorySummary)
    is_current: bool = False
    warning: str = ""


class ProjectListResponse(BaseModel):
    projects: list[ProjectListItem] = Field(default_factory=list)


class ProjectDetailResponse(BaseModel):
    name: str
    display_name: str = ""
    is_current: bool = False
    shape: str = "unknown"
    template: str = "unknown"
    provider_mode: ProviderMode = "local"
    spec_summary: SpecSummary
    entities: list[str] = Field(default_factory=list)
    runtime: RuntimeSummary
    recent_evolution: list[str] = Field(default_factory=list)
    repository: RepositorySummary = Field(default_factory=RepositorySummary)
    analysis: dict[str, Any] = Field(default_factory=dict)
    warning: str = ""
    safe: bool = True


class ProviderModeResponse(BaseModel):
    mode: ProviderMode


class CurrentProjectResponse(BaseModel):
    ok: bool = False
    project_name: str = ""
    is_current: bool = False
    detail: str = ""
    error: str = ""


class AddEntityRequest(BaseModel):
    entity_name: str = ""


class AddEntityResponse(BaseModel):
    ok: bool = False
    project_name: str = ""
    entity_name: str = ""
    detail: str = ""
    error: str = ""
    spec_summary: SpecSummary = Field(default_factory=SpecSummary)
    recent_evolution: list[str] = Field(default_factory=list)


class AddFieldRequest(BaseModel):
    entity_name: str = ""
    field_name: str = ""
    field_type: str = ""


class AddFieldResponse(BaseModel):
    ok: bool = False
    project_name: str = ""
    entity_name: str = ""
    field_name: str = ""
    field_type: str = ""
    detail: str = ""
    error: str = ""
    spec_summary: SpecSummary = Field(default_factory=SpecSummary)
    recent_evolution: list[str] = Field(default_factory=list)


class AddApiRequest(BaseModel):
    method: str = ""
    path: str = ""


class AddApiResponse(BaseModel):
    ok: bool = False
    project_name: str = ""
    method: str = ""
    path: str = ""
    detail: str = ""
    error: str = ""
    spec_summary: SpecSummary = Field(default_factory=SpecSummary)
    recent_evolution: list[str] = Field(default_factory=list)


class AddPageRequest(BaseModel):
    page_path: str = ""


class AddPageResponse(BaseModel):
    ok: bool = False
    project_name: str = ""
    page_path: str = ""
    detail: str = ""
    error: str = ""
    spec_summary: SpecSummary = Field(default_factory=SpecSummary)
    recent_evolution: list[str] = Field(default_factory=list)


class ImplementPageRequest(BaseModel):
    page_path: str = ""


class ImplementPageResponse(BaseModel):
    ok: bool = False
    project_name: str = ""
    page_path: str = ""
    detail: str = ""
    error: str = ""
    spec_summary: SpecSummary = Field(default_factory=SpecSummary)
    recent_evolution: list[str] = Field(default_factory=list)


class RuntimeActionResponse(BaseModel):
    ok: bool = False
    action: str = ""
    status: str = "UNKNOWN"
    detail: str = ""
    error: str = ""
    backend_status: str = "STOPPED"
    frontend_status: str = "STOPPED"
    backend_url: str = ""
    frontend_url: str = ""


class DeleteActionResponse(BaseModel):
    ok: bool = False
    action: str = ""
    project_name: str = ""
    local_deleted: bool = False
    github_deleted: bool = False
    runtime_stopped: bool = False
    detail: str = ""
    error: str = ""


class ProjectAnalysisResponse(BaseModel):
    project_name: str = ""
    entities: list[str] = Field(default_factory=list)
    fields_by_entity: dict[str, list[dict[str, str]]] = Field(default_factory=dict)
    apis: list[dict[str, str]] = Field(default_factory=list)
    pages: list[str] = Field(default_factory=list)
    entity_crud_status: dict[str, dict[str, Any]] = Field(default_factory=dict)
    placeholder_pages: list[str] = Field(default_factory=list)
    nav_visible_pages: list[str] = Field(default_factory=list)
    runtime_status: dict[str, Any] = Field(default_factory=dict)
    suggestions: list[dict[str, str]] = Field(default_factory=list)
    next_action: dict[str, str] = Field(default_factory=dict)
