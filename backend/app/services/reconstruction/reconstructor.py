import asyncio
import logging
import re
from pathlib import Path
from typing import Dict, List, Optional, Set, Tuple
import pymupdf
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.config import settings
from app.models.textbook import ActivityNode, Lesson, SubjectVersion, Unit
from app.schemas.readable import (
    BlockType,
    ListItem,
    ReadableDocumentResponse,
    SemanticBlock,
    SourceRegion,
    TableCell,
    TableRow,
    TextSpan,
)
from app.services.reconstruction.config import ReconstructionRules, get_reconstruction_rules
from app.services.reconstruction.header_footer_filter import HeaderFooterFilter
from app.services.reconstruction.layout_extractor import LayoutExtractor, LayoutLine, PageLayout
from app.services.reconstruction.math_normalizer import MathNormalizer
from app.services.reconstruction.table_detector import TableDetector

logger = logging.getLogger("nctb.reconstruction.engine")


class ReconstructionEngine:
    """
    Core deterministic engine for reconstructing student-friendly readable textbook documents
    using stored raw PDF layout authority alongside persisted curriculum hierarchy.
    """

    def __init__(self, rules: Optional[ReconstructionRules] = None):
        self.rules = rules or get_reconstruction_rules()
        self.header_footer_filter = HeaderFooterFilter(self.rules)
        self.layout_extractor = LayoutExtractor(self.rules)
        self.math_normalizer = MathNormalizer(self.rules)
        self.table_detector = TableDetector(self.rules)

    def _resolve_scope_pages(
        self,
        version: SubjectVersion,
        unit: Optional[Unit],
        lesson: Optional[Lesson],
        page: Optional[int],
    ) -> Tuple[int, int, str, Optional[int], str, Optional[str]]:
        """
        Deterministically resolves start_page, end_page, scope_type, scope_id, title, and subtitle.
        Handles nullable end_page fields gracefully.
        """
        page_count = version.page_count or 1

        if lesson is not None:
            scope_type = "lesson"
            scope_id = lesson.id
            start_p = lesson.start_page
            # Nullable end_page resolution for Lesson
            if lesson.end_page is not None and lesson.end_page >= start_p:
                end_p = lesson.end_page
            else:
                # Check next lesson in parent unit
                parent_unit = lesson.unit
                if parent_unit and parent_unit.lessons:
                    sorted_lessons = sorted(parent_unit.lessons, key=lambda l: (l.start_page, l.ordinal))
                    curr_idx = next((i for i, l in enumerate(sorted_lessons) if l.id == lesson.id), -1)
                    if curr_idx != -1 and curr_idx + 1 < len(sorted_lessons):
                        end_p = max(start_p, sorted_lessons[curr_idx + 1].start_page - 1)
                    elif parent_unit.end_page is not None and parent_unit.end_page >= start_p:
                        end_p = parent_unit.end_page
                    elif version.units:
                        sorted_units = sorted(version.units, key=lambda u: (u.start_page, u.ordinal))
                        u_idx = next((i for i, u in enumerate(sorted_units) if u.id == parent_unit.id), -1)
                        if u_idx != -1 and u_idx + 1 < len(sorted_units):
                            end_p = max(start_p, sorted_units[u_idx + 1].start_page - 1)
                        else:
                            end_p = page_count
                    else:
                        end_p = page_count
                else:
                    end_p = page_count


            title = lesson.title or f"Lesson {lesson.detected_number or lesson.ordinal}"
            subtitle = f"Unit {lesson.unit.detected_number}: {lesson.unit.title}" if lesson.unit else None

        elif unit is not None:
            scope_type = "unit"
            scope_id = unit.id
            start_p = unit.start_page
            # Nullable end_page resolution for Unit
            if unit.end_page is not None and unit.end_page >= start_p:
                end_p = unit.end_page
            else:
                # Check next unit in version
                if version.units:
                    sorted_units = sorted(version.units, key=lambda u: (u.start_page, u.ordinal))
                    curr_idx = next((i for i, u in enumerate(sorted_units) if u.id == unit.id), -1)
                    if curr_idx != -1 and curr_idx + 1 < len(sorted_units):
                        end_p = max(start_p, sorted_units[curr_idx + 1].start_page - 1)
                    else:
                        end_p = page_count
                else:
                    end_p = page_count

            title = unit.title or f"Unit {unit.detected_number or unit.ordinal}"
            subtitle = version.title

        elif page is not None:
            scope_type = "page"
            scope_id = page
            start_p = page
            end_p = page
            title = f"Page {page}"
            subtitle = version.title
        else:
            raise ValueError("Exactly one scope parameter (lesson_id, unit_id, or page) must be provided.")

        # Bound validation against total pages
        start_p = max(1, min(start_p, page_count))
        end_p = max(start_p, min(end_p, page_count))

        return start_p, end_p, scope_type, scope_id, title, subtitle

    @staticmethod
    def _match_activity_node_ids(
        line_bbox: Dict[str, float],
        page_num: int,
        nodes: List[ActivityNode],
    ) -> List[int]:
        """
        Matches a line bounding box against persisted ActivityNodes on the same page.
        """
        matched_ids: List[int] = []
        for node in nodes:
            if node.page_number != page_num:
                continue
            nb = node.bounding_box or {}
            # Vertical overlap check
            if not (line_bbox["y1"] < nb.get("y0", 0) or line_bbox["y0"] > nb.get("y1", 9999)):
                matched_ids.append(node.id)
        return matched_ids

    def reconstruct_from_persisted_ast_fallback(
        self,
        version: SubjectVersion,
        nodes: List[ActivityNode],
        start_page: int,
        end_page: int,
        scope_type: str,
        scope_id: Optional[int],
        title: str,
        subtitle: Optional[str],
        custom_warning: Optional[str] = None,
    ) -> ReadableDocumentResponse:
        """
        Degraded fallback reconstruction when raw physical PDF is unavailable on disk or has no native text layer.
        Does NOT infer geometry-dependent superscripts or fake geometric tables.
        """
        warning_msg = custom_warning or "RAW_PDF_LAYOUT_UNAVAILABLE: Stored physical PDF not found on disk. Rendered from persisted AST fallback."
        warnings = [warning_msg]
        blocks: List[SemanticBlock] = []
        ordinal = 1


        for node in nodes:
            text = (node.content_text or "").strip()
            if not text:
                continue

            # Check if this node starts with a known semantic marker
            block_type = BlockType.PARAGRAPH
            for m in self.rules.markers.example_starters:
                if text.lower().startswith(m.lower()):
                    block_type = BlockType.EXAMPLE
                    break
            for m in self.rules.markers.activity_starters:
                if text.lower().startswith(m.lower()):
                    block_type = BlockType.ACTIVITY
                    break
            for m in self.rules.markers.exercise_starters:
                if text.lower().startswith(m.lower()):
                    block_type = BlockType.EXERCISE
                    break

            # Create fallback block
            spans = [TextSpan(text=text, raw_text=text)]
            regions = [SourceRegion(page=node.page_number, bbox=node.bounding_box or {"x0": 72, "y0": 72, "x1": 500, "y1": 100})]

            blocks.append(
                SemanticBlock(
                    id=f"ast-{node.id}",
                    block_type=block_type,
                    ordinal=ordinal,
                    title=node.title,
                    content_text=text,
                    spans=spans,
                    source_pages=[node.page_number],
                    source_node_ids=[node.id],
                    source_regions=regions,
                    warnings=["Rendered from persisted AST without raw PDF geometry"],
                )
            )
            ordinal += 1

        return ReadableDocumentResponse(
            version_id=version.id,
            scope_type=scope_type,
            scope_id=scope_id,
            title=title,
            subtitle=subtitle,
            grade=version.grade.name if version.grade else None,
            subject=version.subject.name if version.subject else None,
            start_page=start_page,
            end_page=end_page,
            layout_source="persisted_ast_fallback",
            blocks=blocks,
            warnings=warnings,
        )

    def reconstruct_from_pdf_layout(
        self,
        version: SubjectVersion,
        page_layouts: List[PageLayout],
        version_header_patterns: Set[str],
        ast_nodes: List[ActivityNode],
        start_page: int,
        end_page: int,
        scope_type: str,
        scope_id: Optional[int],
        title: str,
        subtitle: Optional[str],
    ) -> ReadableDocumentResponse:
        """
        Reconstructs semantic content blocks from high-fidelity PDF page layouts.
        """
        blocks: List[SemanticBlock] = []
        global_block_ordinal = 1
        warnings: List[str] = []

        # Filter out running headers and footers from each page's lines
        filtered_page_lines: List[Tuple[PageLayout, List[LayoutLine]]] = []
        for p_layout in page_layouts:
            clean_lines: List[LayoutLine] = []
            for line in p_layout.lines:
                if self.header_footer_filter.is_header_or_footer(
                    text=line.text,
                    y0=line.y0,
                    y1=line.y1,
                    page_height=p_layout.height,
                    version_patterns=version_header_patterns,
                ):
                    continue
                clean_lines.append(line)
            filtered_page_lines.append((p_layout, clean_lines))

        # Flatten clean lines across the scope pages
        all_lines: List[LayoutLine] = []
        for _, lines in filtered_page_lines:
            all_lines.extend(lines)

        if not all_lines:
            if ast_nodes:
                return self.reconstruct_from_persisted_ast_fallback(
                    version=version,
                    nodes=ast_nodes,
                    start_page=start_page,
                    end_page=end_page,
                    scope_type=scope_type,
                    scope_id=scope_id,
                    title=title,
                    subtitle=subtitle,
                    custom_warning="RAW_PDF_NATIVE_TEXT_UNAVAILABLE: Physical PDF has no native vector text layer on these pages (scanned image PDF). Rendered from persisted OCR/AST fallback.",
                )


            return ReadableDocumentResponse(
                version_id=version.id,
                scope_type=scope_type,
                scope_id=scope_id,
                title=title,
                subtitle=subtitle,
                grade=version.grade.name if version.grade else None,
                subject=version.subject.name if version.subject else None,
                start_page=start_page,
                end_page=end_page,
                layout_source="raw_pdf_geometry",
                blocks=[],
                warnings=warnings,
            )


        # Baseline body font size for the scope
        all_sizes = [l.median_font_size for l in all_lines]
        body_font_size = sorted(all_sizes)[len(all_sizes) // 2] if all_sizes else 11.0

        i = 0
        n_lines = len(all_lines)

        while i < n_lines:
            line = all_lines[i]
            p_layout = next((pl for pl, _ in filtered_page_lines if pl.page_number == line.page_number), page_layouts[0])

            # 1. Check for Table Block
            table_match = self.table_detector.detect_table_block(
                lines=all_lines[i:],
                drawings=p_layout.drawings,
            )
            if table_match is not None:
                table_rows, consumed_lines, _ = table_match
                t_pages = sorted(list(set(l.page_number for l in consumed_lines)))
                t_regions = [SourceRegion(page=l.page_number, bbox=l.bbox_dict) for l in consumed_lines]
                t_nodes: Set[int] = set()
                for l in consumed_lines:
                    t_nodes.update(self._match_activity_node_ids(l.bbox_dict, l.page_number, ast_nodes))

                blocks.append(
                    SemanticBlock(
                        id=f"tbl-{line.page_number}-{line.y0:.0f}",
                        block_type=BlockType.TABLE,
                        ordinal=global_block_ordinal,
                        content_text="\n".join(l.text for l in consumed_lines),
                        rows=table_rows,
                        source_pages=t_pages,
                        source_node_ids=sorted(list(t_nodes)),
                        source_regions=t_regions,
                    )
                )
                global_block_ordinal += 1
                i += len(consumed_lines)
                continue

            # 2. Check for List Item
            list_marker_match = re.match(r"^(\u2022|\u25cf|[\-\*]|\d+\.|\([0-9a-zA-Z]+\)|[a-zA-Z]\.)\s+(.+)$", line.text.strip())
            if list_marker_match:
                list_items: List[ListItem] = []
                consumed_list_lines: List[LayoutLine] = []

                while i < n_lines:
                    curr_line = all_lines[i]
                    curr_marker_match = re.match(r"^(\u2022|\u25cf|[\-\*]|\d+\.|\([0-9a-zA-Z]+\)|[a-zA-Z]\.)\s+(.+)$", curr_line.text.strip())
                    if curr_marker_match:
                        marker = curr_marker_match.group(1)
                        item_text = curr_marker_match.group(2)
                        item_spans = self.math_normalizer.normalize_line_spans(curr_line, body_font_size)
                        list_items.append(
                            ListItem(
                                marker=marker,
                                text=item_text,
                                spans=item_spans,
                                source_regions=[SourceRegion(page=curr_line.page_number, bbox=curr_line.bbox_dict)],
                            )
                        )
                        consumed_list_lines.append(curr_line)
                        i += 1
                    elif list_items and curr_line.x0 > consumed_list_lines[-1].x0 + 10.0 and curr_line.y0 - consumed_list_lines[-1].y1 < 10.0:
                        # Continuation line of previous list item
                        list_items[-1].text += " " + curr_line.text.strip()
                        list_items[-1].source_regions.append(SourceRegion(page=curr_line.page_number, bbox=curr_line.bbox_dict))
                        consumed_list_lines.append(curr_line)
                        i += 1
                    else:
                        break

                l_pages = sorted(list(set(l.page_number for l in consumed_list_lines)))
                l_regions = [SourceRegion(page=l.page_number, bbox=l.bbox_dict) for l in consumed_list_lines]
                l_nodes: Set[int] = set()
                for l in consumed_list_lines:
                    l_nodes.update(self._match_activity_node_ids(l.bbox_dict, l.page_number, ast_nodes))

                blocks.append(
                    SemanticBlock(
                        id=f"list-{consumed_list_lines[0].page_number}-{consumed_list_lines[0].y0:.0f}",
                        block_type=BlockType.LIST,
                        ordinal=global_block_ordinal,
                        content_text="\n".join(f"{it.marker} {it.text}" for it in list_items),
                        items=list_items,
                        source_pages=l_pages,
                        source_node_ids=sorted(list(l_nodes)),
                        source_regions=l_regions,
                    )
                )
                global_block_ordinal += 1
                continue

            # 3. Check for Heading based on Typographic Evidence
            ratio = line.median_font_size / max(1.0, body_font_size)
            is_bold_heading = (line.spans and line.spans[0].is_bold) and (len(line.text) < 70) and not line.text.endswith(".")
            is_large_heading = ratio >= self.rules.layout.heading_level_3_min_ratio and len(line.text) < 80 and not line.text.endswith(".")

            if is_large_heading or is_bold_heading:
                # Determine Heading Level
                if ratio >= self.rules.layout.heading_level_1_min_ratio:
                    level = 1
                elif ratio >= self.rules.layout.heading_level_2_min_ratio:
                    level = 2
                else:
                    level = 3

                h_nodes = self._match_activity_node_ids(line.bbox_dict, line.page_number, ast_nodes)
                blocks.append(
                    SemanticBlock(
                        id=f"hd-{line.page_number}-{line.y0:.0f}",
                        block_type=BlockType.HEADING,
                        ordinal=global_block_ordinal,
                        level=level,
                        title=line.text,
                        content_text=line.text,
                        spans=self.math_normalizer.normalize_line_spans(line, body_font_size),
                        source_pages=[line.page_number],
                        source_node_ids=h_nodes,
                        source_regions=[SourceRegion(page=line.page_number, bbox=line.bbox_dict)],
                    )
                )
                global_block_ordinal += 1
                i += 1
                continue

            # 4. Check for Pedagogical Callouts (Examples, Activities, Exercises, Definitions, Notes)
            matched_callout_type: Optional[BlockType] = None
            line_lower = line.text.strip().lower()

            for starter in self.rules.markers.example_starters:
                if line_lower.startswith(starter.lower()):
                    matched_callout_type = BlockType.EXAMPLE
                    break
            if not matched_callout_type:
                for starter in self.rules.markers.activity_starters:
                    if line_lower.startswith(starter.lower()):
                        matched_callout_type = BlockType.ACTIVITY
                        break
            if not matched_callout_type:
                for starter in self.rules.markers.exercise_starters:
                    if line_lower.startswith(starter.lower()):
                        matched_callout_type = BlockType.EXERCISE
                        break
            if not matched_callout_type:
                for starter in self.rules.markers.definition_starters:
                    if line_lower.startswith(starter.lower()):
                        matched_callout_type = BlockType.DEFINITION
                        break
            if not matched_callout_type:
                for starter in self.rules.markers.note_starters:
                    if line_lower.startswith(starter.lower()):
                        matched_callout_type = BlockType.NOTE
                        break

            if matched_callout_type:
                callout_lines: List[LayoutLine] = [line]
                i += 1
                # Gather subsequent lines belonging to this callout
                while i < n_lines:
                    next_l = all_lines[i]
                    next_ratio = next_l.median_font_size / max(1.0, body_font_size)
                    # Stop callout if next line is a major heading
                    if next_ratio >= self.rules.layout.heading_level_2_min_ratio and len(next_l.text) < 70:
                        break
                    # Stop callout if next line is another callout starter
                    next_lower = next_l.text.strip().lower()
                    if any(next_lower.startswith(s.lower()) for s in self.rules.markers.example_starters + self.rules.markers.activity_starters + self.rules.markers.exercise_starters):
                        break
                    # Stop callout if large vertical gap
                    v_gap = next_l.y0 - callout_lines[-1].y1
                    if next_l.page_number == callout_lines[-1].page_number and v_gap > 35.0:
                        break

                    callout_lines.append(next_l)
                    i += 1

                c_text = "\n".join(l.text for l in callout_lines)
                c_pages = sorted(list(set(l.page_number for l in callout_lines)))
                c_regions = [SourceRegion(page=l.page_number, bbox=l.bbox_dict) for l in callout_lines]
                c_nodes: Set[int] = set()
                for l in callout_lines:
                    c_nodes.update(self._match_activity_node_ids(l.bbox_dict, l.page_number, ast_nodes))

                # For ExampleBlock, split problem vs solution if 'Solution' marker is present
                prob_text: Optional[str] = None
                sol_text: Optional[str] = None
                if matched_callout_type == BlockType.EXAMPLE:
                    sol_match = re.search(r"\b(solution|answer)\b\s*[:\.]?", c_text, re.IGNORECASE)
                    if sol_match:
                        prob_text = c_text[: sol_match.start()].strip()
                        sol_text = c_text[sol_match.start() :].strip()

                c_spans: List[TextSpan] = []
                for l in callout_lines:
                    c_spans.extend(self.math_normalizer.normalize_line_spans(l, body_font_size))

                blocks.append(
                    SemanticBlock(
                        id=f"callout-{callout_lines[0].page_number}-{callout_lines[0].y0:.0f}",
                        block_type=matched_callout_type,
                        ordinal=global_block_ordinal,
                        content_text=c_text,
                        spans=c_spans,
                        problem_text=prob_text,
                        solution_text=sol_text,
                        source_pages=c_pages,
                        source_node_ids=sorted(list(c_nodes)),
                        source_regions=c_regions,
                    )
                )
                global_block_ordinal += 1
                continue

            # 5. Default: Paragraph Stitching
            para_lines: List[LayoutLine] = [line]
            i += 1

            while i < n_lines:
                curr_l = all_lines[i]
                prev_l = para_lines[-1]

                # Stop merge if page difference > 1
                if curr_l.page_number - prev_l.page_number > 1:
                    break

                # Stop merge if next line is a heading or callout starter
                curr_ratio = curr_l.median_font_size / max(1.0, body_font_size)
                if curr_ratio >= self.rules.layout.heading_level_3_min_ratio and len(curr_l.text) < 70 and not curr_l.text.endswith("."):
                    break
                curr_low = curr_l.text.strip().lower()
                if any(curr_low.startswith(s.lower()) for s in self.rules.markers.example_starters + self.rules.markers.activity_starters + self.rules.markers.exercise_starters):
                    break

                # Stop merge if vertical gap exceeds line gap tolerance
                if curr_l.page_number == prev_l.page_number:
                    v_gap = curr_l.y0 - prev_l.y1
                    avg_h = (curr_l.height + prev_l.height) / 2.0
                    if v_gap > avg_h * self.rules.layout.max_line_gap_ratio:
                        break

                # Check sentence boundary on previous line
                prev_stripped = prev_l.text.strip()
                ends_with_final = prev_stripped.endswith((".", "!", "?", ":"))
                ends_with_hyphen = prev_stripped.endswith("-")
                starts_lower = curr_l.text.strip() and curr_l.text.strip()[0].islower()

                if ends_with_final and not starts_lower:
                    # Paragraph ended cleanly
                    break

                para_lines.append(curr_l)
                i += 1

            # Stitch lines into coherent paragraph text
            para_text_parts: List[str] = []
            for idx, pl in enumerate(para_lines):
                t = pl.text.strip()
                if idx > 0 and para_text_parts[-1].endswith("-"):
                    para_text_parts[-1] = para_text_parts[-1][:-1] + t
                else:
                    para_text_parts.append(t)

            stitched_text = " ".join(para_text_parts)
            p_pages = sorted(list(set(l.page_number for l in para_lines)))
            p_regions = [SourceRegion(page=l.page_number, bbox=l.bbox_dict) for l in para_lines]
            p_nodes: Set[int] = set()
            for l in para_lines:
                p_nodes.update(self._match_activity_node_ids(l.bbox_dict, l.page_number, ast_nodes))

            p_spans: List[TextSpan] = []
            for l in para_lines:
                p_spans.extend(self.math_normalizer.normalize_line_spans(l, body_font_size))

            blocks.append(
                SemanticBlock(
                    id=f"para-{para_lines[0].page_number}-{para_lines[0].y0:.0f}",
                    block_type=BlockType.PARAGRAPH,
                    ordinal=global_block_ordinal,
                    content_text=stitched_text,
                    spans=p_spans,
                    source_pages=p_pages,
                    source_node_ids=sorted(list(p_nodes)),
                    source_regions=p_regions,
                )
            )
            global_block_ordinal += 1

        return ReadableDocumentResponse(
            version_id=version.id,
            scope_type=scope_type,
            scope_id=scope_id,
            title=title,
            subtitle=subtitle,
            grade=version.grade.name if version.grade else None,
            subject=version.subject.name if version.subject else None,
            start_page=start_page,
            end_page=end_page,
            layout_source="raw_pdf_geometry",
            blocks=blocks,
            warnings=warnings,
        )

    async def get_readable_document(
        self,
        session: AsyncSession,
        version_id: str,
        lesson_id: Optional[int] = None,
        unit_id: Optional[int] = None,
        page: Optional[int] = None,
    ) -> ReadableDocumentResponse:
        """
        Main entry point for generating a bounded readable textbook document.
        Requires exactly one bounded scope: lesson_id, unit_id, or page.
        """
        # 1. Enforce exactly one scope
        provided_scopes = [s for s in [lesson_id, unit_id, page] if s is not None]
        if len(provided_scopes) != 1:
            raise ValueError("Exactly one scope parameter (lesson_id, unit_id, or page) must be provided.")

        # 2. Load SubjectVersion with hierarchy
        stmt = (
            select(SubjectVersion)
            .where(SubjectVersion.id == version_id)
            .options(
                selectinload(SubjectVersion.grade),
                selectinload(SubjectVersion.subject),
                selectinload(SubjectVersion.units).selectinload(Unit.lessons).selectinload(Lesson.activity_nodes),
                selectinload(SubjectVersion.units).selectinload(Unit.activity_nodes),
            )
        )
        res = await session.execute(stmt)
        version = res.scalar_one_or_none()
        if not version:
            raise LookupError(f"SubjectVersion {version_id} not found.")

        # 3. Locate Scope Entities
        unit: Optional[Unit] = None
        lesson: Optional[Lesson] = None

        if lesson_id is not None:
            for u in version.units:
                for l in u.lessons:
                    if l.id == lesson_id:
                        lesson = l
                        unit = u
                        break
                if lesson:
                    break
            if not lesson:
                raise LookupError(f"Lesson {lesson_id} not found in version {version_id}.")

        elif unit_id is not None:
            unit = next((u for u in version.units if u.id == unit_id), None)
            if not unit:
                raise LookupError(f"Unit {unit_id} not found in version {version_id}.")

        # 4. Resolve Target Page Range
        start_p, end_p, scope_type, scope_id, title, subtitle = self._resolve_scope_pages(
            version=version,
            unit=unit,
            lesson=lesson,
            page=page,
        )

        # 5. Fetch relevant ActivityNodes from DB for provenance matching
        ast_nodes_stmt = (
            select(ActivityNode)
            .where(ActivityNode.subject_version_id == version_id)
            .where(ActivityNode.page_number >= start_p)
            .where(ActivityNode.page_number <= end_p)
            .order_by(ActivityNode.page_number, ActivityNode.ordinal)
        )
        nodes_res = await session.execute(ast_nodes_stmt)
        ast_nodes = nodes_res.scalars().all()

        # 6. Check Physical PDF Existence on Server
        pdf_path = (settings.STORAGE_ROOT / version.stored_pdf_path) if version.stored_pdf_path else None
        if not pdf_path or not pdf_path.is_file():
            # Fallback to persisted AST
            return self.reconstruct_from_persisted_ast_fallback(
                version=version,
                nodes=ast_nodes,
                start_page=start_p,
                end_page=end_p,
                scope_type=scope_type,
                scope_id=scope_id,
                title=title,
                subtitle=subtitle,
            )

        # 7. Open PyMuPDF in Thread Pool and Extract Page Layouts
        def _extract_pdf_pages() -> Tuple[List[PageLayout], Set[str]]:
            doc = pymupdf.open(pdf_path)
            patterns = self.header_footer_filter.build_version_patterns(version_id, doc)
            layouts: List[PageLayout] = []
            for p_num in range(start_p, end_p + 1):
                p_idx = p_num - 1
                if 0 <= p_idx < doc.page_count:
                    page_obj = doc[p_idx]
                    layout = self.layout_extractor.extract_page_layout(page_obj, p_num)
                    layouts.append(layout)
            doc.close()
            return layouts, patterns

        page_layouts, header_patterns = await asyncio.to_thread(_extract_pdf_pages)

        # 8. Execute Semantic Reconstruction
        return self.reconstruct_from_pdf_layout(
            version=version,
            page_layouts=page_layouts,
            version_header_patterns=header_patterns,
            ast_nodes=ast_nodes,
            start_page=start_p,
            end_page=end_p,
            scope_type=scope_type,
            scope_id=scope_id,
            title=title,
            subtitle=subtitle,
        )
