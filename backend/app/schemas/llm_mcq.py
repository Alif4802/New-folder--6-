from typing import List, Optional
from pydantic import BaseModel, Field


class LLMMCGOption(BaseModel):
    id: str = Field(description="Stable unique option identifier, e.g. 'opt_1', 'opt_2', 'opt_3', 'opt_4'")
    text: str = Field(description="Option text content")
    latex: Optional[str] = Field(default=None, description="Pure LaTeX formula for option if applicable")


class LLMMCGItem(BaseModel):
    question_id: str = Field(description="Unique question identifier within candidate set, e.g. 'q_1'")
    stem: str = Field(description="Question stem in plain text with embedded $...$ math or Markdown")
    stem_latex: Optional[str] = Field(default=None, description="Pure LaTeX formula for stem if applicable")
    options: List[LLMMCGOption] = Field(description="Exactly 4 distinct options already arranged in randomized order by the LLM")
    correct_option_id: str = Field(description="Option ID matching the single mathematically correct answer")
    explanation: str = Field(description="Concise step-by-step mathematical explanation / pedagogical solution")
    source_chunk_ids: List[str] = Field(description="List of cited request-local source chunk IDs, e.g. ['SRC-001']")


class LLMMCGCandidateResponse(BaseModel):
    insufficient_context: bool = Field(default=False, description="True if supplied source text lacks enough content to generate requested MCQs")
    insufficient_reason: Optional[str] = Field(default=None, description="Explanation if source context was insufficient")
    questions: List[LLMMCGItem] = Field(default_factory=list, description="List of generated MCQ items")


# --- LLM Verification Pass Schemas ---

class QuestionVerificationResult(BaseModel):
    question_id: str = Field(description="Question ID being verified")
    is_valid: bool = Field(description="True if the question passes all grounding, correctness, and distractor checks")
    is_grounded_in_source: bool = Field(description="True if supported by cited source chunks")
    is_single_correct_answer: bool = Field(description="True if exactly one option is mathematically correct")
    is_explanation_accurate: bool = Field(description="True if explanation is accurate and consistent with the correct option")
    is_stem_complete: bool = Field(default=True, description="True if the question stem is a complete self-contained problem")
    duplicate_of_question_id: Optional[str] = Field(default=None, description="ID of another question in the set if this is a semantic duplicate")
    issues: List[str] = Field(default_factory=list, description="Specific issues identified if not valid")


class MCQVerificationResponse(BaseModel):
    all_valid: bool = Field(description="True if all questions in the set pass verification")
    evaluations: List[QuestionVerificationResult] = Field(default_factory=list, description="Per-question evaluation results")
