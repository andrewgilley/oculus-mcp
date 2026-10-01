"""Explicit output contracts; raw Oculus state is never returned."""
from typing import Literal

from pydantic import BaseModel, Field

Provider = Literal["github", "codeberg"]


class Project(BaseModel):
    provider: Provider
    repository: str
    name: str | None = None
    path: str | None = None
    groups: list[str] = Field(default_factory=list)
    url: str


class ProjectsPage(BaseModel):
    projects: list[Project]
    total: int
    next_offset: int | None
    source: Literal["tracking_file", "state_file"]


class SavedItem(BaseModel):
    key: str
    provider: Provider
    repository: str | None = None
    event_type: str | None = None
    title: str | None = None
    url: str | None = None
    created_at: str | None = None


class SavedItemsPage(BaseModel):
    items: list[SavedItem]
    total: int
    next_offset: int | None


class InspectionSummary(BaseModel):
    inspection_id: str
    has_explanation: bool
    location_count: int


class InspectionsPage(BaseModel):
    inspections: list[InspectionSummary]
    total: int
    next_offset: int | None


class PatchLocation(BaseModel):
    path: str
    line: int | None = None
    reason: str | None = None


class InspectionContext(BaseModel):
    inspection_id: str
    source: Literal["cached_overview"] = "cached_overview"
    explanation: str | None = None
    explanation_model: str | None = None
    locations: list[PatchLocation] = Field(default_factory=list)
    patch_model: str | None = None
    limitations: str = (
        "Cached AI output, possibly stale. Does not include live buffers, full diffs, "
        "review threads, or verified evidence of correctness."
    )
