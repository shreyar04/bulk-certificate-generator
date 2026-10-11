"""Recipient-level validation.

This is deliberately separate from the Pydantic request schema:

* The schema checks the SHAPE of the whole request. A broken shape is a 422 for the
  entire request.
* validate_recipient() checks ONE recipient's data. A bad recipient is recorded as
  FAILED, and the other recipients are still processed.
"""

import re
from typing import Any

MAX_NAME_LENGTH = 70  # longer names would not fit on the certificate
MAX_EMAIL_LENGTH = 254  # the practical maximum for an email address
MAX_COURSE_LENGTH = 150

# A simple, readable check: something@something.tld (no spaces).
# Real-world email validation is much harder; this is enough for the assignment.
EMAIL_PATTERN = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


def validate_recipient(name: Any, email: Any, course_name: Any = None) -> list[str]:
    """Return a list of human-readable problems. An empty list means the recipient is valid."""
    errors: list[str] = []
    errors += _text_errors("name", name, required=True, max_length=MAX_NAME_LENGTH, must_render=True)
    errors += _email_errors(email)
    errors += _text_errors(
        "course_name", course_name, required=False, max_length=MAX_COURSE_LENGTH, must_render=True
    )
    return errors


def _text_errors(field: str, value: Any, *, required: bool, max_length: int, must_render: bool) -> list[str]:
    if value is None:
        return [f"{field} is required"] if required else []
    if not isinstance(value, str):
        return [f"{field} must be text"]

    text = value.strip()
    if not text:
        return [f"{field} is required"] if required else []
    if len(text) > max_length:
        return [f"{field} must be at most {max_length} characters"]
    if not text.isprintable():
        return [f"{field} contains control characters"]
    if must_render and not _can_render(text):
        return [f"{field} contains characters the certificate font cannot display"]
    return []


def _email_errors(value: Any) -> list[str]:
    if value is None:
        return ["email is required"]
    if not isinstance(value, str):
        return ["email must be text"]
    text = value.strip()
    if not text:
        return ["email is required"]
    if len(text) > MAX_EMAIL_LENGTH or not EMAIL_PATTERN.match(text):
        return ["email is not a valid email address"]
    return []


def _can_render(text: str) -> bool:
    """The built-in PDF fonts only support Western European characters (Windows-1252).

    ReportLab does not raise an error for other characters: it silently prints garbage.
    Rejecting them up front gives the user a clear message instead of a broken certificate.
    """
    try:
        text.encode("cp1252")
    except UnicodeEncodeError:
        return False
    return True
