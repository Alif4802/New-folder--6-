import hashlib
import json
import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.curriculum import Curriculum, Grade, Subject
from app.models.question_bank import (
    QuestionBankItem,
    QuestionBankOption,
    QuestionBankItemScope,
    QuestionBankItemProvenance,
    QuestionSet,
    QuestionSetItem,
)
from app.models.textbook import ActivityNode, CurriculumNode, SubjectVersion, Unit
from app.schemas.assessment import MCQGenerateRequest, MCQQuestionResponse, MCQOptionResponse
from app.schemas.llm_mcq import LLMMCGItem, LLMMCGOption
from app.schemas.question_bank import (
    BatchArchiveQuestionsRequest,
    PaperMetadataSchema,
    QuestionArrangementRequest,
    SaveGeneratedQuestionsRequest,
    SavePaperRequest,
)
from app.services.assessment.job_service import GenerationJob, GenerationJobService
from app.services.assessment.resolver import SourceChunk
from app.services.question_bank.bank_service import (
    QuestionBankService,
    calculate_canonical_content_hash,
)
from app.services.question_bank.paper_service import QuestionPaperService


@pytest.fixture
async def sample_curriculum_and_book(db_session: AsyncSession):
    """Creates a sample SubjectVersion with CurriculumNodes and ActivityNodes for testing."""
    curriculum = Curriculum(
        code="NCTB_TEST",
        name="NCTB Test Curriculum",
        country="Bangladesh",
        authority="Ministry of Education",
        is_active=True,
    )
    db_session.add(curriculum)
    await db_session.flush()

    grade = Grade(curriculum_id=curriculum.id, code="CLASS_7", name="Class 7", level_number=7)
    subject = Subject(curriculum_id=curriculum.id, code="MATH", name="Mathematics", domain="STEM")
    db_session.add_all([grade, subject])
    await db_session.flush()

    version = SubjectVersion(
        id="subver_math_c7_test",
        curriculum_id=curriculum.id,
        subject_id=subject.id,
        grade_id=grade.id,
        title="Mathematics — Class 7",
        source_filename="math7.pdf",
        stored_pdf_path="storage/pdfs/math7.pdf",
        file_size_bytes=10240,
        checksum_sha256="abc123mathchecksum",
        page_count=100,
        ingestion_status="COMPLETED",
    )
    db_session.add(version)
    await db_session.flush()

    cnode_chap5 = CurriculumNode(
        id="cnode_chap5",
        subject_version_id=version.id,
        node_type="chapter",
        source_label="Chapter 5",
        title="Algebraic Formulae and Applications",
        detected_number="5",
        ordinal=5,
        depth=0,
        start_pdf_page=70,
        end_pdf_page=85,
    )
    cnode_sec51 = CurriculumNode(
        id="cnode_sec51",
        subject_version_id=version.id,
        parent_id="cnode_chap5",
        node_type="section",
        source_label="Section 5.1",
        title="Square Formulae",
        detected_number="5.1",
        ordinal=1,
        depth=1,
        start_pdf_page=70,
        end_pdf_page=75,
    )
    db_session.add_all([cnode_chap5, cnode_sec51])
    await db_session.flush()

    unit1 = Unit(
        id=1,
        subject_version_id=version.id,
        ordinal=1,
        detected_number="5",
        label_type="Chapter",
        title="Algebraic Formulae",
        start_page=70,
        end_page=85,
    )
    db_session.add(unit1)
    await db_session.flush()

    act1 = ActivityNode(
        id=101,
        subject_version_id=version.id,
        unit_id=unit1.id,
        curriculum_node_id="cnode_sec51",
        ordinal=1,
        node_type="paragraph",
        title="Square of Binomial",
        content_text="The square of $(a+b)$ is given by $(a+b)^2 = a^2 + 2ab + b^2$.",
        content_hash="hash_act101",
        page_number=71,
    )
    db_session.add(act1)
    await db_session.commit()

    return {
        "version_id": version.id,
        "chap5_id": cnode_chap5.id,
        "sec51_id": cnode_sec51.id,
        "act1_id": act1.id,
    }


def test_canonical_content_hash_ignores_randomization():
    """Verifies canonical content hash is 100% invariant under presentation option reordering."""
    stem = "What is the square of $(a+b)$?"
    options_order_1 = ["$a^2 + 2ab + b^2$", "$a^2 - 2ab + b^2$", "$a^2 + b^2$", "$a^2 - b^2$"]
    options_order_2 = ["$a^2 + b^2$", "$a^2 - b^2$", "$a^2 + 2ab + b^2$", "$a^2 - 2ab + b^2$"]
    correct_text = "$a^2 + 2ab + b^2$"

    hash1 = calculate_canonical_content_hash(stem, options_order_1, correct_text, "MCQ")
    hash2 = calculate_canonical_content_hash(stem, options_order_2, correct_text, "MCQ")
    assert hash1 == hash2, "Content hash must be identical regardless of option presentation order."

    # Different correct text produces different hash
    hash3 = calculate_canonical_content_hash(stem, options_order_1, "$a^2 - 2ab + b^2$", "MCQ")
    assert hash1 != hash3, "Different correct answer must produce different content hash."


