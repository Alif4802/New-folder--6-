from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple
import re
from app.services.pdf.number_parser import NumberTokenParser
from app.services.pdf.reading_order import TextLine
from app.services.pdf.classifier import ActivityNodeClassifier, compute_content_hash
from app.services.pdf.extractor import PageExtractionResult


@dataclass
class ParsedActivityNode:
    ordinal: int
    node_type: str
    title: Optional[str]
    content_text: str
    structured_payload: Optional[Any]
    page_number: int
    bounding_box: Optional[Dict[str, float]]
    content_hash: str
    parser_metadata: Optional[Dict[str, Any]]


@dataclass
class ParsedLesson:
    ordinal: int
    detected_number: Optional[str]
    title: str
    start_page: int
    end_page: Optional[int] = None
    nodes: List[ParsedActivityNode] = field(default_factory=list)


@dataclass
class ParsedUnit:
    ordinal: int
    detected_number: str
    label_type: str
    title: str
    start_page: int
    end_page: Optional[int] = None
    lessons: List[ParsedLesson] = field(default_factory=list)
    direct_nodes: List[ParsedActivityNode] = field(default_factory=list)


@dataclass
class ParsedDocumentStructure:
    units: List[ParsedUnit]
    unresolved_front_matter_pages: List[int]
    warnings: List[str]


