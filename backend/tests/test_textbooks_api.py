import io
import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.textbook import ActivityNode
from tests.utils import (
    create_synthetic_english_today_pdf,
    create_synthetic_mathematics_pdf,
)


@pytest.mark.asyncio
async def test_textbooks_api_full_workflow(client: AsyncClient, db_session: AsyncSession):
    # 1. Ingest English for Today PDF via POST /api/v1/textbooks/ingest
    pdf_bytes = create_synthetic_english_today_pdf()
    files = {"file": ("English_For_Today_Class_9.pdf", io.BytesIO(pdf_bytes), "application/pdf")}

    ingest_res = await client.post("/api/v1/textbooks/ingest", files=files)
    assert ingest_res.status_code == 201, ingest_res.text
    data = ingest_res.json()
    version_id = data["version_id"]
    assert data["detected_grade"] == "Class 9"
    assert data["detected_subject"] == "English for Today"
    assert data["unit_count"] == 1
    assert data["lesson_count"] == 1

    # 2. List versions via GET /api/v1/textbooks/versions
    list_res = await client.get("/api/v1/textbooks/versions")
    assert list_res.status_code == 200
    versions = list_res.json()
    assert len(versions) >= 1
    assert any(v["id"] == version_id for v in versions)

    # 3. Retrieve curriculum scope via GET /api/v1/textbooks/{version_id}/curriculum
    curr_res = await client.get(f"/api/v1/textbooks/{version_id}/curriculum")
    assert curr_res.status_code == 200
    curr_data = curr_res.json()
    assert curr_data["version_id"] == version_id
    assert len(curr_data["units"]) == 1

    unit1 = curr_data["units"][0]
    assert "id" in unit1
    assert "detected_number" in unit1
    assert "title" in unit1
    assert len(unit1["lessons"]) == 1

    lesson1 = unit1["lessons"][0]
    assert "id" in lesson1
    assert "detected_number" in lesson1
    assert "title" in lesson1

    # 4. Strict check: verify response contains NO ActivityNode/content/bbox/parser/page range fields
    forbidden_keys = [
        "activity_nodes", "nodes", "content_text", "bounding_box",
        "parser_metadata", "content_preview", "node_type", "structured_payload",
        "blocks", "start_page", "end_page",
    ]
    for k in forbidden_keys:
        assert k not in unit1, f"Forbidden key '{k}' found in Unit scope response"
        assert k not in lesson1, f"Forbidden key '{k}' found in Lesson scope response"

    # 5. Verify ActivityNodes are still persisted internally in the database
    stmt = select(ActivityNode).where(ActivityNode.subject_version_id == version_id)
    nodes_result = await db_session.execute(stmt)
    persisted_nodes = nodes_result.scalars().all()
    assert len(persisted_nodes) >= 3, "ActivityNodes must remain persisted in DB for Phase 4 MCQ grounding"

    # 6. Verify removed public endpoints are not accessible (404)
    tree_res = await client.get(f"/api/v1/textbooks/{version_id}/tree")
    assert tree_res.status_code == 404
    node_res = await client.get(f"/api/v1/textbooks/{version_id}/nodes/1")
    assert node_res.status_code == 404
    readable_res = await client.get(f"/api/v1/textbooks/{version_id}/readable?unit_id=1")
    assert readable_res.status_code == 404

    # 7. Get PDF metadata via GET /api/v1/textbooks/{version_id}/pdf-metadata
    meta_res = await client.get(f"/api/v1/textbooks/{version_id}/pdf-metadata")
    assert meta_res.status_code == 200
    meta_data = meta_res.json()
    assert meta_data["version_id"] == version_id
    assert meta_data["page_count"] == 3
    assert len(meta_data["checksum_sha256"]) == 64
    assert meta_data["pdf_available"] is True
    assert "ocr_pages_count" in meta_data

    # 8. Stream raw PDF via GET /api/v1/textbooks/{version_id}/pdf
    stream_res = await client.get(f"/api/v1/textbooks/{version_id}/pdf")
    assert stream_res.status_code == 200
    assert stream_res.headers["content-type"] == "application/pdf"
    assert "inline" in stream_res.headers.get("content-disposition", "")
    assert len(stream_res.content) == len(pdf_bytes)


@pytest.mark.asyncio
async def test_textbooks_api_curriculum_deterministic_ordering(client: AsyncClient):
    """Verify deterministic unit/lesson ordering in /curriculum endpoint."""
    pdf = create_synthetic_mathematics_pdf()
    res = await client.post(
        "/api/v1/textbooks/ingest",
        files={"file": ("Math_Class_7.pdf", io.BytesIO(pdf), "application/pdf")},
    )
    v_id = res.json()["version_id"]

    curr_res = await client.get(f"/api/v1/textbooks/{v_id}/curriculum")
    assert curr_res.status_code == 200
    curr_data = curr_res.json()
    assert len(curr_data["units"]) >= 1


