import pytest
import pytest_asyncio
import uuid
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine, async_sessionmaker
from sqlalchemy import select

from app.core.database import Base
from app.models.curriculum import Curriculum, Grade, Subject
from app.models.textbook import ActivityNode, CurriculumNode, SubjectVersion
from app.schemas.assessment import MCQGenerateRequest
from app.schemas.llm_mcq import LLMMCGCandidateResponse, LLMMCGItem, LLMMCGOption
from app.services.assessment.context_builder import ContextBuilder
from app.services.assessment.generator import MCQGeneratorService
from app.services.llm.mock_provider import MockProvider


@pytest_asyncio.fixture
async def isolated_session():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", echo=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    session_factory = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)
    async with session_factory() as session:
        curriculum = Curriculum(code="NCTB_GENERIC_TEST", name="NCTB Test", country="Bangladesh", authority="MoE")
        session.add(curriculum)
        await session.flush()

        grade = Grade(curriculum_id=curriculum.id, code="class-7", name="Class 7", level_number=7)
        math_subj = Subject(curriculum_id=curriculum.id, code="mathematics", name="Mathematics", domain="STEM")
        eft_subj = Subject(curriculum_id=curriculum.id, code="english-for-today", name="English for Today", domain="LANGUAGE")
        eg_subj = Subject(curriculum_id=curriculum.id, code="english-grammar", name="English Grammar and Composition", domain="LANGUAGE")

        session.add_all([grade, math_subj, eft_subj, eg_subj])
        await session.commit()
        yield session

    await engine.dispose()


@pytest.mark.asyncio
async def test_synthetic_structural_test_a_unit_lesson_activity(isolated_session: AsyncSession):
    """
    Synthetic Structural Test A:
    Hierarchy: Unit -> Lesson -> Activity
    Verifies generic persistence, capabilities scope_tree, and scope resolver.
    """
    from app.core.config import settings
    (settings.STORAGE_ROOT / "test_eft.pdf").parent.mkdir(parents=True, exist_ok=True)
    (settings.STORAGE_ROOT / "test_eft.pdf").touch()

    version = SubjectVersion(
        id="test-eft-version-1",
        curriculum_id=1,
        grade_id=1,
        subject_id=2,
        title="English for Today (Class 7)",
        source_filename="eft7.pdf",
        stored_pdf_path="test_eft.pdf",
        file_size_bytes=1024,
        checksum_sha256="sha_eft_1",
        page_count=50,
        ingestion_status="COMPLETED",
        curriculum_quality_status="VALID",
        metadata_status="VALID",
    )
    isolated_session.add(version)
    await isolated_session.flush()

    # Unit 1
    u1 = CurriculumNode(
        id="cnode_eft_u1",
        subject_version_id=version.id,
        parent_id=None,
        node_type="unit",
        source_label="Unit 1",
        title="People Who Stand Out",
        detected_number="1",
        ordinal=1,
        depth=0,
        start_pdf_page=1,
        end_pdf_page=10,
    )
    isolated_session.add(u1)
    await isolated_session.flush()

    # Lesson 1
    l1 = CurriculumNode(
        id="cnode_eft_l1",
        subject_version_id=version.id,
        parent_id=u1.id,
        node_type="lesson",
        source_label="Lesson 1",
        title="Zainul Abedin, the Great Artist",
        detected_number="1",
        ordinal=1,
        depth=1,
        start_pdf_page=1,
        end_pdf_page=5,
    )
    isolated_session.add(l1)
    await isolated_session.flush()

    # Activity 1
    act1 = CurriculumNode(
        id="cnode_eft_act1",
        subject_version_id=version.id,
        parent_id=l1.id,
        node_type="activity",
        source_label="Activity A",
        title="Reading Comprehension Passage",
        detected_number="A",
        ordinal=1,
        depth=2,
        start_pdf_page=1,
        end_pdf_page=2,
    )
    isolated_session.add(act1)
    await isolated_session.flush()

    # ActivityNode content
    node1 = ActivityNode(
        subject_version_id=version.id,
        unit_id=1,
        curriculum_node_id=act1.id,
        ordinal=1,
        node_type="prose",
        title="Passage",
        content_text="Zainul Abedin was born in Kishoreganj on 29 December 1914. He pioneered modern art in Bangladesh and designed the Nabanna exhibition.",
        page_number=1,
        content_hash="hash_eft_1",
    )
    isolated_session.add(node1)
    await isolated_session.commit()

    # 1. Test Capabilities Scope Tree
    cap = await MCQGeneratorService.get_capabilities(isolated_session, version.id)
    assert cap.generation_supported is True
    assert len(cap.scope_tree) == 1
    root = cap.scope_tree[0]
    assert root.node_type == "unit"
    assert root.source_label == "Unit 1"
    assert len(root.children) == 1
    child_lesson = root.children[0]
    assert child_lesson.node_type == "lesson"
    assert len(child_lesson.children) == 1
    child_act = child_lesson.children[0]
    assert child_act.node_type == "activity"

    # 2. Test Context Builder Subtree Resolution
    ctx = await ContextBuilder.build_context(isolated_session, version.id, scope_node_id=child_act.id)
    assert "Zainul Abedin" in ctx.formatted_source_text
    assert ctx.subject_code in ["english_for_today", "english-for-today"]


