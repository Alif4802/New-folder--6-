import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.curriculum import Curriculum, Grade, Subject
from app.models.question_bank import (
    QuestionBankItem,
    QuestionBankOption,
    QuestionSet,
    QuestionSetItem,
)
from app.models.textbook import ActivityNode, CurriculumNode, SubjectVersion
from app.schemas.llm_mcq import LLMMCGItem, LLMMCGOption
from app.schemas.question_bank import (
    PaperMetadataSchema,
    QuestionArrangementRequest,
    SavePaperRequest,
)
from app.services.assessment.job_service import GenerationJob, GenerationJobService
from app.services.assessment.resolver import SourceChunk
from app.services.question_bank.bank_service import QuestionBankService
from app.services.question_bank.paper_service import QuestionPaperService


@pytest.fixture
async def sample_math_subject(db_session: AsyncSession):
    """Creates a sample SubjectVersion with curriculum structure."""
    curriculum = Curriculum(
        code="NCTB_PAPER_TEST",
        name="NCTB Paper Test Curriculum",
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
        id="subver_math_paper_test",
        curriculum_id=curriculum.id,
        subject_id=subject.id,
        grade_id=grade.id,
        title="Mathematics — Class 7",
        source_filename="math7.pdf",
        stored_pdf_path="storage/pdfs/math7.pdf",
        file_size_bytes=10240,
        checksum_sha256="checksum_paper_math_test",
        page_count=100,
        ingestion_status="COMPLETED",
    )
    db_session.add(version)
    await db_session.flush()

    cnode_chap1 = CurriculumNode(
        id="cnode_paper_ch1",
        subject_version_id=version.id,
        node_type="chapter",
        source_label="Chapter 1",
        title="Rational and Irrational Numbers",
        detected_number="1",
        ordinal=1,
        depth=0,
        start_pdf_page=1,
        end_pdf_page=20,
    )
    db_session.add(cnode_chap1)
    await db_session.commit()

    return {
        "version_id": version.id,
        "chap1_id": cnode_chap1.id,
    }


