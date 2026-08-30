from enum import Enum
from typing import Dict, List, Optional
from pydantic import BaseModel, Field


class BlockType(str, Enum):
    HEADING = "heading"
    PARAGRAPH = "paragraph"
    MATH_DISPLAY = "math_display"
    EXAMPLE = "example"
    ACTIVITY = "activity"
    EXERCISE = "exercise"
    TABLE = "table"
    LIST = "list"
    DEFINITION = "definition"
    NOTE = "note"
    GENERIC = "generic"


class SourceRegion(BaseModel):
    page: int
    bbox: Dict[str, float] = Field(
        ...,
        description="Bounding box in 72 DPI PDF point coordinates: x0, y0, x1, y1"
    )


class TextSpan(BaseModel):
    text: str
    is_bold: bool = False
    is_italic: bool = False
    is_math: bool = False
    latex: Optional[str] = None
    raw_text: Optional[str] = None
    is_uncertain: bool = False


class TableCell(BaseModel):
    text: str
    is_header: bool = False
    math_latex: Optional[str] = None
    raw_text: Optional[str] = None


class TableRow(BaseModel):
    cells: List[TableCell] = []


class ListItem(BaseModel):
    marker: str
    text: str
    spans: List[TextSpan] = []
    source_regions: List[SourceRegion] = []


class SemanticBlock(BaseModel):
    id: str
    block_type: BlockType
    ordinal: int
    title: Optional[str] = None
    level: Optional[int] = None
    content_text: str
    spans: List[TextSpan] = []
    math_latex: Optional[str] = None
    raw_math_text: Optional[str] = None
    rows: Optional[List[TableRow]] = None
    items: Optional[List[ListItem]] = None
    problem_text: Optional[str] = None
    solution_text: Optional[str] = None
    source_pages: List[int] = []
    source_node_ids: List[int] = []
    source_regions: List[SourceRegion] = []
    warnings: List[str] = []


class ReadableDocumentResponse(BaseModel):
    version_id: str
    scope_type: str  # "lesson", "unit", or "page"
    scope_id: Optional[int] = None
    title: str
    subtitle: Optional[str] = None
    grade: Optional[str] = None
    subject: Optional[str] = None
    start_page: int
    end_page: int
    layout_source: str = "raw_pdf_geometry"  # "raw_pdf_geometry" or "persisted_ast_fallback"
    blocks: List[SemanticBlock] = []
    warnings: List[str] = []
