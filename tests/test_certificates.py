"""Listing a job's certificates and downloading PDFs (including all the error cases)."""

import io

from pypdf import PdfReader
from sqlalchemy import update

from app.models import CertificateRecipient


def _list_certificates(client, job_id):
    response = client.get(f"/api/v1/jobs/{job_id}/certificates")
    assert response.status_code == 200, response.text
    return response.json()


# --------------------------------------------------------------------------- listing


def test_list_certificates_for_a_job(client, create_job, valid_recipients):
    job_id = create_job(valid_recipients)["job_id"]

    body = _list_certificates(client, job_id)

    assert body["job_id"] == job_id
    assert body["job_status"] == "COMPLETED"
    assert body["count"] == 3
    assert [c["recipient_name"] for c in body["certificates"]] == ["Asha Verma", "Rohan Mehta", "Priya Nair"]
    for certificate in body["certificates"]:
        assert certificate["download_url"] == f"/api/v1/certificates/{certificate['certificate_id']}/download"
    assert body["certificates"][0]["event_name"] == "Advanced Python Bootcamp"
    assert body["certificates"][2]["event_name"] == "Python for Data Science"  # per-recipient override


def test_list_only_contains_successful_certificates(client, create_job):
    job_id = create_job(
        [
            {"name": "Asha Verma", "email": "asha@example.com"},
            {"name": "", "email": "broken"},
        ]
    )["job_id"]

    body = _list_certificates(client, job_id)

    assert body["count"] == 1
    assert body["certificates"][0]["recipient_name"] == "Asha Verma"


def test_list_is_limited_to_the_requested_job(client, create_job, valid_recipients):
    job_a = create_job(valid_recipients[:1])["job_id"]
    job_b = create_job(valid_recipients[1:2])["job_id"]

    ids_a = {c["certificate_id"] for c in _list_certificates(client, job_a)["certificates"]}
    ids_b = {c["certificate_id"] for c in _list_certificates(client, job_b)["certificates"]}

    assert len(ids_a) == 1 and len(ids_b) == 1
    assert ids_a.isdisjoint(ids_b)


def test_list_is_empty_while_the_job_has_not_run(client, make_payload, valid_recipients, defer_processing):
    job_id = client.post("/api/v1/jobs", json=make_payload(valid_recipients)).json()["job_id"]

    body = _list_certificates(client, job_id)

    assert body["job_status"] == "PENDING"
    assert body["count"] == 0
    assert body["certificates"] == []


def test_list_for_unknown_job_returns_404(client):
    response = client.get("/api/v1/jobs/does-not-exist/certificates")
    assert response.status_code == 404


# --------------------------------------------------------------------------- download


def test_download_returns_a_pdf(client, create_job, valid_recipients):
    job_id = create_job(valid_recipients)["job_id"]
    certificate = _list_certificates(client, job_id)["certificates"][0]

    response = client.get(certificate["download_url"])

    assert response.status_code == 200
    assert response.headers["content-type"] == "application/pdf"
    assert response.content.startswith(b"%PDF")
    disposition = response.headers["content-disposition"]
    assert "attachment" in disposition
    assert certificate["certificate_id"] in disposition


def test_downloaded_pdf_belongs_to_the_requested_certificate(client, create_job, valid_recipients):
    job_id = create_job(valid_recipients)["job_id"]
    certificate = _list_certificates(client, job_id)["certificates"][1]  # Rohan

    response = client.get(certificate["download_url"])

    text = "".join(PdfReader(io.BytesIO(response.content)).pages[0].extract_text().split())
    assert "RohanMehta" in text
    assert certificate["certificate_id"].replace(" ", "") in text


def test_unknown_certificate_id_returns_404(client):
    response = client.get("/api/v1/certificates/unknown-id/download")
    assert response.status_code == 404
    assert response.json() == {"detail": "Certificate not found"}


def test_path_traversal_attempt_returns_404(client):
    response = client.get("/api/v1/certificates/..%2F..%2Fetc%2Fpasswd/download")
    assert response.status_code == 404


def test_missing_file_returns_404(client, create_job, cert_dir, valid_recipients):
    job_id = create_job(valid_recipients[:1])["job_id"]
    certificate = _list_certificates(client, job_id)["certificates"][0]
    (cert_dir / f"{certificate['certificate_id']}.pdf").unlink()  # delete the PDF from disk

    response = client.get(certificate["download_url"])

    assert response.status_code == 404
    assert "missing" in response.json()["detail"]


def test_certificate_that_did_not_complete_is_not_served(
    client, create_job, db_session_factory, valid_recipients
):
    job_id = create_job(valid_recipients[:1])["job_id"]
    certificate = _list_certificates(client, job_id)["certificates"][0]

    # Force an inconsistent row: the PDF exists on disk, but the recipient is marked FAILED.
    with db_session_factory() as db:
        db.execute(
            update(CertificateRecipient)
            .where(CertificateRecipient.certificate_id == certificate["certificate_id"])
            .values(status="FAILED", error_message="Simulated failure")
        )
        db.commit()

    response = client.get(certificate["download_url"])

    assert response.status_code == 409


def test_a_file_outside_the_storage_folder_is_never_served(
    client, create_job, db_session_factory, tmp_path, valid_recipients
):
    secret = tmp_path / "secret.pdf"  # outside the certificate folder (tmp_path/certificates)
    secret.write_bytes(b"%PDF-top-secret")
    job_id = create_job(valid_recipients[:1])["job_id"]
    certificate = _list_certificates(client, job_id)["certificates"][0]

    with db_session_factory() as db:
        db.execute(
            update(CertificateRecipient)
            .where(CertificateRecipient.certificate_id == certificate["certificate_id"])
            .values(certificate_path=str(secret))
        )
        db.commit()

    response = client.get(certificate["download_url"])

    assert response.status_code == 404
    assert b"top-secret" not in response.content
