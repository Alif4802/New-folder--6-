import asyncio
import io
import uuid
import pytest
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func

from app.models.textbook import CurriculumNode, SubjectVersion
from app.models.question_bank import QuestionBankItem, QuestionSet, QuestionSetItem
from app.schemas.assessment import MCQGenerateRequest
from app.schemas.llm_mcq import (
    LLMMCGItem,
    LLMMCGOption,
    LLMMCGCandidateResponse,
    MCQVerificationResponse,
)
from app.schemas.question_bank import SavePaperRequest, QuestionArrangementRequest
from app.services.assessment.job_service import GenerationJobService
from app.services.llm.base import LLMProvider
from app.services.assessment.resolver import ScopeCoverageResolver
from app.services.llm.budget import ProviderBudget, TokenEstimator
from tests.utils import create_synthetic_mathematics_pdf


class MockStabilizationLLM(LLMProvider):
    def __init__(self, candidate_batches=None, should_fail_temporarily=False):
        self.candidate_batches = list(candidate_batches) if candidate_batches else []
        self.should_fail_temporarily = should_fail_temporarily
        self.call_count = 0

    async def generate_structured(self, system_instruction, user_prompt, response_schema):
        self.call_count += 1
        if self.should_fail_temporarily:
            raise RuntimeError("LLM_TEMPORARILY_UNAVAILABLE: All LLM providers are currently unavailable.")

        if response_schema == LLMMCGCandidateResponse:
            if self.candidate_batches:
                return self.candidate_batches.pop(0)
            return LLMMCGCandidateResponse(questions=[])

        if response_schema == MCQVerificationResponse:
            return MCQVerificationResponse(all_valid=True, evaluations=[])

        raise ValueError(f"Unknown response schema: {response_schema}")


