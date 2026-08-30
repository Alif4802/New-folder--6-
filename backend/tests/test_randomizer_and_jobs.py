import asyncio
import io
import time
from typing import List, Type, TypeVar
import pytest
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.models.textbook import CurriculumNode
from app.schemas.assessment import (
    MCQAnswerKeyItemResponse,
    MCQGenerateRequest,
    MCQOptionResponse,
    MCQQuestionResponse,
)
from app.schemas.llm_mcq import (
    LLMMCGItem,
    LLMMCGOption,
    LLMMCGCandidateResponse,
    MCQVerificationResponse,
    QuestionVerificationResult,
)
from app.services.assessment.job_service import GenerationJobService, GenerationJob
from app.services.assessment.validator import MCQValidator, RejectionAccounting
from app.services.llm.base import LLMProvider
from app.services.llm.budget import ProviderBudget, TokenEstimator
from app.services.llm.circuit_breaker import ProviderCircuitBreaker, parse_retry_after
from app.services.llm.exceptions import (
    LLMQuotaExhaustedError,
    LLMRateLimitError,
    LLMUnavailableError,
    LLMProviderError,
)
from tests.utils import create_synthetic_mathematics_pdf

T = TypeVar("T", bound=BaseModel)


# ----------------------------------------------------
# 1. Randomize Paper: Pure, Zero-LLM Shuffle & Answer Key Remap
# ----------------------------------------------------
def test_randomize_paper_zero_llm():
    questions = [
        MCQQuestionResponse(
            id="q_1",
            question_number=1,
            question_text="What is 2 + 2?",
            options=[
                MCQOptionResponse(id="opt_1", label="A", text="3"),
                MCQOptionResponse(id="opt_2", label="B", text="4"),
                MCQOptionResponse(id="opt_3", label="C", text="5"),
                MCQOptionResponse(id="opt_4", label="D", text="6"),
            ],
            correct_option_id="opt_2",
            explanation="2 + 2 = 4.",
        ),
        MCQQuestionResponse(
            id="q_2",
            question_number=2,
            question_text="What is 3 * 3?",
            options=[
                MCQOptionResponse(id="opt_21", label="A", text="9"),
                MCQOptionResponse(id="opt_22", label="B", text="6"),
                MCQOptionResponse(id="opt_23", label="C", text="12"),
                MCQOptionResponse(id="opt_24", label="D", text="3"),
            ],
            correct_option_id="opt_21",
            explanation="3 * 3 = 9.",
        ),
    ]

    answer_key = [
        MCQAnswerKeyItemResponse(
            question_number=1,
            question_id="q_1",
            correct_letter="B",
            correct_text="4",
            explanation="2 + 2 = 4.",
        ),
        MCQAnswerKeyItemResponse(
            question_number=2,
            question_id="q_2",
            correct_letter="A",
            correct_text="9",
            explanation="3 * 3 = 9.",
        ),
    ]

    # Perform 5 randomizations
    for _ in range(5):
        shuffled_q, shuffled_ak = MCQValidator.randomize_paper(questions, answer_key)

        assert len(shuffled_q) == 2
        assert len(shuffled_ak) == 2

        # Check that question numbers are strictly sequential (1, 2)
        assert [q.question_number for q in shuffled_q] == [1, 2]
        assert [ak.question_number for ak in shuffled_ak] == [1, 2]

        # Check option label assignment and answer key matching
        for q in shuffled_q:
            labels = [opt.label for opt in q.options]
            assert labels == ["A", "B", "C", "D"]

            matching_ak = next(ak for ak in shuffled_ak if ak.question_number == q.question_number)
            correct_opt = next(opt for opt in q.options if opt.id == q.correct_option_id)

            # The Answer Key letter must match the new label of the correct option
            assert matching_ak.correct_letter == correct_opt.label
            assert matching_ak.correct_text == correct_opt.text
            assert matching_ak.explanation == q.explanation


# ----------------------------------------------------
# 2. Robust Duration Parsing for Groq / Provider Errors
# ----------------------------------------------------
def test_parse_retry_after():
    assert parse_retry_after("Please try again in 16.665s.") == 16.665
    assert parse_retry_after("Rate limit reached. Try again in 2m25s.") == 145.0
    assert parse_retry_after("Tokens per day exhausted. Try again in 20m56s.") == 1256.0
    assert parse_retry_after("Try again in 1h10m5s.") == 4205.0
    assert parse_retry_after("Try again in 34m.") == 2040.0
    assert parse_retry_after("Unknown error", default_wait=60.0) == 60.0