class DynamicStructureParser:
    """
    Parses extracted page lines into dynamic Units, Lessons, and ActivityNodes.
    Uses reusable token parsing without hardcoded chapter names or page limits.
    """

    # Dynamic Unit/Chapter heading regex
    UNIT_PATTERN = re.compile(
        r"(?i)^(UNIT|CHAPTER|MODULE|PART)\s+([A-Za-z0-9IVXLCDM\.\-]+)\s*[:.\-—]?\s*(.*)$"
    )

    # Dynamic Lesson/Section heading regex
    LESSON_PATTERN = re.compile(
        r"(?i)^(LESSON|SECTION|TOPIC)\s+([A-Za-z0-9IVXLCDM\.\-]+)\s*[:.\-—]?\s*(.*)$"
    )

    # Dotted section pattern (e.g. "1.1 Introduction to Real Numbers")
    DOTTED_SECTION_PATTERN = re.compile(
        r"^(\d+\.\d+)\s+([A-Z].*)$"
    )

    # TOC Dot leader pattern (e.g. "Unit 1: Father of the Nation .......... Page 3")
    TOC_ENTRY_PATTERN = re.compile(
        r"(\.{3,}|\_{3,}|\-{3,})\s*(?:page\s*)?\d+\b|\bpage\s+\d+$",
        re.IGNORECASE,
    )

    @classmethod
    def _is_toc_page(cls, lines: List[TextLine]) -> bool:
        """Check if page is a Table of Contents page."""
        for line in lines[:5]:
            clean = line.text.strip().lower()
            if clean in ["contents", "table of contents", "index", "content"]:
                return True
            if clean.startswith("table of contents") or clean.startswith("contents"):
                return True
        return False

    @classmethod
    def _match_unit_header(cls, text: str, next_line_text: str = "") -> Optional[Tuple[str, str, str, bool]]:
        """
        Detect Unit/Chapter header.
        Returns (label_type, detected_number, title, consumed_next_line) or None.
        """
        clean = text.strip()

        # Reject if this is a Table of Contents entry line
        if cls.TOC_ENTRY_PATTERN.search(clean):
            return None

        m = cls.UNIT_PATTERN.match(clean)
        if m:
            label_type = m.group(1).capitalize()
            raw_num = m.group(2)
            title = m.group(3).strip()

            parsed_num = NumberTokenParser.parse_token(raw_num) or raw_num
            consumed_next = False

            # If title was on the next line (e.g. "Unit 1" on line 1, "Father of the Nation" on line 2)
            if not title and next_line_text and not cls.UNIT_PATTERN.match(next_line_text) and not cls.LESSON_PATTERN.match(next_line_text):
                title = next_line_text.strip()
                consumed_next = True
            elif not title:
                title = f"{label_type} {parsed_num}"

            return label_type, parsed_num, title, consumed_next

        return None

    @classmethod
    def _match_lesson_header(cls, text: str, next_line_text: str = "") -> Optional[Tuple[str, str, bool]]:
        """
        Detect Lesson/Section header.
        Returns (detected_number, title, consumed_next_line) or None.
        """
        clean = text.strip()

        # Reject if TOC entry
        if cls.TOC_ENTRY_PATTERN.search(clean):
            return None

        m = cls.LESSON_PATTERN.match(clean)
        if m:
            label_type = m.group(1).capitalize()
            raw_num = m.group(2)
            title = m.group(3).strip()

            parsed_num = NumberTokenParser.parse_token(raw_num) or raw_num
            consumed_next = False

            if not title and next_line_text and not cls.LESSON_PATTERN.match(next_line_text) and not cls.UNIT_PATTERN.match(next_line_text):
                title = next_line_text.strip()
                consumed_next = True
            elif not title:
                title = f"{label_type} {parsed_num}"

            return parsed_num, title, consumed_next

        # Check for dotted section pattern (e.g. "2.1 Set Operations")
        dm = cls.DOTTED_SECTION_PATTERN.match(clean)
        if dm:
            return dm.group(1), dm.group(2).strip(), False

        return None

    @classmethod
    def parse_document(
        cls,
        page_results: List[PageExtractionResult],
        domain: str = "GENERAL",
    ) -> ParsedDocumentStructure:
        """
        Main structural parsing pipeline.
        Processes pages sequentially, discovering unit and lesson boundaries.
        Front-matter and TOC pages prior to Unit 1 are cleanly logged rather than forced into fake units.
        """
        units: List[ParsedUnit] = []
        unresolved_front_matter_pages: List[int] = []
        warnings: List[str] = []

        current_unit: Optional[ParsedUnit] = None
        current_lesson: Optional[ParsedLesson] = None
        global_node_ordinal = 1

        for page in page_results:
            p_num = page.page_number
            if page.warning:
                warnings.append(page.warning)

            lines = page.lines
            if not lines:
                if current_unit is None:
                    unresolved_front_matter_pages.append(p_num)
                continue

            # Check if entire page is TOC before Unit 1
            if current_unit is None and cls._is_toc_page(lines):
                unresolved_front_matter_pages.append(p_num)
                continue

            i = 0
            pending_node_lines: List[TextLine] = []

            def flush_pending_node():
                nonlocal global_node_ordinal, pending_node_lines
                if not pending_node_lines:
                    return

                if current_unit is None:
                    # Lines occurred before any unit was discovered (front matter)
                    if p_num not in unresolved_front_matter_pages:
                        unresolved_front_matter_pages.append(p_num)
                    pending_node_lines = []
                    return

                block_text = "\n".join(l.text for l in pending_node_lines).strip()
                if not block_text:
                    pending_node_lines = []
                    return

                bx0 = min(l.x0 for l in pending_node_lines)
                by0 = min(l.y0 for l in pending_node_lines)
                bx1 = max(l.x1 for l in pending_node_lines)
                by1 = max(l.y1 for l in pending_node_lines)

                node_type, node_title, node_payload = ActivityNodeClassifier.classify_block(
                    text=block_text,
                    domain=domain,
                )

                content_hash = compute_content_hash(block_text)

                node = ParsedActivityNode(
                    ordinal=global_node_ordinal,
                    node_type=node_type,
                    title=node_title,
                    content_text=block_text,
                    structured_payload=node_payload,
                    page_number=p_num,
                    bounding_box={"x0": bx0, "y0": by0, "x1": bx1, "y1": by1},
                    content_hash=content_hash,
                    parser_metadata={
                        "extraction_source": "winocr" if page.ocr_used else "native",
                    },
                )
                global_node_ordinal += 1

                if current_lesson:
                    current_lesson.nodes.append(node)
                else:
                    current_unit.direct_nodes.append(node)

                pending_node_lines = []

            while i < len(lines):
                line = lines[i]
                next_line = lines[i + 1] if i + 1 < len(lines) else None
                next_line_text = next_line.text if next_line else ""

                # 1. Check for Unit Header
                unit_match = cls._match_unit_header(line.text, next_line_text)
                if unit_match:
                    flush_pending_node()
                    label_type, det_num, unit_title, consumed_next = unit_match

                    if current_unit:
                        current_unit.end_page = max(current_unit.start_page, p_num - 1 if p_num > current_unit.start_page else p_num)
                        if current_lesson:
                            current_lesson.end_page = max(current_lesson.start_page, p_num - 1 if p_num > current_lesson.start_page else p_num)
                            current_lesson = None

                    unit_ordinal = len(units) + 1
                    current_unit = ParsedUnit(
                        ordinal=unit_ordinal,
                        detected_number=det_num,
                        label_type=label_type,
                        title=unit_title,
                        start_page=p_num,
                    )
                    units.append(current_unit)
                    current_lesson = None

                    i += 2 if consumed_next else 1
                    continue

                # 2. Check for Lesson Header
                lesson_match = cls._match_lesson_header(line.text, next_line_text)
                if lesson_match:
                    flush_pending_node()
                    det_lesson_num, lesson_title, consumed_next = lesson_match

                    if current_unit is None:
                        current_unit = ParsedUnit(
                            ordinal=1,
                            detected_number="1",
                            label_type="Unit",
                            title="Unit 1",
                            start_page=p_num,
                        )
                        units.append(current_unit)

                    if current_lesson:
                        current_lesson.end_page = max(current_lesson.start_page, p_num - 1 if p_num > current_lesson.start_page else p_num)

                    lesson_ordinal = len(current_unit.lessons) + 1
                    current_lesson = ParsedLesson(
                        ordinal=lesson_ordinal,
                        detected_number=det_lesson_num,
                        title=lesson_title,
                        start_page=p_num,
                    )
                    current_unit.lessons.append(current_lesson)

                    i += 2 if consumed_next else 1
                    continue

                # 3. Regular Content Line
                if pending_node_lines:
                    prev_line = pending_node_lines[-1]
                    vertical_gap = line.y0 - prev_line.y1
                    avg_height = (prev_line.height + line.height) / 2.0
                    # Break into a new activity node if large vertical gap or distinct section starter
                    if vertical_gap > max(14.0, avg_height * 1.6):
                        flush_pending_node()

                pending_node_lines.append(line)
                i += 1

            flush_pending_node()

        # Finalize open end pages
        if units:
            last_page = page_results[-1].page_number if page_results else 1
            for u in units:
                if u.end_page is None or u.end_page < u.start_page:
                    u.end_page = last_page
                for l in u.lessons:
                    if l.end_page is None or l.end_page < l.start_page:
                        l.end_page = last_page

        return ParsedDocumentStructure(
            units=units,
            unresolved_front_matter_pages=unresolved_front_matter_pages,
            warnings=warnings,
        )