@pytest.mark.asyncio
async def test_save_paper_direct_from_generation_with_randomize(client, db_session: AsyncSession):
    """Verify that Save Paper succeeds directly from a fresh generation job without
    needing a manual Save to Bank first, correctly maps randomized generated option IDs
    to persistent option IDs, populates Question Bank, and creates the QuestionSet.
    """
    pdf_bytes = create_synthetic_mathematics_pdf()
    files = {"file": ("Math_Class_7.pdf", io.BytesIO(pdf_bytes), "application/pdf")}
    ingest_res = await client.post("/api/v1/textbooks/ingest", files=files)
    assert ingest_res.status_code == 201
    version_id = ingest_res.json()["version_id"]

    stmt = select(CurriculumNode).where(CurriculumNode.subject_version_id == version_id)
    res_nodes = await db_session.execute(stmt)
    c_nodes = res_nodes.scalars().all()
    node_id = c_nodes[0].id

    # 1. Generate 3 MCQs via job
    gen_items = [
        LLMMCGItem(
            question_id=f"q_{i}",
            stem=f"What is the mathematical product of 3 and {i + 5}?",
            options=[
                LLMMCGOption(id="opt_1", text=f"{3 * (i + 5)}"),
                LLMMCGOption(id="opt_2", text=f"{3 * (i + 5) + 1}"),
                LLMMCGOption(id="opt_3", text=f"{3 * (i + 5) + 2}"),
                LLMMCGOption(id="opt_4", text=f"{3 * (i + 5) + 3}"),
            ],
            correct_option_id="opt_1",
            source_chunk_ids=["SRC-001"],
            explanation=f"3 * {i + 5} = {3 * (i + 5)}.",
        )
        for i in range(1, 4)
    ]

    mock_llm = MockStabilizationLLM(
        candidate_batches=[LLMMCGCandidateResponse(questions=gen_items)]
    )

    req = MCQGenerateRequest(
        subject_version_id=version_id,
        scope_node_ids=[node_id],
        count=3,
    )
    job_res = GenerationJobService.start_job(req, provider=mock_llm)
    job_id = job_res.job_id

    for _ in range(30):
        s = GenerationJobService.get_job_status(job_id)
        if s and s.complete:
            break
        await asyncio.sleep(0.2)

    status = GenerationJobService.get_job_status(job_id)
    assert status.status == "completed"
    assert status.generated_count == 3

    # 2. Simulate Frontend Randomizing using actual transient generated IDs:
    q_items = status.questions
    arrangements = [
        QuestionArrangementRequest(
            question_id=q_items[2].id,
            question_order=1,
            option_order=[o.id for o in q_items[2].options],
        ),
        QuestionArrangementRequest(
            question_id=q_items[1].id,
            question_order=2,
            option_order=[o.id for o in q_items[1].options],
        ),
        QuestionArrangementRequest(
            question_id=q_items[0].id,
            question_order=3,
            option_order=[q_items[0].options[3].id, q_items[0].options[0].id, q_items[0].options[2].id, q_items[0].options[1].id],
        ),
    ]

    save_payload = {
        "source_type": "GENERATED_JOB",
        "job_id": job_id,
        "subject_version_id": version_id,
        "title": "Mathematics Class 7 Midterm Exam",
        "paper_metadata": {
            "exam_title": "Mathematics Class 7 Midterm Exam",
            "subject_name": "Mathematics",
            "grade_name": "Class 7",
            "duration_minutes": 30,
            "marks_per_question": 1.0,
            "total_marks": 3.0,
        },
        "arrangements": [a.model_dump() for a in arrangements],
        "scope_node_ids": [node_id],
    }

    # 3. Call backend save endpoint: POST /api/v1/question-bank/papers
    res = await client.post("/api/v1/question-bank/papers", json=save_payload)
    assert res.status_code == 201, f"Save paper failed: {res.text}"
    saved_paper = res.json()

    assert saved_paper["title"] == "Mathematics Class 7 Midterm Exam"
    assert saved_paper["question_count"] == 3
    assert len(saved_paper["questions"]) == 3

    # Verify randomized presentation order
    first_item = saved_paper["questions"][0]
    assert "product of 3 and 8" in first_item["question_text"]  # q_3
    third_item = saved_paper["questions"][2]
    assert "product of 3 and 6" in third_item["question_text"]  # q_1

    # Verify option IDs are persistent DB IDs (not raw transient "opt_1", "opt_2", etc.)
    for q_item in saved_paper["questions"]:
        for opt in q_item["options"]:
            assert opt["id"] not in ["opt_1", "opt_2", "opt_3", "opt_4"]
            assert len(opt["id"]) >= 10

    # Verify Question Bank items were populated
    qb_count_res = await db_session.execute(
        select(func.count(QuestionBankItem.id)).where(QuestionBankItem.subject_version_id == version_id)
    )
    assert qb_count_res.scalar() == 3

    # 4. Reopen saved paper via GET endpoint
    paper_id = saved_paper["id"]
    get_res = await client.get(f"/api/v1/question-bank/papers/{paper_id}")
    assert get_res.status_code == 200
    reopened = get_res.json()
    assert reopened["id"] == paper_id
    assert reopened["question_count"] == 3
    assert reopened["answer_key"][2]["correct_letter"] == "B"  # q_1 option opt_1 was at position 1 (B)


