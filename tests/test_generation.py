"""PDF generation: the generator function on its own, and through the whole API."""

from datetime import date

import pytest
from pypdf import PdfReader

from app.services import generator
from app.services.generator import CertificateGenerationError, format_issue_date, generate_certificate


def _pdf_text(path) -> str:
    """All text of page 1 with whitespace removed (so spaced-out headings still match)."""
    text = PdfReader(str(path)).pages[0].extract_text()
    return "".join(text.split())


def _squash(text: str) -> str:
    return "".join(text.split())


# --------------------------------------------------------------------------- generator only


def test_generate_certificate_creates_a_landscape_pdf_with_the_right_details(tmp_path):
    output = tmp_path / "new-folder" / "cert.pdf"  # the folder does not exist yet

    result = generate_certificate(
        recipient_name="Asha Verma",
        event_name="Advanced Python Bootcamp",
        issue_date=date(2026, 10, 11),
        certificate_id="abc-123",
        output_path=output,
    )

    assert result == output
    assert output.read_bytes().startswith(b"%PDF")

    reader = PdfReader(str(output))
    assert len(reader.pages) == 1
    page = reader.pages[0]
    assert page.mediabox.width > page.mediabox.height  # landscape

    text = _pdf_text(output)
    for expected in (
        "CERTIFICATE",
        "Asha Verma",
        "Advanced Python Bootcamp",
        "11 October 2026",
        "abc-123",
        "successfully completed",
    ):
        assert _squash(expected) in text, expected


def test_no_temporary_file_is_left_behind(tmp_path):
    generate_certificate(
        recipient_name="Asha Verma",
        event_name="Course",
        issue_date=date(2026, 1, 1),
        certificate_id="id-1",
        output_path=tmp_path / "cert.pdf",
    )
    assert [p.name for p in tmp_path.iterdir()] == ["cert.pdf"]


def test_very_long_name_and_event_still_generate(tmp_path):
    long_name = "Maximilian Alexander Montgomery-Fitzgerald " * 1
    long_event = "Distributed Systems and Cloud Architecture " * 3
    output = tmp_path / "long.pdf"

    generate_certificate(
        recipient_name=long_name.strip(),
        event_name=long_event.strip(),
        issue_date=date(2026, 1, 1),
        certificate_id="id-2",
        output_path=output,
    )

    assert _squash(long_name) in _pdf_text(output)


def test_format_issue_date():
    assert format_issue_date(date(2026, 1, 5)) == "5 January 2026"
    assert format_issue_date(date(2026, 12, 31)) == "31 December 2026"


def test_rendering_error_gives_a_safe_message_and_leaves_no_file(tmp_path, monkeypatch):
    def broken_draw(path, *args):
        path.write_bytes(b"half written")  # simulate a crash in the middle of writing
        raise OSError("disk exploded at /very/secret/path")

    monkeypatch.setattr(generator, "_draw_certificate", broken_draw)

    with pytest.raises(CertificateGenerationError) as error:
        generate_certificate(
            recipient_name="Asha",
            event_name="Course",
            issue_date=date(2026, 1, 1),
            certificate_id="id-3",
            output_path=tmp_path / "cert.pdf",
        )

    assert "/very/secret/path" not in str(error.value)
    assert "OSError" in str(error.value)
    assert list(tmp_path.iterdir()) == []  # neither the PDF nor the .tmp file


# --------------------------------------------------------------------------- through the API


def test_job_creates_one_pdf_per_recipient(create_job, get_job, cert_dir, valid_recipients):
    job = get_job(create_job(valid_recipients)["job_id"])

    ids = [r["certificate_id"] for r in job["recipients"]]
    assert len(set(ids)) == 3  # every certificate ID is unique
    assert sorted(p.name for p in cert_dir.glob("*.pdf")) == sorted(f"{i}.pdf" for i in ids)


def test_each_pdf_contains_its_own_recipient_details(create_job, get_job, cert_dir, valid_recipients):
    job = get_job(create_job(valid_recipients)["job_id"])

    for recipient in job["recipients"]:
        text = _pdf_text(cert_dir / f"{recipient['certificate_id']}.pdf")
        expected_event = recipient["course_name"] or "Advanced Python Bootcamp"
        assert _squash(recipient["name"]) in text
        assert _squash(expected_event) in text  # the per-recipient course_name overrides the job's
        assert _squash(recipient["certificate_id"]) in text
        assert "11October2026" in text
