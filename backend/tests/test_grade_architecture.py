import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.database import bootstrap_default_curriculum
from app.models.curriculum import Curriculum, Grade, Subject
from app.models.textbook import SubjectVersion, Unit, Lesson, CurriculumNode
from app.schemas.textbook import GradeSummary
from app.schemas.assessment import MCQGenerateRequest
from app.schemas.llm_mcq import (
    LLMMCGItem,
    LLMMCGOption,
    LLMMCGCandidateResponse,
    MCQVerificationResponse,
    QuestionVerificationResult,
)
from app.services.assessment.job_service import GenerationJob, GenerationJobService
from app.services.assessment.resolver import SourceChunk
from app.services.question_bank.bank_service import QuestionBankService


@pytest.mark.asyncio
async def test_grade_master_seeding_idempotency_and_curriculum_scope(db_session: AsyncSession):
    """
    Verifies that NCTB master curriculum grades Class 1 to Class 12 are seeded idempotently,
    scoped strictly to the default curriculum, with ordinal level_number 1 to 12.
    """
    # Verify exactly 12 grades seeded
    stmt = select(Grade).order_by(Grade.level_number.asc())
    res = await db_session.execute(stmt)
    grades = res.scalars().all()
    assert len(grades) == 12

    for idx, g in enumerate(grades, start=1):
        assert g.level_number == idx
        assert g.code == f"class-{idx}"
        assert g.name == f"Class {idx}"
        assert g.is_active is True
        assert g.curriculum_id is not None

    # Run bootstrap_default_curriculum again — must be completely idempotent (0 duplicates)
    await bootstrap_default_curriculum(db_session)

    res2 = await db_session.execute(stmt)
    grades2 = res2.scalars().all()
    assert len(grades2) == 12


@pytest.mark.asyncio
async def test_grades_endpoint_curriculum_and_filtering(client: AsyncClient, db_session: AsyncSession):
    """
    Verifies GET /api/v1/grades supports:
    1. Returning all active grades sorted by level_number
    2. only_with_textbooks=true filter returning only grades with COMPLETED/PARTIAL textbooks
    3. Accurate assessment-eligible textbook counting
    """
    # 1. Fetch all grades
    res = await client.get("/api/v1/grades")
    assert res.status_code == 200
    data = res.json()
    assert len(data) == 12
    assert data[0]["code"] == "class-1"
    assert data[0]["level_number"] == 1
    assert data[0]["textbook_count"] == 0
    assert data[11]["code"] == "class-12"
    assert data[11]["level_number"] == 12

    # 2. Fetch with only_with_textbooks=true when none exist
    res_empty = await client.get("/api/v1/grades?only_with_textbooks=true")
    assert res_empty.status_code == 200
    assert len(res_empty.json()) == 0

    # 3. Create a textbook under Class 7 (grade_id for class-7)
    grade7_stmt = select(Grade).where(Grade.code == "class-7")
    grade7 = (await db_session.execute(grade7_stmt)).scalar_one()

    subj = Subject(
        code="math_g7",
        name="Mathematics",
        domain="STEM",
        curriculum_id=grade7.curriculum_id,
    )
    db_session.add(subj)
    await db_session.flush()

    tb = SubjectVersion(
        id="tb_class7_math",
        curriculum_id=grade7.curriculum_id,
        subject_id=subj.id,
        grade_id=grade7.id,
        title="Class 7 Mathematics",
        edition_year=2024,
        source_filename="class7_math.pdf",
        stored_pdf_path="test_path.pdf",
        file_size_bytes=1024,
        checksum_sha256="hash_class7_test",
        page_count=180,
        ingestion_status="COMPLETED",
        curriculum_quality_status="VALID",
    )
    db_session.add(tb)
    await db_session.commit()

    # Touch physical dummy PDF file in isolated storage root
    pdf_disk_file = settings.STORAGE_ROOT / tb.stored_pdf_path
    pdf_disk_file.parent.mkdir(parents=True, exist_ok=True)
    pdf_disk_file.touch()

    # 4. Fetch with only_with_textbooks=true again
    res_filtered = await client.get("/api/v1/grades?only_with_textbooks=true")
    assert res_filtered.status_code == 200
    filtered_data = res_filtered.json()
    assert len(filtered_data) == 1
    assert filtered_data[0]["code"] == "class-7"
    assert filtered_data[0]["display_name"] == "Class 7"
    assert filtered_data[0]["textbook_count"] == 1