@pytest.mark.asyncio
async def test_synthetic_structural_test_b_chapter_section_exercise(isolated_session: AsyncSession):
    """
    Synthetic Structural Test B:
    Hierarchy: Chapter -> Section -> Exercise
    Verifies the SAME code handles Math/Science style hierarchy without hardcoding.
    """
    from app.core.config import settings
    (settings.STORAGE_ROOT / "test_math.pdf").parent.mkdir(parents=True, exist_ok=True)
    (settings.STORAGE_ROOT / "test_math.pdf").touch()

    version = SubjectVersion(
        id="test-math-struct-b",
        curriculum_id=1,
        grade_id=1,
        subject_id=1,
        title="Mathematics (Class 7)",
        source_filename="math7.pdf",
        stored_pdf_path="test_math.pdf",
        file_size_bytes=1024,
        checksum_sha256="sha_math_b",
        page_count=100,
        ingestion_status="COMPLETED",
        curriculum_quality_status="VALID",
        metadata_status="VALID",
    )
    isolated_session.add(version)
    await isolated_session.flush()

    ch1 = CurriculumNode(
        id="cnode_m_ch1",
        subject_version_id=version.id,
        parent_id=None,
        node_type="chapter",
        source_label="Chapter 1",
        title="Rational and Irrational Numbers",
        detected_number="1",
        ordinal=1,
        depth=0,
        start_pdf_page=6,
        end_pdf_page=20,
    )
    isolated_session.add(ch1)
    await isolated_session.flush()

    sec1 = CurriculumNode(
        id="cnode_m_sec1",
        subject_version_id=version.id,
        parent_id=ch1.id,
        node_type="section",
        source_label="1.1",
        title="Squares and square roots",
        detected_number="1.1",
        ordinal=1,
        depth=1,
        start_pdf_page=6,
        end_pdf_page=10,
    )
    isolated_session.add(sec1)
    await isolated_session.flush()

    ex1 = CurriculumNode(
        id="cnode_m_ex1",
        subject_version_id=version.id,
        parent_id=sec1.id,
        node_type="exercise",
        source_label="Exercise 1.1",
        title="Exercise 1.1",
        detected_number="1.1",
        ordinal=1,
        depth=2,
        start_pdf_page=9,
        end_pdf_page=10,
    )
    isolated_session.add(ex1)

    node1 = ActivityNode(
        subject_version_id=version.id,
        unit_id=1,
        curriculum_node_id=ex1.id,
        ordinal=1,
        node_type="exercise",
        title="Problem 1",
        content_text="Which of the following numbers is a perfect square? 16, 20, 24, 30.",
        page_number=9,
        content_hash="hash_m_ex1",
    )
    isolated_session.add(node1)
    await isolated_session.commit()

    cap = await MCQGeneratorService.get_capabilities(isolated_session, version.id)
    assert cap.generation_supported is True
    assert cap.scope_tree[0].node_type == "chapter"
    assert cap.scope_tree[0].children[0].node_type == "section"
    assert cap.scope_tree[0].children[0].children[0].node_type == "exercise"