# ----------------------------------------------------
# 3. Token Budget Enforcement Under Oversized Context
# ----------------------------------------------------
def test_token_budget_enforcement():
    class DummyChunk:
        def __init__(self, cid: str, content: str):
            self.chunk_id = cid
            self.page_number = 1
            self.content = content

    # Create 10 large chunks (each ~600 words)
    chunks = [DummyChunk(f"SRC-{i:03d}", "Mathematics definitions rules theorems and formulas. " * 60) for i in range(10)]

    def render_fn(chunk_list):
        return "\n".join(c.content for c in chunk_list)

    sys_prompt = "You are an expert NCTB MCQ author."
    target_tokens = 2000

    fitted, rendered, est = TokenEstimator.enforce_prompt_token_budget(
        chunks=chunks,
        render_user_prompt_fn=render_fn,
        system_prompt=sys_prompt,
        max_target_tokens=target_tokens,
    )

    # Must be <= target_tokens
    assert est <= target_tokens
    assert len(fitted) < 10
    assert len(fitted) >= 1


# ----------------------------------------------------
# 4. Rejection Accounting Tracking
# ----------------------------------------------------
def test_rejection_accounting_counters():
    accounting = RejectionAccounting()
    accounting.candidates_returned += 10
    accounting.invalid_option_count += 2
    accounting.near_duplicate_rejected += 1
    accounting.deterministic_math_rejected += 1
    accounting.llm_verification_rejected += 1
    accounting.final_accepted += 5

    assert accounting.candidates_returned == 10
    assert accounting.final_accepted == 5
    assert accounting.invalid_option_count == 2
    assert accounting.near_duplicate_rejected == 1
    assert accounting.deterministic_math_rejected == 1
    assert accounting.llm_verification_rejected == 1


# ----------------------------------------------------
# 5. Progressive Generation Job: Batch 1 (5 ready) -> Batch 2 (10 ready)
# ----------------------------------------------------
@pytest.mark.asyncio
async def test_progressive_generation_job(
    client,
    db_session: AsyncSession,
):
    pdf_bytes = create_synthetic_mathematics_pdf()
    files = {"file": ("Math_Class_7.pdf", io.BytesIO(pdf_bytes), "application/pdf")}
    ingest_res = await client.post("/api/v1/textbooks/ingest", files=files)
    assert ingest_res.status_code == 201
    version_id = ingest_res.json()["version_id"]

    stmt = select(CurriculumNode).where(CurriculumNode.subject_version_id == version_id)
    res_nodes = await db_session.execute(stmt)
    c_nodes = res_nodes.scalars().all()
    node_id = c_nodes[0].id

    class MockJobProvider(LLMProvider):
        def __init__(self):
            self.call_count = 0
            self.is_configured = True

        async def generate_structured(self, system_instruction, user_prompt, response_schema):
            self.call_count += 1
            if response_schema == LLMMCGCandidateResponse:
                batch_num = (self.call_count + 1) // 2
                return LLMMCGCandidateResponse(
                    questions=[
                        LLMMCGItem(
                            question_id=f"q_{batch_num}_{i}",
                            stem=f"Question stem for progressive batch {batch_num} item {i}?",
                            options=[
                                LLMMCGOption(id="opt_1", text=f"Answer {batch_num}_{i}"),
                                LLMMCGOption(id="opt_2", text=f"Distractor 1"),
                                LLMMCGOption(id="opt_3", text=f"Distractor 2"),
                                LLMMCGOption(id="opt_4", text=f"Distractor 3"),
                            ],
                            correct_option_id="opt_1",
                            source_chunk_ids=["SRC-001"],
                            explanation="Solution explanation.",
                        )
                        for i in range(1, 6)
                    ]
                )
            else:
                return MCQVerificationResponse(all_valid=True, evaluations=[])

    provider = MockJobProvider()

    req = MCQGenerateRequest(
        subject_version_id=version_id,
        scope_node_ids=[node_id],
        count=10,
    )

    create_res = GenerationJobService.start_job(request=req, provider=provider)
    job_id = create_res.job_id
    assert create_res.status == "processing"
    assert create_res.requested_count == 10

    # Wait for completion in memory
    for _ in range(30):
        status_res = GenerationJobService.get_job_status(job_id)
        if status_res and status_res.complete:
            break
        await asyncio.sleep(0.2)

    final_status = GenerationJobService.get_job_status(job_id)
    assert final_status is not None
    assert final_status.status == "completed"
    assert final_status.generated_count == 10
    assert len(final_status.questions) == 10
    assert len(final_status.answer_key) == 10
    # Clean call count: exactly 2 gen batches + 2 verifications = 4 provider calls
    assert provider.call_count == 4


