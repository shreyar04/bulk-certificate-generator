"""Failure isolation, final job status rules, and crash recovery.

The PDF generator is replaced with a fake that fails on purpose. That is much more
reliable than trying to make the real filesystem or ReportLab fail.
"""

import pytest

from app.models import GenerationJob
from app.services import processor
from app.services.generator import CertificateGenerationError


@pytest.fixture()
def fail_for(monkeypatch):
    """Returns install(names, error): the generator raises `error` for recipients in `names`."""
    real_generate = processor.generate_certificate  # remember the real one

    def install(names, error):
        def fake_generate(**kwargs):
            if kwargs["recipient_name"] in names:
                raise error
            return real_generate(**kwargs)

        monkeypatch.setattr(processor, "generate_certificate", fake_generate)

    return install


# --------------------------------------------------------------------------- isolation


def test_one_failure_does_not_stop_the_other_recipients(
    create_job, get_job, fail_for, cert_dir, valid_recipients
):
    fail_for({"Rohan Mehta"}, CertificateGenerationError("Simulated rendering failure"))

    job = get_job(create_job(valid_recipients)["job_id"])

    assert job["status"] == "PARTIALLY_COMPLETED"
    assert job["completed_count"] == 2
    assert job["failed_count"] == 1
    assert job["pending_count"] == 0
    assert job["processing_count"] == 0
    assert job["progress_percent"] == 100.0

    asha, rohan, priya = job["recipients"]
    assert asha["status"] == "COMPLETED"
    assert rohan["status"] == "FAILED"
    assert rohan["error_message"] == "Simulated rendering failure"
    assert rohan["certificate_id"] is None
    assert priya["status"] == "COMPLETED"  # processed AFTER the failure
    assert len(list(cert_dir.glob("*.pdf"))) == 2


def test_database_counters_after_a_partial_failure(
    create_job, fail_for, db_session_factory, valid_recipients
):
    fail_for({"Rohan Mehta"}, CertificateGenerationError("boom"))

    created = create_job(valid_recipients)

    with db_session_factory() as db:
        job = db.get(GenerationJob, created["job_id"])
        assert job.status == "PARTIALLY_COMPLETED"
        assert job.success_count == 2
        assert job.failure_count == 1


def test_unexpected_exception_does_not_leak_details_to_the_client(
    create_job, get_job, fail_for, valid_recipients
):
    fail_for({"Rohan Mehta"}, RuntimeError("secret: /etc/passwd password=hunter2"))

    job = get_job(create_job(valid_recipients)["job_id"])

    message = job["recipients"][1]["error_message"]
    assert "RuntimeError" in message  # useful: says what kind of error it was
    assert "hunter2" not in message  # safe: no internal details
    assert "/etc/passwd" not in message
    assert job["status"] == "PARTIALLY_COMPLETED"


def test_a_partially_written_file_is_removed_when_generation_fails(
    create_job, get_job, cert_dir, monkeypatch, valid_recipients
):
    def writes_then_fails(**kwargs):
        kwargs["output_path"].write_bytes(b"half a pdf")
        raise CertificateGenerationError("disk full")

    monkeypatch.setattr(processor, "generate_certificate", writes_then_fails)

    job = get_job(create_job(valid_recipients[:1])["job_id"])

    assert job["status"] == "FAILED"
    assert list(cert_dir.iterdir()) == []


# --------------------------------------------------------------------------- final status


def test_all_recipients_failing_gives_failed_status(
    create_job, get_job, fail_for, cert_dir, valid_recipients
):
    fail_for({"Asha Verma", "Rohan Mehta", "Priya Nair"}, CertificateGenerationError("boom"))

    job = get_job(create_job(valid_recipients)["job_id"])

    assert job["status"] == "FAILED"
    assert job["completed_count"] == 0
    assert job["failed_count"] == 3
    assert job["progress_percent"] == 100.0
    assert all(r["error_message"] == "boom" for r in job["recipients"])
    assert list(cert_dir.glob("*.pdf")) == []


@pytest.mark.parametrize(
    "completed,failed,total,expected",
    [
        (3, 0, 3, "COMPLETED"),
        (1, 0, 1, "COMPLETED"),
        (2, 1, 3, "PARTIALLY_COMPLETED"),
        (1, 2, 3, "PARTIALLY_COMPLETED"),
        (0, 3, 3, "FAILED"),
        (0, 1, 1, "FAILED"),
    ],
)
def test_final_status_rules(completed, failed, total, expected):
    assert processor.compute_final_status(completed, failed, total) == expected


# --------------------------------------------------------------------------- safety nets


def test_unexpected_crash_still_leaves_the_job_in_a_terminal_state(
    client, make_payload, valid_recipients, get_job, defer_processing, monkeypatch
):
    job_id = client.post("/api/v1/jobs", json=make_payload(valid_recipients)).json()["job_id"]

    real_process_one = processor._process_one_recipient
    calls = []

    def flaky(db, jid, recipient_id):
        calls.append(recipient_id)
        if len(calls) == 2:
            raise RuntimeError("database exploded")  # a crash OUTSIDE the per-recipient try/except
        real_process_one(db, jid, recipient_id)

    monkeypatch.setattr(processor, "_process_one_recipient", flaky)

    processor.process_job(job_id)  # must not raise

    job = get_job(job_id)
    assert job["pending_count"] == 0
    assert job["processing_count"] == 0
    assert [r["status"] for r in job["recipients"]] == ["COMPLETED", "FAILED", "FAILED"]
    assert "interrupted" in job["recipients"][1]["error_message"]
    assert job["status"] == "PARTIALLY_COMPLETED"


def test_a_job_is_never_processed_twice(
    client, make_payload, valid_recipients, get_job, defer_processing, cert_dir
):
    job_id = client.post("/api/v1/jobs", json=make_payload(valid_recipients)).json()["job_id"]

    processor.process_job(job_id)
    first = get_job(job_id)
    processor.process_job(job_id)  # second run must do nothing
    second = get_job(job_id)

    assert first["status"] == "COMPLETED"
    assert first["recipients"] == second["recipients"]  # same certificate IDs as before
    assert len(list(cert_dir.glob("*.pdf"))) == 3


def test_processing_an_unknown_job_does_not_raise(db_session_factory):
    processor.process_job("no-such-job")  # logs a warning and returns
