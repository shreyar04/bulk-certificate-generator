"""Endpoint that downloads one generated certificate PDF."""

import logging
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import FileResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from app import config
from app.database import get_db
from app.models import CertificateRecipient, RecipientStatus

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/certificates", tags=["Certificates"])


@router.get("/{certificate_id}/download")
def download_certificate(certificate_id: str, db: Session = Depends(get_db)) -> FileResponse:
    """Return the PDF for one certificate.

    Security: the client only supplies a certificate ID. We use it as a DATABASE lookup
    key; the file location always comes from our own database row, never from the request.
    """
    recipient = db.scalar(
        select(CertificateRecipient).where(CertificateRecipient.certificate_id == certificate_id)
    )
    if recipient is None:
        raise HTTPException(status_code=404, detail="Certificate not found")

    # Defensive: a certificate that did not finish generating must not be served.
    if recipient.status != RecipientStatus.COMPLETED.value or not recipient.certificate_path:
        raise HTTPException(status_code=409, detail="Certificate is not available (generation did not complete)")

    file_path = Path(recipient.certificate_path).resolve()
    storage_root = config.CERTIFICATE_DIR.resolve()

    # Defence in depth: only ever serve files that live inside the certificate folder.
    if not file_path.is_relative_to(storage_root):
        logger.warning("Certificate %s points outside the storage folder; refusing to serve it", certificate_id)
        raise HTTPException(status_code=404, detail="Certificate file not found")

    if not file_path.is_file():
        logger.error("Certificate file for %s is missing from disk", certificate_id)
        raise HTTPException(status_code=404, detail="Certificate file is missing from storage")

    return FileResponse(
        path=file_path,
        media_type="application/pdf",
        filename=f"certificate-{certificate_id}.pdf",
    )