@pytest.mark.asyncio
async def test_synthetic_structural_test_c_arbitrary_deep_hierarchy(isolated_session: AsyncSession):
    """
    Synthetic Structural Test C:
    Hierarchy: Part -> Unit -> Lesson -> Activity -> Task (depth 0 to 4)
    Verifies that arbitrary depth requires zero schema changes.
    """
    from app.core.config import settings
    (settings.STORAGE_ROOT / "comp.pdf").parent.mkdir(parents=True, exist_ok=True)
    (settings.STORAGE_ROOT / "comp.pdf").touch()

    version = SubjectVersion(
        id="test-deep-tree-1",
        curriculum_id=1,
        grade_id=1,
        subject_id=2,
        title="Comprehensive English (Class 9)",
        source_filename="comp.pdf",
        stored_pdf_path="comp.pdf",
        file_size_bytes=1024,
        checksum_sha256="sha_deep_1",
        page_count=200,
        ingestion_status="COMPLETED",
        curriculum_quality_status="VALID",
        metadata_status="VALID",
    )
    isolated_session.add(version)
    await isolated_session.flush()

    p1 = CurriculumNode(
        id="cnode_p1",
        subject_version_id=version.id,
        parent_id=None,
        node_type="part",
        source_label="Part I",
        title="Foundation",
        detected_number="I",
        ordinal=1,
        depth=0,
        start_pdf_page=1,
        end_pdf_page=50,
    )
    isolated_session.add(p1)
    await isolated_session.flush()

    u1 = CurriculumNode(
        id="cnode_u1",
        subject_version_id=version.id,
        parent_id=p1.id,
        node_type="unit",
        source_label="Unit 1",
        title="Grammar Basics",
        detected_number="1",
        ordinal=1,
        depth=1,
        start_pdf_page=1,
        end_pdf_page=20,
    )
    isolated_session.add(u1)
    await isolated_session.flush()

    l1 = CurriculumNode(
        id="cnode_l1",
        subject_version_id=version.id,
        parent_id=u1.id,
        node_type="lesson",
        source_label="Lesson 1",
        title="Nouns and Pronouns",
        detected_number="1",
        ordinal=1,
        depth=2,
        start_pdf_page=1,
        end_pdf_page=10,
    )
    isolated_session.add(l1)
    await isolated_session.flush()

    act1 = CurriculumNode(
        id="cnode_act1",
        subject_version_id=version.id,
        parent_id=l1.id,
        node_type="activity",
        source_label="Activity A",
        title="Identify Nouns",
        detected_number="A",
        ordinal=1,
        depth=3,
        start_pdf_page=2,
        end_pdf_page=3,
    )
    isolated_session.add(act1)
    await isolated_session.flush()

    task1 = CurriculumNode(
        id="cnode_task1",
        subject_version_id=version.id,
        parent_id=act1.id,
        node_type="task",
        source_label="Task 1",
        title="Underline Proper Nouns",
        detected_number="1",
        ordinal=1,
        depth=4,
        start_pdf_page=2,
        end_pdf_page=2,
    )
    isolated_session.add(task1)

    node = ActivityNode(
        subject_version_id=version.id,
        unit_id=1,
        curriculum_node_id=task1.id,
        ordinal=1,
        node_type="task",
        title="Proper Nouns in Dhaka",
        content_text="Dhaka is the capital of Bangladesh. It is located on the Buriganga River.",
        page_number=2,
        content_hash="hash_deep_task",
    )
    isolated_session.add(node)
    await isolated_session.commit()

    cap = await MCQGeneratorService.get_capabilities(isolated_session, version.id)
    assert cap.generation_supported is True
    # Verify 5-level deep hierarchy
    assert cap.scope_tree[0].node_type == "part"
    assert cap.scope_tree[0].depth == 0
    assert cap.scope_tree[0].children[0].node_type == "unit"
    assert cap.scope_tree[0].children[0].depth == 1
    assert cap.scope_tree[0].children[0].children[0].node_type == "lesson"
    assert cap.scope_tree[0].children[0].children[0].depth == 2
    assert cap.scope_tree[0].children[0].children[0].children[0].node_type == "activity"
    assert cap.scope_tree[0].children[0].children[0].children[0].depth == 3
    assert cap.scope_tree[0].children[0].children[0].children[0].children[0].node_type == "task"
    assert cap.scope_tree[0].children[0].children[0].children[0].children[0].depth == 4