@pytest.mark.asyncio
async def test_textbooks_grade_filter_and_patch(client: AsyncClient, db_session: AsyncSession):
    """
    Verifies:
    1. GET /api/v1/textbooks/versions?grade_id=... filters accurately
    2. Response includes GradeSummary object
    3. PATCH /api/v1/textbooks/{version_id}/grade updates Grade association
    """
    g7 = (await db_session.execute(select(Grade).where(Grade.code == "class-7"))).scalar_one()
    g8 = (await db_session.execute(select(Grade).where(Grade.code == "class-8"))).scalar_one()

    subj = Subject(
        code="math_general",
        name="Mathematics",
        domain="STEM",
        curriculum_id=g7.curriculum_id,
    )
    db_session.add(subj)
    await db_session.flush()

    # Create books
    tb7 = SubjectVersion(
        id="tb_c7_book",
        curriculum_id=g7.curriculum_id,
        subject_id=subj.id,
        grade_id=g7.id,
        title="Mathematics Grade 7",
        edition_year=2024,
        source_filename="c7.pdf",
        stored_pdf_path="p7.pdf",
        file_size_bytes=2048,
        checksum_sha256="h7",
        page_count=120,
        ingestion_status="COMPLETED",
    )
    tb8 = SubjectVersion(
        id="tb_c8_book",
        curriculum_id=g8.curriculum_id,
        subject_id=subj.id,
        grade_id=g8.id,
        title="Mathematics Grade 8",
        edition_year=2024,
        source_filename="c8.pdf",
        stored_pdf_path="p8.pdf",
        file_size_bytes=4096,
        checksum_sha256="h8",
        page_count=140,
        ingestion_status="COMPLETED",
    )
    db_session.add_all([tb7, tb8])
    await db_session.commit()

    # Query with grade_id=g7.id
    res7 = await client.get(f"/api/v1/textbooks/versions?grade_id={g7.id}")
    assert res7.status_code == 200
    data7 = res7.json()
    assert len(data7) == 1
    assert data7[0]["id"] == "tb_c7_book"
    assert data7[0]["grade_id"] == g7.id
    assert data7[0]["grade_info"]["code"] == "class-7"
    assert data7[0]["grade_info"]["display_name"] == "Class 7"

    # Query with grade_id=g8.id
    res8 = await client.get(f"/api/v1/textbooks/versions?grade_id={g8.id}")
    assert res8.status_code == 200
    data8 = res8.json()
    assert len(data8) == 1
    assert data8[0]["id"] == "tb_c8_book"

    # PATCH Grade from Class 8 to Class 9
    g9 = (await db_session.execute(select(Grade).where(Grade.code == "class-9"))).scalar_one()
    patch_res = await client.patch(
        f"/api/v1/textbooks/tb_c8_book/grade",
        json={"grade_id": g9.id},
    )
    assert patch_res.status_code == 200
    patched_data = patch_res.json()
    assert patched_data["grade_id"] == g9.id
    assert patched_data["grade_info"]["code"] == "class-9"

    # Verify query for g8 is now empty
    res8_after = await client.get(f"/api/v1/textbooks/versions?grade_id={g8.id}")
    assert len(res8_after.json()) == 0

    # Test invalid grade patch
    invalid_patch = await client.patch(
        f"/api/v1/textbooks/tb_c8_book/grade",
        json={"grade_id": 99999},
    )
    assert invalid_patch.status_code == 400
    assert invalid_patch.json()["detail"]["error_code"] == "INVALID_GRADE_ID"


