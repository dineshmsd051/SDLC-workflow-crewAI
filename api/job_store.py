"""Simple thread-safe in-memory job tracker."""

from __future__ import annotations

import threading
from datetime import datetime
from typing import Dict, Optional

from api.models import JobStatus


class Job:
    def __init__(self, job_id: str, jira_ticket_id: str):
        self.job_id = job_id
        self.jira_ticket_id = jira_ticket_id
        self.status: JobStatus = JobStatus.QUEUED
        self.started_at: Optional[datetime] = None
        self.completed_at: Optional[datetime] = None
        self.result: Optional[str] = None
        self.error: Optional[str] = None

    @property
    def duration_seconds(self) -> Optional[float]:
        if self.started_at and self.completed_at:
            return (self.completed_at - self.started_at).total_seconds()
        return None


class JobStore:
    """Thread-safe in-memory store for pipeline job status."""

    def __init__(self) -> None:
        self._jobs: Dict[str, Job] = {}
        self._lock = threading.Lock()

    def create(self, job_id: str, jira_ticket_id: str) -> Job:
        with self._lock:
            job = Job(job_id, jira_ticket_id)
            self._jobs[job_id] = job
            return job

    def get(self, job_id: str) -> Optional[Job]:
        with self._lock:
            return self._jobs.get(job_id)

    def update_status(
        self,
        job_id: str,
        status: JobStatus,
        result: Optional[str] = None,
        error: Optional[str] = None,
    ) -> None:
        with self._lock:
            job = self._jobs.get(job_id)
            if not job:
                return
            job.status = status
            if status == JobStatus.RUNNING and not job.started_at:
                job.started_at = datetime.utcnow()
            if status in {JobStatus.SUCCESS, JobStatus.FAILED}:
                job.completed_at = datetime.utcnow()
            if result is not None:
                job.result = result
            if error is not None:
                job.error = error

    def list_all(self) -> list[Job]:
        with self._lock:
            return list(self._jobs.values())


# Singleton instance
job_store = JobStore()