@pytest.mark.asyncio
async def test_english_for_today_readiness(isolated_session: AsyncSession):
    """
    Verifies English for Today profile resolution, passage-grounding,
    and generic generation pipeline using MockProvider.
    """
    from app.core.config import settings
    (settings.STORAGE_ROOT / "test_eft_ready.pdf").parent.mkdir(parents=True, exist_ok=True)
    (settings.STORAGE_ROOT / "test_eft_ready.pdf").touch()

    version = SubjectVersion(
        id="test-eft-ready-1",
        curriculum_id=1,
        grade_id=1,
        subject_id=2,
        title="English for Today (Class 9)",
        source_filename="eft9.pdf",
        stored_pdf_path="test_eft_ready.pdf",
        file_size_bytes=1024,
        checksum_sha256="sha_eft_ready",
        page_count=30,
        ingestion_status="COMPLETED",
        curriculum_quality_status="VALID",
        metadata_status="VALID",
    )
    isolated_session.add(version)
    await isolated_session.flush()

    u1 = CurriculumNode(
        id="cnode_eft_r_u1",
        subject_version_id=version.id,
        parent_id=None,
        node_type="unit",
        source_label="Unit 1",
        title="Good Citizens",
        detected_number="1",
        ordinal=1,
        depth=0,
        start_pdf_page=1,
        end_pdf_page=10,
    )
    isolated_session.add(u1)

    node = ActivityNode(
        subject_version_id=version.id,
        unit_id=1,
        curriculum_node_id=u1.id,
        ordinal=1,
        node_type="dialogue",
        title="Can you live alone?",
        content_text="Long ago, a young man found life in the village full of problems. So he left his house and went to a forest to live by himself. There he made a nice little hut with bamboo, reeds, and leaves.",
        page_number=2,
        content_hash="hash_eft_dialogue",
    )
    isolated_session.add(node)
    await isolated_session.commit()

    provider = MockProvider()
    req = MCQGenerateRequest(
        subject_version_id=version.id,
        scope_node_id=u1.id,
        count=5,
    )
    res = await MCQGeneratorService.generate_mcqs(isolated_session, req, provider=provider)
    assert res.generated_count == 5
    assert len(res.questions) == 5
    # Verify the prompt included English for Today subject profile
    call = provider.call_history[0]
    assert "NCTB ENGLISH FOR TODAY" in call["system_instruction"] or "Passage-Grounded Comprehension" in call["system_instruction"]


@pytest.mark.asyncio
async def test_english_grammar_readiness(isolated_session: AsyncSession):
    """
    Verifies English Grammar profile resolution, rule-grounding,
    and generic generation pipeline using MockProvider.
    """
    from app.core.config import settings
    (settings.STORAGE_ROOT / "test_eg9.pdf").parent.mkdir(parents=True, exist_ok=True)
    (settings.STORAGE_ROOT / "test_eg9.pdf").touch()

    version = SubjectVersion(
        id="test-eg-ready-1",
        curriculum_id=1,
        grade_id=1,
        subject_id=3,
        title="English Grammar and Composition (Class 9)",
        source_filename="eg9.pdf",
        stored_pdf_path="test_eg9.pdf",
        file_size_bytes=1024,
        checksum_sha256="sha_eg_ready",
        page_count=40,
        ingestion_status="COMPLETED",
        curriculum_quality_status="VALID",
        metadata_status="VALID",
    )
    isolated_session.add(version)
    await isolated_session.flush()

    ch1 = CurriculumNode(
        id="cnode_eg_r_ch1",
        subject_version_id=version.id,
        parent_id=None,
        node_type="chapter",
        source_label="Chapter 2",
        title="Tenses and Modals",
        detected_number="2",
        ordinal=1,
        depth=0,
        start_pdf_page=15,
        end_pdf_page=25,
    )
    isolated_session.add(ch1)

    node = ActivityNode(
        subject_version_id=version.id,
        unit_id=1,
        curriculum_node_id=ch1.id,
        ordinal=1,
        node_type="rule",
        title="Present Continuous Tense",
        content_text="The Present Continuous tense is used for an action going on at the time of speaking. Structure: Subject + am/is/are + verb-ing. Example: She is reading a book.",
        page_number=16,
        content_hash="hash_eg_rule",
    )
    isolated_session.add(node)
    await isolated_session.commit()

    provider = MockProvider()
    req = MCQGenerateRequest(
        subject_version_id=version.id,
        scope_node_id=ch1.id,
        count=5,
    )
    res = await MCQGeneratorService.generate_mcqs(isolated_session, req, provider=provider)
    assert res.generated_count == 5
    call = provider.call_history[0]
    assert "NCTB ENGLISH GRAMMAR" in call["system_instruction"] or "Rule & Application Focus" in call["system_instruction"]
