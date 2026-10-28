"""HTTP request and response models for the hosted API."""

from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from replay_core.models import Baseline, Report


class ProjectCreate(BaseModel):
    name: str = Field(min_length=1, max_length=200)


class ProjectCreated(BaseModel):
    id: UUID
    name: str
    slug: str
    token: str
    created_at: datetime | None = None


class ProjectOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    name: str
    slug: str
    created_at: datetime | None = None


class CollectionCreated(BaseModel):
    id: UUID
    project_id: UUID
    name: str
    created_at: datetime | None = None


class BaselineCreate(BaseModel):
    baseline: Baseline
    collection_id: UUID | None = None


class BaselineCreated(BaseModel):
    id: UUID
    project_id: UUID
    collection_id: UUID | None
    name: str
    target: str
    created_at: datetime | None = None


class RunCreate(BaseModel):
    """Upload a report the CLI already produced. The API does not re-diff."""

    report: Report
    target: str | None = None
    collection_id: UUID | None = None
    baseline_id: UUID | None = None


class RunSummary(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    project_id: UUID
    collection_id: UUID | None
    baseline_id: UUID | None
    name: str
    target: str | None
    total: int
    matched: int
    regressed: int
    errored: int
    created_at: datetime | None = None


class DiagnosisOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    run_id: UUID
    provider: str
    model: str
    prompt_version: str
    content: str
    created_at: datetime | None = None


class RunDetail(RunSummary):
    report: dict[str, Any]
    diagnosis: DiagnosisOut | None = None
