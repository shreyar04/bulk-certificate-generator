"""Pydantic models describing what the API accepts and returns."""

from datetime import date, datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from app import config


# --------------------------------------------------------------------------- requests


class RecipientIn(BaseModel):
    """One recipient in the request.

    The fields are deliberately typed as "Any": if one recipient has a wrong or missing
    value we do NOT want Pydantic to reject the whole request with a 422. Instead the
    recipient is checked later by validate_recipient() and recorded as FAILED, while
    the other recipients carry on.
    """

    name: Any = Field(default=None, description="Full name printed on the certificate (required, max 70 chars).")
    email: Any = Field(default=None, description="Recipient email address (required).")
    course_name: Any = Field(
        default=None,
        description="Optional. Overrides the job's event_name for this recipient only.",
    )


class JobCreateRequest(BaseModel):
    """Body of POST /api/v1/jobs. Problems here are request-level errors (HTTP 422)."""

    model_config = ConfigDict(
        str_strip_whitespace=True,
        json_schema_extra={
            "example": {
                "event_name": "Advanced Python Bootcamp",
                "issue_date": "2026-10-11",
                "recipients": [
                    {"name": "Asha Verma", "email": "asha@example.com"},
                    {"name": "Rohan Mehta", "email": "rohan@example.com", "course_name": "Python for Data Science"},
                    {"name": "", "email": "not-an-email"},
                ],
            }
        },
    )

    event_name: str = Field(min_length=1, max_length=150, description="Event or course name.")
    issue_date: date = Field(description="Certificate issue date (YYYY-MM-DD).")
    recipients: list[RecipientIn] = Field(
        min_length=1,
        max_length=config.MAX_BATCH_SIZE,
        description=f"Between 1 and {config.MAX_BATCH_SIZE} recipients.",
    )


# --------------------------------------------------------------------------- responses


class JobCreatedResponse(BaseModel):
    job_id: str
    status: str
    total_recipients: int
    invalid_recipients: int = Field(description="Recipients rejected by validation (already marked FAILED).")
    status_url: str


class RecipientStatusOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str | None
    email: str | None
    course_name: str | None
    status: str
    certificate_id: str | None
    error_message: str | None


class JobStatusResponse(BaseModel):
    job_id: str
    status: str
    event_name: str
    issue_date: date
    total_recipients: int
    completed_count: int
    failed_count: int
    pending_count: int
    processing_count: int
    progress_percent: float = Field(description="(completed + failed) / total * 100")
    created_at: datetime
    updated_at: datetime
    recipients: list[RecipientStatusOut]


class CertificateOut(BaseModel):
    certificate_id: str
    recipient_name: str | None
    recipient_email: str | None
    event_name: str
    download_url: str


class CertificateListResponse(BaseModel):
    job_id: str
    job_status: str
    count: int
    certificates: list[CertificateOut]


class HealthResponse(BaseModel):
    status: str