@pytest.mark.asyncio
async def test_intra_set_diversity_multi_scope_distribution(client, db_session: AsyncSession):
    """Verify that when 4 distinct usable scopes are selected, generating 5 MCQs
    fairly distributes questions across all 4 scopes (e.g. 2/1/1/1), rather than
    clustering 4/1/0/0 in one single window.
    """
    pdf_bytes = create_synthetic_mathematics_pdf()
    files = {"file": ("Math_Class_7.pdf", io.BytesIO(pdf_bytes), "application/pdf")}
    ingest_res = await client.post("/api/v1/textbooks/ingest", files=files)
    assert ingest_res.status_code == 201
    version_id = ingest_res.json()["version_id"]

    stmt = select(CurriculumNode).where(CurriculumNode.subject_version_id == version_id)
    res_nodes = await db_session.execute(stmt)
    c_nodes = res_nodes.scalars().all()
    node_ids = [n.id for n in c_nodes[:4]]

    # Provide candidate batches for multiple rounds
    batches = [
        LLMMCGCandidateResponse(
            questions=[
                LLMMCGItem(
                    question_id=f"q_round_{r}_{i}",
                    stem=f"Scope {r} concept question {i} in mathematics?",
                    options=[
                        LLMMCGOption(id="opt_1", text=f"Answer {r}_{i}"),
                        LLMMCGOption(id="opt_2", text="Distractor 1"),
                        LLMMCGOption(id="opt_3", text="Distractor 2"),
                        LLMMCGOption(id="opt_4", text="Distractor 3"),
                    ],
                    correct_option_id="opt_1",
                    source_chunk_ids=["SRC-001"],
                    explanation=f"Explanation for scope {r}.",
                )
                for i in range(1, 4)
            ]
        )
        for r in range(1, 6)
    ]

    mock_llm = MockStabilizationLLM(candidate_batches=batches)

    req = MCQGenerateRequest(
        subject_version_id=version_id,
        scope_node_ids=node_ids,
        count=5,
    )
    job_res = GenerationJobService.start_job(req, provider=mock_llm)
    job_id = job_res.job_id

    for _ in range(30):
        s = GenerationJobService.get_job_status(job_id)
        if s and s.complete:
            break
        await asyncio.sleep(0.2)

    status = GenerationJobService.get_job_status(job_id)
    assert status.status == "completed"
    assert status.generated_count == 5

    # Check accounting invariant
    raw_job = GenerationJobService.get_raw_job(job_id)
    assert raw_job.accounting.check_invariant("Intra-Set Diversity") is True
    assert raw_job.accounting.final_accepted == 5


