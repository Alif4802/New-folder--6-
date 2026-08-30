import io
from pathlib import Path
import pytest
from fastapi import UploadFile, HTTPException
from app.services.pdf.validator import stream_and_stage_upload, validate_staged_pdf
from tests.utils import create_synthetic_english_today_pdf


@pytest.mark.asyncio
async def test_stream_and_stage_valid_pdf():
    pdf_bytes = create_synthetic_english_today_pdf()
    file = UploadFile(filename="english_today.pdf", file=io.BytesIO(pdf_bytes))

    staging_path, checksum, total_bytes = await stream_and_stage_upload(file)
    assert staging_path.exists()
    assert len(checksum) == 64
    assert total_bytes == len(pdf_bytes)

    # Validate PDF structure
    page_count = validate_staged_pdf(staging_path)
    assert page_count == 3

    # Clean up
    staging_path.unlink()


@pytest.mark.asyncio
async def test_stream_and_stage_empty_file():
    file = UploadFile(filename="empty.pdf", file=io.BytesIO(b""))
    with pytest.raises(HTTPException) as exc_info:
        await stream_and_stage_upload(file)
    assert exc_info.value.status_code == 400


@pytest.mark.asyncio
async def test_validate_non_pdf_file(tmp_path: Path):
    bad_file = tmp_path / "bad.pdf"
    bad_file.write_bytes(b"This is not a PDF file header.")

    with pytest.raises(HTTPException) as exc_info:
        validate_staged_pdf(bad_file)
    assert exc_info.value.status_code == 400
    assert "INVALID_PDF" in str(exc_info.value.detail)
