import logging
from typing import List, Optional
from fastapi import APIRouter, Depends, Query
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.database import get_db
from app.models.curriculum import Curriculum, Grade
from app.models.textbook import SubjectVersion
from app.schemas.textbook import GradeResponse

logger = logging.getLogger("nctb.api.grades")

router = APIRouter(prefix="/grades", tags=["Grades"])


@router.get(
    "",
    response_model=List[GradeResponse],
    summary="List authoritative Grade catalog scoped to curriculum with assessment-eligible textbook counts",
)
async def list_grades(
    curriculum_id: Optional[int] = Query(None, description="Optional Curriculum ID to scope grades"),
    only_with_textbooks: bool = Query(False, description="Filter to grades with at least one assessment-eligible textbook"),
    session: AsyncSession = Depends(get_db),
):
    """
    Retrieve authoritative Grade master data ordered by academic ordinal (level_number).
    Returns accurate assessment-eligible textbook counts per grade.
    """
    # 1. Resolve target curriculum
    target_curriculum_id = curriculum_id
    if target_curriculum_id is None:
        curr_stmt = select(Curriculum.id).where(Curriculum.code == settings.DEFAULT_CURRICULUM_CODE)
        curr_res = await session.execute(curr_stmt)
        target_curriculum_id = curr_res.scalar_one_or_none()

    # 2. Query grades scoped to curriculum
    grade_stmt = select(Grade).where(Grade.is_active == True)  # noqa: E712
    if target_curriculum_id is not None:
        grade_stmt = grade_stmt.where(Grade.curriculum_id == target_curriculum_id)

    grade_stmt = grade_stmt.order_by(Grade.level_number.asc().nulls_last(), Grade.id.asc())
    grade_res = await session.execute(grade_stmt)
    grades = grade_res.scalars().all()

    # 3. Calculate assessment-eligible textbook counts per grade using central AssessmentReadinessService
    from sqlalchemy.orm import selectinload
    from app.services.assessment.readiness import AssessmentReadinessService

    sv_stmt = (
        select(SubjectVersion)
        .where(
            SubjectVersion.grade_id.is_not(None),
            SubjectVersion.is_deleted == False,
            SubjectVersion.ingestion_status.in_(["COMPLETED", "PARTIAL"]),
        )
        .options(selectinload(SubjectVersion.subject))
    )
    sv_res = await session.execute(sv_stmt)
    active_versions = sv_res.scalars().all()

    counts_map = {}
    for v in active_versions:
        readiness = AssessmentReadinessService.evaluate(v)
        if readiness.is_ready:
            counts_map[v.grade_id] = counts_map.get(v.grade_id, 0) + 1

    response_items: List[GradeResponse] = []
    for g in grades:
        count = counts_map.get(g.id, 0)
        if only_with_textbooks and count == 0:
            continue

        response_items.append(
            GradeResponse(
                id=g.id,
                curriculum_id=g.curriculum_id,
                code=g.code,
                name=g.name,
                display_name=g.name,
                level_number=g.level_number,
                is_active=g.is_active,
                textbook_count=count,
            )
        )

    return response_items
