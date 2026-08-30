import json
import logging
from dataclasses import dataclass
from typing import Dict, List, Optional, Set, Tuple
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.config import settings
from app.models.textbook import ActivityNode, CurriculumNode, Lesson, SubjectVersion, Unit

logger = logging.getLogger("nctb.services.assessment.context_builder")


@dataclass
class SourceChunk:
    chunk_id: str  # e.g. "SRC-001"
    page_number: int
    title: Optional[str]
    content: str
    scope_label: str
    sub_label: Optional[str] = None


@dataclass
class BoundedGroundingContext:
    chunks: List[SourceChunk]
    formatted_source_text: str
    valid_chunk_ids: Set[str]
    total_characters: int
    scope_description: str
    subject_title: str
    grade_name: str
    subject_name: str
    subject_code: str


class ContextBuilder:
    """
    Builds clean, bounded, and chunked textbook source context for LLM generation.
    Structure-agnostic: resolves any selected CurriculumNode and its subtree, preserving
    passage coherence for English and formulas/worked examples for Mathematics.
    """

    @classmethod
    def load_mcq_config(cls) -> Dict:
        try:
            if settings.MCQ_CONFIG_PATH.is_file():
                with open(settings.MCQ_CONFIG_PATH, "r", encoding="utf-8") as f:
                    return json.load(f)
        except Exception as e:
            logger.warning(f"Failed to load mcq_generation.json: {e}")
        return {
            "max_context_characters": 24000,
            "max_llm_retries": 2,
            "min_question_count": 1,
            "default_question_count": 5,
            "generation_batch_size": 5,
        }

    @classmethod
    def load_assessment_profiles(cls) -> Dict:
        try:
            if settings.ASSESSMENT_PROFILES_PATH.is_file():
                with open(settings.ASSESSMENT_PROFILES_PATH, "r", encoding="utf-8") as f:
                    return json.load(f).get("profiles", {})
        except Exception as e:
            logger.warning(f"Failed to load assessment_profiles.json: {e}")
        return {}

    @classmethod
    async def build_context(
        cls,
        session: AsyncSession,
        subject_version_id: str,
        scope_node_id: Optional[str] = None,
        unit_id: Optional[int] = None,
        lesson_id: Optional[int] = None,
    ) -> BoundedGroundingContext:
        config = cls.load_mcq_config()
        max_chars = config.get("max_context_characters", 24000)

        # 1. Fetch SubjectVersion with relations
        stmt = (
            select(SubjectVersion)
            .where(SubjectVersion.id == subject_version_id)
            .options(
                selectinload(SubjectVersion.grade),
                selectinload(SubjectVersion.subject),
                selectinload(SubjectVersion.curriculum_nodes),
                selectinload(SubjectVersion.units).selectinload(Unit.lessons),
            )
        )
        res = await session.execute(stmt)
        version = res.scalar_one_or_none()
        if not version:
            raise ValueError(f"TEXTBOOK_NOT_FOUND: SubjectVersion '{subject_version_id}' does not exist.")

        # Determine subject name & code
        subject_name = version.subject.name if version.subject else "Curriculum"
        subject_code = version.subject.code.lower() if (version.subject and version.subject.code) else "mathematics"
        v_title_lower = (version.title or "").lower()
        if "grammar" in v_title_lower:
            subject_code = "english_grammar"
        elif "english for today" in v_title_lower:
            subject_code = "english_for_today"
        elif "math" in v_title_lower:
            subject_code = "mathematics"

        grade_name = version.grade.name if version.grade else "NCTB Grade"

        activity_nodes: List[ActivityNode] = []
        scope_desc = ""

        # 2. Generic CurriculumNode resolution
        if scope_node_id:
            cnode = next((n for n in version.curriculum_nodes if n.id == scope_node_id), None)
            if not cnode:
                # Check DB directly in case of uncommitted/fresh node
                stmt_cnode = select(CurriculumNode).where(
                    CurriculumNode.id == scope_node_id,
                    CurriculumNode.subject_version_id == subject_version_id,
                )
                res_cnode = await session.execute(stmt_cnode)
                cnode = res_cnode.scalar_one_or_none()

            if not cnode:
                raise ValueError(f"INVALID_CURRICULUM_SCOPE: CurriculumNode ID '{scope_node_id}' does not belong to version {subject_version_id}.")

            scope_desc = f"{cnode.source_label}: {cnode.title}" if cnode.source_label else cnode.title

            # Collect subtree node IDs and page range
            all_cnodes = version.curriculum_nodes or []
            subtree_ids = {cnode.id}
            for n in all_cnodes:
                if n.parent_id == cnode.id or (n.parent_id and n.parent_id in subtree_ids):
                    subtree_ids.add(n.id)

            start_p = cnode.start_pdf_page
            end_p = cnode.end_pdf_page or (start_p + 15)

            # Query ActivityNodes matching either curriculum_node_id or page range
            stmt_nodes = (
                select(ActivityNode)
                .where(
                    ActivityNode.subject_version_id == subject_version_id,
                    ActivityNode.page_number >= start_p,
                    ActivityNode.page_number <= end_p,
                )
                .order_by(ActivityNode.page_number, ActivityNode.ordinal)
            )
            res_nodes = await session.execute(stmt_nodes)
            activity_nodes = res_nodes.scalars().all()

        elif unit_id is not None:
            # Legacy fallback using Unit/Lesson
            target_unit = next((u for u in version.units if u.id == unit_id), None)
            if not target_unit:
                raise ValueError(f"INVALID_CURRICULUM_SCOPE: Unit ID {unit_id} does not belong to version {subject_version_id}.")

            target_lesson: Optional[Lesson] = None
            if lesson_id is not None:
                target_lesson = next((l for l in target_unit.lessons if l.id == lesson_id), None)
                if not target_lesson:
                    raise ValueError(f"INVALID_CURRICULUM_SCOPE: Lesson ID {lesson_id} does not belong to Unit ID {unit_id}.")

            if target_lesson:
                scope_desc = f"{target_unit.label_type} {target_unit.detected_number}: {target_unit.title} > Lesson {target_lesson.detected_number or ''}: {target_lesson.title}"
                node_stmt = (
                    select(ActivityNode)
                    .where(
                        ActivityNode.subject_version_id == subject_version_id,
                        ActivityNode.unit_id == unit_id,
                        ActivityNode.lesson_id == lesson_id,
                    )
                    .order_by(ActivityNode.ordinal)
                )
            else:
                scope_desc = f"{target_unit.label_type} {target_unit.detected_number}: {target_unit.title} (All Lessons)"
                node_stmt = (
                    select(ActivityNode)
                    .where(
                        ActivityNode.subject_version_id == subject_version_id,
                        ActivityNode.unit_id == unit_id,
                    )
                    .order_by(ActivityNode.ordinal)
                )

            res_nodes = await session.execute(node_stmt)
            activity_nodes = res_nodes.scalars().all()
        else:
            raise ValueError("INVALID_CURRICULUM_SCOPE: Either scope_node_id or unit_id must be provided.")

        if not activity_nodes:
            raise ValueError(f"EMPTY_CURRICULUM_SCOPE: No textbook content nodes found for scope '{scope_desc}'.")

        # 3. Build Source Chunks with passage preservation
        chunks: List[SourceChunk] = []
        valid_chunk_ids: Set[str] = set()
        total_chars = 0
        chunk_idx = 1

        for node in activity_nodes:
            content = (node.content_text or "").strip()
            if not content:
                continue

            # Skip tiny headers/footers
            if len(content) < 10 and node.node_type in ["header", "footer", "page_number"]:
                continue

            cid = f"SRC-{chunk_idx:03d}"
            chunk = SourceChunk(
                chunk_id=cid,
                page_number=node.page_number,
                title=node.title,
                content=content,
                scope_label=scope_desc,
            )

            chunk_len = len(content)
            if total_chars + chunk_len > max_chars and len(chunks) >= 3:
                logger.info(f"Source context reached character budget limit ({total_chars}/{max_chars} chars). Capping chunks at {len(chunks)}.")
                break

            chunks.append(chunk)
            valid_chunk_ids.add(cid)
            total_chars += chunk_len
            chunk_idx += 1

        if not chunks:
            raise ValueError(f"INSUFFICIENT_SOURCE_CONTENT: Target scope contains no usable source text.")

        # 4. Format XML Source Blocks for LLM injection defense
        formatted_blocks: List[str] = []
        for c in chunks:
            title_attr = f' title="{c.title}"' if c.title else ""
            block = (
                f'<SOURCE id="{c.chunk_id}" page="{c.page_number}" scope="{c.scope_label}"{title_attr}>\n'
                f"{c.content}\n"
                f"</SOURCE>"
            )
            formatted_blocks.append(block)

        formatted_source_text = "\n\n".join(formatted_blocks)

        return BoundedGroundingContext(
            chunks=chunks,
            formatted_source_text=formatted_source_text,
            valid_chunk_ids=valid_chunk_ids,
            total_characters=total_chars,
            scope_description=scope_desc,
            subject_title=version.title,
            grade_name=grade_name,
            subject_name=subject_name,
            subject_code=subject_code,
        )
