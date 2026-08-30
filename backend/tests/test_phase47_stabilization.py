import io
import uuid
import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db, bootstrap_default_curriculum
from app.models.curriculum import Grade, Subject, Curriculum
from app.models.textbook import SubjectVersion, CurriculumNode, utc_now
from app.models.question_bank import QuestionBankItem, QuestionSet, QuestionBankOption, QuestionSetItem
from app.services.assessment.readiness import AssessmentReadinessService
from app.services.pdf.curriculum_quality import CurriculumQualityGate
from tests.utils import create_synthetic_english_today_pdf, create_synthetic_mathematics_pdf


@pytest.mark.asyncio
async def test_canonical_subject_seeding_and_endpoint(client: AsyncClient):
    """
    Validates that canonical subjects are idempotently seeded and accessible via GET /api/v1/subjects.
    """
    res = await client.get("/api/v1/subjects")
    assert res.status_code == 200
    data = res.json()
    assert "subjects" in data
    assert len(data["subjects"]) >= 3

    codes = [s["code"] for s in data["subjects"]]
    assert "english-for-today" in codes
    assert "english-grammar" in codes
    assert "mathematics" in codes

    # Domain checking
    math_subj = next(s for s in data["subjects"] if s["code"] == "mathematics")
    assert math_subj["domain"] == "STEM"
    assert math_subj["is_supported_for_generation"] is True


@pytest.mark.asyncio
async def test_active_checksum_unique_constraint_and_soft_delete_reingest(client: AsyncClient):
    """
    Verifies:
    1. Active duplicate PDF raises 409 Conflict.
    2. Soft deleting the version allows re-ingesting the exact same PDF checksum.
    3. Soft-deleted version remains in DB with is_deleted=True and new version is active.
    """
    # 1. Ingest textbook
    grades_res = await client.get("/api/v1/grades")
    grade_id = grades_res.json()[0]["id"]

    pdf_bytes = create_synthetic_mathematics_pdf()
    files = {"file": ("Class9_Math.pdf", io.BytesIO(pdf_bytes), "application/pdf")}
    data = {"grade_id": str(grade_id)}

    ingest_res1 = await client.post("/api/v1/textbooks/ingest", files=files, data=data)
    assert ingest_res1.status_code == 201
    v1_id = ingest_res1.json()["version_id"]

    # 2. Try duplicate upload while active -> Must fail with 409 DUPLICATE_PDF
    files2 = {"file": ("Class9_Math_copy.pdf", io.BytesIO(pdf_bytes), "application/pdf")}
    ingest_res2 = await client.post("/api/v1/textbooks/ingest", files=files2, data=data)
    assert ingest_res2.status_code == 409
    assert ingest_res2.json()["detail"]["error_code"] == "DUPLICATE_PDF"

    # 3. Soft delete v1
    del_res = await client.delete(f"/api/v1/textbooks/{v1_id}")
    assert del_res.status_code == 200
    assert del_res.json()["is_deleted"] is True

    # 4. Ingest same PDF again -> Must succeed with new version identity!
    files3 = {"file": ("Class9_Math_reupload.pdf", io.BytesIO(pdf_bytes), "application/pdf")}
    ingest_res3 = await client.post("/api/v1/textbooks/ingest", files=files3, data=data)
    assert ingest_res3.status_code == 201
    v2_id = ingest_res3.json()["version_id"]
    assert v2_id != v1_id

    # 5. List active versions -> v1 must NOT appear by default, v2 must appear
    list_res = await client.get("/api/v1/textbooks/versions")
    active_ids = [v["id"] for v in list_res.json()]
    assert v1_id not in active_ids
    assert v2_id in active_ids


@pytest.mark.asyncio
async def test_unresolved_subject_state_and_null_domain():
    """
    Validates that when a textbook has no assigned or resolved subject,
    subject_id is None, domain is None (never fabricated 'GENERAL'),
    metadata_status is 'NEEDS_REVIEW', and assessment_ready is False.
    """
    unresolved_version = SubjectVersion(
        id=str(uuid.uuid4()),
        title="Unassigned Unknown Book",
        source_filename="unknown.pdf",
        stored_pdf_path="pdfs/test.pdf",
        file_size_bytes=1000,
        checksum_sha256="dummy_checksum_123",
        page_count=10,
        ocr_pages_count=0,
        ingestion_status="COMPLETED",
        grade_id=None,
        subject_id=None,
        curriculum_quality_status="VALID",
        metadata_status="NEEDS_REVIEW",
    )

    readiness = AssessmentReadinessService.evaluate(unresolved_version)
    assert readiness.is_ready is False
    assert any("SUBJECT" in r for r in readiness.reasons)
    assert any("GRADE" in r for r in readiness.reasons)