@pytest.mark.asyncio
async def test_save_paper_from_bank_items_and_reopen_exact_order(
    db_session: AsyncSession,
    sample_math_subject: dict,
):
    """
    Verifies saving a paper from existing bank items with custom option ordering,
    reopening it, and confirming the exact question order, option order, and dynamic Answer Key.
    """
    vid = sample_math_subject["version_id"]

    # 1. Create two bank items in DB
    qbi1 = QuestionBankItem(
        id="qbi_p1",
        subject_version_id=vid,
        question_type="MCQ",
        language="en",
        question_text="Which number is a prime number?",
        explanation="2 is the only even prime number.",
        content_hash="hash_p1",
        status="ACTIVE",
    )
    opt1_1 = QuestionBankOption(id="opt_p1_1", question_id="qbi_p1", option_text="2", canonical_order=0)
    opt1_2 = QuestionBankOption(id="opt_p1_2", question_id="qbi_p1", option_text="4", canonical_order=1)
    opt1_3 = QuestionBankOption(id="opt_p1_3", question_id="qbi_p1", option_text="6", canonical_order=2)
    opt1_4 = QuestionBankOption(id="opt_p1_4", question_id="qbi_p1", option_text="8", canonical_order=3)
    db_session.add_all([qbi1, opt1_1, opt1_2, opt1_3, opt1_4])
    await db_session.flush()
    qbi1.correct_option_id = opt1_1.id

    qbi2 = QuestionBankItem(
        id="qbi_p2",
        subject_version_id=vid,
        question_type="MCQ",
        language="en",
        question_text="What is the value of $\\sqrt{49}$?",
        explanation="$\\sqrt{49} = 7$.",
        content_hash="hash_p2",
        status="ACTIVE",
    )
    opt2_1 = QuestionBankOption(id="opt_p2_1", question_id="qbi_p2", option_text="7", canonical_order=0)
    opt2_2 = QuestionBankOption(id="opt_p2_2", question_id="qbi_p2", option_text="6", canonical_order=1)
    opt2_3 = QuestionBankOption(id="opt_p2_3", question_id="qbi_p2", option_text="8", canonical_order=2)
    opt2_4 = QuestionBankOption(id="opt_p2_4", question_id="qbi_p2", option_text="9", canonical_order=3)
    db_session.add_all([qbi2, opt2_1, opt2_2, opt2_3, opt2_4])
    await db_session.flush()
    qbi2.correct_option_id = opt2_1.id

    await db_session.commit()

    # 2. Arrange questions and shuffle options
    # In Question 1: place correct answer (opt_p1_1) at index 2 -> Label 'C'
    # In Question 2: place correct answer (opt_p2_1) at index 3 -> Label 'D'
    arrangements = [
        QuestionArrangementRequest(
            question_id="qbi_p2",
            question_order=1,  # Question 2 becomes Question 1 in this paper
            option_order=["opt_p2_2", "opt_p2_3", "opt_p2_4", "opt_p2_1"],  # opt_p2_1 is at index 3 -> 'D'
        ),
        QuestionArrangementRequest(
            question_id="qbi_p1",
            question_order=2,  # Question 1 becomes Question 2 in this paper
            option_order=["opt_p1_2", "opt_p1_3", "opt_p1_1", "opt_p1_4"],  # opt_p1_1 is at index 2 -> 'C'
        ),
    ]

    header_meta = PaperMetadataSchema(
        institution_name="Test High School",
        exam_title="Class 7 Mathematics Midterm",
        duration_minutes=20,
        marks_per_question=1.0,
        total_marks=2.0,
        instructions="Answer all questions carefully.",
    )

    save_req = SavePaperRequest(
        subject_version_id=vid,
        title="Midterm Math Exam Set A",
        description="Term 1 exam",
        paper_metadata=header_meta,
        arrangements=arrangements,
        scope_node_ids=[sample_math_subject["chap1_id"]],
    )

    # Save Paper
    saved_paper = await QuestionPaperService.save_paper(db_session, save_req)
    assert saved_paper.id.startswith("qset_")
    assert saved_paper.question_count == 2
    assert saved_paper.title == "Midterm Math Exam Set A"
    assert saved_paper.paper_metadata.institution_name == "Test High School"

    # 3. Reload Paper and verify exact arrangement restoration
    reloaded = await QuestionPaperService.get_paper(db_session, saved_paper.id)
    assert reloaded is not None
    assert len(reloaded.questions) == 2

    # Check Question 1 (was qbi_p2)
    q1 = reloaded.questions[0]
    assert q1.question_number == 1
    assert q1.id == "qbi_p2"
    assert [o.id for o in q1.options] == ["opt_p2_2", "opt_p2_3", "opt_p2_4", "opt_p2_1"]
    assert [o.label for o in q1.options] == ["A", "B", "C", "D"]

    ak1 = reloaded.answer_key[0]
    assert ak1.question_number == 1
    assert ak1.correct_letter == "D", "Correct option at index 3 must map to 'D'."
    assert ak1.correct_text == "7"

    # Check Question 2 (was qbi_p1)
    q2 = reloaded.questions[1]
    assert q2.question_number == 2
    assert q2.id == "qbi_p1"
    assert [o.id for o in q2.options] == ["opt_p1_2", "opt_p1_3", "opt_p1_1", "opt_p1_4"]

    ak2 = reloaded.answer_key[1]
    assert ak2.question_number == 2
    assert ak2.correct_letter == "C", "Correct option at index 2 must map to 'C'."
    assert ak2.correct_text == "2"


