"""Creating jobs, reading their status, and tracking progress."""

from sqlalchemy import func, select

from app.models import CertificateRecipient, GenerationJob
from app.services import processor


def test_health_endpoint(client):
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_create_job_returns_202_with_job_id_and_status_url(client, make_payload, valid_recipients):
    response = client.post("/api/v1/jobs", json=make_payload(valid_recipients))

    assert response.status_code == 202
    body = response.json()
    assert body["job_id"]
    assert body["status"] == "PENDING"
    assert body["total_recipients"] == 3
    assert body["invalid_recipients"] == 0
    assert body["status_url"] == f"/api/v1/jobs/{body['job_id']}"


def test_job_and_recipients_are_saved_in_database(create_job, valid_recipients, db_session_factory):
    created = create_job(valid_recipients)

    with db_session_factory() as db:
        job = db.get(GenerationJob, created["job_id"])
        assert job is not None
        assert job.total_count == 3
        assert job.event_name == "Advanced Python Bootcamp"
        assert [r.name for r in job.recipients] == ["Asha Verma", "Rohan Mehta", "Priya Nair"]
        assert db.scalar(select(func.count()).select_from(CertificateRecipient)) == 3


def test_each_job_gets_a_unique_id(create_job, valid_recipients):
    first = create_job(valid_recipients)
    second = create_job(valid_recipients)
    assert first["job_id"] != second["job_id"]


def test_status_when_all_recipients_succeed(create_job, get_job, valid_recipients):
    job = get_job(create_job(valid_recipients)["job_id"])

    assert job["status"] == "COMPLETED"
    assert job["total_recipients"] == 3
    assert job["completed_count"] == 3
    assert job["failed_count"] == 0
    assert job["pending_count"] == 0
    assert job["processing_count"] == 0
    assert job["progress_percent"] == 100.0
    for recipient in job["recipients"]:
        assert recipient["status"] == "COMPLETED"
        assert recipient["certificate_id"]
        assert recipient["error_message"] is None


def test_job_counters_in_database_match_the_recipients(create_job, valid_recipients, db_session_factory):
    created = create_job(valid_recipients)

    with db_session_factory() as db:
        job = db.get(GenerationJob, created["job_id"])
        assert job.status == "COMPLETED"
        assert job.success_count == 3
        assert job.failure_count == 0


def test_unknown_job_returns_404(client):
    response = client.get("/api/v1/jobs/does-not-exist")
    assert response.status_code == 404
    assert response.json() == {"detail": "Job not found"}


def test_job_stays_pending_until_the_background_task_runs(
    client, make_payload, valid_recipients, get_job, defer_processing
):
    job_id = client.post("/api/v1/jobs", json=make_payload(valid_recipients)).json()["job_id"]

    before = get_job(job_id)
    assert before["status"] == "PENDING"
    assert before["pending_count"] == 3
    assert before["completed_count"] == 0
    assert before["progress_percent"] == 0.0

    processor.process_job(job_id)  # run the background task by hand

    after = get_job(job_id)
    assert after["status"] == "COMPLETED"
    assert after["pending_count"] == 0
    assert after["progress_percent"] == 100.0


def test_progress_is_visible_while_the_job_is_running(
    client, make_payload, valid_recipients, get_job, defer_processing, monkeypatch
):
    job_id = client.post("/api/v1/jobs", json=make_payload(valid_recipients)).json()["job_id"]

    real_generate = processor.generate_certificate
    calls = []
    snapshots = []

    def spying_generate(**kwargs):
        calls.append(kwargs["recipient_name"])
        if len(calls) == 2:
            # Recipient 1 is done, recipient 2 is being generated right now, recipient 3 waits.
            snapshots.append(get_job(job_id))
        return real_generate(**kwargs)

    monkeypatch.setattr(processor, "generate_certificate", spying_generate)

    processor.process_job(job_id)

    midway = snapshots[0]
    assert midway["status"] == "PROCESSING"
    assert midway["completed_count"] == 1
    assert midway["processing_count"] == 1
    assert midway["pending_count"] == 1
    assert midway["progress_percent"] == 33.3
    assert get_job(job_id)["status"] == "COMPLETED"
