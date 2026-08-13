"""HTTP contracts for the V0.9 isolated Coding Agent."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class CodingTaskCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    objective: str = Field(min_length=3, max_length=12_000)
    # The browser supplies its currently active conversation so a manually
    # created task can notify Iris's chat after it reaches review.
    session_id: str | None = Field(default=None, min_length=1, max_length=128)
    project_root: str | None = Field(default=None, max_length=4096)
    context_files: list[str] = Field(default_factory=list, max_length=40)


class CodingInstructionCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    text: str = Field(min_length=1, max_length=4_000)


class CodingTaskClearResponse(BaseModel):
    removed_tasks: int
    preserved_workspaces: bool = True


class CodingTaskResponse(BaseModel):
    model_config = ConfigDict(extra="allow")

    id: str
    objective: str
    model: str
    project_root: str
    workspace_name: str
    status: str
    cancellation_requested: bool = False
    created_at: str
    updated_at: str
    completed_at: str | None = None
    workspace_path: str | None = None
    context_files: list[str] = Field(default_factory=list)
    base_manifest: dict[str, Any] = Field(default_factory=dict)
    result: dict[str, Any] = Field(default_factory=dict)
    patch_text: str | None = None
    error_text: str | None = None
    events: list[dict[str, Any]] = Field(default_factory=list)
    instructions: list[dict[str, Any]] = Field(default_factory=list)


class CodingStatusResponse(BaseModel):
    enabled: bool
    configured_enabled: bool
    available: bool
    availability_reason: str | None = None
    model: str
    available_models: list[str]
    project_root: str
    allowed_project_roots: list[str]
    workspace_name: str
    workspace_root: str
    auto_delegate: bool
    active_task_id: str | None = None
    active_task_status: str | None = None
    queued_count: int = 0