@pytest.mark.asyncio
async def test_anti_tampering_validations(
    db_session: AsyncSession,
    sample_math_subject: dict,
):
    """Verifies that tampering attempts are rejected with clear validation errors."""
    vid = sample_math_subject["version_id"]

    qbi = QuestionBankItem(
        id="qbi_valid_1",
        subject_version_id=vid,
        question_type="MCQ",
        language="en",
        question_text="What is $2 + 2$?",
        explanation="2 + 2 = 4",
        content_hash="hash_valid_1",
        status="ACTIVE",
    )
    opt1 = QuestionBankOption(id="opt_v1_1", question_id="qbi_valid_1", option_text="4", canonical_order=0)
    opt2 = QuestionBankOption(id="opt_v1_2", question_id="qbi_valid_1", option_text="3", canonical_order=1)
    opt3 = QuestionBankOption(id="opt_v1_3", question_id="qbi_valid_1", option_text="5", canonical_order=2)
    opt4 = QuestionBankOption(id="opt_v1_4", question_id="qbi_valid_1", option_text="6", canonical_order=3)
    db_session.add_all([qbi, opt1, opt2, opt3, opt4])
    await db_session.flush()
    qbi.correct_option_id = opt1.id
    await db_session.commit()

    # 1. Tamper: duplicate option IDs
    with pytest.raises(ValueError, match="DUPLICATE_OPTION_IDS"):
        await QuestionPaperService.save_paper(
            db_session,
            SavePaperRequest(
                subject_version_id=vid,
                title="Tampered Paper",
                arrangements=[
                    QuestionArrangementRequest(
                        question_id="qbi_valid_1",
                        question_order=1,
                        option_order=["opt_v1_1", "opt_v1_1", "opt_v1_3", "opt_v1_4"],
                    )
                ],
            ),
        )

    # 2. Tamper: foreign option ID belonging to another question
    with pytest.raises(ValueError, match="FOREIGN_OPTION_ID"):
        await QuestionPaperService.save_paper(
            db_session,
            SavePaperRequest(
                subject_version_id=vid,
                title="Tampered Paper",
                arrangements=[
                    QuestionArrangementRequest(
                        question_id="qbi_valid_1",
                        question_order=1,
                        option_order=["opt_v1_1", "opt_foreign_99", "opt_v1_3", "opt_v1_4"],
                    )
                ],
            ),
        )

    # 3. Tamper: missing correct option
    with pytest.raises(ValueError, match="CORRECT_OPTION_MISSING|FOREIGN_OPTION_ID|INVALID_OPTION_COUNT"):
        await QuestionPaperService.save_paper(
            db_session,
            SavePaperRequest(
                subject_version_id=vid,
                title="Tampered Paper",
                arrangements=[
                    QuestionArrangementRequest(
                        question_id="qbi_valid_1",
                        question_order=1,
                        option_order=["opt_v1_2", "opt_v1_3", "opt_v1_4"],  # only 3 options
                    )
                ],
            ),
        )

    # 4. Tamper: duplicate question order
    with pytest.raises(ValueError, match="DUPLICATE_QUESTION_ORDER"):
        await QuestionPaperService.save_paper(
            db_session,
            SavePaperRequest(
                subject_version_id=vid,
                title="Tampered Paper",
                arrangements=[
                    QuestionArrangementRequest(
                        question_id="qbi_valid_1",
                        question_order=1,
                        option_order=["opt_v1_1", "opt_v1_2", "opt_v1_3", "opt_v1_4"],
                    ),
                    QuestionArrangementRequest(
                        question_id="qbi_valid_1",
                        question_order=1,  # Duplicate order
                        option_order=["opt_v1_1", "opt_v1_2", "opt_v1_3", "opt_v1_4"],
                    ),
                ],
            ),
        )