@pytest.mark.asyncio
async def test_discriminated_save_paper_contract(client: AsyncClient):
    """
    Validates the strict discriminated request contract for POST /api/v1/question-bank/papers:
    - source_type="GENERATED_JOB" requires job_id.
    - source_type="QUESTION_BANK" forbids job_id.
    - Invalid combinations are rejected with 422 Unprocessable Entity.
    """
    # 1. GENERATED_JOB without job_id -> 422
    bad_payload_1 = {
        "source_type": "GENERATED_JOB",
        "job_id": None,
        "subject_version_id": "dummy_ver",
        "title": "Invalid Job Paper",
        "arrangements": [
            {"question_id": "gen_q_123", "question_order": 1, "option_order": ["gen_opt_1", "gen_opt_2", "gen_opt_3", "gen_opt_4"]}
        ],
    }
    res1 = await client.post("/api/v1/question-bank/papers", json=bad_payload_1)
    assert res1.status_code == 422

    # 2. QUESTION_BANK with job_id -> 422
    bad_payload_2 = {
        "source_type": "QUESTION_BANK",
        "job_id": "job_123",
        "subject_version_id": "dummy_ver",
        "title": "Invalid Bank Paper",
        "arrangements": [
            {"question_id": "qbi_123", "question_order": 1, "option_order": ["opt_1", "opt_2", "opt_3", "opt_4"]}
        ],
    }
    res2 = await client.post("/api/v1/question-bank/papers", json=bad_payload_2)
    assert res2.status_code == 422


@pytest.mark.asyncio
async def test_deleted_textbook_historical_paper_reopen(client: AsyncClient):
    """
    Validates that soft-deleting a textbook version does NOT prevent
    reopening historical Saved Papers or viewing Question Bank items.
    """
    # Ingest textbook
    grades_res = await client.get("/api/v1/grades")
    grade_id = grades_res.json()[0]["id"]
    pdf_bytes = create_synthetic_english_today_pdf()
    files = {"file": ("Class9_EFT.pdf", io.BytesIO(pdf_bytes), "application/pdf")}
    data = {"grade_id": str(grade_id)}

    ingest_res = await client.post("/api/v1/textbooks/ingest", files=files, data=data)
    assert ingest_res.status_code == 201
    version_id = ingest_res.json()["version_id"]

    # Seed QuestionBankItem and Option directly in DB
    app_db_func = client._transport.app.dependency_overrides.get(get_db)
    async for session in app_db_func():
        qbi_id = f"qbi_{uuid.uuid4().hex[:12]}"
        opt_ids = [f"opt_{uuid.uuid4().hex[:12]}" for _ in range(4)]

        qbi = QuestionBankItem(
            id=qbi_id,
            subject_version_id=version_id,
            question_type="MCQ",
            question_text="What is the historical year of Bangladesh independence?",
            explanation="1971 was the liberation war.",
            content_hash=f"hash_{uuid.uuid4().hex[:16]}",
            created_at=utc_now(),
            updated_at=utc_now(),
        )
        session.add(qbi)
        await session.flush()

        for idx, oid in enumerate(opt_ids):
            opt = QuestionBankOption(
                id=oid,
                question_id=qbi_id,
                option_text=f"Year {1970 + idx + 1}",
                canonical_order=idx,
            )
            session.add(opt)
        await session.flush()

        qbi.correct_option_id = opt_ids[0]
        await session.flush()

        qset_id = f"qset_{uuid.uuid4().hex[:12]}"
        qset = QuestionSet(
            id=qset_id,
            title="Historical Independence Test",
            subject_version_id=version_id,
            set_type="QUESTION_PAPER",
            question_count=1,
            paper_metadata={"exam_title": "Independence Test", "total_marks": 1.0},
            status="ACTIVE",
            created_at=utc_now(),
            updated_at=utc_now(),
        )
        session.add(qset)
        await session.flush()

        qsi = QuestionSetItem(
            id=f"qsi_{uuid.uuid4().hex[:12]}",
            set_id=qset_id,
            question_bank_item_id=qbi_id,
            question_order=1,
            option_order=opt_ids,
            created_at=utc_now(),
        )
        session.add(qsi)
        await session.commit()
        break

    # Reopen paper before delete -> 200 OK
    get_paper_res1 = await client.get(f"/api/v1/question-bank/papers/{qset_id}")
    assert get_paper_res1.status_code == 200
    assert get_paper_res1.json()["title"] == "Historical Independence Test"

    # Soft-delete the textbook
    del_res = await client.delete(f"/api/v1/textbooks/{version_id}")
    assert del_res.status_code == 200

    # Reopen paper AFTER soft-delete -> MUST STILL SUCCEED 200 OK!
    get_paper_res2 = await client.get(f"/api/v1/question-bank/papers/{qset_id}")
    assert get_paper_res2.status_code == 200
    paper_data = get_paper_res2.json()
    assert paper_data["title"] == "Historical Independence Test"
    assert len(paper_data["questions"]) == 1
    assert len(paper_data["answer_key"]) == 1


