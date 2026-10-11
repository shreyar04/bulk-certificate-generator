"""Background processing of a generation job.

process_job() is what FastAPI's BackgroundTasks runs after the HTTP response is sent.

Key ideas (each one is explained again in the README):

1. It opens its OWN database session. The session that handled the HTTP request must
   never be reused here: sessions are not thread-safe and the request's session is
   closed as soon as the request ends.
2. Every recipient is handled inside its own try/except, so one failure never stops
   the others (failure isolation).
3. Every recipient commits on its own, so progress is visible to GET /jobs/{id} while
   the job is still running, and a crash never loses work that was already done.
4. At the end the job status is calculated from the recipient rows, which are the
   single source of truth.
"""

import logging
from pathlib import Path
from uuid import uuid4

from sqlalchemy import func, select, update
from sqlalchemy.orm import Session

from app import config, database
from app.models import (
    CertificateRecipient,
    GenerationJob,
    JobStatus,
    RecipientStatus,
    utcnow,
)
from app.services.generator import CertificateGenerationError, generate_certificate
from app.services.validation import validate_recipient

logger = logging.getLogger(__name__)

MAX_ERROR_LENGTH = 500


def process_job(job_id: str) -> None:
    """Entry point used by BackgroundTasks. Never raises: errors are logged and recorded."""
    db = database.SessionLocal()  # a brand-new session just for this task
    try:
        _run_job(db, job_id)
    except Exception:
        # Something unexpected (for example the database went away). Log it, then make
        # sure the job does not stay stuck in PROCESSING forever.
        logger.exception("Unexpected error while processing job %s", job_id)
        db.rollback()
        _recover_job(db, job_id)
    finally:
        db.close()


def compute_final_status(completed: int, failed: int, total: int) -> str:
    """The rule that decides a job's final status (documented in the README).

    * every recipient completed          -> COMPLETED
    * nobody completed                   -> FAILED
    * at least one completed, some not   -> PARTIALLY_COMPLETED
    """
    if total > 0 and completed == total:
        return JobStatus.COMPLETED.value
    if completed == 0:
        return JobStatus.FAILED.value
    return JobStatus.PARTIALLY_COMPLETED.value


# --------------------------------------------------------------------------- main flow


def _run_job(db: Session, job_id: str) -> None:
    if not _claim_job(db, job_id):
        logger.warning("Job %s does not exist or was already started; skipping", job_id)
        return

    # Only recipients that are still PENDING are processed. Invalid recipients were already
    # marked FAILED when the job was created, so they are skipped here.
    recipient_ids = list(
        db.scalars(
            select(CertificateRecipient.id)
            .where(
                CertificateRecipient.job_id == job_id,
                CertificateRecipient.status == RecipientStatus.PENDING.value,
            )
            .order_by(CertificateRecipient.id)
        )
    )

    for recipient_id in recipient_ids:
        _process_one_recipient(db, job_id, recipient_id)

    _finalize_job(db, job_id)


def _claim_job(db: Session, job_id: str) -> bool:
    """Atomically switch the job PENDING -> PROCESSING.

    "UPDATE ... WHERE status = 'PENDING'" only succeeds for the first caller. If the same
    job is somehow started twice, the second call changes 0 rows and returns False, so
    certificates are never generated twice.
    """
    result = db.execute(
        update(GenerationJob)
        .where(GenerationJob.id == job_id, GenerationJob.status == JobStatus.PENDING.value)
        .values(status=JobStatus.PROCESSING.value, updated_at=utcnow())
        .execution_options(synchronize_session=False)
    )
    db.commit()
    return result.rowcount == 1


