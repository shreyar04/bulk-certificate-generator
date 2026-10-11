"""Certificate PDF generation with ReportLab.

The only public function is generate_certificate(). It knows nothing about the
database or FastAPI: give it the details and an output path, and it writes a PDF.
"""

import logging
import os
from datetime import date
from pathlib import Path

from reportlab.lib.colors import HexColor, white
from reportlab.lib.pagesizes import A4, landscape
from reportlab.lib.utils import simpleSplit
from reportlab.pdfbase.pdfmetrics import stringWidth
from reportlab.pdfgen.canvas import Canvas

logger = logging.getLogger(__name__)

PAGE_WIDTH, PAGE_HEIGHT = landscape(A4)  # about 842 x 595 points

NAVY = HexColor("#1F3A5F")
GOLD = HexColor("#B8963E")
INK = HexColor("#222222")
GREY = HexColor("#555555")
PAPER = HexColor("#FFFDF7")

STATEMENT = (
    "in recognition of outstanding dedication, effort, and the "
    "successful completion of all requirements."
)


class CertificateGenerationError(Exception):
    """Raised when a PDF could not be created. The message is safe to show to API clients."""


def format_issue_date(issue_date: date) -> str:
    """Return e.g. '11 October 2026' (no platform-specific strftime flags)."""
    return f"{issue_date.day} {issue_date.strftime('%B %Y')}"


def generate_certificate(
    *,
    recipient_name: str,
    event_name: str,
    issue_date: date,
    certificate_id: str,
    output_path: Path,
) -> Path:
    """Create one certificate PDF at output_path and return that path.

    The PDF is first written to a temporary file and then renamed, so a crash in the
    middle never leaves a half-written certificate behind.
    """
    output_path = Path(output_path)
    temp_path = output_path.with_name(output_path.name + ".tmp")
    try:
        output_path.parent.mkdir(parents=True, exist_ok=True)
        _draw_certificate(temp_path, recipient_name, event_name, issue_date, certificate_id)
        os.replace(temp_path, output_path)  # atomic rename
    except Exception as exc:
        temp_path.unlink(missing_ok=True)
        # Keep the real error in the server log; give the client a safe, short message.
        logger.exception("Could not render certificate %s", certificate_id)
        raise CertificateGenerationError(
            f"Could not create the certificate PDF ({type(exc).__name__})"
        ) from exc
    return output_path


# --------------------------------------------------------------------------- drawing


def _draw_certificate(
    path: Path, recipient_name: str, event_name: str, issue_date: date, certificate_id: str
) -> None:
    w, h = PAGE_WIDTH, PAGE_HEIGHT
    cx = w / 2
    c = Canvas(str(path), pagesize=(w, h))
    c.setTitle(f"Certificate - {recipient_name}")
    c.setAuthor("Bulk Certificate Generator")
    c.setSubject(event_name)

    _draw_background_and_borders(c, w, h)

    # Heading
    c.setFillColor(NAVY)
    _centered_spaced(c, "CERTIFICATE", cx, h - 120, "Times-Bold", 50, spacing=6)
    c.setFillColor(GOLD)
    _centered_spaced(c, "OF COMPLETION", cx, h - 148, "Helvetica", 15, spacing=5)
    _divider(c, cx, h - 172)

    # Body
    c.setFillColor(GREY)
    c.setFont("Times-Italic", 17)
    c.drawCentredString(cx, h - 212, "This is to certify that")

    name_size = _fit_font_size(recipient_name, "Times-BoldItalic", 42, 640, minimum=18)
    c.setFillColor(NAVY)
    c.setFont("Times-BoldItalic", name_size)
    c.drawCentredString(cx, h - 266, recipient_name)
    c.setStrokeColor(GOLD)
    c.setLineWidth(0.8)
    c.line(cx - 250, h - 280, cx + 250, h - 280)

    c.setFillColor(GREY)
    c.setFont("Times-Roman", 17)
    c.drawCentredString(cx, h - 310, "has successfully completed")

    _draw_event_name(c, event_name, cx, h - 348)

    c.setFillColor(GREY)
    c.setFont("Times-Italic", 13)
    c.drawCentredString(cx, 172, STATEMENT)

    _draw_footer(c, cx, issue_date, certificate_id)

    c.showPage()
    c.save()