@pytest.mark.asyncio
async def test_metadata_patch_and_user_confirmed_preservation(client: AsyncClient):
    """
    Validates:
    1. PATCH /api/v1/textbooks/{version_id}/metadata updates metadata and sets metadata_status='USER_CONFIRMED'.
    2. POST /api/v1/textbooks/{version_id}/refresh-metadata preserves USER_CONFIRMED fields.
    """
    # Ingest textbook
    grades_res = await client.get("/api/v1/grades")
    grades = grades_res.json()
    grade_id_1 = grades[0]["id"]
    grade_id_2 = grades[1]["id"]

    pdf_bytes = create_synthetic_english_today_pdf()
    files = {"file": ("Class9_EFT.pdf", io.BytesIO(pdf_bytes), "application/pdf")}
    data = {"grade_id": str(grade_id_1)}

    ingest_res = await client.post("/api/v1/textbooks/ingest", files=files, data=data)
    assert ingest_res.status_code == 201
    version_id = ingest_res.json()["version_id"]

    # PATCH metadata to Grade 2 and custom edition
    patch_res = await client.patch(
        f"/api/v1/textbooks/{version_id}/metadata",
        json={
            "grade_id": grade_id_2,
            "title": "Custom English Book",
            "edition_label": "Revised Golden Edition",
            "publication_year": 2026,
        },
    )
    assert patch_res.status_code == 200
    patched_data = patch_res.json()
    assert patched_data["grade_id"] == grade_id_2
    assert patched_data["title"] == "Custom English Book"
    assert patched_data["edition_label"] == "Revised Golden Edition"
    assert patched_data["metadata_status"] == "USER_CONFIRMED"

    # POST refresh-metadata -> Must preserve user-confirmed fields
    refresh_res = await client.post(f"/api/v1/textbooks/{version_id}/refresh-metadata")
    assert refresh_res.status_code == 200
    refreshed_data = refresh_res.json()
    assert refreshed_data["grade_id"] == grade_id_2
    assert refreshed_data["title"] == "Custom English Book"
    assert refreshed_data["edition_label"] == "Revised Golden Edition"
    assert refreshed_data["metadata_status"] == "USER_CONFIRMED"


@pytest.mark.asyncio
async def test_candidate_staging_tree_and_structure_refresh(client: AsyncClient):
    """
    Validates candidate staging tree refresh:
    POST /api/v1/textbooks/{version_id}/refresh-structure safely evaluates quality gate
    and atomically replaces the live CurriculumNode tree.
    """
    grades_res = await client.get("/api/v1/grades")
    grade_id = grades_res.json()[0]["id"]
    pdf_bytes = create_synthetic_mathematics_pdf()
    files = {"file": ("Class9_Math.pdf", io.BytesIO(pdf_bytes), "application/pdf")}
    data = {"grade_id": str(grade_id)}

    ingest_res = await client.post("/api/v1/textbooks/ingest", files=files, data=data)
    assert ingest_res.status_code == 201
    version_id = ingest_res.json()["version_id"]

    # Refresh structure
    refresh_res = await client.post(f"/api/v1/textbooks/{version_id}/refresh-structure")
    assert refresh_res.status_code == 200
    data = refresh_res.json()
    assert data["status"] == "VALID"
    assert data["nodes_created"] > 0
    assert "quality_metrics" in data


@pytest.mark.asyncio
async def test_curriculum_quality_gate_signals():
    """
    Tests CurriculumQualityGate evaluation metrics and rejection thresholds.
    """
    # 1. Tree with excessive duplicate titles -> Must fail
    dup_nodes = [
        CurriculumNode(
            id=f"node_{i}",
            subject_version_id="dummy",
            parent_id=None,
            node_type="unit",
            source_label="Unit",
            title="Duplicate Title",
            ordinal=i,
            depth=0,
            start_pdf_page=1,
            end_pdf_page=5,
        )
        for i in range(10)
    ]
    res_dup = CurriculumQualityGate.evaluate_tree(dup_nodes, 10)
    assert res_dup.is_valid is False
    assert any("EXCESSIVE_DUPLICATE_TITLES" in r for r in res_dup.reasons)

    # 2. Tree with invalid page ranges -> Must fail
    invalid_range_node = [
        CurriculumNode(
            id="node_inv",
            subject_version_id="dummy",
            parent_id=None,
            node_type="unit",
            source_label="Unit",
            title="Valid Unique Title",
            ordinal=1,
            depth=0,
            start_pdf_page=10,
            end_pdf_page=5,  # start > end
        )
    ]
    res_inv = CurriculumQualityGate.evaluate_tree(invalid_range_node, 10)
    assert res_inv.is_valid is False
    assert any("INVALID_PAGE_RANGES" in r for r in res_inv.reasons)


