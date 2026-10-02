"""One-time, account-bound workflow creation in Oculus Web."""

import os
from urllib.parse import urlsplit

import httpx
from pydantic import BaseModel, Field


class WorkflowStep(BaseModel):
    title: str = Field(min_length=3, max_length=150)
    description: str = Field(default="", max_length=300)


class WorkflowResource(BaseModel):
    kind: str = Field(pattern="^(tool|resource|data)$")
    title: str = Field(min_length=2, max_length=100)
    description: str = Field(default="", max_length=300)
    url: str = Field(min_length=8, max_length=500)


class WorkflowInput(BaseModel):
    title: str = Field(min_length=3, max_length=100)
    summary: str = Field(default="", max_length=500)
    activity: str = Field(pattern="^(commercial|entrepreneurial|employment|research)$")
    outcome: str = Field(default="", max_length=300)
    focusArea: str = Field(default="", max_length=100)
    sectorSlug: str = Field(default="personal-pursuits", pattern="^[a-z0-9][a-z0-9-]{1,59}$")
    goal: str = Field(default="", max_length=1000)
    targetRoles: str = Field(default="", max_length=500)
    targetLocations: str = Field(default="", max_length=500)
    constraints: str = Field(default="", max_length=1000)
    steps: list[WorkflowStep] = Field(min_length=1, max_length=20)
    resources: list[WorkflowResource] = Field(default_factory=list, max_length=30)


class CreatedWorkflow(BaseModel):
    id: str
    title: str
    webUrl: str


def configured_api_url() -> str:
    base = os.environ.get("OCULUS_WEB_API_URL", "").rstrip("/")
    parsed = urlsplit(base)
    loopback = parsed.hostname in {"127.0.0.1", "localhost", "::1"}
    if (not base or parsed.scheme not in {"http", "https"}
            or (parsed.scheme == "http" and not loopback)
            or not parsed.hostname or parsed.username or parsed.password
            or parsed.path or parsed.query or parsed.fragment):
        raise ValueError("Set OCULUS_WEB_API_URL to an HTTPS origin or a loopback HTTP origin")
    return base


def create_workflow(setup_code: str, workflow: WorkflowInput) -> CreatedWorkflow:
    base = configured_api_url()
    try:
        with httpx.Client(timeout=10, follow_redirects=False, trust_env=False) as client:
            response = client.post(
                f"{base}/api/workflow-setup/import",
                headers={"Authorization": f"Bearer {setup_code}"},
                json=workflow.model_dump(),
            )
    except httpx.HTTPError as exc:
        raise ValueError("Could not reach Oculus Web") from exc
    if response.status_code == 401:
        raise ValueError("Setup code is invalid or expired. Generate a new code in Oculus Web.")
    if not response.is_success:
        raise ValueError(f"Oculus Web rejected the workflow (HTTP {response.status_code})")
    return CreatedWorkflow.model_validate(response.json())


def list_sectors() -> list[dict[str, str]]:
    base = configured_api_url()
    try:
        with httpx.Client(timeout=10, follow_redirects=False, trust_env=False) as client:
            response = client.get(f"{base}/api/workflow-setup/sectors")
        response.raise_for_status()
    except httpx.HTTPError as exc:
        raise ValueError("Could not reach Oculus Web sectors") from exc
    return response.json()
