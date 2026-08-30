import pytest
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from app.models.curriculum import Curriculum, Grade, Subject
from app.models.textbook import SubjectVersion, Unit, Lesson, ActivityNode


@pytest.mark.asyncio
async def test_curriculum_and_hierarchy_creation(db_session: AsyncSession):
    """Test creating curriculum, grade, subject, and cascading versions."""
    res = await db_session.execute(select(Curriculum).where(Curriculum.code == "NCTB"))
    curriculum = res.scalar_one_or_none()
    assert curriculum is not None
    assert curriculum.code == "NCTB"

    # Fetch seeded Grade or create test grade
    grade_res = await db_session.execute(
        select(Grade).where(Grade.curriculum_id == curriculum.id, Grade.code == "class-9")
    )
    grade = grade_res.scalar_one_or_none()
    if not grade:
        grade = Grade(curriculum_id=curriculum.id, code="class-9", name="Class 9", level_number=9)
        db_session.add(grade)

    # Create Subject with unique code
    subject = Subject(curriculum_id=curriculum.id, code="test-subject-math", name="Mathematics Test", domain="STEM")
    db_session.add(subject)
    await db_session.commit()

    # Create SubjectVersion, Unit, Lesson, ActivityNode
    version = SubjectVersion(
        id="test-uuid-1",
        curriculum_id=curriculum.id,
        grade_id=grade.id,
        subject_id=subject.id,
        title="Mathematics (Class 9)",
        edition_year=2024,
        source_filename="math_class_9.pdf",
        stored_pdf_path="pdfs/test-uuid-1.pdf",
        file_size_bytes=1024,
        checksum_sha256="abc123sha",
        page_count=10,
        ingestion_status="COMPLETED",
    )
    db_session.add(version)
    await db_session.flush()

    unit = Unit(
        subject_version_id=version.id,
        ordinal=1,
        detected_number="1",
        label_type="Chapter",
        title="Real Numbers",
        start_page=1,
        end_page=5,
    )
    db_session.add(unit)
    await db_session.flush()

    lesson = Lesson(
        unit_id=unit.id,
        ordinal=1,
        detected_number="1.1",
        title="Introduction to Real Numbers",
        start_page=1,
        end_page=3,
    )
    db_session.add(lesson)
    await db_session.flush()

    node = ActivityNode(
        subject_version_id=version.id,
        unit_id=unit.id,
        lesson_id=lesson.id,
        ordinal=1,
        node_type="definition",
        title="Definition of Rational Number",
        content_text="A rational number is any number...",
        page_number=1,
        bounding_box={"x0": 10.0, "y0": 20.0, "x1": 200.0, "y1": 50.0},
        content_hash="hash123",
    )
    db_session.add(node)
    await db_session.commit()

    # Verify query using selectinload for async relationship loading
    from sqlalchemy.orm import selectinload
    ver_res = await db_session.execute(
        select(SubjectVersion)
        .where(SubjectVersion.id == "test-uuid-1")
        .options(
            selectinload(SubjectVersion.units)
            .selectinload(Unit.lessons)
            .selectinload(Lesson.activity_nodes)
        )
    )
    fetched_ver = ver_res.scalar_one()
    assert fetched_ver.title == "Mathematics (Class 9)"
    assert len(fetched_ver.units) == 1
    assert len(fetched_ver.units[0].lessons) == 1
    assert len(fetched_ver.units[0].lessons[0].activity_nodes) == 1


@pytest.mark.asyncio
async def test_grade_curriculum_scoped_uniqueness(db_session: AsyncSession):
    """Test unique constraint on (curriculum_id, code)."""
    res = await db_session.execute(select(Curriculum).where(Curriculum.code == "NCTB"))
    curriculum = res.scalar_one()

    grade1 = Grade(curriculum_id=curriculum.id, code="class-test-unique", name="Class Test 1")
    db_session.add(grade1)
    await db_session.commit()

    grade2 = Grade(curriculum_id=curriculum.id, code="class-test-unique", name="Class Test 2")
    db_session.add(grade2)
    with pytest.raises(IntegrityError):
        await db_session.commit()
