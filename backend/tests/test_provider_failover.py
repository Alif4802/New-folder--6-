import asyncio
import time
from typing import List, Type, TypeVar
import pytest
from pydantic import BaseModel

from app.schemas.llm_mcq import (
    LLMMCGItem,
    LLMMCGOption,
    LLMMCGCandidateResponse,
    MCQVerificationResponse,
    QuestionVerificationResult,
)
from app.schemas.assessment import MCQGenerateRequest
from app.services.llm.base import LLMProvider
from app.services.llm.circuit_breaker import ProviderCircuitBreaker, ProviderState
from app.services.llm.exceptions import (
    LLMQuotaExhaustedError,
    LLMRateLimitError,
    LLMTimeoutError,
    LLMUnavailableError,
    LLMSchemaValidationError,
    LLMNotConfiguredError,
    LLMProviderError,
)
from app.services.llm.router import LLMProviderRouter
from app.services.llm.openrouter_provider import OpenRouterProvider, _sanitize_error_message
from app.services.assessment.generator import MCQGeneratorService
from tests.utils import create_synthetic_mathematics_pdf
from sqlalchemy.ext.asyncio import AsyncSession
import io

T = TypeVar("T", bound=BaseModel)


class MockHealthyProvider(LLMProvider):
    """Mock provider that always succeeds and counts invocations."""
    def __init__(self, name: str = "healthy_mock"):
        self.name = name
        self.call_count = 0
        self.is_configured = True

    async def generate_structured(
        self,
        system_instruction: str,
        user_prompt: str,
        response_schema: Type[T],
    ) -> T:
        self.call_count += 1
        if response_schema == LLMMCGCandidateResponse:
            return LLMMCGCandidateResponse(
                questions=[
                    LLMMCGItem(
                        question_id=f"q_{self.call_count}_{i}",
                        stem=f"What is the mathematical definition of rational numbers part {self.call_count}_{i}?",
                        options=[
                            LLMMCGOption(id="opt_1", text="Ratio of two integers with non-zero denominator"),
                            LLMMCGOption(id="opt_2", text="An imaginary complex value"),
                            LLMMCGOption(id="opt_3", text="A decimal that never terminates or repeats"),
                            LLMMCGOption(id="opt_4", text="None of the above"),
                        ],
                        correct_option_id="opt_1",
                        source_chunk_ids=["SRC-001"],
                        explanation="Definition from Section 1.1.",
                    )
                    for i in range(1, 4)
                ]
            )
        elif response_schema == MCQVerificationResponse:
            return MCQVerificationResponse(
                all_valid=True,
                evaluations=[
                    QuestionVerificationResult(
                        question_id=f"q_{self.call_count}_{i}",
                        is_valid=True,
                        is_grounded_in_source=True,
                        is_single_correct_answer=True,
                        is_explanation_accurate=True,
                        is_stem_complete=True,
                        issues=[],
                    )
                    for i in range(1, 4)
                ],
            )
        return response_schema.model_validate({})


class MockQuotaExhaustedProvider(LLMProvider):
    """Mock provider simulating a long Groq 429 quota exhaustion."""
    def __init__(self, retry_after: float = 720.0):
        self.retry_after = retry_after
        self.call_count = 0
        self.is_configured = True

    async def generate_structured(
        self,
        system_instruction: str,
        user_prompt: str,
        response_schema: Type[T],
    ) -> T:
        self.call_count += 1
        raise LLMQuotaExhaustedError(
            f"LLM_QUOTA_EXHAUSTED: Rate limit on tokens per day (TPD). Try again in {self.retry_after}s.",
            retry_after_seconds=self.retry_after,
        )


class MockFailingProvider(LLMProvider):
    """Mock provider that simulates network or 5xx failures."""
    def __init__(self, error_msg: str = "Service Unavailable"):
        self.call_count = 0
        self.is_configured = True
        self.error_msg = error_msg

    async def generate_structured(
        self,
        system_instruction: str,
        user_prompt: str,
        response_schema: Type[T],
    ) -> T:
        self.call_count += 1
        raise LLMProviderError(f"LLM_PROVIDER_ERROR: {self.error_msg}")


# ----------------------------------------------------
# 1. Primary Healthy: Groq Used, OpenRouter Not Called
# ----------------------------------------------------
@pytest.mark.asyncio
async def test_primary_healthy_router():
    cb = ProviderCircuitBreaker()
    primary = MockHealthyProvider("groq")
    fallback = MockHealthyProvider("openrouter")

    router = LLMProviderRouter(primary=primary, fallback=fallback, circuit_breaker=cb)

    res = await router.generate_structured(
        system_instruction="sys",
        user_prompt="usr",
        response_schema=LLMMCGCandidateResponse,
    )

    assert len(res.questions) == 3
    assert primary.call_count == 1
    assert fallback.call_count == 0
    assert cb.is_available("groq") is True
    assert cb.get_status("groq")["failure_count"] == 0


