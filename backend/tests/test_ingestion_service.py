import io
import pytest
from fastapi import UploadFile, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from app.models.textbook import SubjectVersion
from app.services.ingestion import IngestionService
from tests.utils import create_synthetic_english_today_pdf


@pytest.mark.asyncio
async def test_ingestion_service_end_to_end(db_session: AsyncSession):
    pdf_bytes = create_synthetic_english_today_pdf()
    file = UploadFile(filename="English_For_Today_Class_9.pdf", file=io.BytesIO(pdf_bytes))

    response = await IngestionService.ingest_pdf(file=file, session=db_session)

    assert response.ingestion_status in ["COMPLETED", "PARTIAL"]
    assert response.page_count == 3
    assert response.unit_count == 1
    assert response.lesson_count == 1
    assert response.activity_node_count >= 3
    assert response.detected_grade == "Class 9"
    assert response.detected_subject == "English for Today"

    # Check SubjectVersion in DB
    res = await db_session.execute(select(SubjectVersion).where(SubjectVersion.id == response.version_id))
    ver = res.scalar_one_or_none()
    assert ver is not None
    assert ver.title == "English for Today (Class 9)"

    # Attempt duplicate upload -> should raise 409
    dup_file = UploadFile(filename="English_For_Today_Class_9_Copy.pdf", file=io.BytesIO(pdf_bytes))
    with pytest.raises(HTTPException) as exc_info:
        await IngestionService.ingest_pdf(file=dup_file, session=db_session)
    assert exc_info.value.status_code == 409
    assert "DUPLICATE_PDF" in str(exc_info.value.detail)
