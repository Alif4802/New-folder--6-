from datetime import datetime
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, ConfigDict


class ActivityNodeSummary(BaseModel):
    """Compact summary of an activity node for lightweight tree browsing."""
    model_config = ConfigDict(from_attributes=True)

    id: int
    ordinal: int
    node_type: str
    title: Optional[str] = None
    page_number: int
    bounding_box: Optional[Dict[str, float]] = None
    content_hash: str
    content_preview: str


class ActivityNodeDetailResponse(BaseModel):
    """Full detail of an individual activity node with complete content text and payload."""
    model_config = ConfigDict(from_attributes=True)

    id: int
    subject_version_id: str
    unit_id: int
    lesson_id: Optional[int] = None
    ordinal: int
    node_type: str
    title: Optional[str] = None
    content_text: str
    structured_payload: Optional[Any] = None
    page_number: int
    bounding_box: Optional[Dict[str, float]] = None
    content_hash: str
    parser_metadata: Optional[Dict[str, Any]] = None
    created_at: datetime


class LessonTreeResponse(BaseModel):
    """Lesson node in the textbook hierarchy."""
    model_config = ConfigDict(from_attributes=True)

    id: int
    ordinal: int
    detected_number: Optional[str] = None
    title: str
    start_page: int
    end_page: Optional[int] = None
    activity_nodes: List[ActivityNodeSummary] = []


class LessonScopeResponse(BaseModel):
    """Minimal lesson info for curriculum scope selection."""
    model_config = ConfigDict(from_attributes=True)

    id: int
    detected_number: Optional[str] = None
    title: str


class UnitScopeResponse(BaseModel):
    """Minimal unit info for curriculum scope selection."""
    model_config = ConfigDict(from_attributes=True)

    id: int
    detected_number: str
    title: str
    lessons: List[LessonScopeResponse] = []


class CurriculumScopeResponse(BaseModel):
    """Minimal curriculum scope response for Phase 4 MCQ generation."""
    model_config = ConfigDict(from_attributes=True)

    version_id: str
    units: List[UnitScopeResponse] = []


class TOCItemResponse(BaseModel):
    """Clean navigation item for Table of Contents (Unit, Lesson, or reliably detected Exercise)."""
    model_config = ConfigDict(from_attributes=True)

    type: str  # "unit" | "lesson" | "exercise"
    label: str
    number: Optional[str] = None
    page_number: int  # Physical PDF page number (backward compatible)
    pdf_page_number: int  # Physical PDF page number (1-indexed)
    book_page_label: Optional[str] = None  # Printed textbook page label (e.g. "27", "125", "i")
    children: Optional[List["TOCItemResponse"]] = None


class TextbookTOCResponse(BaseModel):
    """Sanitized, client-safe Table of Contents navigation tree for an ingested textbook."""
    model_config = ConfigDict(from_attributes=True)

    version_id: str
    items: List[TOCItemResponse] = []


class UnitTreeResponse(BaseModel):
    """Unit or Chapter node in the textbook hierarchy."""
    model_config = ConfigDict(from_attributes=True)

    id: int
    ordinal: int
    detected_number: str
    label_type: str
    title: str
    start_page: int
    end_page: Optional[int] = None
    lessons: List[LessonTreeResponse] = []
    direct_activity_nodes: List[ActivityNodeSummary] = []


class GradeSummary(BaseModel):
    """Canonical compact Grade metadata contract."""
    model_config = ConfigDict(from_attributes=True)

    id: int
    code: str
    name: str
    display_name: str
    level_number: Optional[int] = None
    is_active: bool = True


class GradeResponse(BaseModel):
    """Authoritative Grade response from /api/v1/grades."""
    model_config = ConfigDict(from_attributes=True)

    id: int
    curriculum_id: int
    code: str
    name: str
    display_name: str
    level_number: Optional[int] = None
    is_active: bool = True
    textbook_count: int = 0


class SubjectSummary(BaseModel):
    """Canonical academic subject scoped to a curriculum."""
    model_config = ConfigDict(from_attributes=True)

    id: int
    curriculum_id: int
    code: str
    name: str
    domain: str
    is_supported_for_generation: bool = True


