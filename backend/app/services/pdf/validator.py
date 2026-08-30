import hashlib
import uuid
import logging
from pathlib import Path
from typing import Tuple
from fastapi import UploadFile, HTTPException, status
import pymupdf
from app.core.config import settings

logger = logging.getLogger("nctb.pdf.validator")

CHUNK_SIZE = 64 * 1024  # 64 KB chunks for memory-safe streaming


async def stream_and_stage_upload(file: UploadFile) -> Tuple[Path, str, int]:
    """
    Stream uploaded file in chunks to a temporary staging file while computing
    its SHA-256 checksum and total byte size simultaneously without loading
    the full file into RAM.
    """
    staging_id = str(uuid.uuid4())
    staging_file = settings.storage_staging_dir / f"{staging_id}.tmp.pdf"
    hasher = hashlib.sha256()
    total_bytes = 0

    try:
        with open(staging_file, "wb") as f_out:
            while chunk := await file.read(CHUNK_SIZE):
                total_bytes += len(chunk)
                if total_bytes > settings.max_upload_size_bytes:
                    raise HTTPException(
                        status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
                        detail={
                            "error_code": "FILE_TOO_LARGE",
                            "message": f"File size exceeds maximum allowed limit of {settings.MAX_UPLOAD_SIZE_MB}MB.",
                        },
                    )
                hasher.update(chunk)
                f_out.write(chunk)

        if total_bytes == 0:
            if staging_file.exists():
                staging_file.unlink()
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail={
                    "error_code": "INVALID_PDF",
                    "message": "Uploaded file is empty.",
                },
            )

        checksum = hasher.hexdigest()
        return staging_file, checksum, total_bytes

    except HTTPException:
        if staging_file.exists():
            staging_file.unlink()
        raise
    except Exception as exc:
        if staging_file.exists():
            staging_file.unlink()
        logger.error(f"Failed to stream and stage upload: {exc}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail={
                "error_code": "UPLOAD_STAGE_FAILED",
                "message": f"Failed to stage uploaded file: {str(exc)}",
            },
        )


def validate_staged_pdf(staging_file: Path) -> int:
    """
    Validate that the staged file is a non-corrupt, non-encrypted PDF with at least 1 page.
    Returns the total page count.
    """
    # 1. Check magic header bytes
    try:
        with open(staging_file, "rb") as f:
            header = f.read(5)
            if not header.startswith(b"%PDF-"):
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail={
                        "error_code": "INVALID_PDF",
                        "message": "Supplied file is not a valid PDF document (missing %PDF- header).",
                    },
                )
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={
                "error_code": "INVALID_PDF",
                "message": f"Could not read file header: {str(exc)}",
            },
        )

    # 2. Validate with PyMuPDF
    try:
        doc = pymupdf.open(str(staging_file))
        page_count = doc.page_count
        is_encrypted = doc.is_encrypted

        if is_encrypted:
            doc.close()
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail={
                    "error_code": "INVALID_PDF",
                    "message": "Password-protected or encrypted PDFs are not supported.",
                },
            )

        if page_count < 1:
            doc.close()
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail={
                    "error_code": "INVALID_PDF",
                    "message": "PDF document contains 0 pages.",
                },
            )

        doc.close()
        return page_count

    except HTTPException:
        raise
    except Exception as exc:
        logger.error(f"PyMuPDF validation failed: {exc}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={
                "error_code": "INVALID_PDF",
                "message": f"PDF is damaged, unreadable, or corrupt: {str(exc)}",
            },
        )