# ----------------------------------------------------
# 2. Long Groq Quota Limit: Groq Circuit Opens, OpenRouter Succeeds Immediately
# ----------------------------------------------------
@pytest.mark.asyncio
async def test_long_groq_quota_failover():
    cb = ProviderCircuitBreaker()
    primary = MockQuotaExhaustedProvider(retry_after=720.0)  # 12 minutes
    fallback = MockHealthyProvider("openrouter")

    router = LLMProviderRouter(primary=primary, fallback=fallback, circuit_breaker=cb)

    t0 = time.time()
    res = await router.generate_structured(
        system_instruction="sys",
        user_prompt="usr",
        response_schema=LLMMCGCandidateResponse,
    )
    t1 = time.time()

    # Must NOT wait 12 minutes; must complete in fractions of a second
    assert (t1 - t0) < 1.0
    assert primary.call_count == 1
    assert fallback.call_count == 1
    assert len(res.questions) == 3

    # Groq circuit must now be OPEN (temporarily unavailable)
    assert cb.is_available("groq") is False
    assert cb.get_status("groq")["state"] == ProviderState.TEMPORARILY_UNAVAILABLE.value
    assert cb.get_status("groq")["unavailable_until"] > time.time() + 700


# ----------------------------------------------------
# 3. Next Request Skips Groq While Circuit Is Open
# ----------------------------------------------------
@pytest.mark.asyncio
async def test_next_request_skips_open_circuit():
    cb = ProviderCircuitBreaker()
    primary = MockQuotaExhaustedProvider(retry_after=720.0)
    fallback = MockHealthyProvider("openrouter")

    router = LLMProviderRouter(primary=primary, fallback=fallback, circuit_breaker=cb)

    # First call: opens circuit
    await router.generate_structured(
        system_instruction="sys",
        user_prompt="usr",
        response_schema=LLMMCGCandidateResponse,
    )
    assert primary.call_count == 1
    assert fallback.call_count == 1

    # Second call: Groq circuit is OPEN -> Groq must be SKIPPED directly
    res2 = await router.generate_structured(
        system_instruction="sys",
        user_prompt="usr",
        response_schema=LLMMCGCandidateResponse,
    )
    assert len(res2.questions) == 3
    # Groq call count remains 1 (0 calls on second request)
    assert primary.call_count == 1
    assert fallback.call_count == 2


# ----------------------------------------------------
# 4. Circuit Recovery After Time Elapsed
# ----------------------------------------------------
@pytest.mark.asyncio
async def test_circuit_recovery_after_time_advances():
    cb = ProviderCircuitBreaker()
    # Mark unavailable for 5 seconds
    cb.mark_unavailable("groq", duration_seconds=5.0, reason="Quota limit")
    assert cb.is_available("groq") is False

    # Simulate advancing time past unavailable_until (duration + safety buffer)
    future_time = time.time() + 30.0
    assert cb.is_available("groq", current_time=future_time) is True
    assert cb.get_status("groq")["state"] == ProviderState.AVAILABLE.value


# ----------------------------------------------------
# 5. Both Providers Unavailable -> Fast Typed Failure (No Mock In Runtime)
# ----------------------------------------------------
@pytest.mark.asyncio
async def test_both_providers_unavailable_clean_failure():
    cb = ProviderCircuitBreaker()
    primary = MockQuotaExhaustedProvider(retry_after=600.0)
    fallback = MockFailingProvider(error_msg="OpenRouter overloaded")

    router = LLMProviderRouter(primary=primary, fallback=fallback, circuit_breaker=cb)

    with pytest.raises(LLMUnavailableError) as exc_info:
        await router.generate_structured(
            system_instruction="sys",
            user_prompt="usr",
            response_schema=LLMMCGCandidateResponse,
        )

    assert "LLM_TEMPORARILY_UNAVAILABLE" in str(exc_info.value)
    assert primary.call_count == 1
    assert fallback.call_count == 1


# ----------------------------------------------------
# 6. Fallback Key Not Configured -> Typed Error
# ----------------------------------------------------
@pytest.mark.asyncio
async def test_fallback_not_configured():
    cb = ProviderCircuitBreaker()
    primary = MockQuotaExhaustedProvider(retry_after=600.0)
    unconfigured_fallback = OpenRouterProvider(api_key="")

    router = LLMProviderRouter(primary=primary, fallback=unconfigured_fallback, circuit_breaker=cb)

    with pytest.raises(LLMUnavailableError) as exc_info:
        await router.generate_structured(
            system_instruction="sys",
            user_prompt="usr",
            response_schema=LLMMCGCandidateResponse,
        )

    assert "backup provider is not configured" in str(exc_info.value)


