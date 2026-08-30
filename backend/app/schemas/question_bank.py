from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field, model_validator


# --- Question Bank Item Schemas ---

class QuestionBankOptionSchema(BaseModel):
    id: str = Field(description="Stable persistent option ID, e.g. 'opt_...'")
    option_text: str = Field(description="Option text content")
    option_latex: Optional[str] = Field(default=None, description="LaTeX formula if applicable")
    canonical_order: int = Field(description="Canonical 0-indexed order in database")


class QuestionBankScopeSchema(BaseModel):
    id: str = Field(description="CurriculumNode ID")
    node_type: str
    source_label: str
    title: str
    detected_number: Optional[str] = None


class QuestionBankProvenanceSchema(BaseModel):
    subject_version_id: str
    curriculum_node_id: Optional[str] = None
    scope_label: Optional[str] = None
    page_number: Optional[int] = None
    source_content_snippet: Optional[str] = None
    origin_type: str = "AI_GENERATED"
    grounding_source: str = "OFFICIAL_NCTB"


class QuestionBankItemDetailResponse(BaseModel):
    id: str = Field(description="Stable QuestionBankItem ID, e.g. 'qbi_...'")
    subject_version_id: str
    subject_title: Optional[str] = None
    grade_name: Optional[str] = None
    subject_name: Optional[str] = None
    question_type: str = "MCQ"
    language: str = "en"
    question_text: str
    question_latex: Optional[str] = None
    options: List[QuestionBankOptionSchema] = Field(default_factory=list)
    correct_option_id: Optional[str] = None
    explanation: str
    difficulty: Optional[str] = None
    marks: Optional[float] = None
    origin_type: str = "AI_GENERATED"
    grounding_source: str = "OFFICIAL_NCTB"
    status: str = "ACTIVE"
    scopes: List[QuestionBankScopeSchema] = Field(default_factory=list)
    provenance: Optional[QuestionBankProvenanceSchema] = None
    created_at: str
    updated_at: str


class QuestionBankItemListResponse(BaseModel):
    items: List[QuestionBankItemDetailResponse] = Field(default_factory=list)
    total_count: int
    page: int
    page_size: int
    total_pages: int


from enum import Enum


class SavedQuestionBankItemMapping(BaseModel):
    generated_question_id: str = Field(description="Transient generated question ID (e.g. gen_q_...)")
    question_bank_item_id: str = Field(description="Persistent QuestionBankItem ID (qbi_...)")
    option_id_map: Dict[str, str] = Field(
        default_factory=dict,
        description="Map from transient generated option ID (gen_opt_...) to persistent DB QuestionBankOption ID (opt_...)",
    )
    is_created: bool = Field(description="True if freshly created, False if reused from existing canonical item")


class SaveGeneratedQuestionsRequest(BaseModel):
    job_id: str = Field(..., description="Generation job identifier holding validated accepted questions")
    question_ids: Optional[List[str]] = Field(default=None, description="Optional subset of question IDs to save. If omitted, saves all.")


class SaveGeneratedQuestionsResponse(BaseModel):
    new_questions_saved: int
    existing_questions_reused: int
    saved_items: List[QuestionBankItemDetailResponse] = Field(default_factory=list)
    saved_items_map: List[SavedQuestionBankItemMapping] = Field(default_factory=list)
    message: str


class BatchArchiveQuestionsRequest(BaseModel):
    question_ids: List[str] = Field(..., description="List of QuestionBankItem IDs to archive or unarchive")
    archive: bool = Field(default=True, description="True to archive, False to restore to active")


# --- Saved Paper / Question Set Schemas ---

class PaperSourceType(str, Enum):
    GENERATED_JOB = "GENERATED_JOB"
    QUESTION_BANK = "QUESTION_BANK"


class PaperMetadataSchema(BaseModel):
    institution_name: Optional[str] = Field(default="", description="School or Institution Name")
    exam_title: Optional[str] = Field(default="MCQ Question Paper", description="Title of the examination paper")
    subject_name: Optional[str] = Field(default="", description="Academic Subject")
    grade_name: Optional[str] = Field(default="", description="Class or Grade level")
    date: Optional[str] = Field(default="", description="Exam date")
    duration_minutes: Optional[int] = Field(default=30, description="Duration in minutes")
    marks_per_question: Optional[float] = Field(default=1.0, description="Marks allocated per MCQ")
    total_marks: Optional[float] = Field(default=None, description="Total marks (derived or custom)")
    instructions: Optional[str] = Field(
        default="Answer all questions. Each question carries 1 mark.",
        description="Exam candidate instructions",
    )