def _draw_background_and_borders(c: Canvas, w: float, h: float) -> None:
    c.setFillColor(PAPER)
    c.rect(0, 0, w, h, stroke=0, fill=1)

    c.setStrokeColor(NAVY)
    c.setLineWidth(4)
    c.rect(22, 22, w - 44, h - 44, stroke=1, fill=0)

    c.setStrokeColor(GOLD)
    c.setLineWidth(1.2)
    c.rect(34, 34, w - 68, h - 68, stroke=1, fill=0)

    # Small gold squares on the corners of the inner border.
    c.setFillColor(GOLD)
    for x, y in ((34, 34), (w - 34, 34), (34, h - 34), (w - 34, h - 34)):
        c.rect(x - 5, y - 5, 10, 10, stroke=0, fill=1)


def _divider(c: Canvas, cx: float, y: float) -> None:
    c.setStrokeColor(GOLD)
    c.setLineWidth(1.2)
    c.line(cx - 110, y, cx - 12, y)
    c.line(cx + 12, y, cx + 110, y)
    c.setFillColor(GOLD)
    p = c.beginPath()
    p.moveTo(cx, y + 6)
    p.lineTo(cx + 6, y)
    p.lineTo(cx, y - 6)
    p.lineTo(cx - 6, y)
    p.close()
    c.drawPath(p, stroke=0, fill=1)


def _draw_event_name(c: Canvas, event_name: str, cx: float, y: float) -> None:
    """Draw the event/course name, wrapping to at most two lines (shrinking if needed)."""
    font, size, max_width = "Helvetica-Bold", 24, 620
    lines = simpleSplit(event_name, font, size, max_width)
    while len(lines) > 2 and size > 12:
        size -= 1
        lines = simpleSplit(event_name, font, size, max_width)
    c.setFillColor(INK)
    c.setFont(font, size)
    for index, line in enumerate(lines[:2]):
        c.drawCentredString(cx, y - index * size * 1.25, line)


def _draw_footer(c: Canvas, cx: float, issue_date: date, certificate_id: str) -> None:
    left_x, right_x = PAGE_WIDTH * 0.25, PAGE_WIDTH * 0.75

    c.setStrokeColor(GOLD)
    c.setLineWidth(1)
    for x in (left_x, right_x):
        c.line(x - 130, 100, x + 130, 100)

    c.setFillColor(INK)
    c.setFont("Helvetica-Bold", 13)
    c.drawCentredString(left_x, 108, format_issue_date(issue_date))
    c.setFont("Helvetica", 10)
    c.drawCentredString(right_x, 108, certificate_id)

    c.setFillColor(GOLD)
    c.setFont("Helvetica", 9)
    c.drawCentredString(left_x, 86, "DATE OF ISSUE")
    c.drawCentredString(right_x, 86, "CERTIFICATE ID")

    # Seal in the middle: gold disc, white ring, navy disc and a white check mark.
    seal_y = 105
    c.setFillColor(GOLD)
    c.circle(cx, seal_y, 32, stroke=0, fill=1)
    c.setStrokeColor(white)
    c.setLineWidth(1.5)
    c.circle(cx, seal_y, 27, stroke=1, fill=0)
    c.setFillColor(NAVY)
    c.circle(cx, seal_y, 22, stroke=0, fill=1)
    c.setStrokeColor(white)
    c.setLineWidth(3)
    check = c.beginPath()
    check.moveTo(cx - 9, seal_y - 1)
    check.lineTo(cx - 3, seal_y - 8)
    check.lineTo(cx + 10, seal_y + 8)
    c.drawPath(check, stroke=1, fill=0)


# --------------------------------------------------------------------------- helpers


def _fit_font_size(text: str, font: str, start: float, max_width: float, minimum: float) -> float:
    """Shrink the font size until the text fits in max_width (never below minimum)."""
    size = start
    while size > minimum and stringWidth(text, font, size) > max_width:
        size -= 1
    return size


def _centered_spaced(
    c: Canvas, text: str, cx: float, y: float, font: str, size: float, spacing: float
) -> None:
    """Draw centred text with extra space between letters (looks more elegant for headings)."""
    width = stringWidth(text, font, size) + spacing * (len(text) - 1)
    t = c.beginText(cx - width / 2, y)
    t.setFont(font, size)
    t.setCharSpace(spacing)
    t.textOut(text)
    # In PDF, character spacing stays switched on until it is reset. Without this line
    # ALL text drawn afterwards on the page would be stretched too.
    t.setCharSpace(0)
    c.drawText(t)