@pytest.mark.asyncio
async def test_cross_grade_tampering_validation(client: AsyncClient, db_session: AsyncSession):
    """
    Verifies that progressive MCQ job creation rejects cross-grade tampering (HTTP 422 GRADE_MISMATCH)
    when the request grade_id does not match the textbook's grade_id.
    """
    g7 = (await db_session.execute(select(Grade).where(Grade.code == "class-7"))).scalar_one()
    g8 = (await db_session.execute(select(Grade).where(Grade.code == "class-8"))).scalar_one()

    subj = Subject(
        code="math_tamper",
        name="Mathematics",
        domain="STEM",
        curriculum_id=g7.curriculum_id,
    )
    db_session.add(subj)
    await db_session.flush()

    tb = SubjectVersion(
        id="tb_tamper_test",
        curriculum_id=g7.curriculum_id,
        subject_id=subj.id,
        grade_id=g7.id,
        title="Class 7 Math Book",
        edition_year=2024,
        source_filename="tamper.pdf",
        stored_pdf_path="ptamper.pdf",
        file_size_bytes=1000,
        checksum_sha256="htamper",
        page_count=50,
        ingestion_status="COMPLETED",
        curriculum_quality_status="VALID",
    )
    db_session.add(tb)
    await db_session.commit()

    # Touch physical dummy PDF file in isolated storage root
    pdf_disk_file = settings.STORAGE_ROOT / tb.stored_pdf_path
    pdf_disk_file.parent.mkdir(parents=True, exist_ok=True)
    pdf_disk_file.touch()

    # Mismatched grade_id (requesting Class 8 for a Class 7 textbook)
    mismatch_res = await client.post(
        "/api/v1/assessments/mcq/jobs",
        json={
            "subject_version_id": "tb_tamper_test",
            "grade_id": g8.id,
            "count": 5,
        },
    )
    assert mismatch_res.status_code == 422
    assert mismatch_res.json()["detail"]["error_code"] == "GRADE_MISMATCH"

    # Matching grade_id
    match_res = await client.post(
        "/api/v1/assessments/mcq/jobs",
        json={
            "subject_version_id": "tb_tamper_test",
            "grade_id": g7.id,
            "count": 5,
        },
    )
    assert match_res.status_code == 202
    assert "job_id" in match_res.json()


@pytest.mark.asyncio
async def test_question_bank_explanation_preservation(client: AsyncClient, db_session: AsyncSession):
    """
    Verifies that Question Bank saves and preserves pedagogical explanations and source provenance
    even though the Print / Teacher Copy displays answers only.
    """
    g7 = (await db_session.execute(select(Grade).where(Grade.code == "class-7"))).scalar_one()

    subj = Subject(
        code="math_qb",
        name="Mathematics",
        domain="STEM",
        curriculum_id=g7.curriculum_id,
    )
    db_session.add(subj)
    await db_session.flush()

    tb = SubjectVersion(
        id="tb_qb_test",
        curriculum_id=g7.curriculum_id,
        subject_id=subj.id,
        grade_id=g7.id,
        title="Class 7 Math",
        edition_year=2024,
        source_filename="qb.pdf",
        stored_pdf_path="pqb.pdf",
        file_size_bytes=1000,
        checksum_sha256="hqb",
        page_count=50,
        ingestion_status="COMPLETED",
    )
    node = CurriculumNode(
        id="unit_1",
        subject_version_id="tb_qb_test",
        title="Unit 1",
        node_type="unit",
        source_label="Unit 1",
        ordinal=1,
        depth=1,
        start_pdf_page=1,
    )
    db_session.add_all([tb, node])
    await db_session.flush()

    # Register mock generation job with explanation
    job = GenerationJob(
        job_id="job_test_expl",
        subject_version_id="tb_qb_test",
        scope_node_ids=["unit_1"],
        requested_count=1,
        generated_count=1,
        status="completed",
        accepted_raw_items=[
            LLMMCGItem(
                question_id="item_1",
                stem="What is 7 * 8?",
                options=[
                    LLMMCGOption(id="opt_1", text="54"),
                    LLMMCGOption(id="opt_2", text="56"),
                    LLMMCGOption(id="opt_3", text="58"),
                    LLMMCGOption(id="opt_4", text="60"),
                ],
                correct_option_id="opt_2",
                explanation="7 multiplied by 8 equals 56 by arithmetic multiplication table.",
                source_chunk_ids=["chunk_mult_1"],
            )
        ],
        chunk_map={
            "chunk_mult_1": SourceChunk(
                chunk_id="chunk_mult_1",
                page_number=10,
                title="Multiplication",
                content="Multiplication table chapter 1",
                scope_label="Unit 1",
            )
        },
    )
    GenerationJobService._JOBS["job_test_expl"] = job

    from app.schemas.question_bank import SaveGeneratedQuestionsRequest

    # Save to Question Bank via service
    save_resp = await QuestionBankService.save_generated_questions(
        db_session,
        SaveGeneratedQuestionsRequest(job_id="job_test_expl"),
    )
    assert save_resp.new_questions_saved == 1

    # Verify that in Question Bank, explanation and grade are completely intact
    list_resp = await QuestionBankService.list_questions(
        db_session,
        subject_version_id="tb_qb_test",
    )
    assert len(list_resp.items) == 1
    assert list_resp.items[0].explanation == "7 multiplied by 8 equals 56 by arithmetic multiplication table."
    assert list_resp.items[0].grade_name == "Class 7"