def _process_one_recipient(db: Session, job_id: str, recipient_id: int) -> None:
    """Handle ONE recipient. Failures are recorded on that recipient and never re-raised."""
    recipient = db.get(CertificateRecipient, recipient_id)
    if recipient is None or recipient.status != RecipientStatus.PENDING.value:
        return  # already handled: never process a recipient twice

    # Step 1: validate (a second line of defence; creation already validated).
    errors = validate_recipient(recipient.name, recipient.email, recipient.course_name)
    if errors:
        _record_failure(db, recipient_id, "; ".join(errors))
        return

    output_path: Path | None = None
    try:
        # Step 2: mark as PROCESSING (committed, so a status request can see it).
        recipient.status = RecipientStatus.PROCESSING.value
        db.commit()

        # Step 3: generate the PDF. The file name comes from our own UUID, never from user input.
        job = db.get(GenerationJob, job_id)
        certificate_id = str(uuid4())
        output_path = config.CERTIFICATE_DIR / f"{certificate_id}.pdf"
        generate_certificate(
            recipient_name=recipient.name,
            event_name=recipient.course_name or job.event_name,
            issue_date=job.issue_date,
            certificate_id=certificate_id,
            output_path=output_path,
        )

        # Step 4: save the result. Recipient and job counter change in ONE commit.
        recipient.certificate_id = certificate_id
        recipient.certificate_path = str(output_path)
        recipient.status = RecipientStatus.COMPLETED.value
        recipient.error_message = None
        job.success_count += 1
        db.commit()

    except Exception as exc:
        # Step 5: isolate the failure. Undo anything uncommitted, delete a partial file,
        # record the error on THIS recipient only, and let the loop continue.
        db.rollback()
        logger.exception("Certificate generation failed for recipient %s in job %s", recipient_id, job_id)
        _remove_file_quietly(output_path)
        _record_failure(db, recipient_id, _safe_error_message(exc))


def _record_failure(db: Session, recipient_id: int, message: str) -> None:
    """Mark one recipient FAILED and bump the job's failure counter (one commit)."""
    recipient = db.get(CertificateRecipient, recipient_id)
    recipient.status = RecipientStatus.FAILED.value
    recipient.error_message = message[:MAX_ERROR_LENGTH]
    recipient.certificate_id = None
    recipient.certificate_path = None
    job = db.get(GenerationJob, recipient.job_id)
    job.failure_count += 1
    db.commit()


def _finalize_job(db: Session, job_id: str) -> None:
    """Recount from the recipient rows and store the final job status."""
    job = db.get(GenerationJob, job_id)
    if job is None:
        return

    rows = db.execute(
        select(CertificateRecipient.status, func.count())
        .where(CertificateRecipient.job_id == job_id)
        .group_by(CertificateRecipient.status)
    ).all()
    counts = {status: count for status, count in rows}
    completed = counts.get(RecipientStatus.COMPLETED.value, 0)
    failed = counts.get(RecipientStatus.FAILED.value, 0)

    job.success_count = completed
    job.failure_count = failed
    job.status = compute_final_status(completed, failed, job.total_count)
    db.commit()


# --------------------------------------------------------------------------- safety nets


def _recover_job(db: Session, job_id: str) -> None:
    """Last resort after an unexpected crash: nothing may stay PENDING or PROCESSING."""
    try:
        db.execute(
            update(CertificateRecipient)
            .where(
                CertificateRecipient.job_id == job_id,
                CertificateRecipient.status.in_(
                    [RecipientStatus.PENDING.value, RecipientStatus.PROCESSING.value]
                ),
            )
            .values(
                status=RecipientStatus.FAILED.value,
                error_message="Processing was interrupted by an unexpected server error",
                updated_at=utcnow(),
            )
            .execution_options(synchronize_session=False)
        )
        db.commit()
        _finalize_job(db, job_id)
    except Exception:
        logger.exception("Could not recover job %s", job_id)
        db.rollback()


def _safe_error_message(exc: Exception) -> str:
    """Text that is safe to show to API clients (no file paths, no stack traces)."""
    if isinstance(exc, CertificateGenerationError):
        return str(exc)  # our own message, already written for clients
    return f"Unexpected error while generating certificate ({type(exc).__name__})"


def _remove_file_quietly(path: Path | None) -> None:
    if path is None:
        return
    try:
        path.unlink(missing_ok=True)
    except OSError:
        logger.warning("Could not remove partial file %s", path)