# ----------------------------------------------------
# 7. Semantic Validation Error Does NOT Trigger Provider Failover
# ----------------------------------------------------
@pytest.mark.asyncio
async def test_validation_error_does_not_failover():
    class MockSemanticFailingProvider(LLMProvider):
        def __init__(self):
            self.call_count = 0
            self.is_configured = True
        async def generate_structured(self, system_instruction, user_prompt, response_schema):
            self.call_count += 1
            raise LLMSchemaValidationError("LLM_SCHEMA_VALIDATION_ERROR: Missing required field 'stem'")

    cb = ProviderCircuitBreaker()
    primary = MockSemanticFailingProvider()
    fallback = MockHealthyProvider("openrouter")

    router = LLMProviderRouter(primary=primary, fallback=fallback, circuit_breaker=cb)

    with pytest.raises(LLMSchemaValidationError):
        await router.generate_structured(
            system_instruction="sys",
            user_prompt="usr",
            response_schema=LLMMCGCandidateResponse,
        )

    # Primary failed on schema -> fallback must NOT be called (don't hide application/prompt bugs)
    assert primary.call_count == 1
    assert fallback.call_count == 0


# ----------------------------------------------------
# 8. Mid-Batch Provider Switch with Ingestion & Generation
# ----------------------------------------------------
@pytest.mark.asyncio
async def test_mid_batch_failover_preserves_questions_and_grounding(
    client,
    db_session: AsyncSession,
):
    # Ingest a Mathematics textbook
    pdf_bytes = create_synthetic_mathematics_pdf()
    files = {"file": ("Math_Class_7.pdf", io.BytesIO(pdf_bytes), "application/pdf")}
    ingest_res = await client.post("/api/v1/textbooks/ingest", files=files)
    assert ingest_res.status_code == 201
    version_id = ingest_res.json()["version_id"]

    # Class that succeeds for call 1 (Batch 1), then fails with quota on call 2 (Batch 2)
    class MockStatefulPrimary(LLMProvider):
        def __init__(self):
            self.call_count = 0
            self.is_configured = True

        async def generate_structured(self, system_instruction, user_prompt, response_schema):
            self.call_count += 1
            if self.call_count <= 2:  # Call 1: Gen batch 1, Call 2: Verify batch 1
                if response_schema == LLMMCGCandidateResponse:
                    return LLMMCGCandidateResponse(
                        questions=[
                            LLMMCGItem(
                                question_id="batch1_q1",
                                stem="What is the square of 5 according to the textbook?",
                                options=[
                                    LLMMCGOption(id="opt_1", text="25"),
                                    LLMMCGOption(id="opt_2", text="10"),
                                    LLMMCGOption(id="opt_3", text="15"),
                                    LLMMCGOption(id="opt_4", text="20"),
                                ],
                                correct_option_id="opt_1",
                                source_chunk_ids=["SRC-001"],
                                explanation="5 squared equals 25.",
                            ),
                            LLMMCGItem(
                                question_id="batch1_q2",
                                stem="What is the square root of 36?",
                                options=[
                                    LLMMCGOption(id="opt_1", text="6"),
                                    LLMMCGOption(id="opt_2", text="12"),
                                    LLMMCGOption(id="opt_3", text="18"),
                                    LLMMCGOption(id="opt_4", text="3"),
                                ],
                                correct_option_id="opt_1",
                                source_chunk_ids=["SRC-001"],
                                explanation="Square root of 36 is 6.",
                            ),
                        ]
                    )
                else:
                    return MCQVerificationResponse(
                        all_valid=True,
                        evaluations=[
                            QuestionVerificationResult(question_id="batch1_q1", is_valid=True, is_grounded_in_source=True, is_single_correct_answer=True, is_explanation_accurate=True),
                            QuestionVerificationResult(question_id="batch1_q2", is_valid=True, is_grounded_in_source=True, is_single_correct_answer=True, is_explanation_accurate=True),
                        ],
                    )
            # Call 3 (Batch 2): Quota exhausted!
            raise LLMQuotaExhaustedError("LLM_QUOTA_EXHAUSTED: Rate limit on tokens per day (TPD). Try again in 900s.", retry_after_seconds=900.0)

    class MockFallbackProvider(LLMProvider):
        def __init__(self):
            self.call_count = 0
            self.is_configured = True

        async def generate_structured(self, system_instruction, user_prompt, response_schema):
            self.call_count += 1
            if response_schema == LLMMCGCandidateResponse:
                # Exclusions check: ensure previous stems were in the prompt
                assert "square of 5" in user_prompt or "exclusion" in user_prompt.lower()
                return LLMMCGCandidateResponse(
                    questions=[
                        LLMMCGItem(
                            question_id="batch2_q3",
                            stem="Which of the following is an irrational number?",
                            options=[
                                LLMMCGOption(id="opt_1", text="Square root of 2"),
                                LLMMCGOption(id="opt_2", text="3/4"),
                                LLMMCGOption(id="opt_3", text="5"),
                                LLMMCGOption(id="opt_4", text="0.25"),
                            ],
                            correct_option_id="opt_1",
                            source_chunk_ids=["SRC-001"],
                            explanation="Square root of 2 cannot be expressed as a ratio of two integers.",
                        ),
                        LLMMCGItem(
                            question_id="batch2_q4",
                            stem="What is the perimeter of a square with side length 4?",
                            options=[
                                LLMMCGOption(id="opt_1", text="16"),
                                LLMMCGOption(id="opt_2", text="8"),
                                LLMMCGOption(id="opt_3", text="12"),
                                LLMMCGOption(id="opt_4", text="4"),
                            ],
                            correct_option_id="opt_1",
                            source_chunk_ids=["SRC-001"],
                            explanation="Perimeter = 4 * 4 = 16.",
                        ),
                        LLMMCGItem(
                            question_id="batch2_q5",
                            stem="What is the square of 9?",
                            options=[
                                LLMMCGOption(id="opt_1", text="81"),
                                LLMMCGOption(id="opt_2", text="18"),
                                LLMMCGOption(id="opt_3", text="27"),
                                LLMMCGOption(id="opt_4", text="36"),
                            ],
                            correct_option_id="opt_1",
                            source_chunk_ids=["SRC-001"],
                            explanation="9 squared equals 81.",
                        ),
                    ]
                )
            else:
                return MCQVerificationResponse(
                    all_valid=True,
                    evaluations=[
                        QuestionVerificationResult(question_id="batch2_q3", is_valid=True, is_grounded_in_source=True, is_single_correct_answer=True, is_explanation_accurate=True),
                        QuestionVerificationResult(question_id="batch2_q4", is_valid=True, is_grounded_in_source=True, is_single_correct_answer=True, is_explanation_accurate=True),
                        QuestionVerificationResult(question_id="batch2_q5", is_valid=True, is_grounded_in_source=True, is_single_correct_answer=True, is_explanation_accurate=True),
                    ],
                )

    cb = ProviderCircuitBreaker()
    primary = MockStatefulPrimary()
    fallback = MockFallbackProvider()
    router = LLMProviderRouter(primary=primary, fallback=fallback, circuit_breaker=cb)

    # Query migrated curriculum node
    from sqlalchemy import select
    from app.models.textbook import CurriculumNode
    stmt = select(CurriculumNode).where(CurriculumNode.subject_version_id == version_id)
    res_nodes = await db_session.execute(stmt)
    c_nodes = res_nodes.scalars().all()
    node_id = c_nodes[0].id

    req = MCQGenerateRequest(
        subject_version_id=version_id,
        scope_node_ids=[node_id],
        count=5,
    )

    res = await MCQGeneratorService.generate_mcqs(db_session, req, provider=router)

    # 1. Total questions returned must equal requested count (5)
    assert res.generated_count == 5
    assert len(res.questions) == 5
    assert len(res.answer_key) == 5

    # 2. Both providers contributed (Batch 1 from Groq, Batch 2 from OpenRouter)
    assert primary.call_count >= 2  # Gen + Ver for batch 1, then failed on call 3
    assert fallback.call_count >= 2  # Gen + Ver for batch 2
    assert cb.is_available("groq") is False  # Groq circuit opened

    # 3. No duplicate stems across batches
    stems = [q.question_text for q in res.questions]
    assert len(set(stems)) == 5

    # 4. Correct answer mapping integrity
    for ak in res.answer_key:
        q = next(q for q in res.questions if q.question_number == ak.question_number)
        opt = next(o for o in q.options if o.label == ak.correct_letter)
        assert opt.text == ak.correct_text


# ----------------------------------------------------
# 9. Error Sanitization Verification
# ----------------------------------------------------
def test_error_sanitization():
    dirty = "Error code: 429 https://console.groq.com/docs/rate-limits org_abc123 Bearer sk-or-v1-secretkey999"
    cleaned = _sanitize_error_message(dirty)
    assert "https" not in cleaned
    assert "console.groq.com" not in cleaned
    assert "org_" not in cleaned
    assert "sk-or-v1" not in cleaned
    assert "[REDACTED]" in cleaned