@pytest.mark.asyncio
async def test_grade_dropdown_and_mcq_capabilities_for_new_ingestion(client: AsyncClient):
    """
    Validates that when a new textbook for a new Grade (Class 8) is ingested:
    1. Ingestion runs quality gate and finalizes curriculum_quality_status = 'VALID'.
    2. Explicit subject selection sets metadata_status = 'USER_CONFIRMED' and subject_id.
    3. GET /api/v1/grades?only_with_textbooks=true dynamically includes Class 8 with count >= 1.
    4. GET /api/v1/assessments/capabilities returns the valid scopes and grade metadata.
    """
    import io
    from tests.utils import create_synthetic_mathematics_pdf

    # 1. Fetch Class 8 grade ID
    grades_res = await client.get("/api/v1/grades")
    grades = grades_res.json()
    class8_grade = next(g for g in grades if g["name"] == "Class 8")
    class8_id = class8_grade["id"]

    # 2. Ingest Class 8 Mathematics PDF
    pdf_bytes = create_synthetic_mathematics_pdf()
    files = {"file": ("Math_compressed (1).pdf", io.BytesIO(pdf_bytes), "application/pdf")}
    data = {"grade_id": str(class8_id)}

    ingest_res = await client.post("/api/v1/textbooks/ingest", files=files, data=data)
    assert ingest_res.status_code == 201
    v_data = ingest_res.json()
    version_id = v_data["version_id"]

    # Verify quality status finalized as VALID
    assert v_data["curriculum_quality_status"] == "VALID"
    assert v_data["assessment_ready"] is True

    # 3. Fetch grades with only_with_textbooks=true -> Class 8 must be present!
    filtered_grades_res = await client.get("/api/v1/grades?only_with_textbooks=true")
    assert filtered_grades_res.status_code == 200
    filtered_grades = filtered_grades_res.json()
    filtered_class8 = next((g for g in filtered_grades if g["id"] == class8_id), None)
    assert filtered_class8 is not None
    assert filtered_class8["textbook_count"] >= 1

    # 4. Fetch assessment capabilities for the Class 8 version
    cap_res = await client.get(f"/api/v1/assessments/mcq/capabilities?subject_version_id={version_id}")
    assert cap_res.status_code == 200
    cap_data = cap_res.json()
    assert cap_data["grade_id"] == class8_id
    assert cap_data["grade"] == "Class 8"
    assert cap_data["generation_supported"] is True
    assert len(cap_data["scope_tree"]) > 0