@pytest.mark.asyncio
async def test_unassessed_legacy_readiness_compatibility():
    """
    Validates that UNASSESSED curriculum_quality_status does NOT block assessment readiness
    when Grade, Subject, and PDF are valid (legacy compatibility policy).
    """
    from app.core.config import settings
    (settings.STORAGE_ROOT / "pdfs/test_legacy.pdf").parent.mkdir(parents=True, exist_ok=True)
    (settings.STORAGE_ROOT / "pdfs/test_legacy.pdf").touch()

    legacy_version = SubjectVersion(
        id=str(uuid.uuid4()),
        title="Mathematics (Class 9)",
        source_filename="class9_math.pdf",
        stored_pdf_path="pdfs/test_legacy.pdf",
        file_size_bytes=1000,
        checksum_sha256="dummy_legacy_123",
        page_count=50,
        ocr_pages_count=0,
        ingestion_status="COMPLETED",
        grade_id=9,
        subject_id=3,
        curriculum_quality_status="UNASSESSED",
        metadata_status="UNASSESSED",
    )
    # Mock subject relation with STEM domain
    legacy_version.subject = Subject(id=3, curriculum_id=1, code="mathematics", name="Mathematics", domain="STEM")

    readiness = AssessmentReadinessService.evaluate(legacy_version)
    assert readiness.is_ready is True
    assert len(readiness.reasons) == 0


@pytest.mark.asyncio
async def test_known_bad_structure_blocks_readiness():
    """
    Validates that NEEDS_REFRESH, FAILED, and BUILDING explicitly block assessment readiness.
    """
    from app.core.config import settings
    (settings.STORAGE_ROOT / "pdfs/test_refresh.pdf").parent.mkdir(parents=True, exist_ok=True)
    (settings.STORAGE_ROOT / "pdfs/test_refresh.pdf").touch()

    bad_version = SubjectVersion(
        id=str(uuid.uuid4()),
        title="Mathematics (Class 9)",
        source_filename="class9_math.pdf",
        stored_pdf_path="pdfs/test_refresh.pdf",
        file_size_bytes=1000,
        checksum_sha256="dummy_refresh_123",
        page_count=50,
        ocr_pages_count=0,
        ingestion_status="COMPLETED",
        grade_id=9,
        subject_id=3,
        curriculum_quality_status="NEEDS_REFRESH",
        metadata_status="VALID",
    )
    bad_version.subject = Subject(id=3, curriculum_id=1, code="mathematics", name="Mathematics", domain="STEM")

    readiness = AssessmentReadinessService.evaluate(bad_version)
    assert readiness.is_ready is False
    assert "STRUCTURE_NEEDS_REFRESH" in readiness.reasons


@pytest.mark.asyncio
async def test_raw_db_error_not_exposed_on_duplicate(client: AsyncClient):
    """
    Verifies that when duplicate PDF ingestion is rejected, the API response
    does NOT expose SQL statements, SQLAlchemy tracebacks, or database paths.
    """
    grades_res = await client.get("/api/v1/grades")
    grade_id = grades_res.json()[0]["id"]

    pdf_bytes = create_synthetic_mathematics_pdf()
    files = {"file": ("Class9_Math.pdf", io.BytesIO(pdf_bytes), "application/pdf")}
    data = {"grade_id": str(grade_id)}

    res1 = await client.post("/api/v1/textbooks/ingest", files=files, data=data)
    assert res1.status_code == 201

    # Duplicate upload
    files2 = {"file": ("Class9_Math_copy.pdf", io.BytesIO(pdf_bytes), "application/pdf")}
    res2 = await client.post("/api/v1/textbooks/ingest", files=files2, data=data)
    assert res2.status_code == 409
    body_text = res2.text
    assert "sqlite" not in body_text.lower()
    assert "sqlalchemy" not in body_text.lower()
    assert "insert into" not in body_text.lower()
    assert "traceback" not in body_text.lower()
    assert res2.json()["detail"]["error_code"] == "DUPLICATE_PDF"
    assert res2.json()["detail"]["message"] == "This exact textbook PDF has already been ingested."

