"""Pydantic request/response models."""

from datetime import datetime
from enum import Enum
from typing import Optional

from pydantic import BaseModel, Field


class JobStatus(str, Enum):
    QUEUED = "queued"
    RUNNING = "running"
    SUCCESS = "success"
    FAILED = "failed"


class PipelineRequest(BaseModel):
    jira_ticket_id: str = Field(
        ...,
        description="Jira ticket ID, e.g. PROJ-42",
        examples=["PROJ-42"],
        pattern=r"^[A-Z][A-Z0-9]+-\d+$",
    )
    workspace_path: Optional[str] = Field(
        default=None,
        description="Optional absolute path override for the target codebase.",
        examples=["/Users/john/projects/my-app"],
    )


class PipelineResponse(BaseModel):
    job_id: str
    status: JobStatus
    jira_ticket_id: str
    message: str


class JobStatusResponse(BaseModel):
    job_id: str
    status: JobStatus
    jira_ticket_id: str
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    duration_seconds: Optional[float] = None
    result: Optional[str] = None
    error: Optional[str] = None


class HealthResponse(BaseModel):
    status: str
    version: str