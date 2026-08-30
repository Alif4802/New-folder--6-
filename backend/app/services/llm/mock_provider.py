import re
from typing import Any, Callable, Dict, List, Optional, Type, TypeVar
from pydantic import BaseModel

from app.schemas.llm_mcq import (
    LLMMCGCandidateResponse,
    LLMMCGItem,
    LLMMCGOption,
    MCQVerificationResponse,
    QuestionVerificationResult,
)
from app.services.llm.base import LLMProvider

T = TypeVar("T", bound=BaseModel)


class MockProvider(LLMProvider):
    """
    Deterministic Mock LLM Provider for unit, integration, and CI/CD testing.
    Dynamically generates the requested number of synthetic questions for arbitrary counts.
    """

    def __init__(
        self,
        default_candidate_response: Optional[LLMMCGCandidateResponse] = None,
        default_verification_response: Optional[MCQVerificationResponse] = None,
        custom_handler: Optional[Callable[[str, str, Type[BaseModel]], BaseModel]] = None,
        simulate_timeout: bool = False,
        simulate_error: Optional[str] = None,
    ):
        self.default_candidate_response = default_candidate_response
        self.default_verification_response = default_verification_response
        self.custom_handler = custom_handler
        self.simulate_timeout = simulate_timeout
        self.simulate_error = simulate_error
        self.call_history: List[Dict[str, Any]] = []

    async def generate_structured(
        self,
        system_instruction: str,
        user_prompt: str,
        response_schema: Type[T],
    ) -> T:
        self.call_history.append({
            "system_instruction": system_instruction,
            "user_prompt": user_prompt,
            "response_schema": response_schema,
        })

        if self.simulate_timeout:
            raise TimeoutError("LLM_TIMEOUT: Simulated timeout in MockProvider.")

        if self.simulate_error:
            raise RuntimeError(f"LLM_PROVIDER_ERROR: {self.simulate_error}")

        if self.custom_handler:
            result = self.custom_handler(system_instruction, user_prompt, response_schema)
            return response_schema.model_validate(result)

        if response_schema == LLMMCGCandidateResponse:
            if self.default_candidate_response is not None:
                return self.default_candidate_response  # type: ignore

            # Parse requested count from user prompt
            count_match = re.search(r"Requested MCQ Count:\s*(\d+)", user_prompt)
            if not count_match:
                count_match = re.search(r"Generate exactly\s*(\d+)", user_prompt)
            requested_count = int(count_match.group(1)) if count_match else 5

            # Parse source chunk IDs from user prompt if present
            chunk_matches = re.findall(r'<SOURCE id="([^"]+)">', user_prompt)
            cited_chunks = [chunk_matches[0]] if chunk_matches else ["SRC-001"]

            # Compute offset based on excluded stems in prompt
            excluded_stems = re.findall(r'-\s*(.+)', user_prompt)
            offset = len(excluded_stems) * 5

            # Programmatically generate dynamic synthetic MCQs
            questions: List[LLMMCGItem] = []
            for i in range(requested_count):
                n = i + 4 + offset
                sq = n * n
                qid = f"q_{i+1+offset}"
                questions.append(
                    LLMMCGItem(
                        question_id=qid,
                        stem=f"What is the square of {n}?",
                        stem_latex=None,
                        options=[
                            LLMMCGOption(id="opt_1", text=str(sq), latex=None),
                            LLMMCGOption(id="opt_2", text=str(sq + 5), latex=None),
                            LLMMCGOption(id="opt_3", text=str(sq - 3 if sq > 3 else sq + 8), latex=None),
                            LLMMCGOption(id="opt_4", text=str(sq + 10), latex=None),
                        ],
                        correct_option_id="opt_1",
                        explanation=f"{n} multiplied by {n} equals {sq}.",
                        source_chunk_ids=cited_chunks,
                    )
                )

            return LLMMCGCandidateResponse(
                insufficient_context=False,
                questions=questions,
            )  # type: ignore

        if response_schema == MCQVerificationResponse:
            if self.default_verification_response is not None:
                return self.default_verification_response  # type: ignore

            # Extract question IDs from candidate list in prompt
            q_ids = re.findall(r"\[Question:\s*([^\]]+)\]", user_prompt)
            if not q_ids:
                q_ids = ["q_1"]

            evals = [
                QuestionVerificationResult(
                    question_id=qid,
                    is_valid=True,
                    is_grounded_in_source=True,
                    is_single_correct_answer=True,
                    is_explanation_accurate=True,
                    is_stem_complete=True,
                    issues=[],
                )
                for qid in q_ids
            ]

            return MCQVerificationResponse(
                all_valid=True,
                evaluations=evals,
            )  # type: ignore

        return response_schema()