@pytest.mark.asyncio
async def test_save_generated_questions_server_authoritative(
    db_session: AsyncSession,
    sample_curriculum_and_book: dict,
):
    """
    Tests server-authoritative Question Bank persistence:
    - Generates dummy job with raw items.
    - Saves to Question Bank.
    - Verifies QuestionBankItem, QuestionBankOption, scopes, and stable provenance.
    - Verifies no persistent SRC-* string in provenance.
    """
    vid = sample_curriculum_and_book["version_id"]
    job_id = "test_job_101"

    # Setup dummy completed GenerationJob in memory
    raw_item = LLMMCGItem(
        question_id="q_1",
        stem="What is the value of $(x+y)^2$?",
        stem_latex=None,
        options=[
            LLMMCGOption(id="opt_1", text="$x^2 + 2xy + y^2$", latex=None),
            LLMMCGOption(id="opt_2", text="$x^2 - 2xy + y^2$", latex=None),
            LLMMCGOption(id="opt_3", text="$x^2 + y^2$", latex=None),
            LLMMCGOption(id="opt_4", text="$x^2 - y^2$", latex=None),
        ],
        correct_option_id="opt_1",
        explanation="By expansion, $(x+y)^2 = x^2 + 2xy + y^2$.",
        source_chunk_ids=["SRC-001"],
    )

    chunk = SourceChunk(
        chunk_id="SRC-001",
        page_number=71,
        title="Square Formulae",
        content="The square of $(a+b)$ is given by $(a+b)^2 = a^2 + 2ab + b^2$.",
        scope_label="Chapter 5: Algebraic Formulae",
        activity_node_id=sample_curriculum_and_book["act1_id"],
        curriculum_node_id=sample_curriculum_and_book["sec51_id"],
    )

    job = GenerationJob(
        job_id=job_id,
        subject_version_id=vid,
        scope_node_ids=[sample_curriculum_and_book["sec51_id"]],
        requested_count=1,
        generated_count=1,
        status="completed",
        accepted_raw_items=[raw_item],
        chunk_map={"SRC-001": chunk},
        request_id="req_gen_999",
    )
    GenerationJobService._JOBS[job_id] = job

    # 1. Save to bank
    resp = await QuestionBankService.save_generated_questions(
        session=db_session,
        request=SaveGeneratedQuestionsRequest(job_id=job_id),
    )

    assert resp.new_questions_saved == 1
    assert resp.existing_questions_reused == 0
    assert len(resp.saved_items) == 1
    saved = resp.saved_items[0]

    assert saved.question_text == "What is the value of $(x+y)^2$?"
    assert saved.origin_type == "AI_GENERATED"
    assert saved.grounding_source == "OFFICIAL_NCTB"
    assert len(saved.options) == 4
    assert saved.correct_option_id is not None

    # Check database records directly
    qbi_res = await db_session.execute(
        select(QuestionBankItem)
        .where(QuestionBankItem.id == saved.id)
        .options(
            selectinload(QuestionBankItem.options),
            selectinload(QuestionBankItem.scopes),
            selectinload(QuestionBankItem.provenances),
        )
    )
    db_qbi = qbi_res.scalar_one()
    assert db_qbi.correct_option_id == db_qbi.options[0].id
    assert len(db_qbi.provenances) == 1
    prov = db_qbi.provenances[0]
    assert prov.activity_node_id == sample_curriculum_and_book["act1_id"]
    assert prov.curriculum_node_id == sample_curriculum_and_book["sec51_id"]
    assert prov.page_number == 71

    # 2. Repeated save -> Idempotent reuse
    resp2 = await QuestionBankService.save_generated_questions(
        session=db_session,
        request=SaveGeneratedQuestionsRequest(job_id=job_id),
    )
    assert resp2.new_questions_saved == 0
    assert resp2.existing_questions_reused == 1


