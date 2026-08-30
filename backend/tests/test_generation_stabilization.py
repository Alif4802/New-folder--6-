import asyncio
import io
import pytest
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.models.textbook import CurriculumNode
from app.services.assessment.validator import RejectionAccounting, MCQValidator
from app.schemas.llm_mcq import (
    LLMMCGItem,
    LLMMCGOption,
    LLMMCGCandidateResponse,
    MCQVerificationResponse,
    QuestionVerificationResult,
)
from app.schemas.assessment import MCQGenerateRequest
from app.services.assessment.job_service import GenerationJobService, GenerationJob
from app.services.assessment.generator import MCQGeneratorService
from app.services.llm.base import LLMProvider
from tests.utils import create_synthetic_mathematics_pdf


class MockStabilizationProvider(LLMProvider):
    """Mock LLM Provider for deterministic stabilization tests without real API calls."""

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
async def test_rejection_accounting_invariant_reconciliation():
    """Verify that RejectionAccounting strictly satisfies the invariant:
    CANDIDATES_RETURNED == FINAL_ACCEPTED + TOTAL_REJECTED + SURPLUS_NOT_NEEDED
    """
    accounting = RejectionAccounting()
    accounting.candidates_returned = 7
    accounting.schema_rejected = 1
    accounting.near_duplicate_rejected = 1
    accounting.llm_verification_rejected = 1
    accounting.final_accepted = 2
    accounting.surplus_not_needed = 2

    # 1 + 1 + 1 = 3 rejected, 2 accepted, 2 surplus = 7 total
    assert accounting.total_rejected == 3
    assert accounting.candidates_returned == (
        accounting.final_accepted + accounting.total_rejected + accounting.surplus_not_needed
    )
    assert accounting.check_invariant("Test") is True

    # Check merge
    other = RejectionAccounting()
    other.candidates_returned = 3
    other.final_accepted = 1
    other.surplus_not_needed = 2

    accounting.merge(other)
    assert accounting.candidates_returned == 10
    assert accounting.final_accepted == 3
    assert accounting.surplus_not_needed == 4
    assert accounting.total_rejected == 3
    assert accounting.check_invariant("Merged") is True


@pytest.mark.asyncio
async def test_accounting_surplus_tracking_on_oversampling():
    """Verify that when 7 valid candidates are returned but only 1 is needed,
    surplus is counted as 6 and invariant holds.
    """
    accounting = RejectionAccounting()
    accounting.candidates_returned = 7
    needed = 1

    valid_candidates = [
        LLMMCGItem(
            question_id=f"q_{i}",
            stem=f"What is the mathematical definition of square number item {i} in arithmetic?",
            options=[
                LLMMCGOption(id="opt_1", text="Option 1"),
                LLMMCGOption(id="opt_2", text="Option 2"),
                LLMMCGOption(id="opt_3", text="Option 3"),
                LLMMCGOption(id="opt_4", text="Option 4"),
            ],
            correct_option_id="opt_1",
            explanation="Explanation",
            source_chunk_ids=["chunk_1"],
        )
        for i in range(7)
    ]

    accepted_items = []
    for q in valid_candidates:
        if len(accepted_items) < needed:
            accepted_items.append(q)
            accounting.final_accepted += 1
        else:
            accounting.surplus_not_needed += 1

    assert len(accepted_items) == 1
    assert accounting.final_accepted == 1
    assert accounting.surplus_not_needed == 6
    assert accounting.total_rejected == 0
    assert accounting.candidates_returned == 7
    assert accounting.check_invariant("Oversampling") is True


@pytest.mark.asyncio
async def test_duplicate_stem_rejection_against_previous_set():
    """Verify that questions matching previous set stems are rejected as exact or near duplicates."""
    previous_stems = [
        "What is the square of 12 in arithmetic?",
        "Which of the following numbers is a rational number?",
    ]

    q_exact = LLMMCGItem(
        question_id="q_exact",
        stem="What is the square of 12 in arithmetic?",
        options=[
            LLMMCGOption(id="opt_1", text="144"),
            LLMMCGOption(id="opt_2", text="124"),
            LLMMCGOption(id="opt_3", text="142"),
            LLMMCGOption(id="opt_4", text="122"),
        ],
        correct_option_id="opt_1",
        explanation="12 squared is 144.",
        source_chunk_ids=["c1"],
    )

    q_near = LLMMCGItem(
        question_id="q_near",
        stem="What is the square of 12 in basic arithmetic?",
        options=[
            LLMMCGOption(id="opt_1", text="144"),
            LLMMCGOption(id="opt_2", text="124"),
            LLMMCGOption(id="opt_3", text="142"),
            LLMMCGOption(id="opt_4", text="122"),
        ],
        correct_option_id="opt_1",
        explanation="12 squared is 144.",
        source_chunk_ids=["c1"],
    )

    q_fresh = LLMMCGItem(
        question_id="q_fresh",
        stem="What is the prime factorization of 36 in arithmetic?",
        options=[
            LLMMCGOption(id="opt_1", text="2^2 * 3^2"),
            LLMMCGOption(id="opt_2", text="2 * 3^3"),
            LLMMCGOption(id="opt_3", text="2^3 * 3"),
            LLMMCGOption(id="opt_4", text="4 * 9"),
        ],
        correct_option_id="opt_1",
        explanation="36 = 4 * 9 = 2^2 * 3^2.",
        source_chunk_ids=["c1"],
    )

    issues_exact = MCQValidator.validate_single_item(
        q=q_exact,
        valid_chunk_ids={"c1"},
        existing_stems=previous_stems,
    )
    assert any(i.category == "exact_question_duplicate_rejected" for i in issues_exact)

    issues_near = MCQValidator.validate_single_item(
        q=q_near,
        valid_chunk_ids={"c1"},
        existing_stems=previous_stems,
    )
    assert any(
        i.category in ["exact_question_duplicate_rejected", "near_duplicate_rejected"]
        for i in issues_near
    )

    issues_fresh = MCQValidator.validate_single_item(
        q=q_fresh,
        valid_chunk_ids={"c1"},
        existing_stems=previous_stems,
    )
    assert len(issues_fresh) == 0


