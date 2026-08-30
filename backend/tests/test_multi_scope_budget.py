import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine, async_sessionmaker

from app.core.database import Base
from app.models.curriculum import Curriculum, Grade, Subject
from app.models.textbook import ActivityNode, CurriculumNode, SubjectVersion
from app.schemas.assessment import MCQGenerateRequest
from app.schemas.llm_mcq import LLMMCGCandidateResponse, LLMMCGItem, LLMMCGOption
from app.services.assessment.generator import MCQGeneratorService
from app.services.assessment.resolver import ScopeCoverageResolver
from app.services.llm.base import LLMProvider
from app.services.llm.budget import ProviderBudget, TokenEstimator
from app.services.llm.groq_provider import _sanitize_error_message
from app.services.llm.mock_provider import MockProvider


@pytest_asyncio.fixture
async def isolated_budget_session():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", echo=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    session_factory = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)
    async with session_factory() as session:
        curriculum = Curriculum(code="NCTB_BUDGET_TEST", name="NCTB Budget Test", country="Bangladesh", authority="MoE")
        session.add(curriculum)
        await session.flush()

        grade = Grade(curriculum_id=curriculum.id, code="class-7", name="Class 7", level_number=7)
        math_subj = Subject(curriculum_id=curriculum.id, code="mathematics", name="Mathematics", domain="STEM")
        session.add_all([grade, math_subj])
        await session.flush()

        # Textbook A (Math 7)
        vA = SubjectVersion(
            id="test-book-A",
            curriculum_id=curriculum.id,
            grade_id=grade.id,
            subject_id=math_subj.id,
            title="Mathematics (Class 7)",
            source_filename="math7.pdf",
            stored_pdf_path="test_math7.pdf",
            file_size_bytes=1024,
            checksum_sha256="sha_A",
            page_count=100,
            ingestion_status="COMPLETED",
        )
        # Textbook B (Another Book)
        vB = SubjectVersion(
            id="test-book-B",
            curriculum_id=curriculum.id,
            grade_id=grade.id,
            subject_id=math_subj.id,
            title="Mathematics (Class 8)",
            source_filename="math8.pdf",
            stored_pdf_path="test_math8.pdf",
            file_size_bytes=1024,
            checksum_sha256="sha_B",
            page_count=100,
            ingestion_status="COMPLETED",
        )
        session.add_all([vA, vB])
        await session.flush()

        # Nodes for Textbook A
        # Chapter 1
        ch1 = CurriculumNode(id="cn_ch1", subject_version_id=vA.id, parent_id=None, node_type="chapter", source_label="Chapter 1", title="Numbers", depth=0, start_pdf_page=1, end_pdf_page=10, ordinal=1)
        # Chapter 3
        ch3 = CurriculumNode(id="cn_ch3", subject_version_id=vA.id, parent_id=None, node_type="chapter", source_label="Chapter 3", title="Measurement", depth=0, start_pdf_page=20, end_pdf_page=30, ordinal=2)
        # Chapter 4
        ch4 = CurriculumNode(id="cn_ch4", subject_version_id=vA.id, parent_id=None, node_type="chapter", source_label="Chapter 4", title="Algebra", depth=0, start_pdf_page=40, end_pdf_page=60, ordinal=3)
        # Sections under Chapter 4
        sec41 = CurriculumNode(id="cn_sec41", subject_version_id=vA.id, parent_id="cn_ch4", node_type="section", source_label="4.1", title="Addition", depth=1, start_pdf_page=40, end_pdf_page=45, ordinal=1)
        sec42 = CurriculumNode(id="cn_sec42", subject_version_id=vA.id, parent_id="cn_ch4", node_type="section", source_label="4.2", title="Multiplication", depth=1, start_pdf_page=46, end_pdf_page=50, ordinal=2)
        sec410 = CurriculumNode(id="cn_sec410", subject_version_id=vA.id, parent_id="cn_ch4", node_type="section", source_label="4.10", title="Polynomial Division", depth=1, start_pdf_page=55, end_pdf_page=60, ordinal=3)

        # Node for Textbook B
        ch_B1 = CurriculumNode(id="cn_B_ch1", subject_version_id=vB.id, parent_id=None, node_type="chapter", source_label="Chapter 1", title="Book B Chapter", depth=0, start_pdf_page=1, end_pdf_page=10, ordinal=1)

        session.add_all([ch1, ch3, ch4, sec41, sec42, sec410, ch_B1])
        await session.flush()

        # Content Nodes
        act_ch1 = ActivityNode(subject_version_id=vA.id, unit_id=1, curriculum_node_id="cn_ch1", ordinal=1, node_type="prose", title="Ch1 Concept", content_text="Rational numbers can be expressed as a/b.", page_number=2, content_hash="h1")
        act_ch3 = ActivityNode(subject_version_id=vA.id, unit_id=1, curriculum_node_id="cn_ch3", ordinal=1, node_type="prose", title="Ch3 Concept", content_text="1 kilometer is equal to 1000 meters.", page_number=22, content_hash="h3")
        act_sec41 = ActivityNode(subject_version_id=vA.id, unit_id=1, curriculum_node_id="cn_sec41", ordinal=1, node_type="prose", title="4.1 Concept", content_text="Algebraic addition combines like terms.", page_number=41, content_hash="h41")
        act_sec42 = ActivityNode(subject_version_id=vA.id, unit_id=1, curriculum_node_id="cn_sec42", ordinal=1, node_type="prose", title="4.2 Concept", content_text="Multiplication of variables adds exponents.", page_number=47, content_hash="h42")
        act_sec410 = ActivityNode(subject_version_id=vA.id, unit_id=1, curriculum_node_id="cn_sec410", ordinal=1, node_type="prose", title="4.10 Concept", content_text="Polynomial division requires descending degree order.", page_number=57, content_hash="h410")

        session.add_all([act_ch1, act_ch3, act_sec41, act_sec42, act_sec410])
        await session.commit()

        yield session

    await engine.dispose()