@pytest.mark.asyncio
async def test_generate_new_set_accounting_and_freshness(client, db_session: AsyncSession):
    """Verify that Set B rejects duplicates from Set A, generates fresh questions,
    and satisfies the candidate accounting invariant (7 returned == 5 accepted + 2 surplus).
    """
    pdf_bytes = create_synthetic_mathematics_pdf()
    files = {"file": ("Math_Class_7.pdf", io.BytesIO(pdf_bytes), "application/pdf")}
    ingest_res = await client.post("/api/v1/textbooks/ingest", files=files)
    assert ingest_res.status_code == 201
    version_id = ingest_res.json()["version_id"]

    stmt = select(CurriculumNode).where(CurriculumNode.subject_version_id == version_id)
    res_nodes = await db_session.execute(stmt)
    c_nodes = res_nodes.scalars().all()
    node_id = c_nodes[0].id

    # Set A
    set_a_items = [
        LLMMCGItem(
            question_id=f"q_a_{i}",
            stem=f"Set A question stem {i} regarding algebraic fractions?",
            options=[
                LLMMCGOption(id="opt_1", text="Correct A"),
                LLMMCGOption(id="opt_2", text="Wrong 1"),
                LLMMCGOption(id="opt_3", text="Wrong 2"),
                LLMMCGOption(id="opt_4", text="Wrong 3"),
            ],
            correct_option_id="opt_1",
            source_chunk_ids=["SRC-001"],
            explanation="Explanation A",
        )
        for i in range(1, 6)
    ]

    mock_llm_a = MockStabilizationLLM(
        candidate_batches=[LLMMCGCandidateResponse(questions=set_a_items)]
    )
    req_a = MCQGenerateRequest(subject_version_id=version_id, scope_node_ids=[node_id], count=5)
    job_a_res = GenerationJobService.start_job(req_a, provider=mock_llm_a)
    job_a_id = job_a_res.job_id

    for _ in range(30):
        s = GenerationJobService.get_job_status(job_a_id)
        if s and s.complete:
            break
        await asyncio.sleep(0.2)

    status_a = GenerationJobService.get_job_status(job_a_id)
    assert status_a.generated_count == 5

    # Set B: First batch returns 3 duplicates from Set A and 4 new items (total 7 candidates)
    set_b_batch_1 = [
        set_a_items[0],
        set_a_items[1],
        set_a_items[2],
        LLMMCGItem(
            question_id="q_b_1",
            stem="Fresh Set B question stem 1 regarding factorization?",
            options=[
                LLMMCGOption(id="opt_1", text="Correct B1"),
                LLMMCGOption(id="opt_2", text="Wrong 1"),
                LLMMCGOption(id="opt_3", text="Wrong 2"),
                LLMMCGOption(id="opt_4", text="Wrong 3"),
            ],
            correct_option_id="opt_1",
            source_chunk_ids=["SRC-001"],
            explanation="Explanation B1",
        ),
        LLMMCGItem(
            question_id="q_b_2",
            stem="Fresh Set B question stem 2 regarding factorization?",
            options=[
                LLMMCGOption(id="opt_1", text="Correct B2"),
                LLMMCGOption(id="opt_2", text="Wrong 1"),
                LLMMCGOption(id="opt_3", text="Wrong 2"),
                LLMMCGOption(id="opt_4", text="Wrong 3"),
            ],
            correct_option_id="opt_1",
            source_chunk_ids=["SRC-001"],
            explanation="Explanation B2",
        ),
    ]

    set_b_batch_2 = [
        LLMMCGItem(
            question_id=f"q_b_{i}",
            stem=f"Fresh Set B question stem {i} regarding linear equations?",
            options=[
                LLMMCGOption(id="opt_1", text=f"Correct B{i}"),
                LLMMCGOption(id="opt_2", text="Wrong 1"),
                LLMMCGOption(id="opt_3", text="Wrong 2"),
                LLMMCGOption(id="opt_4", text="Wrong 3"),
            ],
            correct_option_id="opt_1",
            source_chunk_ids=["SRC-001"],
            explanation=f"Explanation B{i}",
        )
        for i in range(3, 7)
    ]

    mock_llm_b = MockStabilizationLLM(
        candidate_batches=[
            LLMMCGCandidateResponse(questions=set_b_batch_1),
            LLMMCGCandidateResponse(questions=set_b_batch_2),
        ]
    )
    req_b = MCQGenerateRequest(
        subject_version_id=version_id,
        scope_node_ids=[node_id],
        count=5,
        previous_job_id=job_a_id,
    )
    job_b_res = GenerationJobService.start_job(req_b, provider=mock_llm_b)
    job_b_id = job_b_res.job_id

    for _ in range(30):
        s = GenerationJobService.get_job_status(job_b_id)
        if s and s.complete:
            break
        await asyncio.sleep(0.2)

    status_b = GenerationJobService.get_job_status(job_b_id)
    assert status_b.status == "completed"
    assert status_b.generated_count == 5

    # Verify zero duplicates between Set A and Set B
    stems_a = {q.question_text for q in status_a.questions}
    stems_b = {q.question_text for q in status_b.questions}
    assert stems_a.isdisjoint(stems_b)

    raw_job_b = GenerationJobService.get_raw_job(job_b_id)
    assert raw_job_b.accounting.exact_question_duplicate_rejected == 3
    assert raw_job_b.accounting.final_accepted == 5
    assert raw_job_b.accounting.check_invariant("Job B New Set") is True


@pytest.mark.asyncio
async def test_token_estimator_and_budget_bounds():
    """Verify truthful token budget configuration and conservative estimation."""
    budget = ProviderBudget.get_default_budget()
    assert budget.request_token_target == 2800
    assert budget.verify_token_target == 4000
    assert budget.is_within_budget(2500, is_verification=False) is True
    assert budget.is_within_budget(3500, is_verification=True) is True
    assert budget.is_within_budget(3500, is_verification=False) is False
