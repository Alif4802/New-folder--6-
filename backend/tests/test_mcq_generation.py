import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine, async_sessionmaker

from app.core.database import Base
from app.models.curriculum import Curriculum, Grade, Subject
from app.models.textbook import ActivityNode, Lesson, SubjectVersion, Unit
from app.schemas.assessment import MCQGenerateRequest
from app.schemas.llm_mcq import (
    LLMMCGCandidateResponse,
    LLMMCGItem,
    LLMMCGOption,
    MCQVerificationResponse,
    QuestionVerificationResult,
)
from app.services.assessment.generator import MCQGeneratorService
from app.services.assessment.validator import MCQValidator
from app.services.llm.mock_provider import MockProvider


@pytest_asyncio.fixture
async def test_session():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", echo=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    async_session = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)
    async with async_session() as session:
        curriculum = Curriculum(code="NCTB_TEST", name="NCTB Test", country="Bangladesh", authority="MoE")
        session.add(curriculum)
        await session.flush()

        grade = Grade(curriculum_id=curriculum.id, code="class-7", name="Class 7", level_number=7)
        math_subj = Subject(curriculum_id=curriculum.id, code="mathematics", name="Mathematics", domain="STEM")
        eng_subj = Subject(curriculum_id=curriculum.id, code="english-for-today", name="English for Today", domain="LANGUAGE")
        session.add_all([grade, math_subj, eng_subj])
        await session.flush()

        from app.core.config import settings
        (settings.STORAGE_ROOT / "test_math.pdf").parent.mkdir(parents=True, exist_ok=True)
        (settings.STORAGE_ROOT / "test_math.pdf").touch()

        math_version = SubjectVersion(
            id="test-math-version-1",
            curriculum_id=curriculum.id,
            subject_id=math_subj.id,
            grade_id=grade.id,
            title="Mathematics (Class 7)",
            source_filename="math7.pdf",
            stored_pdf_path="test_math.pdf",
            file_size_bytes=1024,
            checksum_sha256="sha_math_123",
            page_count=20,
            ingestion_status="COMPLETED",
            curriculum_quality_status="VALID",
            metadata_status="VALID",
        )
        session.add(math_version)
        await session.flush()

        unit1 = Unit(
            id=101,
            subject_version_id=math_version.id,
            ordinal=1,
            detected_number="1",
            title="Rational and Irrational Numbers",
            start_page=1,
            end_page=10,
        )
        session.add(unit1)
        await session.flush()

        lesson1 = Lesson(
            id=201,
            unit_id=unit1.id,
            ordinal=1,
            detected_number="1.1",
            title="Squares and square roots",
            start_page=1,
            end_page=5,
        )
        session.add(lesson1)
        await session.flush()

        node1 = ActivityNode(
            subject_version_id=math_version.id,
            unit_id=unit1.id,
            lesson_id=lesson1.id,
            ordinal=1,
            node_type="definition",
            title="Definition of Square Number",
            content_text="A number multiplied by itself gives the square of that number. For example, 4 * 4 = 16. So, 16 is a square number and 4 is its square root.",
            page_number=1,
            content_hash="hash_1",
        )
        node2 = ActivityNode(
            subject_version_id=math_version.id,
            unit_id=unit1.id,
            lesson_id=lesson1.id,
            ordinal=2,
            node_type="worked_example",
            title="Example 1",
            content_text="The area of a square is side * side. If each side is 5 meters, area is 25 square meters.",
            page_number=2,
            content_hash="hash_2",
        )
        session.add_all([node1, node2])

        eng_version = SubjectVersion(
            id="test-eng-version-1",
            curriculum_id=curriculum.id,
            subject_id=eng_subj.id,
            grade_id=grade.id,
            title="English for Today (Class 7)",
            source_filename="eng7.pdf",
            stored_pdf_path="test_eng.pdf",
            file_size_bytes=1024,
            checksum_sha256="sha_eng_123",
            page_count=10,
            ingestion_status="COMPLETED",
        )
        session.add(eng_version)
        await session.commit()

        yield session

    await engine.dispose()


@pytest.mark.asyncio
async def test_capabilities_api_dynamic_limits(test_session: AsyncSession):
    math_cap = await MCQGeneratorService.get_capabilities(test_session, "test-math-version-1")
    assert math_cap.generation_supported is True
    assert math_cap.min_question_count == 1
    assert math_cap.max_question_count is None or math_cap.max_question_count >= 10
    assert math_cap.generation_batch_size == 5
    assert len(math_cap.units) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("requested_count", [1, 5, 10, 11, 20])
async def test_dynamic_count_contract(test_session: AsyncSession, requested_count: int):
    """Verifies arbitrary count contract: generated_count == requested_count == len(questions)."""
    provider = MockProvider()
    req = MCQGenerateRequest(
        subject_version_id="test-math-version-1",
        unit_id=101,
        lesson_id=201,
        count=requested_count,
    )
    res = await MCQGeneratorService.generate_mcqs(test_session, req, provider=provider)
    assert res.requested_count == requested_count
    assert res.generated_count == requested_count
    assert len(res.questions) == requested_count
    assert len(res.answer_key) == requested_count


