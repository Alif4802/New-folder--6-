import logging
import uuid
import re
from typing import Dict, List, Optional
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.textbook import ActivityNode, CurriculumNode, Lesson, SubjectVersion, Unit
from app.services.pdf.toc_service import (
    build_textbook_toc,
    clean_heading_text,
    is_valid_unit_number,
    is_valid_unit_title,
    is_valid_lesson_title,
)

logger = logging.getLogger("nctb.curriculum.migration")


async def migrate_subject_version_to_generic_curriculum(
    session: AsyncSession,
    subject_version_id: str,
) -> int:
    """
    Non-destructively migrates a SubjectVersion's structure into the generic CurriculumNode hierarchy.
    Uses source-faithful terminology (e.g. 'chapter' for Mathematics Class 7).
    Links ActivityNodes to CurriculumNodes.
    Returns the count of created CurriculumNodes.
    """
    stmt = (
        select(SubjectVersion)
        .where(SubjectVersion.id == subject_version_id)
        .options(
            selectinload(SubjectVersion.curriculum_nodes),
            selectinload(SubjectVersion.units).selectinload(Unit.lessons),
            selectinload(SubjectVersion.units).selectinload(Unit.activity_nodes),
        )
    )
    res = await session.execute(stmt)
    version = res.scalar_one_or_none()

    if not version:
        logger.warning(f"SubjectVersion '{subject_version_id}' not found for curriculum migration.")
        return 0

    if version.curriculum_nodes:
        logger.info(f"SubjectVersion '{subject_version_id}' already has {len(version.curriculum_nodes)} generic curriculum nodes.")
        return len(version.curriculum_nodes)

    # Determine default top-level node_type based on subject or title
    is_math = "math" in (version.title or "").lower()
    default_top_type = "chapter" if is_math else "unit"

    created_nodes: List[CurriculumNode] = []
    root_ordinal = 1

    # Use quality-gated units and lessons from the existing textbook
    for u in sorted(version.units, key=lambda x: x.ordinal):
        u_title = clean_heading_text(u.title or "")
        if not is_valid_unit_title(u_title):
            continue

        u_num = (u.detected_number or "").strip()
        if not is_valid_unit_number(u_num, u.label_type):
            u_num = str(root_ordinal)

        # Detect source label terminology
        raw_label_type = (u.label_type or "").strip().lower()
        if "chapter" in raw_label_type or is_math:
            node_type = "chapter"
            source_label = f"Chapter {u_num}" if u_num else "Chapter"
        elif "part" in raw_label_type:
            node_type = "part"
            source_label = f"Part {u_num}" if u_num else "Part"
        else:
            node_type = "unit"
            source_label = f"Unit {u_num}" if u_num else "Unit"

        root_id = f"cnode_{uuid.uuid4().hex[:16]}"
        root_node = CurriculumNode(
            id=root_id,
            subject_version_id=version.id,
            parent_id=None,
            node_type=node_type,
            source_label=source_label,
            title=u_title,
            detected_number=u_num,
            ordinal=root_ordinal,
            depth=0,
            start_pdf_page=u.start_page,
            end_pdf_page=u.end_page,
            source_confidence=1.0,
        )
        session.add(root_node)
        created_nodes.append(root_node)
        root_ordinal += 1

        # Process child lessons / sub-divisions
        child_ordinal = 1
        for l in sorted(u.lessons, key=lambda x: x.ordinal):
            l_title = clean_heading_text(l.title or "")
            if not is_valid_lesson_title(l_title, l.detected_number):
                continue

            l_num = (l.detected_number or "").strip()
            l_node_type = "lesson"
            if "exercise" in l_title.lower() or "exercise" in (l_num or "").lower():
                l_node_type = "exercise"
                l_source_label = l_title if "exercise" in l_title.lower() else f"Exercise {l_num}"
            else:
                l_source_label = l_num if l_num else f"Section {child_ordinal}"

            child_id = f"cnode_{uuid.uuid4().hex[:16]}"
            child_node = CurriculumNode(
                id=child_id,
                subject_version_id=version.id,
                parent_id=root_id,
                node_type=l_node_type,
                source_label=l_source_label,
                title=l_title,
                detected_number=l_num,
                ordinal=child_ordinal,
                depth=1,
                start_pdf_page=l.start_page,
                end_pdf_page=l.end_page,
                source_confidence=1.0,
            )
            session.add(child_node)
            created_nodes.append(child_node)
            child_ordinal += 1

    await session.commit()
    logger.info(f"Successfully migrated {len(created_nodes)} generic CurriculumNodes for SubjectVersion '{version.id}'.")

    # Link ActivityNodes to their closest CurriculumNode based on page ranges
    stmt_nodes = select(ActivityNode).where(ActivityNode.subject_version_id == version.id)
    res_nodes = await session.execute(stmt_nodes)
    activity_nodes = res_nodes.scalars().all()

    for an in activity_nodes:
        # Match with deepest matching child node or root node on that page
        matched_cnode = None
        for cn in created_nodes:
            if cn.depth == 1 and cn.start_pdf_page <= an.page_number <= (cn.end_pdf_page or cn.start_pdf_page + 10):
                matched_cnode = cn
                break
        if not matched_cnode:
            for cn in created_nodes:
                if cn.depth == 0 and cn.start_pdf_page <= an.page_number <= (cn.end_pdf_page or cn.start_pdf_page + 20):
                    matched_cnode = cn
                    break
        if matched_cnode:
            an.curriculum_node_id = matched_cnode.id

    await session.commit()
    return len(created_nodes)


async def auto_migrate_all_textbooks(session: AsyncSession) -> Dict[str, int]:
    """Ensures all existing completed textbooks in database have generic CurriculumNodes."""
    stmt = select(SubjectVersion.id).where(SubjectVersion.ingestion_status == "COMPLETED")
    res = await session.execute(stmt)
    version_ids = res.scalars().all()

    results: Dict[str, int] = {}
    for vid in version_ids:
        count = await migrate_subject_version_to_generic_curriculum(session, vid)
        results[vid] = count
    return results
