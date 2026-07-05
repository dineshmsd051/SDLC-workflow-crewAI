"""FastAPI server exposing the SDLC pipeline as HTTP endpoints."""

from __future__ import annotations

import logging
import os
import traceback
import uuid
from contextlib import asynccontextmanager
from typing import List

from dotenv import load_dotenv
from fastapi import BackgroundTasks, FastAPI, HTTPException, status
from fastapi.middleware.cors import CORSMiddleware

from agents.crew import SDLCCrew
from api.job_store import job_store
from api.models import (
    HealthResponse,
    JobStatus,
    JobStatusResponse,
    PipelineRequest,
    PipelineResponse,
)

# ---------------------------------------------------------------------------
# Setup
# ---------------------------------------------------------------------------

load_dotenv()

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("sdlc.api")

VERSION = "1.0.0"

REQUIRED_ENV_VARS = [
    "JIRA_URL",
    "JIRA_EMAIL",
    "JIRA_API_TOKEN",
    "GITHUB_TOKEN",
]


def _check_env() -> List[str]:
    missing = [v for v in REQUIRED_ENV_VARS if not os.getenv(v)]
    if not os.getenv("OPENAI_API_KEY") and not os.getenv("ANTHROPIC_API_KEY"):
        missing.append("OPENAI_API_KEY or ANTHROPIC_API_KEY")
    return missing


@asynccontextmanager
async def lifespan(app: FastAPI):
    missing = _check_env()
    if missing:
        logger.warning("⚠️  Missing env vars: %s", ", ".join(missing))
    else:
        logger.info("✅ All required env vars present")
    logger.info("🚀 SDLC Pipeline API started (v%s)", VERSION)
    yield
    logger.info("👋 SDLC Pipeline API stopped")


app = FastAPI(
    title="Multi-Agent SDLC Pipeline API",
    description="Trigger the AI-powered SDLC pipeline via HTTP.",
    version=VERSION,
    lifespan=lifespan,
)

# Enable CORS for local dev / internal tools
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ---------------------------------------------------------------------------
# Background worker
# ---------------------------------------------------------------------------

def _run_pipeline(job_id: str, jira_ticket_id: str, workspace_path: str | None) -> None:
    """Execute the Crew pipeline in a background thread."""
    logger.info("[%s] Starting pipeline for %s", job_id, jira_ticket_id)

    if workspace_path:
        os.environ["WORKSPACE_PATH"] = workspace_path

    job_store.update_status(job_id, JobStatus.RUNNING)

    try:
        crew = SDLCCrew(jira_ticket_id=jira_ticket_id)
        result = crew.kickoff()
        result_str = str(result)
        job_store.update_status(job_id, JobStatus.SUCCESS, result=result_str)
        logger.info("[%s] ✅ Pipeline completed", job_id)
    except Exception as exc:
        error_msg = f"{type(exc).__name__}: {exc}"
        tb = traceback.format_exc()
        logger.exception("[%s] ❌ Pipeline failed", job_id)
        job_store.update_status(
            job_id,
            JobStatus.FAILED,
            error=f"{error_msg}\n\n{tb}",
        )


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

@app.get("/", response_model=HealthResponse, tags=["Health"])
def root() -> HealthResponse:
    """Health check."""
    return HealthResponse(status="ok", version=VERSION)


@app.get("/health", response_model=HealthResponse, tags=["Health"])
def health() -> HealthResponse:
    missing = _check_env()
    return HealthResponse(
        status="ok" if not missing else f"degraded (missing: {', '.join(missing)})",
        version=VERSION,
    )


@app.post(
    "/pipeline/run",
    response_model=PipelineResponse,
    status_code=status.HTTP_202_ACCEPTED,
    tags=["Pipeline"],
)
def run_pipeline(
    req: PipelineRequest, background_tasks: BackgroundTasks
) -> PipelineResponse:
    """
    Trigger the SDLC pipeline for a Jira ticket.

    Returns immediately with a `job_id`. Poll `/pipeline/status/{job_id}`
    for progress and result.
    """
    missing = _check_env()
    if missing:
        raise HTTPException(
            status_code=503,
            detail=f"Server misconfigured. Missing env vars: {', '.join(missing)}",
        )

    job_id = str(uuid.uuid4())
    job_store.create(job_id=job_id, jira_ticket_id=req.jira_ticket_id)

    background_tasks.add_task(
        _run_pipeline,
        job_id=job_id,
        jira_ticket_id=req.jira_ticket_id,
        workspace_path=req.workspace_path,
    )

    logger.info(
        "[%s] Queued pipeline for %s (workspace=%s)",
        job_id,
        req.jira_ticket_id,
        req.workspace_path or os.getenv("WORKSPACE_PATH", "default"),
    )

    return PipelineResponse(
        job_id=job_id,
        status=JobStatus.QUEUED,
        jira_ticket_id=req.jira_ticket_id,
        message="Pipeline queued. Poll /pipeline/status/{job_id} for progress.",
    )


@app.get(
    "/pipeline/status/{job_id}",
    response_model=JobStatusResponse,
    tags=["Pipeline"],
)
def get_job_status(job_id: str) -> JobStatusResponse:
    """Fetch the current status of a pipeline job."""
    job = job_store.get(job_id)
    if not job:
        raise HTTPException(status_code=404, detail=f"Job '{job_id}' not found.")

    return JobStatusResponse(
        job_id=job.job_id,
        status=job.status,
        jira_ticket_id=job.jira_ticket_id,
        started_at=job.started_at,
        completed_at=job.completed_at,
        duration_seconds=job.duration_seconds,
        result=job.result,
        error=job.error,
    )


@app.get(
    "/pipeline/jobs",
    response_model=List[JobStatusResponse],
    tags=["Pipeline"],
)
def list_jobs() -> List[JobStatusResponse]:
    """List all jobs (running + historical, since server start)."""
    return [
        JobStatusResponse(
            job_id=j.job_id,
            status=j.status,
            jira_ticket_id=j.jira_ticket_id,
            started_at=j.started_at,
            completed_at=j.completed_at,
            duration_seconds=j.duration_seconds,
            result=j.result,
            error=j.error,
        )
        for j in job_store.list_all()
    ]