class QuestionArrangementRequest(BaseModel):
    question_id: str = Field(description="Stable question ID or candidate question ID from generation job")
    question_order: int = Field(description="Sequential question index in paper (1..N)")
    option_order: List[str] = Field(description="Ordered list of 4 stable option IDs for presentation arrangement")


class SavePaperRequest(BaseModel):
    source_type: PaperSourceType = Field(
        default=PaperSourceType.QUESTION_BANK,
        description="Discriminated paper source: GENERATED_JOB (from active generation job) or QUESTION_BANK (from persistent bank items)",
    )
    job_id: Optional[str] = Field(default=None, description="Optional generation job ID if saving from active generation")
    subject_version_id: str = Field(..., description="Target SubjectVersion UUID")
    title: str = Field(..., description="Title for the saved question paper")
    description: Optional[str] = Field(default=None, description="Optional notes or description")
    paper_metadata: Optional[PaperMetadataSchema] = Field(default=None, description="Dynamic header settings")
    arrangements: List[QuestionArrangementRequest] = Field(..., description="Ordered question and option arrangements")
    scope_node_ids: Optional[List[str]] = Field(default=None, description="Selected curriculum scope coverage node IDs")

    @model_validator(mode="after")
    def validate_source_type_contract(self) -> "SavePaperRequest":
        if self.source_type == PaperSourceType.GENERATED_JOB:
            if not self.job_id:
                raise ValueError("JOB_ID_REQUIRED: 'job_id' is required when source_type is 'GENERATED_JOB'.")
        elif self.source_type == PaperSourceType.QUESTION_BANK:
            if self.job_id is not None:
                raise ValueError("JOB_ID_FORBIDDEN: 'job_id' must not be provided when source_type is 'QUESTION_BANK'.")
        return self


class PaperItemOptionResponse(BaseModel):
    id: str
    label: str = Field(description="Display letter label in current arrangement: 'A', 'B', 'C', 'D'")
    text: str
    latex: Optional[str] = None


class PaperItemQuestionResponse(BaseModel):
    id: str = Field(description="QuestionBankItem stable ID")
    question_number: int = Field(description="Sequential question index (1..N)")
    question_text: str
    question_latex: Optional[str] = None
    options: List[PaperItemOptionResponse]
    correct_option_id: Optional[str] = None
    explanation: str


class PaperAnswerKeyItemResponse(BaseModel):
    question_number: int
    question_id: str
    correct_letter: str = Field(description="Assigned correct option letter in current arrangement: 'A', 'B', 'C', 'D'")
    correct_text: str
    correct_latex: Optional[str] = None
    explanation: str


class QuestionSetDetailResponse(BaseModel):
    id: str = Field(description="QuestionSet ID, e.g. 'qset_...'")
    title: str
    description: Optional[str] = None
    subject_version_id: str
    subject_title: Optional[str] = None
    grade_name: Optional[str] = None
    subject_name: Optional[str] = None
    set_type: str = "QUESTION_PAPER"
    question_count: int
    paper_metadata: Optional[PaperMetadataSchema] = None
    status: str = "ACTIVE"
    questions: List[PaperItemQuestionResponse] = Field(default_factory=list)
    answer_key: List[PaperAnswerKeyItemResponse] = Field(default_factory=list)
    scope_node_ids: List[str] = Field(default_factory=list)
    created_at: str
    updated_at: str


class QuestionSetSummaryResponse(BaseModel):
    id: str
    title: str
    description: Optional[str] = None
    subject_version_id: str
    subject_title: Optional[str] = None
    grade_name: Optional[str] = None
    subject_name: Optional[str] = None
    set_type: str = "QUESTION_PAPER"
    question_count: int
    status: str = "ACTIVE"
    created_at: str
    updated_at: str


class QuestionSetListResponse(BaseModel):
    items: List[QuestionSetSummaryResponse] = Field(default_factory=list)
    total_count: int
    page: int
    page_size: int
    total_pages: int