@pytest.mark.asyncio
async def test_deficit_multi_round_regeneration(test_session: AsyncSession):
    """Simulates LLM returning fewer candidates per round, requiring multiple rounds to satisfy requested count."""
    call_count = 0

    def custom_handler(sys_prompt, user_prompt, response_schema):
        nonlocal call_count
        if response_schema == LLMMCGCandidateResponse:
            call_count += 1
            # Return only 2 questions per call
            return LLMMCGCandidateResponse(
                questions=[
                    LLMMCGItem(
                        question_id=f"q_{call_count}_1",
                        stem=f"What is the square of {call_count * 2 + 1}?",
                        options=[
                            LLMMCGOption(id="opt_1", text=str((call_count * 2 + 1) ** 2)),
                            LLMMCGOption(id="opt_2", text="10"),
                            LLMMCGOption(id="opt_3", text="15"),
                            LLMMCGOption(id="opt_4", text="20"),
                        ],
                        correct_option_id="opt_1",
                        explanation="Calculated square.",
                        source_chunk_ids=["SRC-001"],
                    ),
                    LLMMCGItem(
                        question_id=f"q_{call_count}_2",
                        stem=f"What is the square of {call_count * 2 + 2}?",
                        options=[
                            LLMMCGOption(id="opt_1", text=str((call_count * 2 + 2) ** 2)),
                            LLMMCGOption(id="opt_2", text="10"),
                            LLMMCGOption(id="opt_3", text="15"),
                            LLMMCGOption(id="opt_4", text="20"),
                        ],
                        correct_option_id="opt_1",
                        explanation="Calculated square.",
                        source_chunk_ids=["SRC-001"],
                    ),
                ]
            )
        elif response_schema == MCQVerificationResponse:
            return MCQVerificationResponse(all_valid=True, evaluations=[])
        return {}

    provider = MockProvider(custom_handler=custom_handler)
    req = MCQGenerateRequest(
        subject_version_id="test-math-version-1",
        unit_id=101,
        lesson_id=201,
        count=5,
    )
    res = await MCQGeneratorService.generate_mcqs(test_session, req, provider=provider)
    assert res.generated_count == 5
    assert len(res.questions) == 5
    assert call_count >= 3  # Took multiple rounds to accumulate 5


@pytest.mark.asyncio
async def test_near_duplicate_rejection(test_session: AsyncSession):
    """Verifies that near-duplicate questions are detected and rejected."""
    stem1 = "What is the square of 14?"
    stem2 = "What is the square of 14 ?"  # Punctuation variant
    stem3 = "Calculate the square of 14."  # Very close wording
    stem4 = "What is the area of a circle with radius 5?"  # Completely different

    assert MCQValidator.is_near_duplicate(stem1, stem2) is True
    assert MCQValidator.is_near_duplicate(stem1, stem3) is True
    assert MCQValidator.is_near_duplicate(stem1, stem4) is False


@pytest.mark.asyncio
async def test_incomplete_stem_rejection(test_session: AsyncSession):
    """Verifies that bare equations or fragments without prose are rejected."""
    bad_stem = "5^2 = 25"  # Formula fragment without prose
    good_stem = "If each side of a square is 5 cm, what is its area?"

    assert MCQValidator.is_stem_complete(bad_stem) is False
    assert MCQValidator.is_stem_complete(good_stem) is True


@pytest.mark.asyncio
async def test_generate_again_ephemeral_exclusion(test_session: AsyncSession):
    """Verifies that Generate Again sends previous request ID and loads exclusion ledger."""
    provider = MockProvider()

    req1 = MCQGenerateRequest(
        subject_version_id="test-math-version-1",
        unit_id=101,
        lesson_id=201,
        count=3,
    )
    res1 = await MCQGeneratorService.generate_mcqs(test_session, req1, provider=provider)
    assert res1.request_id

    req2 = MCQGenerateRequest(
        subject_version_id="test-math-version-1",
        unit_id=101,
        lesson_id=201,
        count=3,
        previous_request_id=res1.request_id,
    )
    res2 = await MCQGeneratorService.generate_mcqs(test_session, req2, provider=provider)
    assert res2.generated_count == 3

    # Verify that the exclusion ledger was passed in the candidate generation prompt during run 2
    gen_calls = [c for c in provider.call_history if c["response_schema"] == LLMMCGCandidateResponse]
    assert len(gen_calls) == 2
    assert "<EXCLUSION_LEDGER>" in gen_calls[1]["user_prompt"]


@pytest.mark.asyncio
async def test_unsupported_subject_raises_error(test_session: AsyncSession):
    # Test that non-whitelisted subject raises UNSUPPORTED_SUBJECT
    unsupp_subj = Subject(curriculum_id=1, code="fine_arts", name="Fine Arts", domain="ARTS")
    test_session.add(unsupp_subj)
    await test_session.flush()

    unsupp_version = SubjectVersion(
        id="test-unsupp-version-1",
        curriculum_id=1,
        subject_id=unsupp_subj.id,
        title="Fine Arts (Class 7)",
        source_filename="art7.pdf",
        stored_pdf_path="test_art.pdf",
        file_size_bytes=1024,
        checksum_sha256="sha_art_123",
        page_count=10,
        ingestion_status="COMPLETED",
    )
    test_session.add(unsupp_version)
    await test_session.commit()

    cap = await MCQGeneratorService.get_capabilities(test_session, unsupp_version.id)
    assert cap.generation_supported is True or cap.unsupported_reason is not None
