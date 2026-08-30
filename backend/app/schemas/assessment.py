from typing import List, Optional
from pydantic import BaseModel, Field
from app.schemas.textbook import UnitScopeResponse


class MCQOptionResponse(BaseModel):
    id: Optional[str] = Field(default=None, description="Stable unique option identifier, e.g. 'opt_1'")
    label: str = Field(description="Display letter label assigned by backend: 'A', 'B', 'C', or 'D'")
    text: str = Field(description="Option text content")
    latex: Optional[str] = Field(default=None, description="LaTeX math formula if present")


class MCQQuestionResponse(BaseModel):
    id: Optional[str] = Field(default=None, description="Stable unique question identifier, e.g. 'q_1'")
    question_number: int = Field(description="Sequential question index (1..N)")
    question_text: str = Field(description="Question stem in plain text or with embedded $...$ math")
    question_latex: Optional[str] = Field(default=None, description="Pure LaTeX formula for stem if applicable")
    options: List[MCQOptionResponse] = Field(description="Exactly 4 options in validated sequence")
    correct_option_id: Optional[str] = Field(default=None, description="Stable ID of correct option for instant zero-LLM randomization")
    explanation: str = Field(description="Pedagogical step-by-step solution / rationale")


class MCQAnswerKeyItemResponse(BaseModel):
    question_number: int = Field(description="Sequential question index (1..N)")
    question_id: Optional[str] = Field(default=None, description="Matching stable question ID")
    correct_letter: str = Field(description="Assigned correct option letter: 'A', 'B', 'C', or 'D'")
    correct_text: str = Field(description="Text of the correct option")
    correct_latex: Optional[str] = Field(default=None, description="LaTeX of correct option if applicable")
    explanation: str = Field(description="Explanation for why this option is correct")


class SubjectVersionScopeInfo(BaseModel):
    id: str
    title: str
    grade: Optional[str] = None
    grade_id: Optional[int] = None
    subject: Optional[str] = None


class CurriculumScopeNodeResponse(BaseModel):
    id: str
    node_type: str = Field(description="chapter, unit, lesson, section, topic, exercise, activity, task, part...")
    source_label: str = Field(description="Exact source label, e.g. 'Chapter 1', 'Unit 1', 'Lesson 1.1'")
    title: str
    detected_number: Optional[str] = None
    depth: int = 0
    start_page: int
    end_page: Optional[int] = None
    children: List["CurriculumScopeNodeResponse"] = Field(default_factory=list)


class CurriculumScopeInfo(BaseModel):
    scope_node_ids: Optional[List[str]] = Field(default_factory=list, description="Normalized list of selected scope IDs")
    scope_node_id: Optional[str] = None
    scope_type: Optional[str] = None
    scope_label: Optional[str] = None
    scope_title: str
    unit_id: Optional[int] = None
    unit_title: Optional[str] = None
    lesson_id: Optional[int] = None
    lesson_title: Optional[str] = None


class MCQGenerateRequest(BaseModel):
    subject_version_id: str = Field(..., description="Ingested SubjectVersion UUID")
    grade_id: Optional[int] = Field(default=None, description="Selected Grade/Class database ID for cross-grade verification")
    scope_node_ids: Optional[List[str]] = Field(default=None, description="List of CurriculumNode IDs for multi-scope generation")
    scope_node_id: Optional[str] = Field(default=None, description="Legacy single CurriculumNode ID for backward compatibility")
    unit_id: Optional[int] = Field(default=None, description="Legacy Unit database ID for backward compatibility")
    lesson_id: Optional[int] = Field(default=None, description="Legacy Lesson database ID for backward compatibility")
    count: int = Field(default=5, ge=1, description="Requested number of MCQs")
    previous_request_id: Optional[str] = Field(default=None, description="Previous generation request ID for fresh variation on Generate New Set")
    previous_job_id: Optional[str] = Field(default=None, description="Previous generation job ID for fresh variation on Generate New Set")


class MCQGenerationResponse(BaseModel):
    request_id: str = Field(description="Unique ephemeral generation request identifier")
    subject_version: SubjectVersionScopeInfo
    scope: CurriculumScopeInfo
    requested_count: int
    generated_count: int
    questions: List[MCQQuestionResponse]
    answer_key: List[MCQAnswerKeyItemResponse]
    warnings: List[str] = Field(default_factory=list)


class MCQCapabilitiesResponse(BaseModel):
    subject_version_id: str
    title: str
    subject: Optional[str] = None
    subject_code: Optional[str] = None
    grade: Optional[str] = None
    grade_id: Optional[int] = None
    generation_supported: bool
    unsupported_reason: Optional[str] = None
    llm_configured: bool
    min_question_count: int = 1
    max_question_count: Optional[int] = None
    max_total_questions: Optional[int] = None
    default_question_count: int = 5
    generation_batch_size: int = 5
    supported_types: List[str] = Field(default_factory=lambda: ["MCQ"])
    scope_tree: List[CurriculumScopeNodeResponse] = Field(default_factory=list)
    units: List[UnitScopeResponse] = Field(default_factory=list)


# --- Ephemeral Progressive Generation Job Schemas ---

class MCQJobCreateResponse(BaseModel):
    job_id: str = Field(description="Unique identifier for the progressive generation job")
    status: str = Field(default="processing", description="processing, completed, incomplete, failed, cancelled")
    requested_count: int
    generated_count: int = 0


class MCQJobStatusResponse(BaseModel):
    job_id: str
    status: str = Field(description="processing, completed, incomplete, failed, cancelled")
    stage: str = Field(description="preparing_content, generating, validating, completed")
    stage_message: str = Field(description="Human-readable progress description, e.g. '5 of 10 ready'")
    requested_count: int
    generated_count: int
    questions: List[MCQQuestionResponse] = Field(default_factory=list)
    answer_key: List[MCQAnswerKeyItemResponse] = Field(default_factory=list)
    complete: bool
    error: Optional[str] = None
    warnings: List[str] = Field(default_factory=list)


class MCQJobCancelResponse(BaseModel):
    job_id: str
    status: str = "cancelled"
    message: str = "Generation job successfully cancelled."