# ----------------------------------------------------
# 6. Cancellation of In-Progress Generation Job
# ----------------------------------------------------
@pytest.mark.asyncio
async def test_cancel_generation_job():
    job = GenerationJob(
        job_id="test_cancel_job",
        subject_version_id="dummy_version",
        scope_node_ids=["node_1"],
        requested_count=10,
    )
    GenerationJobService._JOBS["test_cancel_job"] = job

    cancel_res = GenerationJobService.cancel_job("test_cancel_job")
    assert cancel_res.status == "cancelled"

    status_res = GenerationJobService.get_job_status("test_cancel_job")
    assert status_res.status == "cancelled"
    assert status_res.complete is True


# ----------------------------------------------------
# 7. Partial Failure & Retry Remaining Flow
# ----------------------------------------------------
@pytest.mark.asyncio
async def test_partial_job_failure_and_retry(
    client,
    db_session: AsyncSession,
):
    pdf_bytes = create_synthetic_mathematics_pdf()
    files = {"file": ("Math_Class_7.pdf", io.BytesIO(pdf_bytes), "application/pdf")}
    ingest_res = await client.post("/api/v1/textbooks/ingest", files=files)
    assert ingest_res.status_code == 201
    version_id = ingest_res.json()["version_id"]

    stmt = select(CurriculumNode).where(CurriculumNode.subject_version_id == version_id)
    res_nodes = await db_session.execute(stmt)
    c_nodes = res_nodes.scalars().all()
    node_id = c_nodes[0].id

    class FailingSecondBatchProvider(LLMProvider):
        def __init__(self):
            self.call_count = 0
            self.is_configured = True

        async def generate_structured(self, system_instruction, user_prompt, response_schema):
            self.call_count += 1
            if self.call_count == 1:
                # Batch 1 returns 5 valid items
                return LLMMCGCandidateResponse(
                    questions=[
                        LLMMCGItem(
                            question_id=f"q_1_{i}",
                            stem=f"Valid partial question number {i}?",
                            options=[
                                LLMMCGOption(id="opt_1", text=f"Answer {i}"),
                                LLMMCGOption(id="opt_2", text=f"Distractor A"),
                                LLMMCGOption(id="opt_3", text=f"Distractor B"),
                                LLMMCGOption(id="opt_4", text=f"Distractor C"),
                            ],
                            correct_option_id="opt_1",
                            source_chunk_ids=["SRC-001"],
                            explanation="Explanation.",
                        )
                        for i in range(1, 6)
                    ]
                )
            elif self.call_count == 2:
                # Batch 1 verification passes
                return MCQVerificationResponse(all_valid=True, evaluations=[])
            else:
                # Batch 2 fails with rate limit / quota
                raise LLMQuotaExhaustedError("Daily tokens exhausted", retry_after_seconds=3600.0)

    provider = FailingSecondBatchProvider()

    req = MCQGenerateRequest(
        subject_version_id=version_id,
        scope_node_ids=[node_id],
        count=10,
    )

    create_res = GenerationJobService.start_job(request=req, provider=provider)
    job_id = create_res.job_id

    for _ in range(30):
        status_res = GenerationJobService.get_job_status(job_id)
        if status_res and status_res.complete:
            break
        await asyncio.sleep(0.2)

    status_res = GenerationJobService.get_job_status(job_id)
    assert status_res is not None
    assert status_res.status == "incomplete"
    assert status_res.generated_count == 5
    assert len(status_res.questions) == 5
    assert len(status_res.answer_key) == 5