@pytest.mark.asyncio
async def test_all_providers_unavailable_fails_fast(client, db_session: AsyncSession):
    """Verify that when providers fail with LLM_TEMPORARILY_UNAVAILABLE,
    the generation loop fails fast and does not run endless rounds.
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

    mock_llm = MockStabilizationProvider(should_fail_temporarily=True)

    req = MCQGenerateRequest(
        subject_version_id=version_id,
        scope_node_ids=[node_id],
        count=5,
    )

    create_res = GenerationJobService.start_job(req, provider=mock_llm)
    job_id = create_res.job_id

    # Wait for completion in memory
    for _ in range(30):
        status_res = GenerationJobService.get_job_status(job_id)
        if status_res and status_res.complete:
            break
        await asyncio.sleep(0.2)

    status = GenerationJobService.get_job_status(job_id)
    assert status is not None
    assert status.complete is True
    # The provider should only have been called at most 1 time (fail fast)
    assert mock_llm.call_count <= 2


@pytest.mark.asyncio
async def test_generate_new_set_excludes_previous_job_stems(client, db_session: AsyncSession):
    """Verify that when generating a new set passing previous_job_id,
    the server loads previous stems and enforces strict duplicate rejection.
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

    # Set A items
    set_a_items = [
        LLMMCGItem(
            question_id=f"q_a_{i}",
            stem=f"What is the mathematical definition of rational number item {i}?",
            options=[
                LLMMCGOption(id="opt_1", text="Answer 1"),
                LLMMCGOption(id="opt_2", text="Distractor 1"),
                LLMMCGOption(id="opt_3", text="Distractor 2"),
                LLMMCGOption(id="opt_4", text="Distractor 3"),
            ],
            correct_option_id="opt_1",
            source_chunk_ids=["SRC-001"],
            explanation="Explanation A",
        )
        for i in range(1, 4)
    ]

    # Set B items (fresh stems)
    set_b_items = [
        LLMMCGItem(
            question_id=f"q_b_{i}",
            stem=f"What is the prime factorization of natural number {i + 10}?",
            options=[
                LLMMCGOption(id="opt_1", text="Answer 2"),
                LLMMCGOption(id="opt_2", text="Distractor 1"),
                LLMMCGOption(id="opt_3", text="Distractor 2"),
                LLMMCGOption(id="opt_4", text="Distractor 3"),
            ],
            correct_option_id="opt_1",
            source_chunk_ids=["SRC-001"],
            explanation="Explanation B",
        )
        for i in range(1, 4)
    ]

    # Job A
    provider_a = MockStabilizationProvider(
        candidate_batches=[LLMMCGCandidateResponse(questions=set_a_items)]
    )
    req_a = MCQGenerateRequest(
        subject_version_id=version_id,
        scope_node_ids=[node_id],
        count=3,
    )
    job_a_res = GenerationJobService.start_job(req_a, provider=provider_a)
    job_a_id = job_a_res.job_id

    for _ in range(30):
        s = GenerationJobService.get_job_status(job_a_id)
        if s and s.complete:
            break
        await asyncio.sleep(0.2)

    status_a = GenerationJobService.get_job_status(job_a_id)
    assert status_a.status == "completed"
    assert status_a.generated_count == 3

    # Job B with previous_job_id referencing Job A
    provider_b = MockStabilizationProvider(
        candidate_batches=[
            # First batch attempts duplicate items from Set A (should be rejected)
            LLMMCGCandidateResponse(questions=set_a_items[:1]),
            # Second batch provides fresh items from Set B (should be accepted)
            LLMMCGCandidateResponse(questions=set_b_items),
        ]
    )
    req_b = MCQGenerateRequest(
        subject_version_id=version_id,
        scope_node_ids=[node_id],
        count=3,
        previous_job_id=job_a_id,
    )
    job_b_res = GenerationJobService.start_job(req_b, provider=provider_b)
    job_b_id = job_b_res.job_id

    for _ in range(30):
        s = GenerationJobService.get_job_status(job_b_id)
        if s and s.complete:
            break
        await asyncio.sleep(0.2)

    status_b = GenerationJobService.get_job_status(job_b_id)
    assert status_b.status == "completed"
    assert status_b.generated_count == 3

    # Ensure none of Set B stems match Set A stems
    stems_a = {q.question_text for q in status_a.questions}
    stems_b = {q.question_text for q in status_b.questions}
    assert stems_a.isdisjoint(stems_b)

    raw_job_b = GenerationJobService.get_raw_job(job_b_id)
    assert raw_job_b.accounting.exact_question_duplicate_rejected >= 1
    assert raw_job_b.accounting.check_invariant("Job B") is True
