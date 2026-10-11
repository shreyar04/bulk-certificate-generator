"""Endpoints that create jobs, report their progress and list their certificates."""

from typing import Any

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import (
    CertificateRecipient,
    GenerationJob,
    JobStatus,
    RecipientStatus,
)
from app.schemas import (
    CertificateListResponse,
    CertificateOut,
    JobCreatedResponse,
    JobCreateRequest,
    JobStatusResponse,
    RecipientStatusOut,
)
from app.services.processor import process_job
from app.services.validation import validate_recipient

router = APIRouter(prefix="/api/v1/jobs", tags=["Jobs"])


# --------------------------------------------------------------------------- create


@router.post("", response_model=JobCreatedResponse, status_code=202)
def create_job(
    payload: JobCreateRequest,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
) -> JobCreatedResponse:
    """Save the job and its recipients, then start generating certificates in the background."""
    job = GenerationJob(
        status=JobStatus.PENDING.value,
        event_name=payload.event_name,
        issue_date=payload.issue_date,
        total_count=len(payload.recipients),
    )

    invalid_count = 0
    for item in payload.recipients:
        problems = validate_recipient(item.name, item.email, item.course_name)
        recipient = CertificateRecipient(
            name=_clean_for_storage(item.name),
            email=_clean_for_storage(item.email),
            course_name=_clean_for_storage(item.course_name),
        )
        if problems:
            # Not silently dropped: stored as FAILED with the reasons.
            recipient.status = RecipientStatus.FAILED.value
            recipient.error_message = "; ".join(problems)
            invalid_count += 1
        else:
            recipient.status = RecipientStatus.PENDING.value
        job.recipients.append(recipient)

    job.failure_count = invalid_count
    db.add(job)
    db.commit()  # the job MUST be saved before the background task starts looking for it
    job_id = job.id

    # The background task opens its own database session (see services/processor.py).
    background_tasks.add_task(process_job, job_id)

    return JobCreatedResponse(
        job_id=job_id,
        status=JobStatus.PENDING.value,
        total_recipients=len(payload.recipients),
        invalid_recipients=invalid_count,
        status_url=f"/api/v1/jobs/{job_id}",
    )


# --------------------------------------------------------------------------- status


@router.get("/{job_id}", response_model=JobStatusResponse)
def get_job_status(job_id: str, db: Session = Depends(get_db)) -> JobStatusResponse:
    """Overall job status, counts, progress and the status of every recipient."""
    job = _get_job_or_404(db, job_id)
    recipients = job.recipients

    def count(status: RecipientStatus) -> int:
        return sum(1 for r in recipients if r.status == status.value)

    completed = count(RecipientStatus.COMPLETED)
    failed = count(RecipientStatus.FAILED)
    total = job.total_count
    progress = round((completed + failed) / total * 100, 1) if total else 0.0

    return JobStatusResponse(
        job_id=job.id,
        status=job.status,
        event_name=job.event_name,
        issue_date=job.issue_date,
        total_recipients=total,
        completed_count=completed,
        failed_count=failed,
        pending_count=count(RecipientStatus.PENDING),
        processing_count=count(RecipientStatus.PROCESSING),
        progress_percent=progress,
        created_at=job.created_at,
        updated_at=job.updated_at,
        recipients=[RecipientStatusOut.model_validate(r) for r in recipients],
    )


# --------------------------------------------------------------------------- certificates


@router.get("/{job_id}/certificates", response_model=CertificateListResponse)
def list_job_certificates(job_id: str, db: Session = Depends(get_db)) -> CertificateListResponse:
    """List the certificates that were generated successfully for THIS job only."""
    job = _get_job_or_404(db, job_id)

    certificates = [
        CertificateOut(
            certificate_id=r.certificate_id,
            recipient_name=r.name,
            recipient_email=r.email,
            event_name=r.course_name or job.event_name,
            download_url=f"/api/v1/certificates/{r.certificate_id}/download",
        )
        for r in job.recipients
        if r.status == RecipientStatus.COMPLETED.value and r.certificate_id
    ]
    return CertificateListResponse(
        job_id=job.id,
        job_status=job.status,
        count=len(certificates),
        certificates=certificates,
    )


# --------------------------------------------------------------------------- helpers


def _get_job_or_404(db: Session, job_id: str) -> GenerationJob:
    job = db.get(GenerationJob, job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Job not found")
    return job


def _clean_for_storage(value: Any, max_length: int = 255) -> str | None:
    """Turn whatever the client sent into a short string (or None) for the database."""
    if value is None:
        return None
    text = value.strip() if isinstance(value, str) else str(value)
    return text[:max_length] or None