@pytest.mark.asyncio
async def test_question_bank_search_and_filtering(
    db_session: AsyncSession,
    sample_curriculum_and_book: dict,
):
    """Tests question bank listing, keyword search, curriculum node filtering, and status."""
    vid = sample_curriculum_and_book["version_id"]

    # Insert two sample bank questions
    qbi1 = QuestionBankItem(
        id="qbi_geo_1",
        subject_version_id=vid,
        question_type="MCQ",
        language="en",
        question_text="What is the perimeter of an equilateral triangle with side $a$?",
        explanation="Perimeter is $3a$.",
        content_hash="hash_geo_1",
        origin_type="AI_GENERATED",
        grounding_source="OFFICIAL_NCTB",
        status="ACTIVE",
    )
    opt1_1 = QuestionBankOption(id="opt_g1_1", question_id="qbi_geo_1", option_text="$3a$", canonical_order=0)
    opt1_2 = QuestionBankOption(id="opt_g1_2", question_id="qbi_geo_1", option_text="$2a$", canonical_order=1)
    opt1_3 = QuestionBankOption(id="opt_g1_3", question_id="qbi_geo_1", option_text="$a^2$", canonical_order=2)
    opt1_4 = QuestionBankOption(id="opt_g1_4", question_id="qbi_geo_1", option_text="$4a$", canonical_order=3)
    db_session.add_all([qbi1, opt1_1, opt1_2, opt1_3, opt1_4])
    await db_session.flush()
    qbi1.correct_option_id = opt1_1.id

    scope1 = QuestionBankItemScope(question_bank_item_id="qbi_geo_1", curriculum_node_id=sample_curriculum_and_book["sec51_id"])
    db_session.add(scope1)

    qbi2 = QuestionBankItem(
        id="qbi_geo_2",
        subject_version_id=vid,
        question_type="MCQ",
        language="en",
        question_text="Which polygon has 4 equal sides and 90 degree angles?",
        explanation="A square has 4 equal sides and right angles.",
        content_hash="hash_geo_2",
        origin_type="AI_GENERATED",
        grounding_source="OFFICIAL_NCTB",
        status="ARCHIVED",
    )
    opt2_1 = QuestionBankOption(id="opt_g2_1", question_id="qbi_geo_2", option_text="Square", canonical_order=0)
    opt2_2 = QuestionBankOption(id="opt_g2_2", question_id="qbi_geo_2", option_text="Rhombus", canonical_order=1)
    opt2_3 = QuestionBankOption(id="opt_g2_3", question_id="qbi_geo_2", option_text="Rectangle", canonical_order=2)
    opt2_4 = QuestionBankOption(id="opt_g2_4", question_id="qbi_geo_2", option_text="Trapezium", canonical_order=3)
    db_session.add_all([qbi2, opt2_1, opt2_2, opt2_3, opt2_4])
    await db_session.flush()
    qbi2.correct_option_id = opt2_1.id

    await db_session.commit()

    # Test list active
    res_active = await QuestionBankService.list_questions(db_session, subject_version_id=vid, status="ACTIVE")
    assert res_active.total_count == 1
    assert res_active.items[0].id == "qbi_geo_1"

    # Test search
    res_search = await QuestionBankService.list_questions(db_session, search="perimeter", status="ACTIVE")
    assert res_search.total_count == 1

    # Test scope filter
    res_scope = await QuestionBankService.list_questions(db_session, scope_node_id=sample_curriculum_and_book["chap5_id"], status="ACTIVE")
    assert res_scope.total_count == 1

    # Test batch archive
    await QuestionBankService.batch_archive_questions(
        db_session,
        BatchArchiveQuestionsRequest(question_ids=["qbi_geo_1"], archive=True),
    )
    res_after = await QuestionBankService.list_questions(db_session, subject_version_id=vid, status="ACTIVE")
    assert res_after.total_count == 0


@pytest.mark.asyncio
async def test_question_bank_api_http(
    client: AsyncClient,
    sample_curriculum_and_book: dict,
    db_session: AsyncSession,
):
    """Verifies Question Bank endpoints over HTTP."""
    vid = sample_curriculum_and_book["version_id"]

    # 1. Setup a job in memory
    job_id = "http_test_job_1"
    raw_item = LLMMCGItem(
        question_id="q_1",
        stem="What is $15 \\times 4$?",
        options=[
            LLMMCGOption(id="opt_1", text="60"),
            LLMMCGOption(id="opt_2", text="50"),
            LLMMCGOption(id="opt_3", text="45"),
            LLMMCGOption(id="opt_4", text="65"),
        ],
        correct_option_id="opt_1",
        explanation="$15 \\times 4 = 60$.",
        source_chunk_ids=["SRC-001"],
    )
    chunk = SourceChunk(
        chunk_id="SRC-001",
        page_number=70,
        title="Multiplication",
        content="Multiplication table",
        scope_label="Chapter 5",
        curriculum_node_id=sample_curriculum_and_book["chap5_id"],
    )
    GenerationJobService._JOBS[job_id] = GenerationJob(
        job_id=job_id,
        subject_version_id=vid,
        scope_node_ids=[sample_curriculum_and_book["chap5_id"]],
        requested_count=1,
        generated_count=1,
        status="completed",
        accepted_raw_items=[raw_item],
        chunk_map={"SRC-001": chunk},
    )

    # 2. Call save-generated endpoint
    resp = await client.post(
        "/api/v1/question-bank/questions/save-generated",
        json={"job_id": job_id},
    )
    assert resp.status_code == 201
    data = resp.json()
    assert data["new_questions_saved"] == 1
    saved_id = data["saved_items"][0]["id"]

    # 3. Call list questions
    list_resp = await client.get(f"/api/v1/question-bank/questions?subject_version_id={vid}")
    assert list_resp.status_code == 200
    list_data = list_resp.json()
    assert list_data["total_count"] == 1

    # 4. Call single question detail
    detail_resp = await client.get(f"/api/v1/question-bank/questions/{saved_id}")
    assert detail_resp.status_code == 200
    detail_data = detail_resp.json()
    assert detail_data["question_text"] == "What is $15 \\times 4$?"
    assert detail_data["origin_type"] == "AI_GENERATED"
    assert detail_data["grounding_source"] == "OFFICIAL_NCTB"