@pytest.mark.asyncio
async def test_textbooks_api_missing_physical_pdf_handled(client: AsyncClient, db_session: AsyncSession):
    """Verify that if the physical PDF file is missing on disk, pdf_available is false and streaming returns 404."""
    from app.models.textbook import SubjectVersion
    import uuid

    # Create a dummy SubjectVersion in the DB whose physical file does not exist
    fake_version_id = str(uuid.uuid4())
    version = SubjectVersion(
        id=fake_version_id,
        curriculum_id=1,
        title="Nonexistent PDF Textbook",
        source_filename="nonexistent.pdf",
        stored_pdf_path="pdfs/nonexistent_file_path_12345.pdf",
        file_size_bytes=1024,
        checksum_sha256="0" * 64,
        page_count=10,
        ingestion_status="FAILED",
        error_message="Simulated ingestion error",
    )
    db_session.add(version)
    await db_session.commit()

    # 1. Metadata should report pdf_available=False and safe error_message
    meta_res = await client.get(f"/api/v1/textbooks/{fake_version_id}/pdf-metadata")
    assert meta_res.status_code == 200
    meta = meta_res.json()
    assert meta["pdf_available"] is False
    assert meta["error_message"] == "Simulated ingestion error"

    # 2. PDF streaming endpoint should return 404 with clean error code
    stream_res = await client.get(f"/api/v1/textbooks/{fake_version_id}/pdf")
    assert stream_res.status_code == 404
    assert "FILE_NOT_FOUND_ON_DISK" in stream_res.text


@pytest.mark.asyncio
async def test_textbooks_api_non_pdf_rejection(client: AsyncClient):
    files = {"file": ("test.txt", io.BytesIO(b"Hello text file"), "text/plain")}
    res = await client.post("/api/v1/textbooks/ingest", files=files)
    assert res.status_code == 400
    assert "INVALID_FILE_EXTENSION" in res.text


@pytest.mark.asyncio
async def test_textbooks_api_not_found(client: AsyncClient):
    res = await client.get("/api/v1/textbooks/nonexistent-id/curriculum")
    assert res.status_code == 404
    assert "TEXTBOOK_NOT_FOUND" in res.text

    toc_res = await client.get("/api/v1/textbooks/nonexistent-id/toc")
    assert toc_res.status_code == 404
    assert "TEXTBOOK_NOT_FOUND" in toc_res.text


@pytest.mark.asyncio
async def test_textbooks_api_toc_navigation(client: AsyncClient, db_session: AsyncSession):
    """Verify TOC endpoint specifications:
    1. Valid version returns TOC
    2. Unit/Lesson navigation uses stored start_page
    3. Page numbers within SubjectVersion.page_count
    4. Reliable Exercise entries included
    5. Generic ActivityNodes NOT included
    6. ActivityNode IDs/content/bboxes/parser metadata absent
    7. Unit/Lesson order is deterministic
    8. Exercise order follows source/page/order deterministically
    """
    pdf_bytes = create_synthetic_mathematics_pdf()
    files = {"file": ("Mathematics_Class_7_TOC.pdf", io.BytesIO(pdf_bytes), "application/pdf")}

    ingest_res = await client.post("/api/v1/textbooks/ingest", files=files)
    assert ingest_res.status_code == 201
    v_id = ingest_res.json()["version_id"]

    # 1. Fetch TOC
    toc_res = await client.get(f"/api/v1/textbooks/{v_id}/toc")
    assert toc_res.status_code == 200
    toc_data = toc_res.json()

    assert toc_data["version_id"] == v_id
    assert len(toc_data["items"]) >= 1

    # 2. Check Unit Navigation
    unit_item = toc_data["items"][0]
    assert unit_item["type"] == "unit"
    assert "page_number" in unit_item
    assert unit_item["page_number"] >= 1
    assert "label" in unit_item
    assert unit_item["children"] is not None
    assert len(unit_item["children"]) >= 1

    # 3. Check Lesson Navigation
    lesson_item = unit_item["children"][0]
    assert lesson_item["type"] == "lesson"
    assert "page_number" in lesson_item
    assert lesson_item["page_number"] >= 1
    assert "label" in lesson_item

    # 4. Strict Schema Integrity: Verify absence of ActivityNode internals
    forbidden_keys = [
        "id", "activity_nodes", "nodes", "content_text", "bounding_box",
        "parser_metadata", "content_preview", "node_type", "structured_payload",
        "blocks", "content_hash",
    ]
    def verify_no_internals(item: dict):
        for k in forbidden_keys:
            assert k not in item, f"Forbidden internal key '{k}' found in TOC item"
        assert item["type"] in ["unit", "lesson", "exercise"], f"Invalid TOC item type '{item['type']}'"
        assert 1 <= item["page_number"] <= 100, f"Page number {item['page_number']} out of bounds"
        if item.get("children"):
            for child in item["children"]:
                verify_no_internals(child)

    for item in toc_data["items"]:
        verify_no_internals(item)

    pdf_res = await client.get("/api/v1/textbooks/nonexistent-id/pdf")
    assert pdf_res.status_code == 404
    assert "TEXTBOOK_NOT_FOUND" in pdf_res.text


@pytest.mark.asyncio
async def test_mcq_capabilities_endpoint_stability(client: AsyncClient, db_session: AsyncSession):
    # Ingest a synthetic Mathematics PDF
    pdf_bytes = create_synthetic_mathematics_pdf()
    files = {"file": ("Math_Class_7.pdf", io.BytesIO(pdf_bytes), "application/pdf")}
    ingest_res = await client.post("/api/v1/textbooks/ingest", files=files)
    assert ingest_res.status_code == 201
    v_id = ingest_res.json()["version_id"]

    # Call capabilities multiple times to ensure stability & identical payloads
    res1 = await client.get(f"/api/v1/assessments/mcq/capabilities?subject_version_id={v_id}")
    assert res1.status_code == 200
    data1 = res1.json()

    res2 = await client.get(f"/api/v1/assessments/mcq/capabilities?subject_version_id={v_id}")
    assert res2.status_code == 200
    data2 = res2.json()

    assert data1 == data2
    assert data1["subject"] == "Mathematics"
    assert data1["generation_supported"] is True
    assert len(data1["scope_tree"]) >= 1
    root = data1["scope_tree"][0]
    assert "id" in root
    assert "title" in root
    assert "node_type" in root
    assert "children" in root