@pytest.mark.asyncio
async def test_archiving_paper_preserves_bank_items(
    db_session: AsyncSession,
    sample_math_subject: dict,
):
    """Confirms that archiving a QuestionSet leaves underlying QuestionBankItems completely intact."""
    vid = sample_math_subject["version_id"]

    qbi = QuestionBankItem(
        id="qbi_preserve_test",
        subject_version_id=vid,
        question_type="MCQ",
        language="en",
        question_text="What is $10 + 20$?",
        explanation="10 + 20 = 30",
        content_hash="hash_pres_test",
        status="ACTIVE",
    )
    opt1 = QuestionBankOption(id="opt_pt_1", question_id="qbi_preserve_test", option_text="30", canonical_order=0)
    opt2 = QuestionBankOption(id="opt_pt_2", question_id="qbi_preserve_test", option_text="20", canonical_order=1)
    opt3 = QuestionBankOption(id="opt_pt_3", question_id="qbi_preserve_test", option_text="40", canonical_order=2)
    opt4 = QuestionBankOption(id="opt_pt_4", question_id="qbi_preserve_test", option_text="50", canonical_order=3)
    db_session.add_all([qbi, opt1, opt2, opt3, opt4])
    await db_session.flush()
    qbi.correct_option_id = opt1.id
    await db_session.commit()

    saved_paper = await QuestionPaperService.save_paper(
        db_session,
        SavePaperRequest(
            subject_version_id=vid,
            title="Disposable Paper",
            arrangements=[
                QuestionArrangementRequest(
                    question_id="qbi_preserve_test",
                    question_order=1,
                    option_order=["opt_pt_1", "opt_pt_2", "opt_pt_3", "opt_pt_4"],
                )
            ],
        ),
    )

    # Archive the paper
    archived = await QuestionPaperService.archive_paper(db_session, saved_paper.id, archive=True)
    assert archived is True

    # Paper status is ARCHIVED
    reloaded_paper = await QuestionPaperService.get_paper(db_session, saved_paper.id)
    assert reloaded_paper.status == "ARCHIVED"

    # But QuestionBankItem is STILL ACTIVE and unmodified!
    qbi_check = await QuestionBankService.get_question(db_session, "qbi_preserve_test")
    assert qbi_check is not None
    assert qbi_check.status == "ACTIVE"


@pytest.mark.asyncio
async def test_saved_papers_api_http(
    client: AsyncClient,
    sample_math_subject: dict,
    db_session: AsyncSession,
):
    """Verifies Saved Papers API endpoints over HTTP."""
    vid = sample_math_subject["version_id"]

    # 1. Setup bank item
    qbi = QuestionBankItem(
        id="qbi_http_paper_1",
        subject_version_id=vid,
        question_type="MCQ",
        language="en",
        question_text="What is $12 \\div 3$?",
        explanation="12 / 3 = 4",
        content_hash="hash_http_p1",
        status="ACTIVE",
    )
    opt1 = QuestionBankOption(id="opt_hp_1", question_id="qbi_http_paper_1", option_text="4", canonical_order=0)
    opt2 = QuestionBankOption(id="opt_hp_2", question_id="qbi_http_paper_1", option_text="3", canonical_order=1)
    opt3 = QuestionBankOption(id="opt_hp_3", question_id="qbi_http_paper_1", option_text="2", canonical_order=2)
    opt4 = QuestionBankOption(id="opt_hp_4", question_id="qbi_http_paper_1", option_text="5", canonical_order=3)
    db_session.add_all([qbi, opt1, opt2, opt3, opt4])
    await db_session.flush()
    qbi.correct_option_id = opt1.id
    await db_session.commit()

    # 2. POST save paper
    payload = {
        "subject_version_id": vid,
        "title": "HTTP Quiz Paper",
        "description": "Weekly quiz",
        "paper_metadata": {
            "institution_name": "NCTB Academy",
            "exam_title": "Weekly Math Quiz",
            "duration_minutes": 15,
            "marks_per_question": 1.0,
        },
        "arrangements": [
            {
                "question_id": "qbi_http_paper_1",
                "question_order": 1,
                "option_order": ["opt_hp_2", "opt_hp_1", "opt_hp_3", "opt_hp_4"],  # opt_hp_1 is index 1 -> 'B'
            }
        ],
    }

    create_resp = await client.post("/api/v1/question-bank/papers", json=payload)
    assert create_resp.status_code == 201
    paper_data = create_resp.json()
    paper_id = paper_data["id"]
    assert paper_data["title"] == "HTTP Quiz Paper"
    assert paper_data["answer_key"][0]["correct_letter"] == "B"

    # 3. GET list papers
    list_resp = await client.get(f"/api/v1/question-bank/papers?subject_version_id={vid}")
    assert list_resp.status_code == 200
    assert list_resp.json()["total_count"] >= 1

    # 4. GET single paper
    get_resp = await client.get(f"/api/v1/question-bank/papers/{paper_id}")
    assert get_resp.status_code == 200
    assert get_resp.json()["id"] == paper_id

    # 5. DELETE (archive) paper
    del_resp = await client.delete(f"/api/v1/question-bank/papers/{paper_id}")
    assert del_resp.status_code == 200
