"""Request-level validation (HTTP 422) and recipient-level validation (recorded as FAILED)."""

import pytest
from sqlalchemy import func, select

from app import config
from app.models import GenerationJob
from app.services.validation import validate_recipient

# --------------------------------------------------------------------------- request-level


def test_missing_event_name_is_rejected(client, make_payload, valid_recipients):
    payload = make_payload(valid_recipients)
    del payload["event_name"]
    assert client.post("/api/v1/jobs", json=payload).status_code == 422


def test_blank_event_name_is_rejected(client, make_payload, valid_recipients):
    response = client.post("/api/v1/jobs", json=make_payload(valid_recipients, event_name="   "))
    assert response.status_code == 422


def test_invalid_issue_date_is_rejected(client, make_payload, valid_recipients):
    response = client.post("/api/v1/jobs", json=make_payload(valid_recipients, issue_date="not-a-date"))
    assert response.status_code == 422


def test_missing_recipients_field_is_rejected(client, make_payload, valid_recipients):
    payload = make_payload(valid_recipients)
    del payload["recipients"]
    assert client.post("/api/v1/jobs", json=payload).status_code == 422


def test_empty_recipient_list_is_rejected(client, make_payload):
    assert client.post("/api/v1/jobs", json=make_payload([])).status_code == 422


def test_batch_larger_than_the_limit_is_rejected(client, make_payload):
    too_many = [
        {"name": f"Person {i}", "email": f"person{i}@example.com"}
        for i in range(config.MAX_BATCH_SIZE + 1)
    ]
    assert client.post("/api/v1/jobs", json=make_payload(too_many)).status_code == 422


def test_recipient_that_is_not_an_object_is_rejected(client, make_payload):
    response = client.post("/api/v1/jobs", json=make_payload(["just a string"]))
    assert response.status_code == 422


def test_nothing_is_saved_when_the_request_is_rejected(client, make_payload, db_session_factory):
    client.post("/api/v1/jobs", json=make_payload([]))
    with db_session_factory() as db:
        assert db.scalar(select(func.count()).select_from(GenerationJob)) == 0


# --------------------------------------------------------------------------- recipient-level


def test_invalid_recipients_do_not_block_valid_ones(create_job, get_job, cert_dir):
    recipients = [
        {"name": "Asha Verma", "email": "asha@example.com"},  # valid
        {"name": "", "email": "empty@example.com"},  # empty name
        {"name": "No Email"},  # missing email
        {"name": "Bad Email", "email": "not-an-email"},  # malformed email
        {"name": 12345, "email": "number@example.com"},  # name has the wrong type
        {"name": "Rohan Mehta", "email": "rohan@example.com"},  # valid
    ]

    created = create_job(recipients)
    assert created["total_recipients"] == 6
    assert created["invalid_recipients"] == 4

    job = get_job(created["job_id"])
    assert job["status"] == "PARTIALLY_COMPLETED"
    assert job["total_recipients"] == 6  # invalid recipients are NOT silently dropped
    assert job["completed_count"] == 2
    assert job["failed_count"] == 4
    assert job["progress_percent"] == 100.0

    statuses = [r["status"] for r in job["recipients"]]
    assert statuses == ["COMPLETED", "FAILED", "FAILED", "FAILED", "FAILED", "COMPLETED"]

    errors = [r["error_message"] for r in job["recipients"]]
    assert "name is required" in errors[1]
    assert "email is required" in errors[2]
    assert "valid email" in errors[3]
    assert "name must be text" in errors[4]

    assert len(list(cert_dir.glob("*.pdf"))) == 2  # PDFs only for the two valid recipients


def test_job_with_only_invalid_recipients_ends_as_failed(create_job, get_job, cert_dir):
    created = create_job([{"name": "", "email": "x"}, {}])

    job = get_job(created["job_id"])
    assert job["status"] == "FAILED"
    assert job["completed_count"] == 0
    assert job["failed_count"] == 2
    assert all(r["error_message"] for r in job["recipients"])
    assert list(cert_dir.glob("*.pdf")) == []


def test_text_the_pdf_font_cannot_display_is_rejected_with_a_clear_message(create_job, get_job):
    created = create_job([{"name": "नमस्ते", "email": "hi@example.com"}])

    recipient = get_job(created["job_id"])["recipients"][0]
    assert recipient["status"] == "FAILED"
    assert "cannot display" in recipient["error_message"]


def test_surrounding_whitespace_is_trimmed(create_job, get_job):
    created = create_job([{"name": "  Padded Name  ", "email": " padded@example.com "}])

    recipient = get_job(created["job_id"])["recipients"][0]
    assert recipient["status"] == "COMPLETED"
    assert recipient["name"] == "Padded Name"
    assert recipient["email"] == "padded@example.com"


# --------------------------------------------------------------------------- unit tests


@pytest.mark.parametrize(
    "name,email,course",
    [
        ("Asha Verma", "asha@example.com", None),
        ("José Müller", "jose@example.co.in", "Cours d'été"),
        ("  Padded Name  ", "  padded@example.com ", ""),
    ],
)
def test_valid_recipients_have_no_errors(name, email, course):
    assert validate_recipient(name, email, course) == []


@pytest.mark.parametrize(
    "name,email,course,expected",
    [
        (None, "a@b.co", None, "name is required"),
        ("", "a@b.co", None, "name is required"),
        ("   ", "a@b.co", None, "name is required"),
        (123, "a@b.co", None, "name must be text"),
        ("A" * 71, "a@b.co", None, "at most 70"),
        ("Bad\x00Name", "a@b.co", None, "control characters"),
        ("नमस्ते", "a@b.co", None, "cannot display"),
        ("Asha", None, None, "email is required"),
        ("Asha", "plainaddress", None, "valid email"),
        ("Asha", "a@b", None, "valid email"),
        ("Asha", "a b@example.com", None, "valid email"),
        ("Asha", "a@b.co", 42, "course_name must be text"),
        ("Asha", "a@b.co", "C" * 151, "course_name must be at most 150"),
    ],
)
def test_invalid_recipients_report_a_clear_error(name, email, course, expected):
    errors = validate_recipient(name, email, course)
    assert any(expected in error for error in errors), errors


def test_all_problems_are_reported_together():
    errors = validate_recipient(None, None)
    assert len(errors) == 2
