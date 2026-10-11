"""SQLAlchemy 2.x ORM models: one job has many recipients."""

import enum
import uuid
from datetime import date, datetime, timezone

from sqlalchemy import CheckConstraint, Date, DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


class JobStatus(str, enum.Enum):
    PENDING = "PENDING"
    PROCESSING = "PROCESSING"
    COMPLETED = "COMPLETED"
    PARTIALLY_COMPLETED = "PARTIALLY_COMPLETED"
    FAILED = "FAILED"


class RecipientStatus(str, enum.Enum):
    PENDING = "PENDING"
    PROCESSING = "PROCESSING"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"


def utcnow() -> datetime:
    """Current UTC time (stored without tzinfo because SQLite has no timezone type)."""
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _in_list(column: str, enum_class: type[enum.Enum]) -> str:
    values = ", ".join(f"'{item.value}'" for item in enum_class)
    return f"{column} IN ({values})"


class GenerationJob(Base):
    __tablename__ = "generation_jobs"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    event_name: Mapped[str] = mapped_column(String(150), nullable=False)
    issue_date: Mapped[date] = mapped_column(Date, nullable=False)
    status: Mapped[str] = mapped_column(
        String(20), nullable=False, default=JobStatus.PENDING.value, index=True
    )
    total_count: Mapped[int] = mapped_column(Integer, nullable=False)
    success_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    failure_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, default=utcnow, onupdate=utcnow
    )

    recipients: Mapped[list["CertificateRecipient"]] = relationship(
        back_populates="job",
        cascade="all, delete-orphan",
        order_by="CertificateRecipient.id",
    )

    __table_args__ = (
        CheckConstraint(_in_list("status", JobStatus), name="ck_job_status_valid"),
        CheckConstraint("total_count >= 0", name="ck_job_total_non_negative"),
        CheckConstraint("success_count >= 0 AND failure_count >= 0", name="ck_job_counts_non_negative"),
    )


class CertificateRecipient(Base):
    __tablename__ = "certificate_recipients"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    job_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("generation_jobs.id", ondelete="CASCADE"), nullable=False, index=True
    )
    # name / email / course_name are nullable because an INVALID recipient (for example one
    # with a missing name) must still be stored, so it can be reported as FAILED.
    name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    email: Mapped[str | None] = mapped_column(String(255), nullable=True)
    course_name: Mapped[str | None] = mapped_column(String(255), nullable=True)  # optional override
    status: Mapped[str] = mapped_column(
        String(20), nullable=False, default=RecipientStatus.PENDING.value, index=True
    )
    # Filled only after the PDF has been generated. SQLite allows many NULLs in a UNIQUE column.
    certificate_id: Mapped[str | None] = mapped_column(String(36), unique=True, nullable=True)
    certificate_path: Mapped[str | None] = mapped_column(String(500), nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, default=utcnow, onupdate=utcnow
    )

    job: Mapped["GenerationJob"] = relationship(back_populates="recipients")

    __table_args__ = (
        CheckConstraint(_in_list("status", RecipientStatus), name="ck_recipient_status_valid"),
    )