@pytest.mark.asyncio
async def test_multi_scope_request_and_allocation(isolated_budget_session: AsyncSession):
    """
    Test 1: Multiple Scopes (Chapter 1 + Chapter 3).
    Verifies content collected from both, no duplicate content, allocation covers both.
    """
    plan = await ScopeCoverageResolver.resolve_coverage(
        session=isolated_budget_session,
        subject_version_id="test-book-A",
        scope_node_ids=["cn_ch1", "cn_ch3"],
        requested_count=5,
    )
    assert len(plan.normalized_scope_node_ids) == 2
    assert "cn_ch1" in plan.normalized_scope_node_ids
    assert "cn_ch3" in plan.normalized_scope_node_ids

    # Verify windows cover both chapters
    all_window_text = " ".join(w.formatted_xml for w in plan.source_windows)
    assert "Rational numbers" in all_window_text
    assert "1000 meters" in all_window_text
    assert "Algebraic addition" not in all_window_text


@pytest.mark.asyncio
async def test_partial_chapter_selection(isolated_budget_session: AsyncSession):
    """
    Test 2: Partial Chapter Selection (4.1 + 4.2 only).
    Verifies context does NOT contain unrelated 4.10.
    """
    plan = await ScopeCoverageResolver.resolve_coverage(
        session=isolated_budget_session,
        subject_version_id="test-book-A",
        scope_node_ids=["cn_sec41", "cn_sec42"],
        requested_count=5,
    )
    all_window_text = " ".join(w.formatted_xml for w in plan.source_windows)
    assert "Algebraic addition" in all_window_text
    assert "Multiplication of variables" in all_window_text
    assert "Polynomial division" not in all_window_text


@pytest.mark.asyncio
async def test_overlapping_scope_deduplication(isolated_budget_session: AsyncSession):
    """
    Test 3: Overlapping Selection (Chapter 4 AND 4.1).
    Verifies 4.1 is normalized and not duplicated.
    """
    plan = await ScopeCoverageResolver.resolve_coverage(
        session=isolated_budget_session,
        subject_version_id="test-book-A",
        scope_node_ids=["cn_ch4", "cn_sec41"],
        requested_count=5,
    )
    # Ancestor cn_ch4 covers cn_sec41, so normalized list has only 1 root
    assert len(plan.normalized_scope_node_ids) == 1
    assert plan.normalized_scope_node_ids[0] == "cn_ch4"


@pytest.mark.asyncio
async def test_cross_book_attack_rejected(isolated_budget_session: AsyncSession):
    """
    Test 4: Cross-Book Scope ID Rejection.
    Selected SubjectVersion A + scope_node_id from SubjectVersion B.
    """
    with pytest.raises(ValueError) as exc:
        await ScopeCoverageResolver.resolve_coverage(
            session=isolated_budget_session,
            subject_version_id="test-book-A",
            scope_node_ids=["cn_B_ch1"],
            requested_count=5,
        )
    assert "INVALID_CURRICULUM_SCOPE" in str(exc.value)


def test_token_estimator_and_budget():
    """
    Test 5: Token Estimator and ProviderBudget calculation.
    """
    budget = ProviderBudget(tpm_limit=8000, request_token_target=2800)
    sample_text = "Let $x^2 + y^2 = r^2$ be a circle equation with radius $r$."
    est = TokenEstimator.estimate_text_tokens(sample_text)
    assert est.estimated_tokens > 0
    assert est.character_count == len(sample_text)
    assert budget.is_within_budget(est.estimated_tokens) is True


def test_raw_provider_error_sanitization():
    """
    Test 6: Raw Provider Error Sanitization.
    Verifies URLs, billing links, and keys are stripped from error output.
    """
    raw_error = (
        "Error 413: Request too large for model openai/gpt-oss-120b. "
        "Please visit https://console.groq.com/docs/rate-limits or contact org_998811 for billing. "
        "Key: gsk_abc123def456."
    )
    sanitized = _sanitize_error_message(raw_error)
    assert "https://" not in sanitized
    assert "console.groq.com" not in sanitized
    assert "org_998811" not in sanitized
    assert "gsk_abc123def456" not in sanitized