class SubjectResponse(BaseModel):
    """Container response for canonical curriculum subjects."""
    subjects: List[SubjectSummary]
    total: int


class TextbookTreeResponse(BaseModel):
    """Bounded textbook structural tree containing unit/lesson hierarchy with node summaries."""
    model_config = ConfigDict(from_attributes=True)

    version_id: str
    title: str
    grade: Optional[str] = None
    grade_id: Optional[int] = None
    grade_info: Optional[GradeSummary] = None
    subject: Optional[str] = None
    subject_id: Optional[int] = None
    domain: Optional[str] = None
    edition_year: Optional[int] = None
    edition_label: Optional[str] = None
    publication_year: Optional[int] = None
    page_count: int
    ingestion_status: str
    curriculum_quality_status: str = "UNASSESSED"
    metadata_status: str = "UNASSESSED"
    assessment_ready: bool = True
    assessment_readiness_reasons: List[str] = []
    warnings: Optional[List[str]] = None
    error_message: Optional[str] = None
    units: List[UnitTreeResponse] = []


class TextbookVersionSummary(BaseModel):
    """Summary item for the ingested textbooks listing."""
    model_config = ConfigDict(from_attributes=True)

    id: str
    title: str
    grade: Optional[str] = None
    grade_id: Optional[int] = None
    grade_info: Optional[GradeSummary] = None
    subject: Optional[str] = None
    subject_id: Optional[int] = None
    domain: Optional[str] = None
    edition_year: Optional[int] = None
    edition_label: Optional[str] = None
    publication_year: Optional[int] = None
    page_count: int
    ingestion_status: str
    curriculum_quality_status: str = "UNASSESSED"
    metadata_status: str = "UNASSESSED"
    assessment_ready: bool = True
    assessment_readiness_reasons: List[str] = []
    ocr_pages_count: int
    is_deleted: bool = False
    error_message: Optional[str] = None
    created_at: datetime


class UpdateTextbookMetadataRequest(BaseModel):
    """Request payload for updating textbook metadata without re-uploading PDF."""
    title: Optional[str] = None
    grade_id: Optional[int] = None
    subject_id: Optional[int] = None
    edition_label: Optional[str] = None
    publication_year: Optional[int] = None


class TextbookDependencySummary(BaseModel):
    """Analysis of dependent records before textbook soft-deletion."""
    version_id: str
    title: str
    curriculum_nodes_count: int = 0
    activity_nodes_count: int = 0
    question_bank_items_count: int = 0
    question_sets_count: int = 0
    can_soft_delete: bool = True


class IngestionResponse(BaseModel):
    """Immediate response after textbook ingestion is executed."""
    version_id: str
    title: str
    grade_id: Optional[int] = None
    grade_name: Optional[str] = None
    subject_id: Optional[int] = None
    detected_grade: Optional[str] = None
    detected_subject: Optional[str] = None
    detected_domain: Optional[str] = None
    edition_label: Optional[str] = None
    publication_year: Optional[int] = None
    curriculum_quality_status: str = "VALID"
    metadata_status: str = "VALID"
    assessment_ready: bool = True
    assessment_readiness_reasons: List[str] = []
    page_count: int
    unit_count: int
    lesson_count: int
    activity_node_count: int
    ocr_pages_count: int
    ingestion_status: str
    warnings: List[str] = []


class PDFMetadataResponse(BaseModel):
    """Diagnostic and file metadata for an ingested textbook."""
    model_config = ConfigDict(from_attributes=True)

    version_id: str
    source_filename: str
    file_size_bytes: int
    checksum_sha256: str
    page_count: int
    ocr_pages_count: int = 0
    ingestion_status: str
    pdf_available: bool = True
    detected_metadata: Optional[Dict[str, Any]] = None
    warnings: Optional[List[str]] = None
    error_message: Optional[str] = None


# Re-export readable schemas
from app.schemas.readable import (
    BlockType,
    SourceRegion,
    TextSpan,
    TableCell,
    TableRow,
    ListItem,
    SemanticBlock,
    ReadableDocumentResponse,
)

