from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field

ProviderMode = Literal["local", "cloud", "auto"]


class ProviderUpdateRequest(BaseModel):
    mode: ProviderMode


class RuntimeSummary(BaseModel):
    overall_status: str = "NOT_RUNNING"
    backend_status: str = "STOPPED"
    frontend_status: str = "STOPPED"
    backend_url: str = ""
    frontend_url: str = ""
    backend_reason: str = ""
    frontend_reason: str = ""
    backend_reason_detail: str = ""
    frontend_reason_detail: str = ""
    backend_last_known_url: str = ""
    frontend_last_known_url: str = ""
    backend_urls: list[str] = Field(default_factory=list)
    frontend_urls: list[str] = Field(default_factory=list)
    backend_reachability_status: str = "UNREACHABLE"
    frontend_reachability_status: str = "UNREACHABLE"
    backend_local_reachable: bool = False
    frontend_local_reachable: bool = False
    backend_lan_reachable: bool = False
    frontend_lan_reachable: bool = False
    backend_external_reachable: bool = False
    frontend_external_reachable: bool = False


class SpecSummary(BaseModel):
    stage: str = "Stage 0"
    entities: int = 0
    apis: int = 0
    pages: int = 0
    history_count: int = 0


class RepositorySummary(BaseModel):
    status: str = "NONE"
    url: str = ""
    repo_status: str = "NONE"
    repo_url: str = ""
    sync_status: str = "NOT_ATTEMPTED"
    sync_reason: str = ""
    sync_hint: str = ""
    sync_dirty_detail: str = ""
    sync_remote_url: str = ""
    sync_remote_type: str = ""
    last_commit_hash: str = ""
    working_tree_state: str = ""


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
    backend_urls: list[str] = Field(default_factory=list)
    frontend_urls: list[str] = Field(default_factory=list)
    runtime_state: str = "NOT_RUNNING"
    repository: RepositorySummary = Field(default_factory=RepositorySummary)
    project_health_status: str = "IDLE"
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
    recent_runs: list[dict[str, Any]] = Field(default_factory=list)
    evolution_history: list[dict[str, Any]] = Field(default_factory=list)
    architecture: dict[str, Any] = Field(default_factory=dict)
    logs: dict[str, Any] = Field(default_factory=dict)
    auto_summary: dict[str, Any] = Field(default_factory=dict)
    verification: dict[str, Any] = Field(default_factory=dict)
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
    entity_graph: dict[str, Any] = Field(default_factory=dict)
    api_map: dict[str, Any] = Field(default_factory=dict)
    page_map: dict[str, Any] = Field(default_factory=dict)
    visualization_gaps: list[dict[str, Any]] = Field(default_factory=list)
    entity_crud_status: dict[str, dict[str, Any]] = Field(default_factory=dict)
    placeholder_pages: list[str] = Field(default_factory=list)
    nav_visible_pages: list[str] = Field(default_factory=list)
    runtime_status: dict[str, Any] = Field(default_factory=dict)
    suggestions: list[dict[str, str]] = Field(default_factory=list)
    next_candidates: list[dict[str, Any]] = Field(default_factory=list)
    next_action: dict[str, str] = Field(default_factory=dict)
    next_action_explanation: dict[str, str] = Field(default_factory=dict)


class RunCommandRequest(BaseModel):
    command: str = ""
    strategy: str = ""


class RunCommandResponse(BaseModel):
    ok: bool = False
    project_name: str = ""
    command: str = ""
    detail: str = ""
    error: str = ""
    auto_result: dict[str, Any] = Field(default_factory=dict)
    spec_summary: SpecSummary = Field(default_factory=SpecSummary)
    recent_evolution: list[str] = Field(default_factory=list)


class NewProjectWizardRequest(BaseModel):
    idea: str = ""
    template: str = "auto"
    mode: str = "balanced"
    language: str = "english"
    llm_mode: str = "local"


class NewProjectWizardResponse(BaseModel):
    ok: bool = False
    project_name: str = ""
    detail: str = ""
    error: str = ""
    status: str = "UNKNOWN"
    request: dict[str, str] = Field(default_factory=dict)


class ProjectLogsResponse(BaseModel):
    project_name: str = ""
    default_source: str = "latest"
    max_lines: int = 200
    sources: list[dict[str, Any]] = Field(default_factory=list)
